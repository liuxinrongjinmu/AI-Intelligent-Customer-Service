"""
Embedding 模型加载：BAAI/bge-small-zh-v1.5
含查询结果缓存，相同文本直接返回，避免重复推理

线程池策略：
- 使用专用 ThreadPoolExecutor 执行 CPU 密集型 embedding 推理
- 避免阻塞 FastAPI 默认线程池（用于其他 I/O 操作）
- 最大线程数 = 2（推理是 CPU 密集型，过多线程导致上下文切换开销）
"""
import os
import time
import hashlib
import threading
import asyncio
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from backend.config import EMBEDDING_MODEL, EMBEDDING_DEVICE, HF_ENDPOINT, EMBED_CACHE_MAX_SIZE

_embedding_model = None
_model_lock = threading.Lock()

# 专用线程池：CPU 密集型 embedding 推理，与默认 I/O 线程池隔离
_EMBED_MAX_WORKERS = 2
_embed_executor = None  # type: Optional[ThreadPoolExecutor]
_embed_executor_lock = threading.Lock()

# Embedding 查询缓存：LRU + TTL
_embed_cache: OrderedDict[str, tuple[list[float], float]] = OrderedDict()
_embed_cache_lock = threading.Lock()
_EMBED_CACHE_TTL = 600  # 10 分钟
_last_cache_cleanup = 0.0
_CACHE_CLEANUP_INTERVAL = 120  # 每 120 秒清理一次过期条目


def _get_embed_executor() -> ThreadPoolExecutor:
    """获取专用 embedding 线程池（懒初始化，线程安全）"""
    global _embed_executor
    if _embed_executor is None:
        with _embed_executor_lock:
            if _embed_executor is None:
                _embed_executor = ThreadPoolExecutor(
                    max_workers=_EMBED_MAX_WORKERS,
                    thread_name_prefix="embed-"
                )
    return _embed_executor


def shutdown_embed_executor():
    """关闭 embedding 线程池（应用关闭时调用）"""
    global _embed_executor
    if _embed_executor is not None:
        _embed_executor.shutdown(wait=True)
        _embed_executor = None


def _cache_key(text: str) -> str:
    """生成缓存 key"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def get_embedding_model():
    """
    懒加载 embedding 模型，首次调用时下载并缓存
    使用 HF 镜像站加速国内下载
    """
    global _embedding_model
    if _embedding_model is None:
        with _model_lock:
            if _embedding_model is None:
                if HF_ENDPOINT:
                    os.environ["HF_ENDPOINT"] = HF_ENDPOINT

                from langchain_huggingface import HuggingFaceEmbeddings

                _embedding_model = HuggingFaceEmbeddings(
                    model_name=EMBEDDING_MODEL,
                    model_kwargs={"device": EMBEDDING_DEVICE},
                    encode_kwargs={"normalize_embeddings": True}
                )
    return _embedding_model


def _cleanup_expired_cache():
    """定期清理过期的缓存条目"""
    global _last_cache_cleanup
    now = time.time()
    if now - _last_cache_cleanup < _CACHE_CLEANUP_INTERVAL:
        return
    _last_cache_cleanup = now
    expired_keys = [
        k for k, (_, ts) in _embed_cache.items()
        if now - ts > _EMBED_CACHE_TTL
    ]
    for k in expired_keys:
        del _embed_cache[k]


def embed_query_cached(query: str) -> list[float]:
    """
    带缓存的 embed_query：相同文本直接返回缓存结果

    :param query: 查询文本
    :return: 向量列表
    """
    key = _cache_key(query)
    with _embed_cache_lock:
        if key in _embed_cache:
            result, ts = _embed_cache[key]
            if time.time() - ts < _EMBED_CACHE_TTL:
                # LRU：移到末尾
                _embed_cache.move_to_end(key)
                return result
            else:
                # 已过期，删除
                del _embed_cache[key]

    # 缓存未命中，执行推理
    model = get_embedding_model()
    result = model.embed_query(query)

    with _embed_cache_lock:
        _embed_cache[key] = (result, time.time())
        _embed_cache.move_to_end(key)
        # 超出容量时淘汰最旧的
        while len(_embed_cache) > EMBED_CACHE_MAX_SIZE:
            _embed_cache.popitem(last=False)
        # 定期清理过期条目
        _cleanup_expired_cache()

    return result


async def embed_query_cached_async(query: str) -> list[float]:
    """
    embed_query_cached 的异步包装，使用专用线程池不阻塞事件循环

    :param query: 查询文本
    :return: 向量列表
    """
    loop = asyncio.get_running_loop()
    executor = _get_embed_executor()
    return await loop.run_in_executor(executor, embed_query_cached, query)


async def embed_documents_async(texts: list[str]) -> list[list[float]]:
    """
    批量 embedding 的异步包装，使用专用线程池不阻塞事件循环

    :param texts: 文本列表
    :return: 向量列表的列表
    """
    loop = asyncio.get_running_loop()

    def _batch_embed():
        model = get_embedding_model()
        return model.embed_documents(texts)

    executor = _get_embed_executor()
    return await loop.run_in_executor(executor, _batch_embed)


def embed_documents_sync(texts: list[str]) -> list[list[float]]:
    """
    批量 embedding（同步版本，供 sync_service 等同步调用链使用）

    :param texts: 文本列表
    :return: 向量列表的列表
    """
    model = get_embedding_model()
    return model.embed_documents(texts)


def clear_embed_cache():
    """清空 embedding 缓存"""
    with _embed_cache_lock:
        _embed_cache.clear()


def embed_cache_stats() -> dict:
    """返回缓存统计信息"""
    with _embed_cache_lock:
        return {"size": len(_embed_cache), "max_size": EMBED_CACHE_MAX_SIZE}
