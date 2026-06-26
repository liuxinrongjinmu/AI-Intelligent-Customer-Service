"""
ChromaDB 向量存储封装：按租户 + 知识库类型隔离 collection

知识库类型：
- faq:     商家FAQ问答对
- product: 商家商品FAQ
- rule:    商家规则文档
- public:  平台公共知识库（跨租户共享）

优化：读写分离 — 写入操作通过队列异步执行，不阻塞用户查询
"""
import logging
import threading
import queue
import time
import chromadb
from chromadb.config import Settings
from typing import Optional
from backend.config import CHROMA_PATH

logger = logging.getLogger(__name__)

KB_COLLECTIONS = ["faq", "product", "rule", "public"]


def _collection_name(tenant_id: str, kb_type: str) -> str:
    """
    生成 ChromaDB collection 名称
    公共知识库使用固定名称 public_kb，租户知识库使用 tenant_{id}_{type}
    """
    if kb_type == "public":
        return "public_kb"
    return f"knowledge_{tenant_id}_{kb_type}"


_client = None
_client_lock = threading.Lock()


def _get_client() -> chromadb.PersistentClient:
    """获取 ChromaDB 客户端（单例，双重检查锁）"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = chromadb.PersistentClient(
                    path=CHROMA_PATH,
                    settings=Settings(anonymized_telemetry=False)
                )
    return _client


def get_chroma_client() -> chromadb.PersistentClient:
    """
    获取 ChromaDB 客户端实例（公共接口，供健康检查等外部模块使用）

    :return: ChromaDB PersistentClient 实例
    """
    return _get_client()


def get_collection(tenant_id: str, kb_type: str = "faq") -> chromadb.Collection:
    """
    获取指定租户和知识库类型的 ChromaDB collection

    :param tenant_id: 租户ID
    :param kb_type: 知识库类型（faq/product/rule/public）
    """
    client = _get_client()
    name = _collection_name(tenant_id, kb_type)
    return client.get_or_create_collection(name=name)


def get_collections(tenant_id: str, kb_types: Optional[list[str]] = None) -> list[tuple[str, chromadb.Collection]]:
    """
    批量获取多个知识库类型的 collection

    :param tenant_id: 租户ID
    :param kb_types: 知识库类型列表，默认获取全部类型
    :return: [(kb_type, collection), ...]
    """
    if kb_types is None:
        kb_types = KB_COLLECTIONS
    return [(kt, get_collection(tenant_id, kt)) for kt in kb_types]


def delete_collection(tenant_id: str, kb_type: str):
    """
    删除指定租户的 collection（慎用）
    """
    client = _get_client()
    name = _collection_name(tenant_id, kb_type)
    try:
        client.delete_collection(name=name)
    except Exception as e:
        logger.warning(f"删除 collection 失败（可能不存在）: name={name}, error={e}")


def delete_tenant_collections(tenant_id: str):
    """
    删除指定租户的所有 collection
    """
    for kb_type in KB_COLLECTIONS:
        delete_collection(tenant_id, kb_type)


def clear_collection(tenant_id: str, kb_type: str):
    """
    清空 collection 中所有文档（保留 collection 本身）
    优化：直接使用 delete(where) 替代全量读取再删除
    """
    collection = get_collection(tenant_id, kb_type)
    try:
        # 使用 where 条件删除，避免全量读取
        collection.delete(where={"kb_type": kb_type})
    except Exception:
        # 降级：全量读取再删除
        try:
            all_data = collection.get()
            if all_data and all_data.get("ids"):
                collection.delete(ids=all_data["ids"])
        except Exception as e:
            logger.error(f"清空 collection 失败: tenant={tenant_id}, kb_type={kb_type}, error={e}")


# ============================================================
# 读写分离：写入队列 + 后台消费者线程
# ============================================================

_write_queue: queue.Queue = queue.Queue()
_write_thread: Optional[threading.Thread] = None
_write_thread_lock = threading.Lock()
_WRITE_THREAD_NAME = "chroma-writer"


def _write_worker():
    """
    后台写入消费者线程

    从队列中取出写入任务并执行，串行化所有 ChromaDB 写入操作，
    避免写入锁竞争阻塞用户查询线程。
    """
    while True:
        try:
            task = _write_queue.get(timeout=1)
            if task is None:
                # 哨兵值，退出线程
                break
            op_type, args, result_event, result_container = task
            try:
                if op_type == "add":
                    tenant_id, kb_type, ids, documents, metadatas, embeddings = args
                    collection = get_collection(tenant_id, kb_type)
                    collection.add(
                        ids=ids,
                        documents=documents,
                        metadatas=metadatas,
                        embeddings=embeddings
                    )
                elif op_type == "delete":
                    tenant_id, kb_type, ids = args
                    collection = get_collection(tenant_id, kb_type)
                    collection.delete(ids=ids)
                elif op_type == "clear":
                    tenant_id, kb_type = args
                    clear_collection(tenant_id, kb_type)
                result_container["status"] = "ok"
            except Exception as e:
                logger.error(f"ChromaDB 异步写入失败: op={op_type}, error={e}")
                result_container["status"] = "error"
                result_container["error"] = e
            finally:
                if result_event:
                    result_event.set()
        except queue.Empty:
            continue


def _ensure_write_thread():
    """确保写入线程已启动"""
    global _write_thread
    with _write_thread_lock:
        if _write_thread is None or not _write_thread.is_alive():
            _write_thread = threading.Thread(
                target=_write_worker,
                name=_WRITE_THREAD_NAME,
                daemon=True
            )
            _write_thread.start()
            logger.info("ChromaDB 写入线程已启动")


def add_to_collection(
    tenant_id: str,
    kb_type: str,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict],
    embeddings: list[list[float]],
    async_write: bool = True,
):
    """
    批量添加文档到 ChromaDB

    :param tenant_id: 租户ID
    :param kb_type: 知识库类型
    :param ids: 文档ID列表
    :param documents: 文档内容列表
    :param metadatas: 元数据列表
    :param embeddings: 向量列表
    :param async_write: 是否异步写入（默认 True，不阻塞调用线程）
    """
    if async_write:
        _ensure_write_thread()
        _write_queue.put(("add", (tenant_id, kb_type, ids, documents, metadatas, embeddings), None, {"status": "queued"}))
    else:
        # 同步写入（用于需要立即确认结果的场景）
        collection = get_collection(tenant_id, kb_type)
        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings
        )


def add_to_collection_sync(
    tenant_id: str,
    kb_type: str,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict],
    embeddings: list[list[float]],
    timeout: float = 30.0,
) -> bool:
    """
    同步写入 ChromaDB（通过队列，等待写入完成确认）

    :param timeout: 等待超时时间（秒）
    :return: 是否写入成功
    """
    _ensure_write_thread()
    result_event = threading.Event()
    result_container = {"status": "pending"}
    _write_queue.put(("add", (tenant_id, kb_type, ids, documents, metadatas, embeddings), result_event, result_container))
    if result_event.wait(timeout=timeout):
        return result_container["status"] == "ok"
    return False


def delete_from_collection(tenant_id: str, kb_type: str, ids: list[str], async_write: bool = True):
    """
    从 ChromaDB 删除指定文档
    """
    if async_write:
        _ensure_write_thread()
        _write_queue.put(("delete", (tenant_id, kb_type, ids), None, {"status": "queued"}))
    else:
        collection = get_collection(tenant_id, kb_type)
        try:
            collection.delete(ids=ids)
        except Exception as e:
            logger.warning(f"删除文档失败: tenant={tenant_id}, kb_type={kb_type}, ids={ids}, error={e}")


def query_collection(
    tenant_id: str,
    kb_type: str,
    query_embeddings: list[list[float]],
    n_results: int = 5
):
    """
    向量检索单个 collection（读操作，不受写入影响）

    :param tenant_id: 租户ID
    :param kb_type: 知识库类型
    :param query_embeddings: 查询向量
    :param n_results: 返回结果数
    """
    collection = get_collection(tenant_id, kb_type)
    if collection.count() == 0:
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    return collection.query(
        query_embeddings=query_embeddings,
        n_results=n_results,
        where={"kb_type": kb_type} if kb_type else None,
    )


def query_multi_collections(
    tenant_id: str,
    kb_types: list[str],
    query_embeddings: list[list[float]],
    n_results: int = 5
) -> dict[str, dict]:
    """
    向量检索多个 collection，合并返回

    :param tenant_id: 租户ID
    :param kb_types: 知识库类型列表
    :param query_embeddings: 查询向量
    :param n_results: 每个 collection 的返回结果数
    :return: {kb_type: raw_chromadb_result, ...}
    """
    results = {}
    for kb_type in kb_types:
        try:
            raw = query_collection(tenant_id, kb_type, query_embeddings, n_results)
            results[kb_type] = raw
        except Exception as e:
            logger.warning(f"检索 collection 失败: tenant={tenant_id}, kb_type={kb_type}, error={e}")
            results[kb_type] = {}
    return results


def shutdown_write_thread():
    """优雅关闭写入线程：先等待队列排空，再发送退出信号"""
    global _write_thread
    if _write_thread and _write_thread.is_alive():
        # 等待队列中的任务处理完毕（最多等 10 秒）
        deadline = time.time() + 10
        while not _write_queue.empty() and time.time() < deadline:
            time.sleep(0.1)
        # 发送哨兵值退出线程
        _write_queue.put(None)
        _write_thread.join(timeout=5)
        if _write_thread.is_alive():
            logger.warning("ChromaDB 写入线程未能在超时内退出")
        _write_thread = None
