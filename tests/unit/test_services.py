"""
服务层单元测试

Mock 外部 HTTP 调用，验证业务逻辑（重试、降级、格式化）
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

from backend.services.order_service import format_order_result, _map_order_status
from backend.services.refund_service import process_refund, query_refund_status, format_refund_result
from backend.services.handoff_service import create_handoff_ticket, resolve_handoff_ticket


class TestFormatOrderResult:
    """订单结果格式化"""

    def test_format_success_basic(self):
        """基本成功格式化"""
        result = {
            "success": True,
            "data": {
                "orderNo": "DD20240101001",
                "status": "PAID",
                "fullOrderInfo": {
                    "title": "燕麦片500g",
                    "totalFee": "38.80",
                    "created": "2024-01-01 10:00:00",
                },
            },
        }
        text = format_order_result(result)
        assert "DD20240101001" in text
        assert "燕麦片500g" in text
        assert "38.80" in text
        assert "已付款" in text

    def test_format_success_with_sub_orders(self):
        """含子订单的格式化"""
        result = {
            "success": True,
            "data": {
                "orderNo": "DD001",
                "status": "SHIPPED",
                "fullOrderInfo": {
                    "title": "组合装",
                    "totalFee": "100",
                    "created": "2024-01-01",
                    "subOrders": [
                        {
                            "productName": "商品A",
                            "specName": "红色L码",
                            "quantity": 2,
                            "price": "50",
                            "shippingStatus": "已发货",
                            "subOrderNo": "SUB001",
                        },
                    ],
                },
            },
        }
        text = format_order_result(result)
        assert "商品A" in text
        assert "红色L码" in text
        assert "SUB001" in text

    def test_format_success_with_receiver(self):
        """含收件人信息"""
        result = {
            "success": True,
            "data": {
                "orderNo": "DD001",
                "status": "DELIVERED",
                "fullOrderInfo": {
                    "title": "商品",
                    "totalFee": "10",
                    "created": "2024-01-01",
                    "receiverName": "张三",
                    "receiverMobile": "138****8888",
                    "receiverAddress": "北京市朝阳区",
                },
            },
        }
        text = format_order_result(result)
        assert "张三" in text
        assert "138****8888" in text
        assert "北京市朝阳区" in text

    def test_format_failed_result(self):
        """失败的查询结果"""
        result = {"success": False, "message": "订单不存在"}
        text = format_order_result(result)
        assert text == "订单不存在"

    def test_format_success_no_data(self):
        """成功但无数据"""
        result = {"success": True, "data": None}
        text = format_order_result(result)
        assert "没有找到相关订单" in text

    def test_format_success_empty_data(self):
        """成功但空字典"""
        result = {"success": True, "data": {}}
        text = format_order_result(result)
        assert "订单号" in text  # 应该有默认值"未知"


class TestMapOrderStatus:
    """订单状态映射"""

    @pytest.mark.parametrize("status,expected", [
        ("UNPAID", "待付款"),
        ("PAID", "已付款"),
        ("SHIPPED", "已发货"),
        ("DELIVERED", "已签收"),
        ("COMPLETED", "已完成"),
        ("CANCELLED", "已取消"),
        ("REFUNDING", "退款中"),
        ("REFUNDED", "已退款"),
        ("pending", "待付款"),  # 小写也能映射
        ("paid", "已付款"),
        ("unknown_status", "unknown_status"),  # 未知状态原样返回
        ("", ""),
    ])
    def test_status_mapping(self, status, expected):
        assert _map_order_status(status) == expected


class TestOrderQuery:
    """订单查询服务（Mock HTTP）"""

    @patch("backend.services.order_service._do_query_order")
    @pytest.mark.asyncio
    async def test_query_order_success(self, mock_do_query):
        """查询成功"""
        mock_do_query.return_value = {
            "success": True,
            "data": {"orderNo": "DD001", "status": "PAID"},
        }
        from backend.services.order_service import query_order
        result = await query_order("tenant_001", "DD001")
        assert result["success"] is True
        assert result["data"]["orderNo"] == "DD001"

    @pytest.mark.asyncio
    async def test_query_order_empty_order_no(self):
        """空订单号"""
        from backend.services.order_service import query_order
        result = await query_order("tenant_001", "")
        assert result["success"] is False
        assert "请提供订单号" in result["message"]

    @patch("backend.services.order_service._do_query_order", side_effect=httpx.TimeoutException("timeout"))
    @pytest.mark.asyncio
    async def test_query_order_timeout(self, mock_do_query):
        """查询超时"""
        from backend.services.order_service import query_order
        result = await query_order("tenant_001", "DD001")
        assert result["success"] is False
        assert "超时" in result["message"]

    @patch("backend.services.order_service._do_query_order", side_effect=Exception("connection error"))
    @pytest.mark.asyncio
    async def test_query_order_general_error(self, mock_do_query):
        """查询异常"""
        from backend.services.order_service import query_order
        result = await query_order("tenant_001", "DD001")
        assert result["success"] is False
        assert "暂时不可用" in result["message"]


class TestRefundService:
    """退款服务（占位实现）"""

    @pytest.mark.asyncio
    async def test_process_refund_returns_unavailable(self):
        """退款处理返回暂不可用"""
        result = await process_refund("tenant_001", "DD001", "refund_only")
        assert result["success"] is False
        assert "暂未开放" in result["message"]
        assert result["need_confirmation"] is False

    @pytest.mark.asyncio
    async def test_query_refund_status_returns_unavailable(self):
        """退款查询返回暂不可用"""
        result = await query_refund_status("tenant_001", "DD001")
        assert result["success"] is False
        assert "暂未开放" in result["message"]

    def test_format_refund_result_failed(self):
        """格式化失败的退款结果"""
        result = {"success": False, "message": "退款查询失败"}
        text = format_refund_result(result)
        assert text == "退款查询失败"

    def test_format_refund_result_success_placeholder(self):
        """格式化成功的退款结果（占位）"""
        result = {"success": True, "message": ""}
        text = format_refund_result(result)
        assert "暂未开放" in text

    @pytest.mark.parametrize("action", ["refund_only", "return_refund", "exchange", "repair"])
    @pytest.mark.asyncio
    async def test_all_supported_actions(self, action):
        """所有支持的售后操作类型"""
        result = await process_refund("tenant_001", "DD001", action)
        assert result["success"] is False  # 都是占位返回


class TestHandoffService:
    """转人工工单服务"""

    @patch("backend.services.handoff_service.SessionLocal")
    def test_create_handoff_ticket_success(self, mock_session_local):
        """创建工单成功"""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_ticket = MagicMock()
        mock_ticket.id = 1
        mock_ticket.thread_id = "thread_001"
        mock_ticket.status = "pending"
        mock_ticket.reason = "user_request"
        mock_db.add.return_value = None
        mock_db.refresh.side_effect = lambda x: setattr(x, 'id', 1)

        result = create_handoff_ticket(
            tenant_id="tenant_001",
            conversation_id="conv_001",
            thread_id="thread_001",
            reason="user_request",
        )
        assert mock_db.add.called
        assert mock_db.commit.called

    @patch("backend.services.handoff_service.SessionLocal")
    def test_create_handoff_ticket_db_error(self, mock_session_local):
        """数据库异常时不抛出"""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_db.commit.side_effect = Exception("DB error")

        result = create_handoff_ticket(
            tenant_id="tenant_001",
            conversation_id="conv_001",
            thread_id="thread_001",
            reason="complaint",
        )
        # 应该有 error 字段而不是抛异常
        assert "error" in result or result.get("success") is False

    @patch("backend.services.handoff_service.SessionLocal")
    def test_resolve_handoff_ticket(self, mock_session_local):
        """解决工单"""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_ticket = MagicMock()
        mock_ticket.id = 1
        mock_ticket.status = "pending"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_ticket

        result = resolve_handoff_ticket("1", "resolved by agent")
        assert mock_db.commit.called
