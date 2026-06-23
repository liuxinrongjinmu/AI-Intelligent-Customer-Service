"""
响应缓存模块：减少 LLM 调用延迟
- 意图分类缓存：相同问题文本直接复用意图结果
- 热点答案缓存：高频问题缓存完整回复
"""
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


intent_cache = _LRUCache(max_size=INTENT_CACHE_MAX_SIZE, ttl=INTENT_CACHE_TTL)
answer_cache = _LRUCache(max_size=ANSWER_CACHE_MAX_SIZE, ttl=ANSWER_CACHE_TTL)


def get_cached_intent(message: str, tenant_id: str = "") -> dict | None:
    """
    获取缓存的意图分类结果

    :param message: 用户消息文本
    :param tenant_id: 租户 ID（参与缓存 key，避免跨租户污染）
    :return: 缓存的意图结果，无则返回 None
    """
    key = f"{tenant_id}:{message}"
    return intent_cache.get(key)


def set_cached_intent(message: str, result: dict, tenant_id: str = ""):
    """
    缓存意图分类结果

    :param message: 用户消息文本
    :param result: 意图分类结果
    :param tenant_id: 租户 ID（参与缓存 key，避免跨租户污染）
    """
    key = f"{tenant_id}:{message}"
    intent_cache.set(key, result)


def get_cached_answer(message: str, tenant_id: str) -> str | None:
    """获取缓存的热点答案"""
    key = f"{tenant_id}:{message}"
    return answer_cache.get(key)


def set_cached_answer(message: str, tenant_id: str, answer: str):
    """缓存热点答案"""
    key = f"{tenant_id}:{message}"
    answer_cache.set(key, answer)


def cache_stats() -> dict:
    """获取缓存统计"""
    return {
        "intent_cache": intent_cache.stats(),
        "answer_cache": answer_cache.stats(),
    }