"""
知识库同步 API 单元测试
"""
import pytest
from unittest.mock import patch, MagicMock


class TestSyncKnowledge:
    """POST /api/v1/knowledge/sync/{tenant_id}/{kb_type}"""

    @patch("backend.api.knowledge.process_sync")
    def test_sync_full_success(self, mock_process, client_with_seed):
        """全量同步成功"""
        mock_process.return_value = {"processed_count": 3, "deleted_count": 2}
        resp = client_with_seed.post("/api/v1/knowledge/sync/test_tenant/faq", json={
            "sync_type": "full",
            "items": [
                {"id": "faq_001", "content": "退货政策是什么？\n7天无理由退货"},
                {"id": "faq_002", "content": "发货时间\n下单后24小时内发货"},
                {"id": "faq_003", "content": "运费规则\n满99元包邮"},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["synced_count"] == 3
        assert data["deleted_count"] == 2
        assert data["kb_type"] == "faq"

    @patch("backend.api.knowledge.process_sync")
    def test_sync_incremental_success(self, mock_process, client_with_seed):
        """增量同步成功"""
        mock_process.return_value = {"processed_count": 1, "deleted_count": 0}
        resp = client_with_seed.post("/api/v1/knowledge/sync/test_tenant/faq", json={
            "sync_type": "incremental",
            "items": [
                {"id": "faq_new", "content": "新FAQ"},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["synced_count"] == 1
        assert data["deleted_count"] == 0

    def test_sync_invalid_kb_type(self, client_with_seed):
        """无效的知识库类型"""
        resp = client_with_seed.post("/api/v1/knowledge/sync/test_tenant/invalid_type", json={
            "sync_type": "full",
            "items": [{"id": "1", "content": "test"}],
        })
        assert resp.status_code == 400

    def test_sync_tenant_not_found(self, client):
        """租户不存在"""
        resp = client.post("/api/v1/knowledge/sync/nonexistent/faq", json={
            "sync_type": "full",
            "items": [{"id": "1", "content": "test"}],
        })
        assert resp.status_code == 404

    def test_sync_empty_items(self, client_with_seed):
        """空 items 列表"""
        resp = client_with_seed.post("/api/v1/knowledge/sync/test_tenant/faq", json={
            "sync_type": "full",
            "items": [],
        })
        assert resp.status_code == 422

    def test_sync_too_many_items(self, client_with_seed):
        """超过 1000 条 items"""
        items = [{"id": f"item_{i}", "content": f"content_{i}"} for i in range(1001)]
        resp = client_with_seed.post("/api/v1/knowledge/sync/test_tenant/faq", json={
            "sync_type": "full",
            "items": items,
        })
        assert resp.status_code == 422

    def test_sync_invalid_item_id(self, client_with_seed):
        """item id 含非法字符"""
        resp = client_with_seed.post("/api/v1/knowledge/sync/test_tenant/faq", json={
            "sync_type": "full",
            "items": [{"id": "id with spaces", "content": "test"}],
        })
        assert resp.status_code == 422

    @patch("backend.api.knowledge.process_sync")
    def test_sync_public_kb_skips_tenant_check(self, mock_process, client):
        """public 知识库跳过租户校验"""
        mock_process.return_value = {"processed_count": 1, "deleted_count": 0}
        resp = client.post("/api/v1/knowledge/sync/any_tenant/public", json={
            "sync_type": "full",
            "items": [{"id": "pub_001", "content": "公共FAQ"}],
        })
        assert resp.status_code == 200


class TestSyncBatch:
    """POST /api/v1/knowledge/sync/{tenant_id}/{kb_type}/batch"""

    @patch("backend.api.knowledge.process_batch")
    def test_batch_add_only(self, mock_batch, client_with_seed):
        """仅添加"""
        mock_batch.return_value = {"processed_count": 2, "deleted_count": 0}
        resp = client_with_seed.post("/api/v1/knowledge/sync/test_tenant/faq/batch", json={
            "add": [
                {"id": "faq_new_1", "content": "新FAQ1"},
                {"id": "faq_new_2", "content": "新FAQ2"},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["synced_count"] == 2
        assert data["deleted_count"] == 0

    @patch("backend.api.knowledge.process_batch")
    def test_batch_delete_only(self, mock_batch, client_with_seed):
        """仅删除"""
        mock_batch.return_value = {"processed_count": 0, "deleted_count": 1}
        resp = client_with_seed.post("/api/v1/knowledge/sync/test_tenant/faq/batch", json={
            "delete_ids": ["faq_old_001"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted_count"] == 1

    @patch("backend.api.knowledge.process_batch")
    def test_batch_add_and_delete(self, mock_batch, client_with_seed):
        """同时添加和删除"""
        mock_batch.return_value = {"processed_count": 1, "deleted_count": 1}
        resp = client_with_seed.post("/api/v1/knowledge/sync/test_tenant/faq/batch", json={
            "add": [{"id": "faq_new", "content": "新FAQ"}],
            "delete_ids": ["faq_old"],
        })
        assert resp.status_code == 200

    def test_batch_both_empty(self, client_with_seed):
        """add 和 delete_ids 同时为空"""
        resp = client_with_seed.post("/api/v1/knowledge/sync/test_tenant/faq/batch", json={})
        assert resp.status_code == 422

    def test_batch_invalid_kb_type(self, client_with_seed):
        """无效知识库类型"""
        resp = client_with_seed.post("/api/v1/knowledge/sync/test_tenant/invalid/batch", json={
            "add": [{"id": "1", "content": "test"}],
        })
        assert resp.status_code == 400


class TestClearKnowledge:
    """DELETE /api/v1/knowledge/sync/{tenant_id}/{kb_type}"""

    @patch("backend.api.knowledge.clear_collection")
    def test_clear_success(self, mock_clear, client_with_seed):
        """清空知识库"""
        resp = client_with_seed.delete("/api/v1/knowledge/sync/test_tenant/faq")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        mock_clear.assert_called_once_with("test_tenant", "faq")

    def test_clear_invalid_kb_type(self, client_with_seed):
        """无效知识库类型"""
        resp = client_with_seed.delete("/api/v1/knowledge/sync/test_tenant/invalid")
        assert resp.status_code == 400

    def test_clear_tenant_not_found(self, client):
        """租户不存在"""
        resp = client.delete("/api/v1/knowledge/sync/nonexistent/faq")
        assert resp.status_code == 404


class TestSyncHistory:
    """GET /api/v1/knowledge/sync/{tenant_id}/history"""

    @patch("backend.knowledge.sync_log.get_sync_history")
    def test_get_history(self, mock_history, client_with_seed):
        """获取同步历史"""
        mock_history.return_value = [
            {"kb_type": "faq", "sync_type": "full", "item_count": 10, "status": "success"},
        ]
        resp = client_with_seed.get("/api/v1/knowledge/sync/test_tenant/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["history"]) == 1

    @patch("backend.knowledge.sync_log.get_sync_history")
    def test_get_history_empty(self, mock_history, client_with_seed):
        """空历史"""
        mock_history.return_value = []
        resp = client_with_seed.get("/api/v1/knowledge/sync/test_tenant/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["history"] == []

    @patch("backend.knowledge.sync_log.get_sync_history")
    def test_get_history_with_kb_type_filter(self, mock_history, client_with_seed):
        """按知识库类型过滤历史"""
        mock_history.return_value = []
        resp = client_with_seed.get("/api/v1/knowledge/sync/test_tenant/history", params={"kb_type": "faq"})
        assert resp.status_code == 200
        mock_history.assert_called_once_with("test_tenant", "faq", 20)
