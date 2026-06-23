"""
Redis 客户端单例：限流与缓存共享

使用 redis-py 的异步客户端，支持连接池复用。
首次连接失败时降级为 None，调用方需自行处理（如限流降级为放行）。

重连机制：连接失败后每隔 _RECONNECT_INTERVAL 秒尝试重连，
避免 Redis 临时故障后永久不可用。
"""
import asyncio
import logging
import time
from typing import Optional

import redis.asyncio as redis_async

from backend.config import REDIS_URL, REDIS_PASSWORD

logger = logging.getLogger(__name__)

_redis_client: Optional[redis_async.Redis] = None
_redis_unavailable_logged = False  # 避免日志刷屏
_last_fail_time: float = 0.0  # 上次连接失败时间戳
_RECONNECT_INTERVAL: float = 30.0  # 重连间隔（秒），避免高频重连压垮服务
_reconnect_lock: Optional[asyncio.Lock] = None  # 重连锁，懒加载（必须在事件循环内创建）
_last_ping_ok: float = 0.0  # 上次 ping 成功时间戳
_PING_INTERVAL: float = 10.0  # ping 结果缓存间隔（秒），避免每次调用都 ping


def _mask_url(url: str) -> str:
    """
    脱敏 Redis URL 中的密码信息，避免日志泄漏凭据

    例如：redis://:secret_pwd@host:6379/0 -> redis://***@host:6379/0

    :param url: 原始 Redis URL
    :return: 脱敏后的 URL；解析失败返回 "***"
    """
    if not url:
        return url
    try:
        if "://" in url and "@" in url:
            scheme, rest = url.split("://", 1)
            # rest 形如 :password@host:port/db 或 user:password@host:port/db
            _, host_part = rest.split("@", 1)
            return f"{scheme}://***@{host_part}"
        return url
    except Exception:
        return "***"


async def get_redis() -> Optional[redis_async.Redis]:
    """
    获取全局 Redis 客户端单例（含自动重连）

    - 已连接：直接返回（ping 结果在 _PING_INTERVAL 秒内缓存，避免每次调用都 ping）
    - 未连接且距上次失败超过 _RECONNECT_INTERVAL：尝试重连（加锁串行化，双重检查）
    - 未连接且在重连冷却期内：返回 None

    :return: Redis 客户端实例；连接失败返回 None
    """
    global _redis_client, _redis_unavailable_logged, _last_fail_time
    global _reconnect_lock, _last_ping_ok

    if _redis_client is not None:
        # 已有客户端，检查是否仍可用（ping 结果缓存，降低性能损耗）
        now = time.time()
        if (now - _last_ping_ok) < _PING_INTERVAL:
            # ping 缓存有效，直接返回，跳过本次 ping
            return _redis_client
        try:
            await _redis_client.ping()
            _last_ping_ok = now
            return _redis_client
        except Exception as e:
            logger.warning(f"Redis 连接已断开，准备重连: {e}")
            try:
                await _redis_client.aclose()
            except Exception:
                pass
            _redis_client = None
            _last_ping_ok = 0.0
            _last_fail_time = time.time()

    # 重连冷却检查：避免高频重连
    now = time.time()
    if _last_fail_time > 0 and (now - _last_fail_time) < _RECONNECT_INTERVAL:
        return None

    # 懒加载重连锁（Lock 必须在事件循环内创建，避免跨循环绑定报错）
    if _reconnect_lock is None:
        _reconnect_lock = asyncio.Lock()

    # 串行化重连，避免多协程并发 from_url 创建客户端导致旧客户端泄漏与连接风暴
    async with _reconnect_lock:
        # 双重检查：持锁后再次确认是否已被其他协程重连成功
        if _redis_client is not None:
            return _redis_client

        # 尝试（重新）连接
        try:
            _redis_client = redis_async.from_url(
                REDIS_URL,
                password=REDIS_PASSWORD or None,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                retry_on_timeout=True,
                health_check_interval=30,  # 每 30 秒发送 PING 保活
            )
            await _redis_client.ping()
            _last_ping_ok = time.time()
            logger.info(f"Redis 连接成功: {_mask_url(REDIS_URL)}")
            _redis_unavailable_logged = False
            _last_fail_time = 0.0
            return _redis_client
        except Exception as e:
            if not _redis_unavailable_logged:
                logger.warning(f"Redis 不可用，限流将降级为内存模式: {e}")
                _redis_unavailable_logged = True
            else:
                logger.debug(f"Redis 重连失败: {e}")
            _redis_client = None
            _last_ping_ok = 0.0
            _last_fail_time = time.time()
            return None


async def close_redis():
    """
    关闭 Redis 连接（应用关闭时调用）
    """
    global _redis_client, _redis_unavailable_logged, _last_fail_time, _last_ping_ok
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception as e:
            logger.warning(f"关闭 Redis 连接异常: {e}")
        finally:
            _redis_client = None
            _redis_unavailable_logged = False
            _last_fail_time = 0.0
            _last_ping_ok = 0.0
