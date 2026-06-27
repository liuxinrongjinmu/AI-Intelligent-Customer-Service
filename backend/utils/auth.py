"""
接口认证模块

认证策略：
- 聊天接口：三模式认证
  - JWT token（Authorization: Bearer <token>）→ JWT 验签
  - Gateway 静态令牌（X-Gateway-Verified + IP 白名单）→ 兼容旧版
  - 开发/测试环境无认证头 → 直连放行（调试用）
- 同步/统计接口：JWT 或 Gateway 认证（服务间调用）
- 管理接口：ADMIN_API_KEY 认证（内部管理操作）
"""
import hmac
import logging
from fastapi import Request, HTTPException

from backend.config import ADMIN_API_KEY
from backend.middleware.gateway_auth import verify_request, extract_identity

logger = logging.getLogger(__name__)


# ─── 聊天接口认证 ──────────────────────────────────────────────────────


async def verify_chat_api_key(request: Request) -> str:
    """
    聊天接口认证（三模式）

    1. 携带 JWT token 或 Gateway 头 → 走完整认证
    2. 开发/测试环境无认证头 → 允许前端直连（调试用）
    3. 生产环境无认证头 → 拒绝

    :return: 认证标识
    :raises HTTPException: 认证失败
    """
    # 检测是否有任何认证凭证
    has_jwt = request.headers.get("Authorization", "").startswith("Bearer ")
    has_gateway = bool(request.headers.get("X-Gateway-Verified", ""))
    has_auth = has_jwt or has_gateway

    if has_auth:
        return await verify_request(request)

    # 无认证凭证 → 按环境处理
    from backend.config import ENV
    client_ip = request.client.host if request.client else "unknown"

    if ENV == "prod":
        logger.warning(f"生产环境聊天接口直连被拒: IP={client_ip}")
        raise HTTPException(status_code=401, detail={
            "code": "AUTH_REQUIRED",
            "message": "生产环境必须通过 Gateway 认证或 JWT 认证访问"
        })
    else:
        logger.info(f"聊天接口直连放行(非生产): IP={client_ip}")
        # 直连模式下从请求体提取身份（由 API 层处理）
        return "chat_direct"


# ─── 服务间接口认证 ──────────────────────────────────────────────────────


async def verify_sync_api_key(request: Request) -> str:
    """知识同步接口认证（JWT 或 Gateway）"""
    return await verify_request(request)


# ─── 管理接口认证 ──────────────────────────────────────────────────────


async def verify_admin_key(request: Request) -> str:
    """管理接口认证（ADMIN_API_KEY）"""
    api_key = request.headers.get("X-Admin-Key", "")
    if not ADMIN_API_KEY or ADMIN_API_KEY == "change-me-admin-key":
        raise HTTPException(status_code=500, detail={
            "code": "ADMIN_NOT_CONFIGURED",
            "message": "管理接口未配置，请设置 ADMIN_API_KEY"
        })
    if not api_key or not hmac.compare_digest(api_key, ADMIN_API_KEY):
        raise HTTPException(status_code=403, detail={
            "code": "AUTH_FAILED",
            "message": "无效的 Admin API Key"
        })
    return "admin_authed"


# ─── 身份提取工具 ──────────────────────────────────────────────────────


def get_identity_from_request(request: Request) -> dict:
    """
    从请求中提取身份信息（门户 Header 优先，回退到 request.state）

    用于 chat.py 等需要知道当前租户和用户的接口
    """
    # 优先从 Gateway Header 提取
    identity = extract_identity(request)
    if identity.get("tenant_id"):
        return identity

    # 回退到认证时写入的 request.state
    if hasattr(request.state, "identity"):
        return request.state.identity

    return {"tenant_id": "", "user_id": "", "user_name": ""}
