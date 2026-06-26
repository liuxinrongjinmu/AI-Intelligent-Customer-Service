"""
意图分类节点：意图识别 + 指代消解 + 路由分发
"""
import json
import re
import time
import logging
from typing import Literal

from langchain_core.messages import SystemMessage, HumanMessage

from backend.agent.state import AgentState, INTENT_HIERARCHY
from backend.agent.prompts import CLASSIFY_SYSTEM_PROMPT, CLASSIFY_USER_PROMPT
from backend.agent.llm_utils import safe_llm_invoke, get_classify_llm
from backend.agent.retrieval_utils import format_history
from backend.utils.response_cache import get_cached_intent, set_cached_intent
from backend.utils.metrics import record_llm_call, record_cache, record_request_timing
from backend.utils.token_budget import estimate_tokens
from backend.retrieval.hybrid_search import ALL_KB_TYPES

logger = logging.getLogger(__name__)


async def classify_intent_node(state: AgentState) -> dict:
    """意图识别节点（含指代消解 + 两层意图分类）"""
    t0 = time.time()
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_id = state.get("tenant_id", "")
    history = format_history(messages[:-1]) if len(messages) > 1 else "（无历史对话）"

    # 意图缓存：仅对无历史对话的首条消息生效
    has_history = len(messages) > 1
    if not has_history:
        cached = get_cached_intent(current_message, tenant_id)
        if cached:
            record_cache(True)
            logger.info(f"意图缓存命中: {cached['intent']}/{cached['intent_sub_type']}")
            return cached

    record_cache(False)
    llm = get_classify_llm()
    raw_response = await safe_llm_invoke(
        llm,
        [
            SystemMessage(content=CLASSIFY_SYSTEM_PROMPT),
            HumanMessage(content=CLASSIFY_USER_PROMPT.format(
                history=history,
                message=current_message
            ))
        ],
        fallback_text='{"intent":"other","intent_sub_type":"unknown","entities":{},"coref_resolved":"","search_query":""}'
    )

    try:
        content = raw_response.strip()
        if content.startswith("```"):
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```\s*$', '', content)
        result = json.loads(content)
        intent = result.get("intent", "other")
        intent_sub_type = result.get("intent_sub_type", "")
        entities = result.get("entities", {})
        coref_resolved = result.get("coref_resolved") or current_message
        search_query = result.get("search_query") or coref_resolved
        suggested_kb_types = result.get("suggested_kb_types", ALL_KB_TYPES)
        if not suggested_kb_types or not isinstance(suggested_kb_types, list):
            suggested_kb_types = ALL_KB_TYPES
        valid_kb_types = [kb for kb in suggested_kb_types if kb in ALL_KB_TYPES]
        if not valid_kb_types:
            valid_kb_types = ALL_KB_TYPES
    except (json.JSONDecodeError, AttributeError):
        intent = "other"
        intent_sub_type = "unknown"
        entities = {}
        coref_resolved = current_message
        search_query = current_message
        valid_kb_types = ALL_KB_TYPES

    # 连续失败计数
    ai_failed_count = state.get("ai_failed_count", 0)
    if intent == "other" and intent_sub_type in ("unknown", "ambiguous"):
        ai_failed_count += 1
    else:
        ai_failed_count = 0

    # 子类标准化
    _SUB_TYPE_NORMALIZE = {
        ("human_service", "transfer_to_human"): "user_request",
        ("human_service", "ai_failed"): "ai_limitation",
    }
    normalize_key = (intent, intent_sub_type)
    if normalize_key in _SUB_TYPE_NORMALIZE:
        intent_sub_type = _SUB_TYPE_NORMALIZE[normalize_key]
        logger.info(f"子类标准化: {normalize_key} → {intent_sub_type}")

    # 验证子类在 INTENT_HIERARCHY 中
    valid_sub_types = INTENT_HIERARCHY.get(intent, {}).get("sub_types", {})
    if intent_sub_type and intent_sub_type not in valid_sub_types:
        logger.warning(f"子类 {intent_sub_type} 不存在于 {intent} 中，回退到默认值")
        if valid_sub_types:
            intent_sub_type = list(valid_sub_types.keys())[0]
        else:
            intent_sub_type = ""

    # 连续 2 次失败 → 自动转人工
    if ai_failed_count >= 2:
        intent = "human_service"
        intent_sub_type = "ai_limitation"
        logger.warning(f"AI连续失败 {ai_failed_count} 次，自动转人工")

    logger.info(
        f"意图识别: intent={intent}/{intent_sub_type}, "
        f"coref={coref_resolved[:50]}, failed_count={ai_failed_count}, "
        f"search_query={search_query[:50]}, kb_types={valid_kb_types}, "
        f"history_tokens={estimate_tokens(history)}, msg_tokens={estimate_tokens(current_message)}"
    )

    result = {
        "intent": intent,
        "intent_sub_type": intent_sub_type,
        "intent_entities": entities,
        "search_query": search_query,
        "suggested_kb_types": valid_kb_types,
        "coref_resolved": coref_resolved,
        "ai_failed_count": ai_failed_count,
    }
    set_cached_intent(current_message, result, tenant_id)
    record_request_timing(time.time() - t0, intent=f"{intent}/{intent_sub_type}")
    return result


def route_by_intent(state: AgentState) -> Literal[
    "retrieve_knowledge", "order_query_node",
    "greeting_answer", "complaint_node", "human_service_node",
    "product_query_node", "coupon_query_node", "account_query_node",
]:
    """根据意图路由到不同节点"""
    intent = state.get("intent", "other")

    route_map = {
        "human_service": "human_service_node",
        "order_query": "order_query_node",
        "logistics_query": "order_query_node",
        "product_query": "product_query_node",
        "coupon_query": "coupon_query_node",
        "account_query": "account_query_node",
        "knowledge_query": "retrieve_knowledge",
        "complaint": "complaint_node",
        "greeting": "greeting_answer",
        "feedback": "greeting_answer",
        "other": "greeting_answer",
    }

    target = route_map.get(intent, "greeting_answer")
    logger.info(f"路由: intent={intent} → {target}")
    return target
