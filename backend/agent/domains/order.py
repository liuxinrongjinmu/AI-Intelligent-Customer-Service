"""
订单查询节点：处理 order_query 和 logistics_query
"""
import logging

from backend.agent.state import AgentState
from backend.agent.retrieval_utils import clean_answer
from backend.utils.security import sanitize_output
from backend.utils.tool_logger import call_and_log
from backend.services.order_service import query_order, format_order_result, query_order_list, format_order_list_result
from backend.services.logistics_service import query_logistics, format_logistics_result

logger = logging.getLogger(__name__)


async def order_query_node(state: AgentState) -> dict:
    """订单查询节点：处理 order_query 和 logistics_query（订单+物流联动）"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_id = state.get("tenant_id", "")
    entities = state.get("intent_entities", {})
    intent = state.get("intent", "order_query")
    intent_sub_type = state.get("intent_sub_type", "")
    user_id = state.get("user_id", "")

    # 按子类分流：history_order → 查列表，其他 → 查详情
    if intent_sub_type == "history_order" and user_id:
        list_result = await call_and_log(
            tenant_id=tenant_id,
            tool_name="query_order_list",
            tool_params={"tenant_id": tenant_id, "user_id": user_id},
            func=query_order_list,
            conversation_id=state.get("thread_id", ""),
        )
        if list_result.get("success", False):
            formatted = format_order_list_result(list_result)
            return {"final_answer": formatted}
        if "暂未配置" in list_result.get("message", ""):
            return {"final_answer": '订单查询服务暂未配置，无法为您查询订单列表。如需帮助，请说"转人工"联系客服。'}
        answer = clean_answer(list_result.get("message", ""))
        return {"final_answer": sanitize_output(answer)}

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

        # 物流查询 → 优先从 OrderDetailsVO.expressList 获取，无则单独调物流接口
        if intent == "logistics_query" and api_result.get("data"):
            order_data = api_result.get("data")
            # 尝试从 expressList 直接提取物流（已随订单查询返回）
            express_list = None
            if isinstance(order_data, dict):
                express_list = order_data.get("expressList")
                order_no = order_data.get("orderNo") or order_keyword
            elif isinstance(order_data, list) and order_data:
                express_list = order_data[0].get("expressList") if isinstance(order_data[0], dict) else None
                order_no = order_data[0].get("orderNo") if isinstance(order_data[0], dict) else order_keyword
            else:
                order_no = order_keyword

            if express_list and len(express_list) > 0:
                # expressList 已有数据，直接格式化
                formatted += "\n\n" + format_logistics_result({"success": True, "data": express_list})
            else:
                # 无物流数据，单独查询
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
