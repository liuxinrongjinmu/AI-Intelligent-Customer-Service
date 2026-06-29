"""
回答生成节点：知识问答生成 + 问候/闲聊/反馈
"""
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from backend.agent.state import AgentState
from backend.agent.prompts import GENERATE_SYSTEM_PROMPT, GENERATE_USER_PROMPT
from backend.agent.llm_utils import safe_llm_stream, get_generate_llm
from backend.agent.retrieval_utils import format_docs_for_llm, clean_answer
from backend.utils.security import sanitize_output
from backend.utils.response_cache import get_cached_answer, set_cached_answer, get_cached_intent
from backend.utils.advanced import get_fallback_response
from backend.utils.metrics import record_cache
from backend.utils.token_budget import estimate_tokens

logger = logging.getLogger(__name__)


async def generate_answer_node(state: AgentState) -> dict:
    """知识问答生成节点"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_name = state.get("tenant_name", "平台")
    tenant_id = state.get("tenant_id", "")
    docs = state.get("retrieved_docs", [])

    cached_answer = get_cached_answer(current_message, tenant_id)
    if cached_answer:
        record_cache(True)
        logger.info(f"答案缓存命中: tenant={tenant_id}, msg={current_message[:30]}")
        return {"final_answer": cached_answer}

    record_cache(False)
    context = format_docs_for_llm(docs)
    llm = get_generate_llm(streaming=True)

    raw = await safe_llm_stream(
        llm,
        [
            SystemMessage(content=GENERATE_SYSTEM_PROMPT.format(tenant_name=tenant_name)),
            HumanMessage(content=GENERATE_USER_PROMPT.format(message=current_message, context=context))
        ],
        fallback_text="抱歉，我暂时无法生成回答，请稍后重试或联系人工客服。",
        node_name="generate_answer"
    )

    answer = clean_answer(raw)
    answer = sanitize_output(answer)

    # 只要 LLM 生成了有意义回复就缓存（不限于有检索结果时）
    from backend.config import MIN_ANSWER_LENGTH_CACHE
    if answer and len(answer) > MIN_ANSWER_LENGTH_CACHE:
        set_cached_answer(current_message, tenant_id, answer)

    logger.info(
        f"生成回答: length={len(answer)}, "
        f"context_tokens={estimate_tokens(context)}, "
        f"msg_tokens={estimate_tokens(current_message)}"
    )
    return {"final_answer": answer}


async def greeting_answer_node(state: AgentState) -> dict:
    """非知识类回答（问候/闲聊/反馈/其他）"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_name = state.get("tenant_name", "平台")
    intent = state.get("intent", "other")

    if intent == "feedback":
        answer = "不客气！如果还有其他问题随时找我。"
    elif intent == "other":
        answer = get_fallback_response("other")
    else:
        llm = get_generate_llm(streaming=True)
        raw = await safe_llm_stream(
            llm,
            [
                SystemMessage(content=f'你是{tenant_name}的AI客服助手"小聚"。请友好、简洁地回复用户的问候或闲聊。'),
                HumanMessage(content=current_message)
            ],
            fallback_text="您好！有什么可以帮您的吗？",
            node_name="greeting_answer"
        )
        answer = clean_answer(raw)

    answer = sanitize_output(answer)
    return {"final_answer": answer}
