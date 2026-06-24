"""
监控统计 API 单元测试
"""
import pytest
from unittest.mock import patch, MagicMock


class TestHealthCheck:
    """GET /api/v1/system/health"""

    def test_health_returns_ok(self, client):
        """健康检查返回 ok"""
        resp = client.get("/api/v1/system/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestMetrics:
    """GET /api/v1/system/metrics"""

    def test_metrics_text_format(self, client):
        """Prometheus 文本格式指标"""
        resp = client.get("/api/v1/system/metrics")
        assert resp.status_code == 200
        assert "kefu_uptime_seconds" in resp.text
        assert "kefu_active_requests" in resp.text

    def test_metrics_json_format(self, client):
        """JSON 格式指标（prometheus_client 改造后仅提供 uptime + note）"""
        resp = client.get("/api/v1/system/metrics/json")
        assert resp.status_code == 200
        data = resp.json()
        assert "uptime_seconds" in data
        assert "note" in data


class TestCacheInfo:
    """GET /api/v1/system/cache"""

    def test_cache_info(self, client):
        """缓存统计"""
        resp = client.get("/api/v1/system/cache")
        assert resp.status_code == 200


class TestStats:
    """GET /api/v1/system/stats"""

    def test_stats_global(self, client_with_seed):
        """全局统计（不指定 tenant_id）"""
        resp = client_with_seed.get("/api/v1/system/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "全局"
        assert data["total_conversations"] >= 1
        assert data["total_messages"] >= 2
        assert "avg_messages_per_conversation" in data

    def test_stats_by_tenant(self, client_with_seed):
        """按租户统计"""
        resp = client_with_seed.get("/api/v1/system/stats", params={"tenant_id": "test_tenant"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "test_tenant"
        assert data["total_conversations"] >= 1

    def test_stats_nonexistent_tenant(self, client_with_seed):
        """不存在的租户返回 0 统计"""
        resp = client_with_seed.get("/api/v1/system/stats", params={"tenant_id": "nonexistent"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_conversations"] == 0

    def test_stats_days_validation(self, client):
        """days 参数边界校验"""
        resp = client.get("/api/v1/system/stats", params={"days": 0})
        assert resp.status_code == 422
        resp = client.get("/api/v1/system/stats", params={"days": 91})
        assert resp.status_code == 422
        resp = client.get("/api/v1/system/stats", params={"days": 1})
        assert resp.status_code == 200


class TestTicketStats:
    """GET /api/v1/system/stats/tickets"""

    def test_ticket_stats(self, client_with_seed):
        """工单统计"""
        resp = client_with_seed.get("/api/v1/system/stats/tickets", params={"tenant_id": "test_tenant"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "test_tenant"
        assert "tickets_by_reason" in data

    def test_ticket_stats_missing_tenant_id(self, client):
        """缺少 tenant_id 参数"""
        resp = client.get("/api/v1/system/stats/tickets")
        assert resp.status_code == 422


class TestKbHealth:
    """GET /api/v1/system/stats/kb-health"""

    @patch("backend.retrieval.vector_store.get_collection")
    def test_kb_health_all_healthy(self, mock_get_collection, client):
        """所有知识库健康"""
        mock_collection = MagicMock()
        mock_collection.count.return_value = 10
        mock_get_collection.return_value = mock_collection

        resp = client.get("/api/v1/system/stats/kb-health", params={"tenant_id": "test_tenant"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_status"] == "healthy"
        assert data["total_documents"] == 40  # 4 collections × 10

    @patch("backend.retrieval.vector_store.get_collection")
    def test_kb_health_all_empty(self, mock_get_collection, client):
        """所有知识库为空"""
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_get_collection.return_value = mock_collection

        resp = client.get("/api/v1/system/stats/kb-health", params={"tenant_id": "test_tenant"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_status"] == "warning"
        assert data["total_documents"] == 0

    @patch("backend.retrieval.vector_store.get_collection")
    def test_kb_health_collection_error(self, mock_get_collection, client):
        """知识库查询异常"""
        mock_get_collection.side_effect = Exception("ChromaDB connection failed")

        resp = client.get("/api/v1/system/stats/kb-health", params={"tenant_id": "test_tenant"})
        assert resp.status_code == 200
        data = resp.json()
        for col_info in data["collections"].values():
            assert col_info["status"] == "error"
