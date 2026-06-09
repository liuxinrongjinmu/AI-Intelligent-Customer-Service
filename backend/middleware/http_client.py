"""
全局 HTTP 客户端连接池 + 限流中间件
"""
import time
import logging
import threading
from collections import defaultdict
from threading import Lock
import httpx
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_shared_client: httpx.AsyncClient | None = None
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
    简易全局限流中间件（内存存储）

    当前实现使用内存 dict 存储计数，服务重启后计数归零。
    生产环境建议升级为 Redis 持久化方案，避免服务重启后限流窗口被绕过。

    限流策略：
    - 默认每 IP 每分钟 120 次请求
    - chat 和 sync 端点限制更严格：每 IP 每分钟 60 次
    - 含全局过期 key 定期清理，防止内存泄漏

    升级路径（Redis）：
    1. 使用 redis-py 的 Sorted Set 实现滑动窗口
    2. 使用 Redis + Lua 脚本保证原子性
    3. 多 Worker 共享同一个 Redis 限流计数器
    """

    def __init__(self, app, default_limit: int = 120, chat_limit: int = 60):
        super().__init__(app)
        self._default_limit = default_limit
        self._chat_limit = chat_limit
        self._counts: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._last_cleanup = time.time()
        self._cleanup_interval = 60  # 每 60 秒清理一次过期 key

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _check_limit(self, key: str, limit: int) -> bool:
        """检查是否超过限流阈值，未超过则记录并返回 True"""
        now = time.time()
        with self._lock:
            # 清理当前 key 的过期记录
            self._counts[key] = [t for t in self._counts[key] if now - t < 60]

            # 定期全局清理：删除所有已无记录的 key，防止内存泄漏
            if now - self._last_cleanup > self._cleanup_interval:
                expired_keys = [k for k, v in self._counts.items() if not v]
                for k in expired_keys:
                    del self._counts[k]
                self._last_cleanup = now

            # 超过阈值则拒绝
            if len(self._counts[key]) >= limit:
                return False
            # 未超过阈值，记录本次请求时间戳并放行
            self._counts[key].append(now)
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
            rate_key = f"{ip}:chat"
        else:
            limit = self._default_limit
            rate_key = f"{ip}:api"

        if not self._check_limit(rate_key, limit):
            logger.warning(f"限流触发: ip={ip}, path={path}")
            return Response(
                content='{"detail":"请求过于频繁，请稍后再试"}',
                status_code=429,
                media_type="application/json",
            )

        return await call_next(request)
