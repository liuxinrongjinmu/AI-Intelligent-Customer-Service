"""
响应缓存模块：减少 LLM 调用延迟
- 意图分类缓存：相同问题文本直接复用意图结果
- 热点答案缓存：高频问题缓存完整回复

缓存策略：Redis 优先 + 内存降级
- 优先使用 Redis 存储缓存（支持多实例共享、持久化）
- Redis 不可用时自动降级为进程内 LRU 缓存
"""
import json
import time
import hashlib
import logging
from collections import OrderedDict
from threading import Lock

logger = logging.getLogger(__name__)

INTENT_CACHE_MAX_SIZE = 500
ANSWER_CACHE_MAX_SIZE = 200
INTENT_CACHE_TTL = 300
ANSWER_CACHE_TTL = 600

# Redis key 前缀，避免与其他业务 key 冲突
_REDIS_KEY_PREFIX = "kefu:cache:"


class _LRUCache:
    def __init__(self, max_size: int, ttl: int):
        self._max_size = max_size
        self._ttl = ttl
        self._store = OrderedDict()
        self._lock = Lock()

    def _make_key(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def get(self, text: str):
        key = self._make_key(text)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.time() - entry["ts"] > self._ttl:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return entry["value"]

    def set(self, text: str, value):
        key = self._make_key(text)
        with self._lock:
            if key in self._store:
                del self._store[key]
            self._store[key] = {"value": value, "ts": time.time()}
            if len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def clear(self):
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        with self._lock:
            alive = sum(1 for e in self._store.values() if time.time() - e["ts"] <= self._ttl)
            return {"size": len(self._store), "alive": alive, "max_size": self._max_size, "ttl": self._ttl}


# 内存降级缓存实例
intent_cache = _LRUCache(max_size=INTENT_CACHE_MAX_SIZE, ttl=INTENT_CACHE_TTL)
answer_cache = _LRUCache(max_size=ANSWER_CACHE_MAX_SIZE, ttl=ANSWER_CACHE_TTL)


async def _get_redis():
    """
    获取 Redis 客户端，不可用时返回 None

    :return: Redis 客户端实例或 None
    """
    try:
        from backend.utils.redis_client import get_redis
        return await get_redis()
    except Exception:
        return None


def _make_redis_key(category: str, text: str) -> str:
    """
    生成 Redis 缓存 key

    :param category: 缓存分类（intent / answer）
    :param text: 缓存原始 key 文本
    :return: Redis key 字符串
    """
    hashed = hashlib.md5(text.encode("utf-8")).hexdigest()
    return f"{_REDIS_KEY_PREFIX}{category}:{hashed}"


def get_cached_intent(message: str, tenant_id: str = "") -> dict | None:
    """
    获取缓存的意图分类结果

    :param message: 用户消息文本
    :param tenant_id: 租户 ID（参与缓存 key，避免跨租户污染）
    :return: 缓存的意图结果，无则返回 None
    """
    key = f"{tenant_id}:{message}"
    # 内存缓存作为同步方法的快速路径
    return intent_cache.get(key)


async def get_cached_intent_async(message: str, tenant_id: str = "") -> dict | None:
    """
    获取缓存的意图分类结果（Redis 优先 + 内存降级）

    :param message: 用户消息文本
    :param tenant_id: 租户 ID（参与缓存 key，避免跨租户污染）
    :return: 缓存的意图结果，无则返回 None
    """
    key = f"{tenant_id}:{message}"
    redis_key = _make_redis_key("intent", key)

    # 1. 尝试 Redis
    redis = await _get_redis()
    if redis is not None:
        try:
            raw = await redis.get(redis_key)
            if raw is not None:
                return json.loads(raw)
        except Exception as e:
            logger.debug(f"Redis 读取意图缓存失败，降级到内存: {e}")

    # 2. 降级到内存缓存
    return intent_cache.get(key)


def set_cached_intent(message: str, result: dict, tenant_id: str = ""):
    """
    缓存意图分类结果

    :param message: 用户消息文本
    :param result: 意图分类结果
    :param tenant_id: 租户 ID（参与缓存 key，避免跨租户污染）
    """
    key = f"{tenant_id}:{message}"
    # 同步写入内存缓存
    intent_cache.set(key, result)


async def set_cached_intent_async(message: str, result: dict, tenant_id: str = ""):
    """
    缓存意图分类结果（Redis 优先 + 内存降级）

    :param message: 用户消息文本
    :param result: 意图分类结果
    :param tenant_id: 租户 ID（参与缓存 key，避免跨租户污染）
    """
    key = f"{tenant_id}:{message}"
    redis_key = _make_redis_key("intent", key)

    # 1. 写入内存缓存（确保降级时可用）
    intent_cache.set(key, result)

    # 2. 尝试写入 Redis
    redis = await _get_redis()
    if redis is not None:
        try:
            await redis.setex(redis_key, INTENT_CACHE_TTL, json.dumps(result, ensure_ascii=False))
        except Exception as e:
            logger.debug(f"Redis 写入意图缓存失败，仅内存缓存生效: {e}")


def get_cached_answer(message: str, tenant_id: str) -> str | None:
    """获取缓存的热点答案"""
    key = f"{tenant_id}:{message}"
    return answer_cache.get(key)


async def get_cached_answer_async(message: str, tenant_id: str) -> str | None:
    """
    获取缓存的热点答案（Redis 优先 + 内存降级）

    :param message: 用户消息文本
    :param tenant_id: 租户 ID
    :return: 缓存的答案文本，无则返回 None
    """
    key = f"{tenant_id}:{message}"
    redis_key = _make_redis_key("answer", key)

    # 1. 尝试 Redis
    redis = await _get_redis()
    if redis is not None:
        try:
            raw = await redis.get(redis_key)
            if raw is not None:
                return raw
        except Exception as e:
            logger.debug(f"Redis 读取答案缓存失败，降级到内存: {e}")

    # 2. 降级到内存缓存
    return answer_cache.get(key)


def set_cached_answer(message: str, tenant_id: str, answer: str):
    """缓存热点答案"""
    key = f"{tenant_id}:{message}"
    answer_cache.set(key, answer)


async def set_cached_answer_async(message: str, tenant_id: str, answer: str):
    """
    缓存热点答案（Redis 优先 + 内存降级）

    :param message: 用户消息文本
    :param tenant_id: 租户 ID
    :param answer: 答案文本
    """
    key = f"{tenant_id}:{message}"
    redis_key = _make_redis_key("answer", key)

    # 1. 写入内存缓存
    answer_cache.set(key, answer)

    # 2. 尝试写入 Redis
    redis = await _get_redis()
    if redis is not None:
        try:
            await redis.setex(redis_key, ANSWER_CACHE_TTL, answer)
        except Exception as e:
            logger.debug(f"Redis 写入答案缓存失败，仅内存缓存生效: {e}")


def cache_stats() -> dict:
    """获取缓存统计"""
    return {
        "intent_cache": intent_cache.stats(),
        "answer_cache": answer_cache.stats(),
    }
