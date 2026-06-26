"""
投诉处理节点
"""
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from backend.agent.state import AgentState
from backend.agent.prompts import COMPLAINT_PROMPT
from backend.agent.llm_utils import safe_llm_stream, get_generate_llm
from backend.agent.retrieval_utils import format_history, clean_answer
from backend.utils.security import sanitize_output

logger = logging.getLogger(__name__)


async def complaint_node(state: AgentState) -> dict:
    """投诉处理节点：表达歉意并总结问题，转接人工客服"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_name = state.get("tenant_name", "平台")
    entities = state.get("intent_entities", {})
    complaint_reason = entities.get("reason", "") or entities.get("complaint", "")
    history = format_history(messages[:-1]) if len(messages) > 1 else "（无历史对话）"

    user_context = current_message
    if complaint_reason:
        user_context = f"投诉原因: {complaint_reason}\n原始消息: {current_message}"
    if history != "（无历史对话）":
        user_context = f"对话历史:\n{history}\n\n当前投诉: {user_context}"

    llm = get_generate_llm(streaming=True)
    raw = await safe_llm_stream(
        llm,
        [
            SystemMessage(content=COMPLAINT_PROMPT.format(tenant_name=tenant_name, message=current_message)),
            HumanMessage(content=user_context)
        ],
        fallback_text="非常抱歉给您带来不好的体验，我们已记录您的投诉，将尽快安排专人处理。",
        node_name="complaint_node"
    )
    answer = clean_answer(raw)
    answer = sanitize_output(answer)
    logger.info(f"投诉回复: length={len(answer)}")
    return {"final_answer": answer}
