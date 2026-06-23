"""
优惠券查询服务：对接聚宝赞 ext-merchant API

接口：
- POST /api/v1/ext-merchant/coupon-list  查询买家优惠券列表
"""
import logging
from datetime import datetime, timedelta
import httpx
from typing import Any
from backend.config import (
    COUPON_API_TIMEOUT,
    COUPON_SERVICE_NAME,
)
from backend.nacos.http_client import nacos_request
from backend.utils.retry import retry_on_transient_error

logger = logging.getLogger(__name__)

COUPON_LIST_PATH = "/api/v1/ext-merchant/coupon-list"


@retry_on_transient_error(max_retries=2)
async def _do_query_coupon(tenant_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """
    执行优惠券查询 HTTP 请求（含重试）

    :param tenant_id: 租户ID
    :param body: 请求体
    :return: API 响应 JSON
    """
    headers = {"Content-Type": "application/json"}

    response = await nacos_request(
        "POST",
        service_name=COUPON_SERVICE_NAME,
        path=COUPON_LIST_PATH,
        json_data=body,
        headers=headers,
        timeout=httpx.Timeout(COUPON_API_TIMEOUT),
    )
    return response.json()


async def query_coupon(
    tenant_id: str,
    user_id: str = "",
    status: str = "",
    start_time: str = "",
    end_time: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """
    查询用户优惠券，调用聚宝赞 coupon-list 接口

    请求参数映射 (CouponListSearchDTO):
    - tenantId: 租户ID
    - buyerId: 买家ID ← user_id
    - couponId: 优惠券ID
    - couponType: 优惠券类型
    - page: 分页页码
    - pageSize: 每页数量
    - status: 券状态
    - startTime [必填]: 起始时间
    - endTime [必填]: 结束时间

    :param tenant_id: 租户ID
    :param user_id: 用户ID → buyerId
    :param status: 券状态
    :param start_time: 起始时间（ISO 8601，未提供时默认当前时间往前推1年）
    :param end_time: 结束时间（ISO 8601，未提供时默认当前时间往后推1年）
    :param page: 页码
    :param page_size: 每页数量
    :return: {success: bool, data: list[dict], total: int, message: str}
    """
    try:
        now = datetime.now()
        if not start_time:
            start_time = (now - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S")
        if not end_time:
            end_time = (now + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S")

        body: dict[str, Any] = {
            "tenantId": tenant_id,
            "page": page,
            "pageSize": page_size,
            "startTime": start_time,
            "endTime": end_time,
        }
        if user_id:
            body["buyerId"] = user_id
        if status:
            body["status"] = status

        result = await _do_query_coupon(tenant_id, body)

        success = result.get("success", result.get("code", -1) == 0)
        data = result.get("data")

        # CouponListVO: {list: array<CouponItemVO>}
        if isinstance(data, dict) and "list" in data:
            records = data.get("list", [])
        elif isinstance(data, list):
            records = data
        else:
            records = [data] if data else []

        return {
            "success": success,
            "data": records,
            "total": len(records),
            "message": result.get("message", ""),
        }
    except httpx.TimeoutException:
        logger.error(f"优惠券查询超时: tenant={tenant_id}, user={user_id}")
        return {"success": False, "data": [], "total": 0, "message": "优惠券查询超时，请稍后重试"}
    except httpx.HTTPStatusError as e:
        logger.error(f"优惠券查询HTTP错误: tenant={tenant_id}, status={e.response.status_code}")
        return {"success": False, "data": [], "total": 0, "message": f"优惠券查询服务异常（{e.response.status_code}），请联系管理员"}
    except Exception as e:
        logger.error(f"优惠券查询异常: tenant={tenant_id}, error={e}")
        return {"success": False, "data": [], "total": 0, "message": "优惠券查询服务暂时不可用，请稍后重试或联系人工客服"}


def format_coupon_result(result: dict[str, Any]) -> str:
    """
    格式化优惠券查询结果为用户可读文本

    适配 CouponItemVO 字段：
    - couponName → 优惠券名称
    - couponType → 类型
    - drawTime → 领取时间
    """
    if not result.get("success"):
        return result.get("message", "优惠券查询失败")

    data = result.get("data") or []
    if not data:
        return '您当前暂无可用的优惠券。可以在APP"我的-优惠券"中查看详情。'

    total = result.get("total", len(data))
    parts = [f"您共有 {total} 张优惠券：\n"]

    for i, coupon in enumerate(data[:5]):
        name = coupon.get("couponName", "优惠券")
        coupon_type = coupon.get("couponType", "")
        draw_time = coupon.get("drawTime", "")
        nick = coupon.get("nick", "")
        mobile = coupon.get("mobile", "")

        desc = f"{i + 1}. {name}"
        if coupon_type:
            desc += f"（类型：{coupon_type}）"
        if draw_time:
            desc += f"，领取时间：{draw_time}"
        if nick:
            desc += f"，用户：{nick}"
        if mobile:
            # 手机号脱敏，仅保留前3后4
            masked_mobile = mobile[:3] + "****" + mobile[-4:] if len(mobile) >= 7 else "****"
            desc += f"，手机：{masked_mobile}"
        parts.append(desc)

    return "\n".join(parts)