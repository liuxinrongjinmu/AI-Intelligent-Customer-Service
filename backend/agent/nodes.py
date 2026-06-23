"""
Agent 节点实现：意图识别 → 路由分发 → 知识检索 / Action → 生成回答

路由策略（按优先级从高到低）：
  human_service   → human_service_node（转人工）
  order_query     → order_query_node（订单含物流状态）
  logistics_query → order_query_node（查最近订单 → 查物流）
  product_query   → product_query_node（商品咨询）
  coupon_query    → coupon_query_node（优惠券咨询）
  account_query   → account_query_node（账户查询）
  knowledge_query → retrieve_knowledge → generate_answer
  greeting        → greeting_answer
  feedback        → greeting_answer
  other           → greeting_answer

复合意图：订单+物流联动（logistics_query 先查订单再回答）
"""
import json
import re
import time
import logging
import asyncio
import copy
from typing import Literal
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_deepseek import ChatDeepSeek

from backend.config import (
    DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODEL,
    HISTORY_MESSAGE_BUDGET, KNOWLEDGE_CONTEXT_BUDGET,
    HISTORY_MAX_TURNS_FALLBACK,
)
from backend.agent.state import AgentState
from backend.agent.prompts import (
    CLASSIFY_SYSTEM_PROMPT, CLASSIFY_USER_PROMPT,
    GENERATE_SYSTEM_PROMPT, GENERATE_USER_PROMPT,
    HUMAN_SERVICE_PROMPT, COMPLAINT_PROMPT,
)
from backend.utils.security import sanitize_output
from backend.utils.advanced import get_fallback_response, get_ab_config
from backend.utils.response_cache import (
    get_cached_intent,
    set_cached_intent,
    get_cached_answer,
    set_cached_answer,
)
from backend.utils.metrics import record_llm_call, record_error, record_cache, record_retrieval, record_handoff, record_request_timing
from backend.utils.token_budget import format_history_token_aware, format_knowledge_token_aware, estimate_tokens
from backend.retrieval.hybrid_search import hybrid_search, keyword_match_search, ALL_KB_TYPES
from backend.services.order_service import query_order, format_order_result
from backend.services.product_service import query_product, format_product_result
from backend.services.coupon_service import query_coupon, format_coupon_result
from backend.services.user_profile_service import query_user_profile, format_user_profile_result
from backend.services.logistics_service import query_logistics, format_logistics_result
from backend.services.handoff_service import create_handoff_ticket
from backend.utils.tool_logger import call_and_log

logger = logging.getLogger(__name__)

_BANNED_PATTERNS = [
    r"\[\d+\]",
    r"明细来源[:：]\s*\S+",
    r"\(来源[:：]\s*\S+\)",
    r"信息来源[:：]\s*\S+",
]

_BANNED_PHRASES = [
    "建议联系人工客服",
    "建议咨询人工客服",
    "建议您联系人工客服",
    "建议您联系人工",
    "如需了解更多，建议联系人工客服",
    "建议转人工处理",
    "请联系人工客服",
    "建议联系在线客服",
    "建议联系在线",
    "如需进一步了解，建议",
    "根据知识库信息，",
    "根据知识库内容，",
    "根据知识库，",
]


async def _safe_llm_invoke(llm, messages: list, fallback_text: str = "抱歉，服务暂时不可用，请稍后重试。", node_name: str = "unknown") -> str:
    """
    安全的 LLM 调用包装：含重试 + 异常兜底

    :param llm: ChatDeepSeek 实例
    :param messages: 消息列表
    :param fallback_text: 失败时的兜底回复
    :param node_name: 调用节点名称（用于指标采集）
    :return: LLM 响应文本或兜底文本
    """
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = await llm.ainvoke(messages)
            record_llm_call(node_name)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"LLM 调用失败(第{attempt + 1}次重试): {e}")
                await asyncio.sleep(1 * (attempt + 1))
            else:
                logger.error(f"LLM 调用最终失败: {e}")
                record_error("llm_call_failed")
                return fallback_text


async def _safe_llm_stream(llm, messages: list, fallback_text: str = "抱歉，服务暂时不可用，请稍后重试。", node_name: str = "unknown") -> str:
    """
    流式 LLM 调用：逐 token 生成，支持首 token 前重试

    通过 LangGraph 的 stream_mode="messages" 拦截 astream 调用，
    将 token 实时推送到 SSE，同时累积完整答案用于持久化。

    重试策略：
    - 首 token 到达前失败 → 可重试（用户未看到任何内容）
    - 首 token 到达后失败 → 不可重试（已发送部分内容，返回已累积的文本）

    :param llm: ChatDeepSeek 实例（必须 streaming=True）
    :param messages: 消息列表
    :param fallback_text: 失败时的兜底回复
    :param node_name: 调用节点名称（用于指标采集）
    :return: 完整的 LLM 响应文本
    """
    max_retries = 2
    accumulated = ""
    for attempt in range(max_retries + 1):
        try:
            async for chunk in llm.astream(messages):
                content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                if content:
                    accumulated += content
            record_llm_call(node_name)
            return accumulated
        except Exception as e:
            if accumulated:
                # 已流式输出部分内容，不可重试，返回已累积文本
                logger.error(f"LLM 流式中途失败（已发送部分内容）: {e}")
                return accumulated
            if attempt < max_retries:
                logger.warning(f"LLM 流式调用失败(第{attempt + 1}次重试): {e}")
                await asyncio.sleep(1 * (attempt + 1))
            else:
                logger.error(f"LLM 流式调用最终失败: {e}")
                record_error("llm_call_failed")
                return fallback_text
    return accumulated or fallback_text


_classify_llm = None
_generate_llm = None
_generate_llm_stream = None


def _get_classify_llm() -> ChatDeepSeek:
    """意图分类 LLM（非流式，temperature=0，单例复用）"""
    global _classify_llm
    if _classify_llm is None:
        _classify_llm = ChatDeepSeek(
            model=DEEPSEEK_MODEL,
            api_key=DEEPSEEK_API_KEY,
            api_base=DEEPSEEK_BASE_URL,
            temperature=0,
            streaming=False,
            request_timeout=30,
        )
    return _classify_llm


def _get_generate_llm(streaming: bool = True) -> ChatDeepSeek:
    """回答生成 LLM（支持 A/B 测试配置，单例复用）"""
    global _generate_llm, _generate_llm_stream
    ab_config = get_ab_config()
    if streaming:
        if _generate_llm_stream is None:
            _generate_llm_stream = ChatDeepSeek(
                model=DEEPSEEK_MODEL,
                api_key=DEEPSEEK_API_KEY,
                api_base=DEEPSEEK_BASE_URL,
                temperature=ab_config.get("temperature", 0.7),
                streaming=True,
                request_timeout=60,
                max_tokens=ab_config.get("max_tokens", 2048),
            )
        return _generate_llm_stream
    else:
        if _generate_llm is None:
            _generate_llm = ChatDeepSeek(
                model=DEEPSEEK_MODEL,
                api_key=DEEPSEEK_API_KEY,
                api_base=DEEPSEEK_BASE_URL,
                temperature=ab_config.get("temperature", 0.7),
                streaming=False,
                request_timeout=60,
                max_tokens=ab_config.get("max_tokens", 2048),
            )
        return _generate_llm


def _format_history(messages: list, max_turns: int = 4) -> str:
    """
    格式化对话历史（token 感知的动态裁剪版本）

    优先使用 token 预算裁剪，自动适配短消息和长消息场景。
    短消息对话可以保留更多轮，长消息自动减少轮数。

    :param messages: 历史消息列表（不含当前消息）
    :param max_turns: 固定轮数回退（仅 token 估算失败时使用）
    :return: 格式化的对话历史文本
    """
    return format_history_token_aware(
        messages=messages,
        max_tokens=HISTORY_MESSAGE_BUDGET,
        max_turns_fallback=max_turns,
    )


def _reciprocal_rank_fusion(
    result_groups: list[list[dict]],
    k: int = 60,
    top_k: int = 5
) -> list[dict]:
    """Reciprocal Rank Fusion：融合多路检索结果"""
    rrf_scores: dict[str, tuple[float, dict]] = {}
    for group in result_groups:
        for rank, doc in enumerate(group):
            doc_id = doc.get("source_id", "") or doc.get("content", "")
            if not doc_id:
                doc_id = doc.get("content", "")[:80]
            rrf_score = 1.0 / (k + rank + 1)
            if doc_id in rrf_scores:
                rrf_scores[doc_id] = (
                    rrf_scores[doc_id][0] + rrf_score,
                    rrf_scores[doc_id][1]
                )
            else:
                rrf_scores[doc_id] = (rrf_score, doc)
    sorted_docs = sorted(rrf_scores.values(), key=lambda x: x[0], reverse=True)
    return [doc for _, doc in sorted_docs[:top_k]]


def _keyword_boost(
    docs: list[dict],
    keywords: list[str],
    boost_factor: float = 0.3,
    top_k: int = 5
) -> list[dict]:
    """关键词加成（深拷贝，避免修改原始数据）"""
    if not keywords or not docs:
        return docs
    boosted = copy.deepcopy(docs)
    for doc in boosted:
        content_lower = doc.get("content", "").lower()
        keyword_hits = sum(1 for kw in keywords if kw.lower() in content_lower)
        if keyword_hits > 0:
            boost = keyword_hits * boost_factor
            doc["score"] = min(doc.get("score", 0.0) + boost, 1.0)
    boosted.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return boosted[:top_k]


def _format_docs_for_llm(docs: list[dict]) -> str:
    """
    将检索结果格式化为 LLM 可读的上下文（token 感知版本）

    自动按知识上下文预算裁剪，保留高相关性文档。
    :param docs: 检索到的文档列表
    :return: 格式化的知识上下文文本
    """
    return format_knowledge_token_aware(
        docs=docs,
        max_tokens=KNOWLEDGE_CONTEXT_BUDGET,
    )


def _clean_answer(answer: str) -> str:
    """后处理清理"""
    for phrase in _BANNED_PHRASES:
        answer = answer.replace(phrase, "")
    for pattern in _BANNED_PATTERNS:
        answer = re.sub(pattern, "", answer)
    answer = re.sub(r"[。.]\s*$", "", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer)
    answer = answer.strip()
    return answer


# ============================================================
# 意图识别节点
# ============================================================

async def classify_intent_node(state: AgentState) -> dict:
    """
    意图识别节点（含指代消解 + 两层意图分类）
    输出: intent / intent_sub_type / intent_priority / entities / search_query / ai_failed_count
    """
    t0 = time.time()
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_id = state.get("tenant_id", "")
    history = _format_history(messages[:-1]) if len(messages) > 1 else "（无历史对话）"

    # 意图缓存：仅对无历史对话的首条消息生效，避免多轮对话误路由
    has_history = len(messages) > 1
    if not has_history:
        cached = get_cached_intent(current_message, tenant_id)
        if cached:
            record_cache(True)
            logger.info(f"意图缓存命中: {cached['intent']}/{cached['intent_sub_type']}")
            return cached

    record_cache(False)
    llm = _get_classify_llm()
    raw_response = await _safe_llm_invoke(
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

    # 连续失败计数：other/unknown 视为失败，成功则重置
    ai_failed_count = state.get("ai_failed_count", 0)
    if intent == "other" and intent_sub_type in ("unknown", "ambiguous"):
        ai_failed_count += 1
    else:
        ai_failed_count = 0

    # 子类标准化：将 LLM 可能返回的非标准子类映射到标准子类
    _SUB_TYPE_NORMALIZE = {
        ("human_service", "transfer_to_human"): "user_request",
        ("human_service", "ai_failed"): "ai_limitation",
    }
    normalize_key = (intent, intent_sub_type)
    if normalize_key in _SUB_TYPE_NORMALIZE:
        intent_sub_type = _SUB_TYPE_NORMALIZE[normalize_key]
        logger.info(f"子类标准化: {normalize_key} → {intent_sub_type}")

    # 验证子类是否存在于 INTENT_HIERARCHY 中
    from backend.agent.state import INTENT_HIERARCHY
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


# ============================================================
# 路由函数
# ============================================================

def route_by_intent(state: AgentState) -> Literal[
    "retrieve_knowledge", "order_query_node",
    "greeting_answer", "complaint_node", "human_service_node",
    "product_query_node", "coupon_query_node", "account_query_node",
]:
    """
    根据意图路由到不同节点

    路由表（按优先级）：
    - human_service → human_service_node
    - order_query / logistics_query → order_query_node（统一处理订单+物流）
    - product_query → product_query_node
    - coupon_query → coupon_query_node
    - account_query → account_query_node
    - knowledge_query → retrieve_knowledge → generate_answer
    - greeting / feedback / other → greeting_answer
    """
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


# ============================================================
# 知识检索节点
# ============================================================

async def retrieve_knowledge_node(state: AgentState) -> dict:
    """
    知识检索节点：定向检索知识库 collection（faq/product/rule/public）
    """
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_id = state.get("tenant_id", "")
    search_query = state.get("search_query", current_message)
    entities = state.get("intent_entities", {})
    keywords = entities.get("keywords", [])
    kb_types = state.get("suggested_kb_types", ALL_KB_TYPES)

    query_list = [search_query]
    if search_query != current_message:
        query_list.append(current_message)

    vector_groups = []
    for query in query_list:
        try:
            results = await asyncio.to_thread(hybrid_search, query=query, tenant_id=tenant_id, kb_types=kb_types)
            if not results:
                results = await asyncio.to_thread(hybrid_search, query=query, tenant_id=tenant_id, kb_types=kb_types, relevance_threshold=0.15)
        except Exception as e:
            logger.exception(f"向量检索异常(tenant={tenant_id}): {e}")
            results = []
        if results:
            vector_groups.append(results)

    kw_docs = []
    if keywords:
        try:
            kw_docs = await asyncio.to_thread(keyword_match_search, keywords=keywords, tenant_id=tenant_id, kb_types=kb_types, min_hits=1)
        except Exception as e:
            logger.exception(f"关键词检索异常: {e}")

    if len(vector_groups) == 0 and not kw_docs:
        logger.info(f"知识检索: 无结果, tenant={tenant_id}, kb_types={kb_types}")
        return {"retrieved_docs": []}

    vector_fused = vector_groups[0] if len(vector_groups) == 1 else _reciprocal_rank_fusion(vector_groups)

    seen_contents = set()
    final_docs = []
    for doc in kw_docs:
        key = doc.get("content", "")[:80]
        if key not in seen_contents:
            seen_contents.add(key)
            final_docs.append(doc)
    for doc in vector_fused:
        key = doc.get("content", "")[:80]
        if key not in seen_contents:
            seen_contents.add(key)
            final_docs.append(doc)

    final_docs = _keyword_boost(final_docs, keywords)

    has_results = len(final_docs) > 0
    record_retrieval(has_results)
    logger.info(f"知识检索: query={search_query[:50]}, 召回 {len(final_docs)} 条, tenant={tenant_id}")
    return {"retrieved_docs": final_docs}


# ============================================================
# 生成回答节点
# ============================================================

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
    context = _format_docs_for_llm(docs)
    llm = _get_generate_llm(streaming=True)

    raw = await _safe_llm_stream(
        llm,
        [
            SystemMessage(content=GENERATE_SYSTEM_PROMPT.format(tenant_name=tenant_name)),
            HumanMessage(content=GENERATE_USER_PROMPT.format(message=current_message, context=context))
        ],
        fallback_text="抱歉，我暂时无法生成回答，请稍后重试或联系人工客服。",
        node_name="generate_answer"
    )

    answer = _clean_answer(raw)
    answer = sanitize_output(answer)

    if docs:
        set_cached_answer(current_message, tenant_id, answer)

    logger.info(f"生成回答: length={len(answer)}, context_tokens={estimate_tokens(context)}, msg_tokens={estimate_tokens(current_message)}")
    return {"final_answer": answer}


# ============================================================
# 问候/闲聊/反馈 节点
# ============================================================

async def greeting_answer_node(state: AgentState) -> dict:
    """非知识类回答"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_name = state.get("tenant_name", "平台")
    intent = state.get("intent", "other")

    if intent == "feedback":
        answer = "不客气！如果还有其他问题随时找我。"
    elif intent == "other":
        answer = get_fallback_response("other")
    else:
        llm = _get_generate_llm(streaming=True)
        raw = await _safe_llm_stream(
            llm,
            [
                SystemMessage(content=f'你是{tenant_name}的AI客服助手"小聚"。请友好、简洁地回复用户的问候或闲聊。'),
                HumanMessage(content=current_message)
            ],
            fallback_text="您好！有什么可以帮您的吗？",
            node_name="greeting_answer"
        )
        answer = _clean_answer(raw)

    answer = sanitize_output(answer)
    return {"final_answer": answer}


# ============================================================
# 订单查询节点（含物流联动）
# ============================================================

async def order_query_node(state: AgentState) -> dict:
    """订单查询节点：处理 order_query 和 logistics_query"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_id = state.get("tenant_id", "")
    tenant_name = state.get("tenant_name", "平台")
    entities = state.get("intent_entities", {})
    intent = state.get("intent", "order_query")
    intent_sub_type = state.get("intent_sub_type", "")

    order_keyword = entities.get("order_no", "") or entities.get("order_keyword", "")

    if not order_keyword:
        order_keyword = current_message

    thread_id = state.get("thread_id", "")
    api_result = await call_and_log(
        tenant_id=tenant_id,
        tool_name="query_order",
        tool_params={
            "tenant_id": tenant_id,
            "order_no": order_keyword,
        },
        func=query_order,
        conversation_id=thread_id,
    )

    if api_result.get("success", False):
        formatted = format_order_result(api_result)
        logger.info(f"订单查询成功: tenant={tenant_id}, total={api_result.get('total', 0)}")

        # 物流查询 → 在订单结果后追加物流追踪
        if intent == "logistics_query" and api_result.get("data"):
            order_data = api_result.get("data")
            # 防御 data 为 list 类型时调用 .get() 崩溃
            if isinstance(order_data, dict):
                order_no = order_data.get("orderNo") or order_keyword
            elif isinstance(order_data, list) and order_data and isinstance(order_data[0], dict):
                order_no = order_data[0].get("orderNo") or order_keyword
            else:
                order_no = order_keyword
            logistics_result = await call_and_log(
                tenant_id=tenant_id,
                tool_name="query_logistics",
                tool_params={
                    "tenant_id": tenant_id,
                    "order_no": order_no,
                },
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
        # API 未配置时禁止 LLM 生成无依据回复（避免幻觉编造订单信息）
        logger.warning(f"订单API未配置，返回明确提示: tenant={tenant_id}")
        reply = '订单查询服务暂未配置，无法为您查询订单信息。如需帮助，请说"转人工"联系客服。'
        return {"final_answer": reply}

    answer = _clean_answer(api_result.get("message", ""))
    answer = sanitize_output(answer)
    return {"final_answer": answer}


# ============================================================
# 商品咨询节点
# ============================================================

async def product_query_node(state: AgentState) -> dict:
    """商品咨询节点：处理 product_query，API 未配置时回退到知识库检索"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_id = state.get("tenant_id", "")
    tenant_name = state.get("tenant_name", "平台")
    entities = state.get("intent_entities", {})
    product_name = entities.get("product_name", "")
    product_id = entities.get("product_id", "")
    sku = entities.get("sku", "")

    search_name = product_name or current_message
    thread_id = state.get("thread_id", "")
    api_result = await call_and_log(
        tenant_id=tenant_id,
        tool_name="query_product",
        tool_params={
            "tenant_id": tenant_id,
            "product_name": search_name,
            "product_id": product_id,
        },
        func=query_product,
        conversation_id=thread_id,
    )

    if api_result.get("success", False):
        formatted = format_product_result(api_result)
        logger.info(f"商品查询成功: tenant={tenant_id}, total={api_result.get('total', 0)}")
        return {"final_answer": formatted}

    # 商品 API 未配置或查询失败 → 回退到知识库检索
    if "暂未配置" in api_result.get("message", "") or not api_result.get("success"):
        logger.info(f"商品API未配置/失败，回退知识库检索: tenant={tenant_id}, query={search_name}")
        # 执行知识库检索
        try:
            docs = await asyncio.to_thread(
                hybrid_search,
                query=search_name,
                tenant_id=tenant_id,
                kb_types=["product", "faq"],
            )
            if not docs:
                docs = await asyncio.to_thread(
                    hybrid_search,
                    query=search_name,
                    tenant_id=tenant_id,
                    kb_types=["product", "faq"],
                    relevance_threshold=0.15,
                )
        except Exception as e:
            logger.exception(f"知识库检索回退异常: {e}")
            docs = []

        if docs:
            # 用检索到的知识生成回答
            context = _format_docs_for_llm(docs)
            llm = _get_generate_llm(streaming=True)
            raw = await _safe_llm_stream(
                llm,
                [
                    SystemMessage(content=GENERATE_SYSTEM_PROMPT.format(tenant_name=tenant_name)),
                    HumanMessage(content=GENERATE_USER_PROMPT.format(message=current_message, context=context))
                ],
                fallback_text="抱歉，我暂时无法查询该商品信息，请稍后重试或联系人工客服。",
                node_name="product_query_node"
            )
            answer = _clean_answer(raw)
            answer = sanitize_output(answer)
            logger.info(f"商品查询降级→知识库: tenant={tenant_id}, 召回{len(docs)}条")
            return {"final_answer": answer}

        # 知识库也无结果，返回友好提示
        if product_name:
            reply = f'抱歉，暂未找到\u201c{product_name}\u201d的相关信息，建议您联系人工客服获取帮助。'
        else:
            reply = "抱歉，暂未找到相关商品信息，请提供更具体的商品名称，或联系人工客服。"
        return {"final_answer": reply}

    answer = _clean_answer(api_result.get("message", ""))
    answer = sanitize_output(answer)
    return {"final_answer": answer}


# ============================================================
# 优惠券咨询节点
# ============================================================

async def coupon_query_node(state: AgentState) -> dict:
    """优惠券咨询节点：处理 coupon_query"""
    tenant_id = state.get("tenant_id", "")
    tenant_name = state.get("tenant_name", "平台")
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

    thread_id = state.get("thread_id", "")
    api_result = await call_and_log(
        tenant_id=tenant_id,
        tool_name="query_coupon",
        tool_params={
            "tenant_id": tenant_id,
            "user_id": user_id,
            "status": status,
        },
        func=query_coupon,
        conversation_id=thread_id,
    )

    if api_result.get("success", False):
        formatted = format_coupon_result(api_result)
        logger.info(f"优惠券查询成功: tenant={tenant_id}, total={api_result.get('total', 0)}")
        return {"final_answer": formatted}

    messages_map = {
        "available_coupons": '正在为您查询可用优惠券，建议您也可以在APP\u201c我的-优惠券\u201d中查看。',
        "coupon_rules": "正在为您查询优惠券使用规则，请稍候。",
        "coupon_unusable": "正在为您排查优惠券不可用的原因，常见原因包括：未达使用门槛、商品不适用、已过期等。",
        "coupon_expiring": "正在为您查询即将过期的优惠券，请稍候。",
    }
    reply = messages_map.get(intent_sub_type, "正在为您查询优惠券信息，请稍候。")
    return {"final_answer": reply}


# ============================================================
# 账户查询节点
# ============================================================

async def account_query_node(state: AgentState) -> dict:
    """账户查询节点：处理 account_query"""
    tenant_id = state.get("tenant_id", "")
    tenant_name = state.get("tenant_name", "平台")
    intent_sub_type = state.get("intent_sub_type", "")
    entities = state.get("intent_entities", {})
    user_id = state.get("user_id", "") or entities.get("user_id", "")

    if intent_sub_type in ("membership_level", "points_balance"):
        thread_id = state.get("thread_id", "")
        api_result = await call_and_log(
            tenant_id=tenant_id,
            tool_name="query_user_profile",
            tool_params={
                "tenant_id": tenant_id,
                "user_id": user_id,
            },
            func=query_user_profile,
            conversation_id=thread_id,
        )
        if api_result.get("success", False):
            formatted = format_user_profile_result(api_result)
            logger.info(f"用户画像查询成功: tenant={tenant_id}")
            return {"final_answer": formatted}
        else:
            # API 失败时返回明确错误提示，而非"请稍候"（无后续推送会导致用户空等）
            msg = api_result.get("message", "")
            if "暂未配置" in msg:
                return {"final_answer": "账户查询服务暂未配置，如需帮助请联系人工客服。"}
            return {"final_answer": "抱歉，暂时无法查询您的账户信息，请稍后重试或联系人工客服。"}

    messages_map = {
        "membership_level": "正在为您查询会员等级信息，请稍候。",
        "points_balance": "正在为您查询积分余额，请稍候。",
        "address_manage": '您可以在APP\u201c我的-收货地址\u201d中查看和管理地址信息。',
        "account_security": "账户安全问题需要核实身份，正在为您转接人工客服处理。",
    }
    reply = messages_map.get(intent_sub_type, "正在为您查询账户信息，请稍候。")
    return {"final_answer": reply}


# ============================================================
# 投诉处理节点
# ============================================================

async def complaint_node(state: AgentState) -> dict:
    """投诉处理节点：表达歉意并总结问题，转接人工客服"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_name = state.get("tenant_name", "平台")
    entities = state.get("intent_entities", {})
    complaint_reason = entities.get("reason", "") or entities.get("complaint", "")
    history = _format_history(messages[:-1]) if len(messages) > 1 else "（无历史对话）"

    user_context = current_message
    if complaint_reason:
        user_context = f"投诉原因: {complaint_reason}\n原始消息: {current_message}"
    if history != "（无历史对话）":
        user_context = f"对话历史:\n{history}\n\n当前投诉: {user_context}"

    llm = _get_generate_llm(streaming=True)
    raw = await _safe_llm_stream(
        llm,
        [
            SystemMessage(content=COMPLAINT_PROMPT.format(tenant_name=tenant_name, message=current_message)),
            HumanMessage(content=user_context)
        ],
        fallback_text="非常抱歉给您带来不好的体验，我们已记录您的投诉，将尽快安排专人处理。",
        node_name="complaint_node"
    )
    answer = _clean_answer(raw)
    answer = sanitize_output(answer)
    logger.info(f"投诉回复: length={len(answer)}")
    return {"final_answer": answer}


# ============================================================
# 转人工节点
# ============================================================

async def human_service_node(state: AgentState) -> dict:
    """转人工服务节点"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_name = state.get("tenant_name", "平台")
    tenant_id = state.get("tenant_id", "")
    intent_sub_type = state.get("intent_sub_type", "")
    history = _format_history(messages[:-1]) if len(messages) > 1 else "（无历史对话）"
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
        answer = "抱歉，转人工服务暂时不可用，请稍后重试或拨打客服热线。"
        return {"final_answer": answer}

    record_handoff()

    if intent_sub_type == "ai_limitation":
        answer = "抱歉未能完全理解您的问题，正在为您转接人工客服，请稍候。人工客服可以更准确地解答您的问题。"
        return {"final_answer": answer}

    user_context = current_message
    if history != "（无历史对话）":
        user_context = f"对话历史:\n{history}\n\n当前请求: {current_message}"

    llm = _get_generate_llm(streaming=True)
    raw = await _safe_llm_stream(
        llm,
        [
            SystemMessage(content=HUMAN_SERVICE_PROMPT.format(tenant_name=tenant_name, message=current_message)),
            HumanMessage(content=user_context)
        ],
        fallback_text="正在为您转接人工客服，请稍候。",
        node_name="human_service_node"
    )
    answer = _clean_answer(raw)
    answer = sanitize_output(answer)
    logger.info(f"转人工回复: length={len(answer)}")
    return {"final_answer": answer}