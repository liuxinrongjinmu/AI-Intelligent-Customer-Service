"""
全局 HTTP 客户端连接池 + 限流中间件

限流策略：
- 优先使用 Redis 滑动窗口（多 Worker 共享，服务重启后仍生效）
- Redis 不可用时降级为内存模式（单进程内有效）
- 默认每 IP 每分钟 120 次请求，chat/sync 端点 60 次
"""
import time
import logging
import threading
import uuid
from collections import defaultdict
from threading import Lock
from typing import Optional
import httpx
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import RATE_LIMIT_WINDOW
from backend.utils.redis_client import get_redis

logger = logging.getLogger(__name__)

_shared_client: Optional[httpx.AsyncClient] = None
_shared_client_lock = threading.Lock()


def get_shared_client() -> httpx.AsyncClient:
    """获取全局共享的 httpx.AsyncClient（连接池复用，线程安全）"""
    global _shared_client
    if _shared_client is None:
        with _shared_client_lock:
            if _shared_client is None:
                _shared_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0, connect=5.0),
                    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                )
    return _shared_client


async def close_shared_client():
    """关闭全局客户端（应用关闭时调用）"""
    global _shared_client
    if _shared_client is not None:
        await _shared_client.aclose()
        _shared_client = None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    限流中间件（Redis 优先 + 内存降级）

    Redis 模式：
    - 使用 Sorted Set 实现滑动窗口
    - 多 Worker 共享计数，服务重启后窗口仍有效
    - 原子性由 Redis 单线程保证

    内存降级模式：
    - Redis 不可用时自动降级
    - 单进程内有效，服务重启后计数归零
    """

    def __init__(self, app, default_limit: int = 120, chat_limit: int = 60):
        super().__init__(app)
        self._default_limit = default_limit
        self._chat_limit = chat_limit
        # 内存降级模式的数据结构
        self._counts: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._last_cleanup = time.time()
        self._cleanup_interval = 60

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实 IP（仅使用 TCP 对端 IP，不信任可伪造的代理头）"""
        return request.client.host if request.client else "unknown"

    def _check_limit_memory(self, key: str, limit: int) -> bool:
        """内存模式：检查是否超过限流阈值"""
        now = time.time()
        with self._lock:
            self._counts[key] = [t for t in self._counts[key] if now - t < RATE_LIMIT_WINDOW]
            if now - self._last_cleanup > self._cleanup_interval:
                expired_keys = [k for k, v in self._counts.items() if not v]
                for k in expired_keys:
                    del self._counts[k]
                self._last_cleanup = now
            if len(self._counts[key]) >= limit:
                return False
            self._counts[key].append(now)
            return True

    async def _check_limit_redis(self, redis_client, key: str, limit: int) -> bool:
        """
        Redis 模式：滑动窗口限流

        使用 Sorted Set：
        - member = 唯一 ID（避免同毫秒请求被去重）
        - score = 时间戳
        - 先清理过期成员，再判断当前窗口内数量
        """
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW
        member = f"{now}:{uuid.uuid4().hex}"
        pipe = redis_client.pipeline()
        # 1. 移除窗口外的过期记录
        pipe.zremrangebyscore(key, 0, window_start)
        # 2. 先统计当前窗口内数量（添加前检查）
        pipe.zcard(key)
        # 3. 添加当前请求（使用 uuid4 保证 member 唯一）
        pipe.zadd(key, {member: now})
        # 4. 设置 key 过期时间（避免冷 key 永久占用内存）
        pipe.expire(key, RATE_LIMIT_WINDOW + 10)
        results = await pipe.execute()
        current_count = results[1]
        # 若超限，移除刚添加的 member，避免被拒请求占用 slot
        if current_count >= limit:
            await redis_client.zrem(key, member)
            return False
        return True

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        ip = self._get_client_ip(request)

        # 只对 API 接口限流，页面和静态资源不限
        if not path.startswith("/api/"):
            return await call_next(request)

        # 健康检查和监控指标不限流
        if path.startswith("/api/v1/system/health") or path.startswith("/api/v1/system/metrics"):
            return await call_next(request)

        # 区分聊天/同步接口和其他接口的限流
        if "/chat/" in path or "/knowledge/sync" in path:
            limit = self._chat_limit
            rate_key = f"ratelimit:{ip}:chat"
        else:
            limit = self._default_limit
            rate_key = f"ratelimit:{ip}:api"

        # 优先 Redis，降级内存
        allowed = False
        redis_client = await get_redis()
        if redis_client is not None:
            try:
                allowed = await self._check_limit_redis(redis_client, rate_key, limit)
            except Exception as e:
                logger.warning(f"Redis 限流异常，降级内存模式: {e}")
                allowed = self._check_limit_memory(rate_key, limit)
        else:
            allowed = self._check_limit_memory(rate_key, limit)

        if not allowed:
            logger.warning(f"限流触发: ip={ip}, path={path}")
            return Response(
                content='{"code":"RATE_LIMITED","message":"请求过于频繁，请稍后再试"}',
                status_code=429,
                media_type="application/json",
            )

        return await call_next(request)
