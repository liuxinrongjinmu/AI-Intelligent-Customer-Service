"""
通用重试工具：指数退避 + 断路器语义

用于业务 API 调用层，在网络抖动、临时故障时自动重试。
- 可重试异常：TimeoutException, HTTPStatusError(5xx), 网络错误
- 不可重试异常：HTTPStatusError(4xx), 参数校验错误
"""
import asyncio
import functools
import logging
import random
from typing import Callable, TypeVar, Any

import httpx

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# 可重试的 HTTP 状态码（5xx 服务端临时错误）
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}

# 默认重试配置
DEFAULT_MAX_RETRIES = 3        # 最大重试次数
DEFAULT_BASE_DELAY = 0.5       # 基础延迟（秒）
DEFAULT_MAX_DELAY = 10.0       # 最大延迟（秒）
DEFAULT_BACKOFF_FACTOR = 2.0   # 退避因子


def _is_retryable_error(exception: Exception) -> bool:
    """
    判断异常是否可重试

    :param exception: 捕获的异常
    :return: 是否可重试
    """
    # 超时错误 → 可重试
    if isinstance(exception, httpx.TimeoutException):
        return True

    # HTTP 状态错误 → 仅 5xx 可重试
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code in RETRYABLE_STATUS_CODES

    # 网络层错误 → 可重试
    if isinstance(exception, (httpx.NetworkError, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True

    # 其他异常默认不重试
    return False


def retry_on_transient_error(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
) -> Callable[[F], F]:
    """
    装饰器：为异步函数添加指数退避重试

    重试策略：指数退避 + 随机抖动（jitter）
    - 第1次重试：base_delay * (1 ± jitter) 秒
    - 第2次重试：base_delay * backoff_factor * (1 ± jitter) 秒
    - 第3次重试：base_delay * backoff_factor² * (1 ± jitter) 秒

    用法：
        @retry_on_transient_error(max_retries=3)
        async def my_api_call():
            ...

    :param max_retries: 最大重试次数
    :param base_delay: 基础延迟（秒）
    :param max_delay: 最大延迟（秒）
    :param backoff_factor: 退避因子
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    if attempt >= max_retries:
                        # 已达最大重试次数
                        logger.error(
                            f"[{func.__name__}] 重试耗尽 (attempt={attempt + 1}/{max_retries + 1}): {e}"
                        )
                        raise

                    if not _is_retryable_error(e):
                        # 不可重试的错误，直接抛出
                        logger.warning(
                            f"[{func.__name__}] 不可重试错误，直接抛出: {e}"
                        )
                        raise

                    # 计算延迟：指数退避 + 随机抖动
                    delay = min(
                        base_delay * (backoff_factor ** attempt),
                        max_delay,
                    )
                    jitter = random.uniform(0.75, 1.25)
                    actual_delay = delay * jitter

                    logger.warning(
                        f"[{func.__name__}] 重试 {attempt + 1}/{max_retries}, "
                        f"等待 {actual_delay:.1f}s, 错误: {e}"
                    )
                    await asyncio.sleep(actual_delay)

            # 理论上不会到达这里，但保留兜底
            raise last_exception  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator