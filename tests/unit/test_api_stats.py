"""
监控 API 单元测试
"""
import pytest


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
