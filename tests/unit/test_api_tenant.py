"""
租户管理 API 单元测试
"""
import pytest
from backend.models.tenant import Tenant


class TestCreateTenant:
    """POST /api/v1/tenant/create"""

    def test_create_tenant_success(self, client, db_session):
        """正常创建租户"""
        resp = client.post("/api/v1/tenant/create", json={
            "name": "新商家",
            "tenant_id": "new_shop_001",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "new_shop_001"
        assert data["name"] == "新商家"
        assert data["is_active"] is True
        assert len(data["api_key"]) > 0

    def test_create_tenant_duplicate(self, client_with_seed, db_with_seed):
        """重复创建租户返回 409"""
        resp = client_with_seed.post("/api/v1/tenant/create", json={
            "name": "测试商家",
            "tenant_id": "test_tenant",
        })
        assert resp.status_code == 409

    def test_create_tenant_invalid_id_format(self, client):
        """tenant_id 格式不合法（1位太短）"""
        resp = client.post("/api/v1/tenant/create", json={
            "name": "商家",
            "tenant_id": "a",  # 太短（最少2位）
        })
        assert resp.status_code == 422

    def test_create_tenant_id_with_special_chars(self, client):
        """tenant_id 含特殊字符"""
        resp = client.post("/api/v1/tenant/create", json={
            "name": "商家",
            "tenant_id": "shop-001!",  # 含非法字符
        })
        assert resp.status_code == 422

    def test_create_tenant_missing_name(self, client):
        """缺少 name 字段"""
        resp = client.post("/api/v1/tenant/create", json={
            "tenant_id": "shop_002",
        })
        assert resp.status_code == 422

    def test_create_tenant_missing_tenant_id(self, client):
        """缺少 tenant_id 字段"""
        resp = client.post("/api/v1/tenant/create", json={
            "name": "商家",
        })
        assert resp.status_code == 422

    def test_create_tenant_empty_name(self, client):
        """name 为空字符串"""
        resp = client.post("/api/v1/tenant/create", json={
            "name": "",
            "tenant_id": "shop_003",
        })
        assert resp.status_code == 422

    def test_create_tenant_name_too_long(self, client):
        """name 超过 100 字符"""
        resp = client.post("/api/v1/tenant/create", json={
            "name": "x" * 101,
            "tenant_id": "shop_004",
        })
        assert resp.status_code == 422

    def test_create_tenant_persists_to_db(self, client, db_session):
        """创建后数据库中存在记录"""
        resp = client.post("/api/v1/tenant/create", json={
            "name": "持久化测试",
            "tenant_id": "persist_001",
        })
        assert resp.status_code == 200
        tenant = db_session.query(Tenant).filter_by(tenant_id="persist_001").first()
        assert tenant is not None
        assert tenant.name == "持久化测试"
        assert tenant.is_active is True
        assert tenant.api_key_hash is not None
        assert tenant.api_key_prefix is not None
