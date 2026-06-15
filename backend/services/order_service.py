"""
订单查询服务：对接聚宝赞 ext-merchant API

接口：POST /api/v1/ext-merchant/order-details
"""
import logging
import httpx
from typing import Any
from backend.config import (
    ORDER_API_TIMEOUT,
    ORDER_SERVICE_NAME,
)
from backend.nacos.http_client import nacos_request
from backend.utils.retry import retry_on_transient_error

logger = logging.getLogger(__name__)

# 聚宝赞 ext-merchant API 路径
ORDER_DETAILS_PATH = "/api/v1/ext-merchant/order-details"


@retry_on_transient_error(max_retries=2)
async def _do_query_order(tenant_id: str, order_no: str) -> dict[str, Any]:
    """
    执行订单查询 HTTP 请求（含重试）

    :param tenant_id: 租户ID
    :param order_no: 订单号
    :return: API 响应 JSON
    """
    body: dict[str, Any] = {"tenantId": tenant_id, "orderNo": order_no}
    headers = {"Content-Type": "application/json"}

    response = await nacos_request(
        "POST",
        service_name=ORDER_SERVICE_NAME,
        path=ORDER_DETAILS_PATH,
        json_data=body,
        headers=headers,
        timeout=httpx.Timeout(ORDER_API_TIMEOUT),
    )
    return response.json()


async def query_order(
    tenant_id: str,
    order_no: str = "",
) -> dict[str, Any]:
    """
    查询订单信息，调用聚宝赞 order-details 接口

    :param tenant_id: 租户ID
    :param order_no: 订单号
    :return: {"success": bool, "data": dict | None, "message": str}
    """
    if not order_no:
        return {"success": False, "data": None, "message": "请提供订单号以查询订单信息"}

    try:
        result = await _do_query_order(tenant_id, order_no)
        return {
            "success": result.get("success", False),
            "data": result.get("data"),
            "message": result.get("message", ""),
        }
    except httpx.TimeoutException:
        logger.error(f"订单查询超时: tenant={tenant_id}, orderNo={order_no}")
        return {"success": False, "data": None, "message": "订单查询超时，请稍后重试"}
    except httpx.HTTPStatusError as e:
        logger.error(f"订单查询HTTP错误: tenant={tenant_id}, status={e.response.status_code}")
        return {"success": False, "data": None, "message": f"订单查询服务异常（{e.response.status_code}），请联系管理员"}
    except Exception as e:
        logger.error(f"订单查询异常: tenant={tenant_id}, error={e}")
        return {"success": False, "data": None, "message": "订单查询服务暂时不可用，请稍后重试或联系人工客服"}


def format_order_result(result: dict[str, Any]) -> str:
    """
    将订单查询结果格式化为人类可读的文本

    适配聚宝赞 OrderDetailsVO 结构：
    - orderNo: 订单号
    - status: 订单状态
    - fullOrderInfo: OrderFullInfoVO（含 title, totalFee, status, created, receiverName 等）

    :param result: query_order 返回的结果字典
    :return: 格式化后的文本
    """
    if not result.get("success", False):
        return result.get("message", "订单查询失败")

    data = result.get("data") or {}
    if not data:
        return "没有找到相关订单，请核实订单号后重试，或联系人工客服协助查询。"

    # 解析 OrderDetailsVO
    order_no = data.get("orderNo", "未知")
    status = _map_order_status(data.get("status", ""))
    full_info = data.get("fullOrderInfo") or {}

    title = full_info.get("title", "")
    total_fee = full_info.get("totalFee", "未知")
    created = full_info.get("created", "未知")
    receiver_name = full_info.get("receiverName", "")
    receiver_mobile = full_info.get("receiverMobile", "")
    receiver_address = full_info.get("receiverAddress", "")
    supplier_name = full_info.get("supplierName", "")
    sub_orders = full_info.get("subOrders") or []

    lines = [
        f"订单号：{order_no}",
        f"商品标题：{title}",
        f"金额：¥{total_fee}",
        f"订单状态：{status}",
        f"下单时间：{created}",
    ]

    if supplier_name:
        lines.append(f"供应商：{supplier_name}")

    if receiver_name or receiver_mobile or receiver_address:
        receiver_parts = []
        if receiver_name:
            receiver_parts.append(receiver_name)
        if receiver_mobile:
            receiver_parts.append(receiver_mobile)
        lines.append(f"收件人：{' '.join(receiver_parts)}")
        if receiver_address:
            lines.append(f"收件地址：{receiver_address}")

    # 子订单信息
    if sub_orders:
        lines.append("\n子订单：")
        for i, sub in enumerate(sub_orders):
            product_name = sub.get("productName", "")
            spec_name = sub.get("specName", "")
            quantity = sub.get("quantity", "")
            price = sub.get("price", "")
            shipping_status = sub.get("shippingStatus", "")
            sub_order_no = sub.get("subOrderNo", "")

            sub_line = f"  [{i + 1}] {product_name}"
            if spec_name:
                sub_line += f"（{spec_name}）"
            sub_line += f" × {quantity}  ¥{price}"
            if shipping_status:
                sub_line += f"  发货状态：{shipping_status}"
            if sub_order_no:
                sub_line = f"  [{i + 1}] 子订单号：{sub_order_no}  {product_name}"
                if spec_name:
                    sub_line += f"（{spec_name}）"
                sub_line += f" × {quantity}  ¥{price}"
                if shipping_status:
                    sub_line += f"  发货状态：{shipping_status}"
            lines.append(sub_line)

    return "\n".join(lines)


def _map_order_status(status: str) -> str:
    """
    映射订单状态为中文

    聚宝赞端常见状态值：UNPAID, PAID, SHIPPED, DELIVERED, COMPLETED, CANCELLED, REFUNDING, REFUNDED
    """
    status_map = {
        "UNPAID": "待付款",
        "PAID": "已付款",
        "SHIPPED": "已发货",
        "DELIVERED": "已签收",
        "COMPLETED": "已完成",
        "CANCELLED": "已取消",
        "REFUNDING": "退款中",
        "REFUNDED": "已退款",
        "pending": "待付款",
        "paid": "已付款",
        "shipped": "已发货",
        "delivered": "已签收",
        "completed": "已完成",
        "cancelled": "已取消",
        "refunding": "退款中",
        "refunded": "已退款",
    }
    return status_map.get(status, str(status))