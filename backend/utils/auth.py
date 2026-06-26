"""
接口认证模块

认证策略：
- 聊天接口：双模式认证
  - 带 X-Gateway-Verified 头：Gateway 认证（服务间调用，校验头值 + IP 白名单）
  - 不带 X-Gateway-Verified 头：
    - 生产环境（ENV=prod）：拒绝直连，必须通过 Gateway 认证
    - 开发/测试环境：允许前端直连放行（调试用），记录警告
- 同步/统计接口：Gateway 认证（仅服务间调用）
- 管理接口：ADMIN_API_KEY 认证（内部管理操作）
"""
import hmac
import logging
from fastapi import Request, HTTPException

from backend.config import ADMIN_API_KEY, GATEWAY_VERIFIED_HEADER
from backend.middleware.gateway_auth import verify_gateway_request

logger = logging.getLogger(__name__)


# ─── 聊天接口认证（双模式：前端直连放行 + Gateway 认证） ──────────────────────


async def verify_chat_api_key(request: Request) -> str:
    """
    聊天接口认证（双模式，按环境区分）

    1. 带 X-Gateway-Verified 头：走 Gateway 认证（服务间调用）
    2. 不带该头：
       - 生产环境：拒绝直连，必须通过 Gateway 认证
       - 开发/测试环境：允许前端直连放行（调试用）

    :param request: FastAPI 请求对象
    :return: 认证通过的标识
    :raises HTTPException: 认证失败
    """
    gateway_header = request.headers.get(GATEWAY_VERIFIED_HEADER, "")
    if gateway_header:
        # 带了 Gateway 头 → 服务间调用，必须通过完整认证
        return await verify_gateway_request(request)
    else:
        # 没带 Gateway 头 → 检查运行环境
        from backend.config import ENV
        if ENV == "prod":
            # 生产环境：必须通过 Gateway 认证，拒绝直连
            client_ip = request.client.host if request.client else "unknown"
            logger.warning(f"生产环境聊天接口直连被拒: IP={client_ip}")
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "GATEWAY_AUTH_REQUIRED",
                    "message": "生产环境必须通过 Gateway 认证访问"
                }
            )
        else:
            # 开发/测试环境：允许前端直连（调试用）
            client_ip = request.client.host if request.client else "unknown"
            logger.info(f"聊天接口前端直连放行(非生产环境): IP={client_ip}")
            return "chat_direct"


# ─── 服务间接口认证（同步/统计） ──────────────────────────────────────────


async def verify_sync_api_key(request: Request) -> str:
    """
    知识同步接口认证（统一 Gateway 认证）

    :param request: FastAPI 请求对象
    :return: 认证通过的标识
    :raises HTTPException: 认证失败
    """
    return await verify_gateway_request(request)


# ─── 管理接口认证（始终 API Key，不走 Gateway） ────────────────────────────


async def verify_admin_key(request: Request) -> str:
    """
    管理接口认证（始终使用 ADMIN_API_KEY）

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
