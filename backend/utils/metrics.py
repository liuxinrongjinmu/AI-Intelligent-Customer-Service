"""
系统监控指标收集
"""
import time
import logging
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)


class MetricsCollector:
    """线程安全的指标收集器"""

    def __init__(self):
        self._lock = Lock()
        self._request_count = 0
        self._error_count = 0
        self._total_latency = 0.0
        self._intent_distribution = defaultdict(int)
        self._cache_hits = 0
        self._cache_misses = 0
        self._handoff_count = 0
        self._kb_retrieval_count = 0
        self._kb_retrieval_miss = 0
        self._start_time = time.time()

    def record_request(self, latency: float, intent: str = "", has_error: bool = False):
        with self._lock:
            self._request_count += 1
            self._total_latency += latency
            if has_error:
                self._error_count += 1
            if intent:
                self._intent_distribution[intent] += 1

    def record_cache(self, hit: bool):
        with self._lock:
            if hit:
                self._cache_hits += 1
            else:
                self._cache_misses += 1

    def record_handoff(self):
        with self._lock:
            self._handoff_count += 1

    def record_retrieval(self, has_results: bool):
        with self._lock:
            self._kb_retrieval_count += 1
            if not has_results:
                self._kb_retrieval_miss += 1

    def snapshot(self) -> dict:
        with self._lock:
            uptime = time.time() - self._start_time
            avg_latency = self._total_latency / max(self._request_count, 1)
            error_rate = self._error_count / max(self._request_count, 1)
            cache_hit_rate = self._cache_hits / max(self._cache_hits + self._cache_misses, 1)
            kb_miss_rate = self._kb_retrieval_miss / max(self._kb_retrieval_count, 1)
            return {
                "uptime_seconds": round(uptime, 1),
                "request_count": self._request_count,
                "error_count": self._error_count,
                "error_rate": round(error_rate, 4),
                "avg_latency_ms": round(avg_latency * 1000, 1),
                "cache_hit_rate": round(cache_hit_rate, 4),
                "handoff_count": self._handoff_count,
                "kb_retrieval_count": self._kb_retrieval_count,
                "kb_miss_rate": round(kb_miss_rate, 4),
                "intent_distribution": dict(self._intent_distribution),
            }


metrics = MetricsCollector()