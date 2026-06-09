"""
接口认证模块

认证策略：
- 服务间接口（聊天/同步/统计）：统一通过内网 VPN + Gateway 认证
  校验 X-Gateway-Verified 头 + 来源 IP 在 VPN 网段白名单内
- 管理接口（租户管理）：始终使用 ADMIN_API_KEY 认证（内部管理操作，不走 Gateway）
"""
import hmac
import logging
from fastapi import Request, HTTPException

from backend.config import ADMIN_API_KEY
from backend.middleware.gateway_auth import verify_gateway_request

logger = logging.getLogger(__name__)


# ─── 服务间接口认证（聊天/同步/统计） ─────────────────────────────────────


async def verify_chat_api_key(request: Request) -> str:
    """
    聊天接口认证（统一 Gateway 认证）

    校验 X-Gateway-Verified 头 + 来源 IP 在 VPN 网段白名单内

    :param request: FastAPI 请求对象
    :return: 认证通过的标识
    :raises HTTPException: 认证失败
    """
    return await verify_gateway_request(request)


async def verify_sync_api_key(request: Request) -> str:
    """
    知识同步接口认证（统一 Gateway 认证）

    校验 X-Gateway-Verified 头 + 来源 IP 在 VPN 网段白名单内

    :param request: FastAPI 请求对象
    :return: 认证通过的标识
    :raises HTTPException: 认证失败
    """
    return await verify_gateway_request(request)


# ─── 管理接口认证（始终 API Key，不走 Gateway） ────────────────────────────


async def verify_admin_key(request: Request) -> str:
    """
    管理接口认证（始终使用 ADMIN_API_KEY）

    管理接口是内部操作，不走 Gateway，始终需要 API Key 认证。

    :param request: FastAPI 请求对象
    :return: 认证通过的标识
    :raises HTTPException: 认证失败
    """
    api_key = request.headers.get("X-Admin-Key", "")
    if not api_key or not ADMIN_API_KEY:
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_FAILED", "message": "无效的 Admin API Key"}
        )
    if not hmac.compare_digest(api_key, ADMIN_API_KEY):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_FAILED", "message": "无效的 Admin API Key"}
        )
    return "admin_authed"
