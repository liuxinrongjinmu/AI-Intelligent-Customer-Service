"""
转人工服务节点
"""
import asyncio
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from backend.agent.state import AgentState
from backend.agent.prompts import HUMAN_SERVICE_PROMPT
from backend.agent.llm_utils import safe_llm_stream, get_generate_llm
from backend.agent.retrieval_utils import format_history, clean_answer
from backend.utils.security import sanitize_output
from backend.utils.metrics import record_handoff
from backend.services.handoff_service import create_handoff_ticket

logger = logging.getLogger(__name__)


async def human_service_node(state: AgentState) -> dict:
    """转人工服务节点：创建工单 + 更新会话状态 + 生成转接回复"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_name = state.get("tenant_name", "平台")
    tenant_id = state.get("tenant_id", "")
    intent_sub_type = state.get("intent_sub_type", "")
    history = format_history(messages[:-1]) if len(messages) > 1 else "（无历史对话）"
    user_id = state.get("user_id", "")
    user_name = state.get("user_name", "")
    thread_id = state.get("thread_id", "")

    reason_map = {
        "user_request": "user_request",
        "complaint": "complaint",
        "emotional": "emotional",
        "sensitive_operation": "sensitive_operation",
        "ai_limitation": "ai_limitation",
    }
    reason = reason_map.get(intent_sub_type, "user_request")

    # 创建转人工工单（10s 超时保护）
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                create_handoff_ticket,
                tenant_id=tenant_id,
                conversation_id=thread_id,
                thread_id=thread_id,
                reason=reason,
                reason_detail=f"用户消息: {current_message[:200]}",
                summary=history[:500],
                user_id=user_id,
                user_name=user_name,
            ),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        logger.error(f"创建转人工工单超时: tenant={tenant_id}, thread={thread_id}")
        return {"final_answer": "抱歉，转人工服务暂时不可用，请稍后重试或拨打客服热线。"}

    # 更新会话状态为"人工接待中"（失败重试 1 次，写库失败不阻塞转人工回复）
    for attempt in range(2):
        try:
            from backend.database import SessionLocal
            from backend.models.conversation import Conversation
            with SessionLocal() as db:
                conv = db.query(Conversation).filter_by(thread_id=thread_id).first()
                if conv and conv.status == "ai_serving":
                    conv.transfer_to_human(
                        priority=5, summary=history[:500],
                        tags=["转人工", reason],
                    )
                    db.commit()
                    logger.info(f"会话状态已更新为 human_serving: thread={thread_id}")
            break
        except Exception as e:
            if attempt == 0:
                logger.warning(f"更新会话状态失败(第1次), 准备重试: {e}")
                await asyncio.sleep(0.5)
            else:
                logger.error(f"更新会话状态最终失败: {e}")

    record_handoff()

    # 保留 ai_failed_count 用于后台审计：AI 连续失败转人工 vs 用户主动转人工
    ai_failed_count = state.get("ai_failed_count", 0)

    if intent_sub_type == "ai_limitation":
        return {
            "final_answer": "抱歉未能完全理解您的问题，正在为您转接人工客服，请稍候。人工客服可以更准确地解答您的问题。",
            "ai_failed_count": ai_failed_count,
        }

    user_context = current_message
    if history != "（无历史对话）":
        user_context = f"对话历史:\n{history}\n\n当前请求: {current_message}"

    llm = get_generate_llm(streaming=True)
    raw = await safe_llm_stream(
        llm,
        [
            SystemMessage(content=HUMAN_SERVICE_PROMPT.format(tenant_name=tenant_name, message=current_message)),
            HumanMessage(content=user_context)
        ],
        fallback_text="正在为您转接人工客服，请稍候。",
        node_name="human_service_node"
    )
    answer = clean_answer(raw)
    answer = sanitize_output(answer)
    logger.info(f"转人工回复: length={len(answer)}")
    return {"final_answer": answer}
