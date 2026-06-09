"""
Gateway 认证中间件

生产模式下，服务间接口调用通过内网 VPN + Gateway 中转，
不再使用 API Key 认证，而是信任 Gateway 转发的请求。

校验逻辑：
1. 请求必须携带 X-Gateway-Verified 头（由 Gateway 注入）
2. 请求来源 IP 必须在 VPN 网段白名单内
3. 两个条件同时满足才放行

这确保了：
- 外部请求无法伪造 Gateway 头（因为不在 VPN 网段内）
- Gateway 本身的身份由 VPN 网络层保证
"""
import ipaddress
import logging
from fastapi import Request, HTTPException

from backend.config import (
    GATEWAY_VERIFIED_HEADER, GATEWAY_VERIFIED_VALUE, GATEWAY_IP_WHITELIST,
)

logger = logging.getLogger(__name__)

# 解析 IP 白名单（启动时一次性解析）
_parsed_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []


def _parse_ip_whitelist() -> list:
    """
    解析 IP 白名单配置为网络对象列表

    :return: IPv4Network / IPv6Network 列表
    """
    if _parsed_networks:
        return _parsed_networks

    if not GATEWAY_IP_WHITELIST:
        logger.warning("GATEWAY_IP_WHITELIST 未配置，Gateway 认证将接受所有来源 IP")
        return []

    for cidr in GATEWAY_IP_WHITELIST.split(","):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            _parsed_networks.append(network)
        except ValueError as e:
            logger.error(f"无效的 IP 网段配置: {cidr}, 错误: {e}")

    logger.info(f"Gateway IP 白名单已加载: {[str(n) for n in _parsed_networks]}")
    return _parsed_networks


def _is_ip_in_whitelist(client_ip: str) -> bool:
    """
    检查客户端 IP 是否在白名单网段内

    :param client_ip: 客户端 IP 地址
    :return: 是否在白名单内
    """
    networks = _parse_ip_whitelist()
    if not networks:
        # 白名单为空时允许所有（需配合 Gateway 头校验）
        return True

    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    return any(ip in network for network in networks)


def _get_client_ip(request: Request) -> str:
    """
    获取客户端真实 IP（考虑代理转发）

    优先级：X-Real-IP > X-Forwarded-For 第一个 > request.client.host

    :param request: FastAPI 请求对象
    :return: 客户端 IP 地址
    """
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.split(",")[0].strip()

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if request.client:
        return request.client.host

    return "unknown"


async def verify_gateway_request(request: Request) -> str:
    """
    Gateway 认证校验

    校验条件（必须同时满足）：
    1. 请求携带 X-Gateway-Verified 头，值为 "true"（由 Gateway 注入）
    2. 请求来源 IP 在 VPN 网段白名单内

    :param request: FastAPI 请求对象
    :return: 认证通过的标识
    :raises HTTPException: 认证失败
    """
    # 1. 校验 Gateway 头
    gateway_header = request.headers.get(GATEWAY_VERIFIED_HEADER, "")
    if gateway_header.lower() != GATEWAY_VERIFIED_VALUE.lower():
        client_ip = _get_client_ip(request)
        logger.warning(f"Gateway 认证失败：缺少或无效的 {GATEWAY_VERIFIED_HEADER} 头, IP={client_ip}")
        raise HTTPException(
            status_code=401,
            detail={
                "code": "GATEWAY_AUTH_REQUIRED",
                "message": "请求未经过 Gateway 认证，请通过内网 Gateway 访问"
            }
        )

    # 2. 校验来源 IP
    client_ip = _get_client_ip(request)
    if not _is_ip_in_whitelist(client_ip):
        logger.warning(f"Gateway 认证失败：来源 IP 不在白名单内, IP={client_ip}")
        raise HTTPException(
            status_code=401,
            detail={
                "code": "GATEWAY_IP_FORBIDDEN",
                "message": "请求来源 IP 不在允许的网段内"
            }
        )

    return "gateway_authed"
