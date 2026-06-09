"""
物流查询服务：对接聚宝赞 ext-merchant API

接口：POST /api/v1/ext-merchant/logistics
"""
import logging
import httpx
from typing import Any
from backend.config import (
    LOGISTICS_API_TIMEOUT,
    LOGISTICS_SERVICE_NAME,
)
from backend.middleware.http_client import get_shared_client
from backend.nacos.http_client import nacos_request

logger = logging.getLogger(__name__)

LOGISTICS_PATH = "/api/v1/ext-merchant/logistics"


async def query_logistics(
    tenant_id: str,
    order_no: str = "",
) -> dict[str, Any]:
    """
    查询物流信息，调用聚宝赞 logistics 接口

    请求参数映射 (LogisticsQueryDTO):
    - tenantId: 租户ID
    - orderNo: 订单号

    :param tenant_id: 租户ID
    :param order_no: 订单号
    :return: {success: bool, data: dict | None, message: str}
    """
    if not order_no:
        return {
            "success": False, "data": None,
            "message": "请提供订单号以查询物流信息",
        }

    try:
        body: dict[str, Any] = {
            "tenantId": tenant_id,
            "orderNo": order_no,
        }

        headers = {"Content-Type": "application/json"}

        client = get_shared_client()
        response = await nacos_request(
            "POST",
            service_name=LOGISTICS_SERVICE_NAME,
            path=LOGISTICS_PATH,
            json_data=body,
            headers=headers,
            timeout=httpx.Timeout(LOGISTICS_API_TIMEOUT),
        )
        result = response.json()
        return {
            "success": result.get("success", result.get("code", -1) == 0),
            "data": result.get("data"),
            "message": result.get("message", ""),
        }
    except httpx.TimeoutException:
        logger.error(f"物流查询超时: tenant={tenant_id}, order={order_no}")
        return {"success": False, "data": None, "message": "物流查询超时，请稍后重试"}
    except httpx.HTTPStatusError as e:
        logger.error(f"物流查询HTTP错误: tenant={tenant_id}, status={e.response.status_code}")
        return {"success": False, "data": None, "message": f"物流查询服务异常（{e.response.status_code}），请联系管理员"}
    except Exception as e:
        logger.error(f"物流查询异常: tenant={tenant_id}, error={e}")
        return {"success": False, "data": None, "message": "物流查询服务暂时不可用，请稍后重试或联系人工客服"}


def format_logistics_result(result: dict[str, Any]) -> str:
    """
    格式化物流查询结果为用户可读文本

    适配聚宝赞 LogisticsVO 结构：
    - expressList: array<ExpressInfoVO>
      ExpressInfoVO 含: name(快递公司), no(运单号), status, courier, courierPhone, trailList
    """
    if not result.get("success"):
        return result.get("message", "物流查询失败")

    data = result.get("data") or {}
    if not data:
        return "暂无物流信息"

    express_list = data.get("expressList") or []
    if not express_list:
        return "暂无物流信息"

    parts = []
    for idx, express in enumerate(express_list):
        name = express.get("name", "未知快递")
        no = express.get("no", "未知")
        status = express.get("status", "")
        courier = express.get("courier", "")
        courier_phone = express.get("courierPhone", "")
        trail_list = express.get("trailList") or []

        if len(express_list) > 1:
            parts.append(f"--- 快递 {idx + 1} ---")

        parts.append(f"快递公司：{name}")
        parts.append(f"运单号：{no}")
        if status:
            parts.append(f"当前状态：{status}")
        if courier:
            courier_info = courier
            if courier_phone:
                courier_info += f"（{courier_phone}）"
            parts.append(f"快递员：{courier_info}")

        if trail_list:
            parts.append("\n物流轨迹：")
            for t in trail_list[:5]:
                time_str = t.get("time", "")
                content = t.get("content", "")
                location = t.get("location", "")
                line = f"  {time_str}  {content}"
                if location:
                    line += f"  [{location}]"
                parts.append(line)

        if idx < len(express_list) - 1:
            parts.append("")

    return "\n".join(parts)