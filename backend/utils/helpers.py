"""
公共辅助函数
"""
import uuid
from datetime import datetime, timezone


def utcnow() -> datetime:
    """
    返回当前 UTC 时间（时区感知）

    替代已弃用的 datetime.utcnow()，返回带时区信息的 datetime 对象。
    Python 3.12+ 中 datetime.utcnow() 已标记为弃用。
    """
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    """
    生成 UUID 字符串

    统一替代各模型中重复定义的 generate_uuid() 函数。
    """
    return str(uuid.uuid4())
