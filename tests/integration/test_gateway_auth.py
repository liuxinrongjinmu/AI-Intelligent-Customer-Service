"""
Gateway 认证集成测试

验证 Gateway 认证中间件在各种场景下的行为：
1. 聊天接口双模式认证（前端直连放行 + Gateway 认证）
2. 同步接口 Gateway 认证（必须通过认证）
3. IP 白名单校验
4. 错误头/缺失头/错误 IP 的拒绝行为

前置条件：
  - 服务已启动在 http://localhost:8080
  - .env 中 GATEWAY_IP_WHITELIST 包含 127.0.0.1/32（测试环境）
"""
import os
import httpx
import pytest

SKIP = os.getenv("SKIP_E2E", "").lower() == "true"
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")


@pytest.mark.skipif(SKIP, reason="SKIP_E2E=true，跳过集成测试")
@pytest.mark.asyncio
async def test_chat_no_gateway_header_passes():
    """
    聊天接口：无 Gateway 头 → 放行（消费者前端直连）

    验证：聊天接口面向消费者，前端页面直接访问无需认证
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/chat/demo_001/stream",
            json={"message": "你好", "session_id": "gw_test_1", "user_id": "test_user"},
        )
    assert resp.status_code == 200, f"无 Gateway 头应放行，实际: {resp.status_code}"


@pytest.mark.skipif(SKIP, reason="SKIP_E2E=true，跳过集成测试")
@pytest.mark.asyncio
async def test_chat_valid_gateway_header_passes():
    """
    聊天接口：正确 Gateway 头 + 白名单 IP → 放行

    验证：服务间调用通过 Gateway 认证
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/chat/demo_001/stream",
            json={"message": "你好", "session_id": "gw_test_2", "user_id": "test_user"},
            headers={"X-Gateway-Verified": "true"},
        )
    assert resp.status_code == 200, f"正确 Gateway 头应放行，实际: {resp.status_code}"


@pytest.mark.skipif(SKIP, reason="SKIP_E2E=true，跳过集成测试")
@pytest.mark.asyncio
async def test_chat_invalid_gateway_header_rejected():
    """
    聊天接口：错误 Gateway 头值 → 401 拒绝

    验证：带了 Gateway 头但值不正确时，必须拒绝
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/chat/demo_001/stream",
            json={"message": "你好", "session_id": "gw_test_3", "user_id": "test_user"},
            headers={"X-Gateway-Verified": "false"},
        )
    assert resp.status_code == 401, f"错误 Gateway 头值应返回 401，实际: {resp.status_code}"


@pytest.mark.skipif(SKIP, reason="SKIP_E2E=true，跳过集成测试")
@pytest.mark.asyncio
async def test_chat_gateway_header_with_bad_ip_rejected():
    """
    聊天接口：正确 Gateway 头 + 非白名单 IP → 401 拒绝

    验证：即使带了正确的 Gateway 头，来源 IP 不在白名单内也必须拒绝
    模拟外部攻击者伪造 Gateway 头
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/chat/demo_001/stream",
            json={"message": "你好", "session_id": "gw_test_4", "user_id": "test_user"},
            headers={
                "X-Gateway-Verified": "true",
                "X-Real-IP": "8.8.8.8",  # 非白名单 IP
            },
        )
    assert resp.status_code == 401, f"非白名单 IP 应返回 401，实际: {resp.status_code}"


@pytest.mark.skipif(SKIP, reason="SKIP_E2E=true，跳过集成测试")
@pytest.mark.asyncio
async def test_sync_no_gateway_header_rejected():
    """
    同步接口：无 Gateway 头 → 401 拒绝

    验证：同步接口必须通过 Gateway 认证，不能前端直连
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/knowledge/sync/demo_001/faq",
            json={"sync_type": "full", "items": []},
        )
    assert resp.status_code == 401, f"同步接口无 Gateway 头应返回 401，实际: {resp.status_code}"


@pytest.mark.skipif(SKIP, reason="SKIP_E2E=true，跳过集成测试")
@pytest.mark.asyncio
async def test_sync_valid_gateway_header_passes():
    """
    同步接口：正确 Gateway 头 + 白名单 IP → 放行

    验证：服务间调用通过 Gateway 认证
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/knowledge/sync/demo_001/faq",
            json={"sync_type": "full", "items": []},
            headers={"X-Gateway-Verified": "true"},
        )
    # 认证通过后可能返回 200/400/422（空列表或格式问题），只要不是 401 就说明认证通过了
    assert resp.status_code != 401, f"正确 Gateway 头应放行（非 401），实际: {resp.status_code}"


@pytest.mark.skipif(SKIP, reason="SKIP_E2E=true，跳过集成测试")
@pytest.mark.asyncio
async def test_sync_gateway_header_with_bad_ip_rejected():
    """
    同步接口：正确 Gateway 头 + 非白名单 IP → 401 拒绝

    验证：IP 白名单对同步接口同样生效
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/knowledge/sync/demo_001/faq",
            json={"sync_type": "full", "items": []},
            headers={
                "X-Gateway-Verified": "true",
                "X-Real-IP": "8.8.8.8",
            },
        )
    assert resp.status_code == 401, f"非白名单 IP 应返回 401，实际: {resp.status_code}"


@pytest.mark.skipif(SKIP, reason="SKIP_E2E=true，跳过集成测试")
@pytest.mark.asyncio
async def test_admin_api_key_rejected_without_key():
    """
    管理接口：无 Admin API Key → 403 拒绝

    验证：管理接口始终需要 API Key 认证
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/tenant/create",
            json={"tenant_id": "test_no_key", "name": "测试租户"},
        )
    assert resp.status_code == 403, f"无 Admin Key 应返回 403，实际: {resp.status_code}"


@pytest.mark.skipif(SKIP, reason="SKIP_E2E=true，跳过集成测试")
@pytest.mark.asyncio
async def test_admin_api_key_with_wrong_key_rejected():
    """
    管理接口：错误 Admin API Key → 403 拒绝

    验证：错误的 API Key 必须拒绝
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/tenant/create",
            json={"tenant_id": "test_wrong_key", "name": "测试租户"},
            headers={"X-Admin-Key": "wrong-key"},
        )
    assert resp.status_code == 403, f"错误 Admin Key 应返回 403，实际: {resp.status_code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
