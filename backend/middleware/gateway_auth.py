"""
Gateway 认证中间件

支持双模式认证（通过 GATEWAY_AUTH_MODE 配置切换）：
1. JWT 模式：Authorization: Bearer <token>，验签后提取 claims
2. Static 模式：X-Gateway-Verified 头 + IP 白名单

身份识别：优先从 Gateway 注入的 Header 提取（X-Tenant-Id / X-Buyer-Id）

安全策略：
- JWT 验签使用 HS256，密钥来自配置 jwt_secret（可从 Nacos 获取）
- Static 模式仅使用 TCP 对端 IP，不信任可伪造的代理头
"""
from __future__ import annotations

import ipaddress
import logging
import threading
from typing import Optional

import jwt as pyjwt
from fastapi import Request, HTTPException

from backend.config import (
    GATEWAY_AUTH_MODE,
    JWT_SECRET,
    GATEWAY_VERIFIED_HEADER,
    GATEWAY_VERIFIED_VALUE,
    GATEWAY_IP_WHITELIST,
    GATEWAY_TRUST_HEADERS,
)

logger = logging.getLogger(__name__)

# ─── IP 白名单解析（线程安全懒加载）───────────────────────────────────────

_parsed_networks: list = []
_parse_lock = threading.Lock()
_parsed = False


def _parse_ip_whitelist() -> list:
    """解析 IP 白名单配置为网络对象列表"""
    global _parsed
    if _parsed:
        return _parsed_networks
    with _parse_lock:
        if _parsed:
            return _parsed_networks
        if not GATEWAY_IP_WHITELIST:
            _parsed = True
            return _parsed_networks
        for cidr in GATEWAY_IP_WHITELIST.split(","):
            cidr = cidr.strip()
            if not cidr:
                continue
            try:
                _parsed_networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError as e:
                logger.error(f"无效的 IP 网段: {cidr}, error={e}")
        _parsed = True
        return _parsed_networks


def _is_ip_in_whitelist(client_ip: str) -> bool:
    """检查 IP 是否在白名单内"""
    networks = _parse_ip_whitelist()
    if not networks:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return any(ip in net for net in networks)


def _get_client_ip(request: Request, trusted_proxy: bool = False) -> str:
    """获取客户端真实 IP"""
    if trusted_proxy:
        x_real_ip = request.headers.get("X-Real-IP")
        if x_real_ip:
            return x_real_ip.split(",")[0].strip()
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# ─── JWT 验签 ────────────────────────────────────────────────────────────

def verify_jwt_token(token: str) -> dict:
    """
    验证 JWT token 并返回 payload

    :param token: JWT token 字符串（不含 Bearer 前缀）
    :return: 解码后的 payload dict
    :raises HTTPException: 验签失败
    """
    if not JWT_SECRET:
        logger.error("JWT_SECRET 未配置，JWT 验签无法执行")
        raise HTTPException(
            status_code=500,
            detail={"code": "AUTH_CONFIG_ERROR", "message": "认证服务配置异常"}
        )

    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail={"code": "TOKEN_EXPIRED", "message": "JWT token 已过期"})
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail={"code": "TOKEN_INVALID", "message": f"JWT token 无效: {e}"})


def extract_jwt_from_request(request: Request) -> Optional[str]:
    """从请求中提取 JWT token（Bearer 格式）"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


# ─── 身份提取 ────────────────────────────────────────────────────────────

def extract_identity(request: Request) -> dict:
    """
    从 Gateway 注入的 Header 提取身份信息

    Header 来源（聚宝赞 PrincipalFilter.java 注入）：
    - X-Tenant-Id   → tenant_id
    - X-Buyer-Id    → user_id（消费者）
    - X-User-Id     → user_id（通用用户）
    - X-Agent-Id    → agent_id（坐席）
    - X-Admin-Id    → admin_id（管理员）
    - X-System      → system（系统身份类型）
    - X-Username    → user_name（用户名，URL编码）
    - X-Permissions → permissions（权限列表）

    :return: {"tenant_id": str, "user_id": str, "user_name": str}
    """
    identity = {}
    if GATEWAY_TRUST_HEADERS:
        identity["tenant_id"] = request.headers.get("X-Tenant-Id", "")
        identity["user_id"] = request.headers.get("X-Buyer-Id", "") or request.headers.get("X-User-Id", "")
        identity["user_name"] = request.headers.get("X-Username", "")
    return identity


# ─── 统一认证入口 ─────────────────────────────────────────────────────────

async def verify_request(request: Request) -> str:
    """
    统一认证入口：根据 GATEWAY_AUTH_MODE 选择认证策略

    - jwt:   验证 Authorization: Bearer <JWT>
    - static: 验证 X-Gateway-Verified 头 + IP 白名单
    - both:  优先 JWT，回退 static

    :return: 认证标识字符串
    :raises HTTPException: 所有认证方式均失败
    """
    client_ip = _get_client_ip(request)

    # JWT 认证
    if GATEWAY_AUTH_MODE in ("jwt", "both"):
        token = extract_jwt_from_request(request)
        if token:
            try:
                verify_jwt_token(token)
                # 将 Gateway Header 中的身份信息写入 request.state
                identity = extract_identity(request)
                request.state.identity = identity
                logger.debug(f"JWT 认证成功, identity={identity}")
                return "jwt_authed"
            except HTTPException:
                if GATEWAY_AUTH_MODE == "jwt":
                    raise  # jwt-only 模式直接拒绝
                # both 模式回退到 static

    # Static 令牌认证
    if GATEWAY_AUTH_MODE in ("static", "both"):
        gateway_header = request.headers.get(GATEWAY_VERIFIED_HEADER, "")
        if gateway_header and gateway_header.lower() == GATEWAY_VERIFIED_VALUE.lower():
            if _is_ip_in_whitelist(client_ip):
                identity = extract_identity(request)
                request.state.identity = identity
                return "static_authed"
            else:
                raise HTTPException(status_code=401, detail={
                    "code": "GATEWAY_IP_FORBIDDEN",
                    "message": f"来源 IP {client_ip} 不在白名单内"
                })

    # 所有认证方式均失败
    logger.warning(f"认证失败: IP={client_ip}, mode={GATEWAY_AUTH_MODE}")
    raise HTTPException(status_code=401, detail={
        "code": "AUTH_REQUIRED",
        "message": "请求未通过认证，请携带有效的 JWT token 或 Gateway 验证头"
    })


# ─── 向后兼容别名 ────────────────────────────────────────────────────────

# 保持旧函数名可用（同步/统计接口等原有调用方）
async def verify_gateway_request(request: Request) -> str:
    """向后兼容别名 → verify_request"""
    return await verify_request(request)
