"""
优惠券咨询节点
"""
import logging

from backend.agent.state import AgentState
from backend.utils.tool_logger import call_and_log
from backend.services.coupon_service import query_coupon, format_coupon_result

logger = logging.getLogger(__name__)


async def coupon_query_node(state: AgentState) -> dict:
    """优惠券咨询节点：处理 coupon_query"""
    tenant_id = state.get("tenant_id", "")
    intent_sub_type = state.get("intent_sub_type", "")
    entities = state.get("intent_entities", {})
    user_id = state.get("user_id", "") or entities.get("user_id", "")

    status_map = {
        "available_coupons": "available",
        "coupon_rules": "available",
        "coupon_expiring": "expiring",
        "coupon_unusable": "unusable",
    }
    status = status_map.get(intent_sub_type, "available")

    if not user_id:
        return {"final_answer": "查询优惠券需要登录后操作，请先登录后再试。如需帮助，可以联系人工客服。"}

    thread_id = state.get("thread_id", "")
    api_result = await call_and_log(
        tenant_id=tenant_id,
        tool_name="query_coupon",
        tool_params={"tenant_id": tenant_id, "user_id": user_id, "status": status},
        func=query_coupon,
        conversation_id=thread_id,
    )

    if api_result.get("success", False):
        formatted = format_coupon_result(api_result)
        logger.info(f"优惠券查询成功: tenant={tenant_id}, total={api_result.get('total', 0)}")
        return {"final_answer": formatted}

    messages_map = {
        "available_coupons": '正在为您查询可用优惠券，建议您也可以在APP"我的-优惠券"中查看。',
        "coupon_rules": "正在为您查询优惠券使用规则，请稍候。",
        "coupon_unusable": "正在为您排查优惠券不可用的原因，常见原因包括：未达使用门槛、商品不适用、已过期等。",
        "coupon_expiring": "正在为您查询即将过期的优惠券，请稍候。",
    }
    reply = messages_map.get(intent_sub_type, "正在为您查询优惠券信息，请稍候。")
    return {"final_answer": reply}
