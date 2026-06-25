"""
转人工工单管理 API 单元测试
"""
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.database import get_db
from backend.utils.auth import verify_admin_key
from backend.api.handoff import router as handoff_router


# ─── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def handoff_client(db_session):
    """
    包含 handoff 路由的 TestClient（覆盖认证和数据库依赖）

    :param db_session: 内存 SQLite 数据库会话
    :yield: TestClient 实例
    """
    app = FastAPI()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    async def override_admin_auth():
        return "test_admin_auth"

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_admin_key] = override_admin_auth
    app.include_router(handoff_router)

    yield TestClient(app)


# ─── 测试：GET /{tenant_id}/tickets ───────────────────────────────────────


class TestListHandoffTickets:
    """GET /api/v1/handoff/{tenant_id}/tickets"""

    @patch("backend.api.handoff.query_handoff_tickets")
    def test_list_tickets_success(self, mock_query, handoff_client):
        """正常查询工单列表"""
        mock_query.return_value = {
            "success": True,
            "total": 2,
            "tickets": [
                {"id": "t1", "tenant_id": "shop_001", "status": "pending"},
                {"id": "t2", "tenant_id": "shop_001", "status": "assigned"},
            ],
        }
        resp = handoff_client.get("/api/v1/handoff/shop_001/tickets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total"] == 2
        assert len(data["tickets"]) == 2
        mock_query.assert_called_once_with(
            tenant_id="shop_001", status="", limit=50, offset=0,
        )

    @patch("backend.api.handoff.query_handoff_tickets")
    def test_list_tickets_with_status_filter(self, mock_query, handoff_client):
        """按状态筛选工单"""
        mock_query.return_value = {
            "success": True,
            "total": 1,
            "tickets": [{"id": "t1", "status": "pending"}],
        }
        resp = handoff_client.get("/api/v1/handoff/shop_001/tickets?status=pending")
        assert resp.status_code == 200
        mock_query.assert_called_once_with(
            tenant_id="shop_001", status="pending", limit=50, offset=0,
        )

    @patch("backend.api.handoff.query_handoff_tickets")
    def test_list_tickets_with_pagination(self, mock_query, handoff_client):
        """分页查询工单"""
        mock_query.return_value = {
            "success": True,
            "total": 100,
            "tickets": [{"id": f"t{i}"} for i in range(10)],
        }
        resp = handoff_client.get("/api/v1/handoff/shop_001/tickets?limit=10&offset=20")
        assert resp.status_code == 200
        mock_query.assert_called_once_with(
            tenant_id="shop_001", status="", limit=10, offset=20,
        )

    @patch("backend.api.handoff.query_handoff_tickets")
    def test_list_tickets_empty_result(self, mock_query, handoff_client):
        """查询结果为空"""
        mock_query.return_value = {
            "success": True,
            "total": 0,
            "tickets": [],
        }
        resp = handoff_client.get("/api/v1/handoff/nonexistent/tickets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["tickets"] == []

    @patch("backend.api.handoff.query_handoff_tickets")
    def test_list_tickets_nonexistent_tenant(self, mock_query, handoff_client):
        """不存在的 tenant_id 仍返回空列表（由服务层决定）"""
        mock_query.return_value = {
            "success": True,
            "total": 0,
            "tickets": [],
        }
        resp = handoff_client.get("/api/v1/handoff/ghost_tenant/tickets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["tickets"] == []

    @patch("backend.api.handoff.query_handoff_tickets")
    def test_list_tickets_invalid_status_filter(self, mock_query, handoff_client):
        """无效的状态过滤值（服务层返回空）"""
        mock_query.return_value = {
            "success": True,
            "total": 0,
            "tickets": [],
        }
        resp = handoff_client.get("/api/v1/handoff/shop_001/tickets?status=invalid_status")
        assert resp.status_code == 200
        mock_query.assert_called_once_with(
            tenant_id="shop_001", status="invalid_status", limit=50, offset=0,
        )

    @patch("backend.api.handoff.query_handoff_tickets")
    def test_list_tickets_query_failed(self, mock_query, handoff_client):
        """查询失败返回 500"""
        mock_query.return_value = {
            "success": False,
            "message": "数据库连接超时",
        }
        resp = handoff_client.get("/api/v1/handoff/shop_001/tickets")
        assert resp.status_code == 500
        data = resp.json()
        assert data["detail"]["code"] == "QUERY_FAILED"
        assert "数据库连接超时" in data["detail"]["message"]

    def test_list_tickets_limit_exceeds_max(self, handoff_client):
        """limit 超过 200 上限返回 422"""
        resp = handoff_client.get("/api/v1/handoff/shop_001/tickets?limit=999")
        assert resp.status_code == 422

    def test_list_tickets_limit_below_min(self, handoff_client):
        """limit 小于 1 返回 422"""
        resp = handoff_client.get("/api/v1/handoff/shop_001/tickets?limit=0")
        assert resp.status_code == 422

    def test_list_tickets_offset_negative(self, handoff_client):
        """offset 为负数返回 422"""
        resp = handoff_client.get("/api/v1/handoff/shop_001/tickets?offset=-1")
        assert resp.status_code == 422


# ─── 测试：PUT /tickets/{ticket_id}/resolve ───────────────────────────────


class TestResolveTicket:
    """PUT /api/v1/handoff/tickets/{ticket_id}/resolve"""

    @patch("backend.api.handoff.resolve_handoff_ticket")
    def test_resolve_ticket_success(self, mock_resolve, handoff_client):
        """正常解决工单"""
        mock_resolve.return_value = {
            "success": True,
            "ticket": {"id": "t1", "status": "resolved", "assigned_to": "agent_001"},
        }
        resp = handoff_client.put("/api/v1/handoff/tickets/t1/resolve?assigned_to=agent_001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        mock_resolve.assert_called_once_with(ticket_id="t1", assigned_to="agent_001")

    @patch("backend.api.handoff.resolve_handoff_ticket")
    def test_resolve_ticket_without_assigned_to(self, mock_resolve, handoff_client):
        """解决工单不指定处理人"""
        mock_resolve.return_value = {
            "success": True,
            "ticket": {"id": "t1", "status": "resolved"},
        }
        resp = handoff_client.put("/api/v1/handoff/tickets/t1/resolve")
        assert resp.status_code == 200
        mock_resolve.assert_called_once_with(ticket_id="t1", assigned_to="")

    @patch("backend.api.handoff.resolve_handoff_ticket")
    def test_resolve_ticket_not_found(self, mock_resolve, handoff_client):
        """工单不存在返回 404"""
        mock_resolve.return_value = {
            "success": False,
            "message": "工单不存在",
        }
        resp = handoff_client.put("/api/v1/handoff/tickets/nonexistent/resolve")
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "NOT_FOUND"
        assert "工单不存在" in data["detail"]["message"]

    @patch("backend.api.handoff.resolve_handoff_ticket")
    def test_resolve_ticket_service_error(self, mock_resolve, handoff_client):
        """服务层异常返回 404（统一走 not found 分支）"""
        mock_resolve.return_value = {
            "success": False,
            "message": "数据库异常",
        }
        resp = handoff_client.put("/api/v1/handoff/tickets/t1/resolve")
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "NOT_FOUND"
