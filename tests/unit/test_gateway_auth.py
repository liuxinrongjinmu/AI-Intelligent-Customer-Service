"""
Gateway 认证核心逻辑单元测试

测试范围：
1. _is_ip_in_whitelist  — IP 白名单校验
2. _get_client_ip       — 客户端 IP 获取
3. verify_gateway_request — Gateway 头校验（集成校验）

运行方式：python -m pytest tests/unit/test_gateway_auth.py -v
"""
import ipaddress
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException

from backend.middleware import gateway_auth
from backend.middleware.gateway_auth import (
    _is_ip_in_whitelist,
    _get_client_ip,
    _parse_ip_whitelist,
    verify_gateway_request,
)


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

def _make_mock_request(
    headers: dict | None = None,
    client_host: str = "127.0.0.1",
    client_port: int = 54321,
) -> MagicMock:
    """
    构建模拟的 FastAPI Request 对象

    :param headers: 请求头字典
    :param client_host: 直连 IP
    :param client_port: 直连端口
    :return: MagicMock 模拟的 Request
    """
    request = MagicMock()
    request.headers = headers or {}
    request.client = MagicMock()
    request.client.host = client_host
    request.client.port = client_port
    return request


def _reset_ip_whitelist_cache():
    """清空 _parsed_networks 缓存，使下次 _parse_ip_whitelist 重新从 config 读取"""
    gateway_auth._parsed_networks.clear()


# ---------------------------------------------------------------------------
# TestGatewayAuth
# ---------------------------------------------------------------------------


class TestGatewayAuth:
    """Gateway 认证核心逻辑测试"""

    # ========================================================================
    # 1. _is_ip_in_whitelist — IP 白名单校验
    # ========================================================================

    def test_ip_10_0_0_5_in_10_slash_8(self, monkeypatch):
        """10.0.0.5 在 10.0.0.0/8 网段内 → True"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "10.0.0.0/8")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("10.0.0.5") is True

    def test_ip_192_168_1_1_in_192_168_slash_16(self, monkeypatch):
        """192.168.1.1 在 192.168.0.0/16 网段内 → True"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "192.168.0.0/16")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("192.168.1.1") is True

    def test_172_16_slash_12_network_boundary_min(self, monkeypatch):
        """172.16.0.0/12 网段最小值 172.16.0.0 → True"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "172.16.0.0/12")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("172.16.0.0") is True

    def test_172_16_slash_12_network_boundary_max(self, monkeypatch):
        """172.16.0.0/12 网段最大值 172.31.255.255 → True"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "172.16.0.0/12")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("172.31.255.255") is True

    def test_172_16_slash_12_outside_range(self, monkeypatch):
        """172.32.0.1 不在 172.16.0.0/12 内 → False"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "172.16.0.0/12")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("172.32.0.1") is False

    def test_ip_8_8_8_8_not_in_whitelist(self, monkeypatch):
        """8.8.8.8 不在默认白名单内 → False"""
        monkeypatch.setattr(
            gateway_auth, "GATEWAY_IP_WHITELIST", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
        )
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("8.8.8.8") is False

    def test_ipv6_address_in_whitelist(self, monkeypatch):
        """IPv6 地址 fd00::1 在 fd00::/8 网段内 → True"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "fd00::/8")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("fd00::1") is True

    def test_ipv6_address_not_in_whitelist(self, monkeypatch):
        """IPv6 地址 2001:db8::1 不在 fd00::/8 网段内 → False"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "fd00::/8")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("2001:db8::1") is False

    def test_ipv4_not_in_ipv6_whitelist(self, monkeypatch):
        """IPv4 地址不在纯 IPv6 白名单内 → False"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "fd00::/8")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("10.0.0.5") is False

    def test_empty_whitelist_returns_true_compat_mode(self, monkeypatch):
        """白名单为空字符串时返回 True（兼容模式）"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("8.8.8.8") is True
        assert _is_ip_in_whitelist("10.0.0.1") is True

    def test_whitelist_none_returns_true(self, monkeypatch):
        """白名单为 None 时返回 True"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", None)
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("8.8.8.8") is True

    def test_single_ip_format_slash_32(self, monkeypatch):
        """单 IP 格式 10.0.0.1/32 精确匹配 → True"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "10.0.0.1/32")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("10.0.0.1") is True

    def test_single_ip_format_slash_32_not_match(self, monkeypatch):
        """单 IP 格式 10.0.0.1/32 不匹配邻居地址 → False"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "10.0.0.1/32")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("10.0.0.2") is False

    def test_invalid_ip_string_returns_false(self, monkeypatch):
        """无效 IP 字符串返回 False"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "10.0.0.0/8")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("not-an-ip") is False

    def test_multiple_cidr_whitelist(self, monkeypatch):
        """多个 CIDR 网段白名单，匹配其中一个即通过"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16")
        _reset_ip_whitelist_cache()
        assert _is_ip_in_whitelist("10.10.10.10") is True
        assert _is_ip_in_whitelist("172.20.0.5") is True
        assert _is_ip_in_whitelist("192.168.100.200") is True
        assert _is_ip_in_whitelist("100.100.100.100") is False

    # ========================================================================
    # 2. _get_client_ip — 客户端 IP 获取
    # ========================================================================

    def test_x_real_ip_priority(self):
        """X-Real-IP 头存在时优先使用"""
        req = _make_mock_request(
            headers={"X-Real-IP": "10.0.0.1", "X-Forwarded-For": "192.168.1.1"},
        )
        assert _get_client_ip(req) == "10.0.0.1"

    def test_x_forwarded_for_fallback(self):
        """无 X-Real-IP 时使用 X-Forwarded-For 第一个 IP"""
        req = _make_mock_request(
            headers={"X-Forwarded-For": "192.168.1.100, 10.0.0.2, 172.16.0.1"},
        )
        assert _get_client_ip(req) == "192.168.1.100"

    def test_x_forwarded_for_single_ip(self):
        """X-Forwarded-For 只有单个 IP"""
        req = _make_mock_request(
            headers={"X-Forwarded-For": "172.16.5.5"},
        )
        assert _get_client_ip(req) == "172.16.5.5"

    def test_x_real_ip_with_multiple_entries(self):
        """X-Real-IP 包含多个值（逗号分隔），取第一个"""
        req = _make_mock_request(
            headers={"X-Real-IP": "10.0.0.5, 10.0.0.6"},
        )
        assert _get_client_ip(req) == "10.0.0.5"

    def test_direct_connection_ip(self):
        """无代理头时使用直连 IP """
        req = _make_mock_request(client_host="203.0.113.42")
        assert _get_client_ip(req) == "203.0.113.42"

    def test_x_real_ip_overrides_all(self):
        """X-Real-IP 优先级最高，覆盖 X-Forwarded-For 和直连 IP"""
        req = _make_mock_request(
            headers={
                "X-Real-IP": "10.10.10.10",
                "X-Forwarded-For": "first-proxy, second-proxy",
            },
            client_host="8.8.8.8",
        )
        assert _get_client_ip(req) == "10.10.10.10"

    def test_no_headers_no_client_returns_unknown(self):
        """request.client 为 None 时返回 'unknown'"""
        req = MagicMock()
        req.headers = {}
        req.client = None
        assert _get_client_ip(req) == "unknown"

    # ========================================================================
    # 3. verify_gateway_request — Gateway 头校验（集成校验）
    # ========================================================================

    @pytest.mark.asyncio
    async def test_correct_gateway_header_and_ip(self, monkeypatch):
        """正确的 Gateway 头 + IP 在白名单内 → 通过"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "10.0.0.0/8")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_HEADER", "X-Gateway-Verified")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_VALUE", "true")
        _reset_ip_whitelist_cache()

        req = _make_mock_request(
            headers={"X-Gateway-Verified": "true", "X-Real-IP": "10.0.0.1"},
        )
        result = await verify_gateway_request(req)
        assert result == "gateway_authed"

    @pytest.mark.asyncio
    async def test_wrong_gateway_header_value(self, monkeypatch):
        """错误的 Gateway 头值 → 401"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "10.0.0.0/8")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_HEADER", "X-Gateway-Verified")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_VALUE", "true")
        _reset_ip_whitelist_cache()

        req = _make_mock_request(
            headers={"X-Gateway-Verified": "false", "X-Real-IP": "10.0.0.1"},
        )
        with pytest.raises(HTTPException) as exc_info:
            await verify_gateway_request(req)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "GATEWAY_AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_missing_gateway_header(self, monkeypatch):
        """缺少 Gateway 头 → 401"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "10.0.0.0/8")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_HEADER", "X-Gateway-Verified")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_VALUE", "true")
        _reset_ip_whitelist_cache()

        req = _make_mock_request(
            headers={"X-Real-IP": "10.0.0.1"},
        )
        with pytest.raises(HTTPException) as exc_info:
            await verify_gateway_request(req)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "GATEWAY_AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_correct_header_but_ip_not_in_whitelist(self, monkeypatch):
        """正确 Gateway 头但 IP 不在白名单 → 401"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "10.0.0.0/8")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_HEADER", "X-Gateway-Verified")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_VALUE", "true")
        _reset_ip_whitelist_cache()

        req = _make_mock_request(
            headers={"X-Gateway-Verified": "true", "X-Real-IP": "8.8.8.8"},
        )
        with pytest.raises(HTTPException) as exc_info:
            await verify_gateway_request(req)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "GATEWAY_IP_FORBIDDEN"

    @pytest.mark.asyncio
    async def test_empty_whitelist_with_correct_header(self, monkeypatch):
        """白名单为空 + 正确 Gateway 头 → 通过（兼容模式）"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_HEADER", "X-Gateway-Verified")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_VALUE", "true")
        _reset_ip_whitelist_cache()

        req = _make_mock_request(
            headers={"X-Gateway-Verified": "true", "X-Real-IP": "8.8.8.8"},
        )
        result = await verify_gateway_request(req)
        assert result == "gateway_authed"

    @pytest.mark.asyncio
    async def test_empty_whitelist_without_header(self, monkeypatch):
        """白名单为空但缺少 Gateway 头 → 401（两者都必须满足）"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_HEADER", "X-Gateway-Verified")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_VALUE", "true")
        _reset_ip_whitelist_cache()

        req = _make_mock_request(
            headers={"X-Real-IP": "10.0.0.1"},
        )
        with pytest.raises(HTTPException) as exc_info:
            await verify_gateway_request(req)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "GATEWAY_AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_gateway_header_case_insensitive(self, monkeypatch):
        """Gateway 头值大小写不敏感 → 通过"""
        monkeypatch.setattr(gateway_auth, "GATEWAY_IP_WHITELIST", "10.0.0.0/8")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_HEADER", "X-Gateway-Verified")
        monkeypatch.setattr(gateway_auth, "GATEWAY_VERIFIED_VALUE", "true")
        _reset_ip_whitelist_cache()

        req = _make_mock_request(
            headers={"X-Gateway-Verified": "TRUE", "X-Real-IP": "10.0.0.1"},
        )
        result = await verify_gateway_request(req)
        assert result == "gateway_authed"

        # 再测混合大小写
        req2 = _make_mock_request(
            headers={"X-Gateway-Verified": "True", "X-Real-IP": "10.0.0.2"},
        )
        result2 = await verify_gateway_request(req2)
        assert result2 == "gateway_authed"