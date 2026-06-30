"""
服务层单元测试

Mock 外部 HTTP 调用，验证业务逻辑（重试、降级、格式化）
"""
import pytest
from unittest.mock import patch, MagicMock

from backend.services.order_service import format_order_result, _map_order_status
from backend.services.handoff_service import create_handoff_ticket, resolve_handoff_ticket


class TestFormatOrderResult:
    """订单结果格式化（适配 OrderDetailVO 扁平结构）"""

    def test_format_success_basic(self):
        """基本成功格式化"""
        result = {
            "success": True,
            "data": {
                "orderNo": "DD20240101001",
                "status": "PAID",
                "title": "燕麦片500g",
                "totalFee": "38.80",
                "created": "2024-01-01 10:00:00",
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
                "title": "商品",
                "totalFee": "10",
                "created": "2024-01-01",
                "receiverName": "张三",
                "receiverMobile": "138****8888",
                "receiverAddress": "北京市朝阳区",
            },
        }
        text = format_order_result(result)
        assert "张三" in text
        assert "138****8888" in text
        assert "北京市朝阳区" in text

    def test_format_failed_result(self):
        """失败结果返回消息"""
        result = {"success": False, "message": "订单不存在"}
        text = format_order_result(result)
        assert "订单不存在" in text

    def test_format_success_no_data(self):
        """成功但无数据"""
        result = {"success": True, "data": None}
        text = format_order_result(result)
        assert "没有找到" in text

    def test_format_success_empty_data(self):
        """成功但 data 为空"""
        result = {"success": True}
        text = format_order_result(result)
        assert "没有找到" in text


class TestMapOrderStatus:
    """订单状态映射测试"""

    @pytest.mark.parametrize("status_code,expected", [
        ("UNPAID", "待付款"),
        ("PAID", "已付款"),
        ("SHIPPED", "已发货"),
        ("DELIVERED", "已签收"),
        ("COMPLETED", "已完成"),
        ("CANCELLED", "已取消"),
        ("REFUNDING", "退款中"),
        ("REFUNDED", "已退款"),
        ("unpaid", "unpaid"),  # 大小写敏感，未匹配时返回原值
        ("unknown_status", "unknown_status"),
        ("", ""),
    ])
    def test_map_order_status(self, status_code, expected):
        assert _map_order_status(status_code) == expected


class TestHandoffService:
    """转人工工单服务"""

    @patch("backend.services.handoff_service.get_db_session")
    def test_create_handoff_ticket_success(self, mock_session_local):
        """创建工单成功"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_session_local.return_value = mock_db
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

    @patch("backend.services.handoff_service.get_db_session")
    def test_create_handoff_ticket_db_error(self, mock_session_local):
        """数据库异常时不抛出"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_session_local.return_value = mock_db
        mock_db.commit.side_effect = Exception("DB error")

        result = create_handoff_ticket(
            tenant_id="tenant_001",
            conversation_id="conv_001",
            thread_id="thread_001",
            reason="complaint",
        )
        assert "error" in result or result.get("success") is False

    @patch("backend.services.handoff_service.get_db_session")
    def test_resolve_handoff_ticket(self, mock_session_local):
        """解决工单"""
        mock_db = MagicMock()
        mock_db.__enter__.return_value = mock_db
        mock_session_local.return_value = mock_db
        mock_ticket = MagicMock()
        mock_ticket.id = 1
        mock_ticket.status = "pending"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_ticket

        result = resolve_handoff_ticket("1", "resolved by agent")
        assert mock_db.commit.called
