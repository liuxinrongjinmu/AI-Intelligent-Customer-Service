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


def resolve_tenant_id(tenant_id: str) -> str | int:
    """
    将我方字符串 tenant_id 映射为聚宝赞端 int64 tenantId

    映射规则：
    1. 若 TENANT_ID_MAP 已配置且包含匹配项，返回对应的 int64 值
    2. 否则尝试将 tenant_id 转为 int（如 "123" → 123）
    3. 转换失败则原样返回字符串（需聚宝赞端兼容）

    :param tenant_id: 我方租户 ID（字符串）
    :return: 映射后的租户 ID（int 或 str）
    """
    from backend.config import TENANT_ID_MAP
    if TENANT_ID_MAP:
        for pair in TENANT_ID_MAP.split(","):
            pair = pair.strip()
            if ":" in pair:
                key, val = pair.split(":", 1)
                if key.strip() == tenant_id:
                    try:
                        return int(val.strip())
                    except ValueError:
                        return val.strip()
    # 尝试直接转 int
    try:
        return int(tenant_id)
    except (ValueError, TypeError):
        return tenant_id
