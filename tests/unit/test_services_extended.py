"""
服务层扩展测试

覆盖 coupon_service / logistics_service / product_service / user_profile_service / sync_service
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestCouponService:
    """优惠券服务测试"""

    @pytest.mark.asyncio
    @patch("backend.services.coupon_service.nacos_request", new_callable=AsyncMock)
    async def test_query_coupon_success(self, mock_nacos):
        """优惠券查询成功"""
        from backend.services.coupon_service import query_coupon
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "success": True, "data": {"list": [{"couponId": "c1", "couponName": "满100减20"}]}}
        mock_nacos.return_value = mock_response
        result = await query_coupon(tenant_id="t1", user_id="u1", status="available")
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("backend.services.coupon_service.nacos_request", new_callable=AsyncMock)
    async def test_query_coupon_timeout(self, mock_nacos):
        """优惠券查询超时"""
        from backend.services.coupon_service import query_coupon
        import httpx
        mock_nacos.side_effect = httpx.TimeoutException("timeout")
        result = await query_coupon(tenant_id="t1", user_id="u1")
        assert result["success"] is False
        assert "超时" in result.get("message", "") or "timeout" in result.get("message", "").lower()

    def test_format_coupon_with_mobile(self):
        """优惠券格式化含手机号脱敏"""
        from backend.services.coupon_service import format_coupon_result
        data = {"success": True, "data": [{"couponName": "满减券", "mobile": "13812345678"}], "total": 1}
        result = format_coupon_result(data)
        assert "138****5678" in result
        assert "13812345678" not in result


class TestLogisticsService:
    """物流服务测试"""

    @pytest.mark.asyncio
    @patch("backend.services.logistics_service.nacos_request", new_callable=AsyncMock)
    async def test_query_logistics_success(self, mock_nacos):
        """物流查询成功"""
        from backend.services.logistics_service import query_logistics
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "success": True, "data": {"expressList": [{"name": "顺丰", "no": "SF123", "courier": "张三", "courierPhone": "13912345678", "trailList": []}]}}
        mock_nacos.return_value = mock_response
        result = await query_logistics(tenant_id="t1", order_no="ORD001")
        assert result["success"] is True

    def test_format_logistics_masks_phone(self):
        """物流格式化含手机号脱敏"""
        from backend.services.logistics_service import format_logistics_result
        data = {"success": True, "data": {"expressList": [{"name": "顺丰", "no": "SF123", "courier": "张三", "courierPhone": "13912345678", "trailList": []}]}}
        result = format_logistics_result(data)
        assert "139****5678" in result
        assert "13912345678" not in result


class TestProductService:
    """商品服务测试"""

    @pytest.mark.asyncio
    @patch("backend.services.product_service.nacos_request", new_callable=AsyncMock)
    async def test_query_product_success(self, mock_nacos):
        """商品查询成功"""
        from backend.services.product_service import query_product
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "success": True, "data": {"name": "燕麦片", "price": 29.9}}
        mock_nacos.return_value = mock_response
        result = await query_product(tenant_id="t1", product_id="p1")
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("backend.services.product_service.nacos_request", new_callable=AsyncMock)
    async def test_query_product_empty_keyword(self, mock_nacos):
        """空关键词查询"""
        from backend.services.product_service import query_product
        result = await query_product(tenant_id="t1")
        assert result["success"] is False


class TestUserProfileService:
    """用户画像服务测试"""

    @pytest.mark.asyncio
    @patch("backend.services.user_profile_service.nacos_request", new_callable=AsyncMock)
    async def test_query_profile_success(self, mock_nacos):
        """用户画像查询成功"""
        from backend.services.user_profile_service import query_user_profile
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "success": True, "data": {"nickname": "测试用户", "phone": "13812345678"}}
        mock_nacos.return_value = mock_response
        result = await query_user_profile(tenant_id="t1", user_id="u1")
        assert result["success"] is True

    def test_format_profile_masks_phone(self):
        """用户画像格式化含手机号脱敏"""
        from backend.services.user_profile_service import format_user_profile_result
        data = {"success": True, "data": {"nickname": "测试", "phone": "13812345678", "levelName": "gold"}}
        result = format_user_profile_result(data)
        assert "138****5678" in result
        assert "13812345678" not in result


class TestSyncService:
    """知识同步服务测试"""

    @patch("backend.services.sync_service.get_embedding_model")
    @patch("backend.services.sync_service.add_to_collection_sync")
    @patch("backend.services.sync_service.get_collection")
    def test_process_sync_empty_items(self, mock_get_coll, mock_add, mock_embed):
        """空 items 同步返回 0"""
        from backend.services.sync_service import process_sync
        result = process_sync(tenant_id="t1", kb_type="faq", sync_type="incremental", items=[])
        assert result["processed_count"] == 0

    @patch("backend.services.sync_service.get_embedding_model")
    @patch("backend.services.sync_service.add_to_collection_sync")
    @patch("backend.services.sync_service.get_collection")
    @patch("backend.services.sync_service.chunk_items", return_value=[{"id": "1", "content": "测试", "metadata": {}}])
    def test_process_sync_single_item(self, mock_chunk, mock_get_coll, mock_add, mock_embed):
        """单条同步成功"""
        from backend.services.sync_service import process_sync
        mock_model = MagicMock()
        mock_model.embed_documents.return_value = [[0.1] * 128]
        mock_embed.return_value = mock_model
        mock_get_coll.return_value = MagicMock(get=MagicMock(return_value={"ids": []}))
        with patch("backend.knowledge.sync_log.record_sync_log"), \
             patch("backend.services.sync_service._persist_relational_records"):
            result = process_sync(
                tenant_id="t1", kb_type="faq", sync_type="incremental",
                items=[{"id": "1", "content": "测试", "metadata": {}}]
            )
            assert result["processed_count"] == 1
