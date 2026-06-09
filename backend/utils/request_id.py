"""
请求链路追踪：X-Request-ID 上下文变量

提供 ContextVar 存储当前请求的 request_id，
供下游模块（如 chat.py）在日志中使用。
"""
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="unknown")


def get_request_id() -> str:
    """
    获取当前请求的链路追踪 ID

    :return: request_id 字符串
    """
    return request_id_var.get()