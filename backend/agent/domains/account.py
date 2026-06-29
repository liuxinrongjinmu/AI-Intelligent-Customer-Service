"""
账户查询节点：会员等级 / 积分 / 地址 / 安全
"""
import logging

from backend.agent.state import AgentState
from backend.utils.tool_logger import call_and_log
from backend.services.user_profile_service import query_user_profile, format_user_profile_result

logger = logging.getLogger(__name__)


async def account_query_node(state: AgentState) -> dict:
    """账户查询节点：处理 account_query"""
    tenant_id = state.get("tenant_id", "")
    intent_sub_type = state.get("intent_sub_type", "")
    entities = state.get("intent_entities", {})
    user_id = state.get("user_id", "") or entities.get("user_id", "")

    if intent_sub_type in ("membership_level", "points_balance"):
        thread_id = state.get("thread_id", "")
        api_result = await call_and_log(
            tenant_id=tenant_id,
            tool_name="query_user_profile",
            tool_params={"tenant_id": tenant_id, "user_id": user_id},
            func=query_user_profile,
            conversation_id=thread_id,
        )
        if api_result.get("success", False):
            formatted = format_user_profile_result(api_result)
            logger.info(f"用户画像查询成功: tenant={tenant_id}")
            return {"final_answer": formatted}
        else:
            msg = api_result.get("message", "")
            if "暂未配置" in msg:
                return {"final_answer": "账户查询服务暂未配置，如需帮助请联系人工客服。"}
            return {"final_answer": "抱歉，暂时无法查询您的账户信息，请稍后重试或联系人工客服。"}

    # membership_level / points_balance 在上方已通过 API 处理并返回
    messages_map = {
        "address_manage": '您可以在APP"我的-收货地址"中查看和管理地址信息。',
        "account_security": "账户安全问题需要核实身份，正在为您转接人工客服处理。",
    }
    reply = messages_map.get(intent_sub_type, "正在为您查询账户信息，请稍候。")
    return {"final_answer": reply}
