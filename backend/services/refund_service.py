"""
退款/售后处理服务：聚宝赞端暂未提供相关 API

当前状态：
- 退款进度 API：聚宝赞端正在调整中，待后续补充
- 售后处理 API：暂未提供

本模块保留接口定义，所有调用返回"暂不可用"提示，
待聚宝赞端提供完整 API 后再行对接。
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_ACTIONS = ("refund_only", "return_refund", "exchange", "repair")


async def process_refund(
    tenant_id: str,
    order_no: str,
    action: str,
    reason: str = "",
    images: list[str] | None = None,
) -> dict[str, Any]:
    """
    处理售后申请（聚宝赞端暂未提供 API）

    :param tenant_id: 租户ID
    :param order_no: 订单号
    :param action: 操作类型（refund_only / return_refund / exchange / repair）
    :param reason: 售后原因
    :param images: 凭证图片URL列表
    :return: {success: bool, data: None, message: str, need_confirmation: bool}
    """
    logger.info(f"售后申请（暂不可用）: tenant={tenant_id}, order={order_no}, action={action}")
    return {
        "success": False,
        "data": None,
        "message": "退款/售后功能暂未开放，请联系人工客服处理",
        "need_confirmation": False,
    }


async def query_refund_status(
    tenant_id: str,
    order_no: str = "",
    refund_id: str = "",
) -> dict[str, Any]:
    """
    查询退款进度（聚宝赞端暂未提供 API）

    :param tenant_id: 租户ID
    :param order_no: 订单号
    :param refund_id: 退款单号
    :return: {success: bool, data: None, message: str}
    """
    logger.info(f"退款进度查询（暂不可用）: tenant={tenant_id}, order={order_no}")
    return {
        "success": False,
        "data": None,
        "message": "退款进度查询功能暂未开放，请联系人工客服处理",
    }


def format_refund_result(result: dict[str, Any]) -> str:
    """
    格式化退款查询结果为用户可读文本

    :param result: 退款查询结果字典
    :return: 格式化后的文本
    """
    if not result.get("success"):
        return result.get("message", "退款查询失败")
    return "退款功能暂未开放，请联系人工客服处理"
