"""
订单查询节点：处理 order_query 和 logistics_query
"""
import logging

from backend.agent.state import AgentState
from backend.agent.retrieval_utils import clean_answer
from backend.utils.security import sanitize_output
from backend.utils.tool_logger import call_and_log
from backend.services.order_service import query_order, format_order_result
from backend.services.logistics_service import query_logistics, format_logistics_result

logger = logging.getLogger(__name__)


async def order_query_node(state: AgentState) -> dict:
    """订单查询节点：处理 order_query 和 logistics_query（订单+物流联动）"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_id = state.get("tenant_id", "")
    entities = state.get("intent_entities", {})
    intent = state.get("intent", "order_query")

    order_keyword = entities.get("order_no", "") or entities.get("order_keyword", "")
    if not order_keyword:
        order_keyword = current_message

    thread_id = state.get("thread_id", "")
    api_result = await call_and_log(
        tenant_id=tenant_id,
        tool_name="query_order",
        tool_params={"tenant_id": tenant_id, "order_no": order_keyword},
        func=query_order,
        conversation_id=thread_id,
    )

    if api_result.get("success", False):
        formatted = format_order_result(api_result)
        logger.info(f"订单查询成功: tenant={tenant_id}, total={api_result.get('total', 0)}")

        # 物流查询 → 在订单结果后追加物流追踪
        if intent == "logistics_query" and api_result.get("data"):
            order_data = api_result.get("data")
            if isinstance(order_data, dict):
                order_no = order_data.get("orderNo") or order_keyword
            elif isinstance(order_data, list) and order_data and isinstance(order_data[0], dict):
                order_no = order_data[0].get("orderNo") or order_keyword
            else:
                order_no = order_keyword
            logistics_result = await call_and_log(
                tenant_id=tenant_id,
                tool_name="query_logistics",
                tool_params={"tenant_id": tenant_id, "order_no": order_no},
                func=query_logistics,
                conversation_id=thread_id,
            )
            if logistics_result.get("success", False):
                formatted += "\n\n" + format_logistics_result(logistics_result)
            elif "暂未配置" in logistics_result.get("message", ""):
                formatted += "\n\n物流信息暂未配置，请稍后重试或联系人工客服。"
            else:
                formatted += "\n\n暂无物流信息，您的订单可能尚未发货。"
        return {"final_answer": formatted}

    if "暂未配置" in api_result.get("message", ""):
        logger.warning(f"订单API未配置，返回明确提示: tenant={tenant_id}")
        return {"final_answer": '订单查询服务暂未配置，无法为您查询订单信息。如需帮助，请说"转人工"联系客服。'}

    answer = clean_answer(api_result.get("message", ""))
    answer = sanitize_output(answer)
    return {"final_answer": answer}
