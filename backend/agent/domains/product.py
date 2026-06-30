"""
商品咨询节点：API 查询 + 知识库降级
"""
import asyncio
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from backend.agent.state import AgentState
from backend.agent.prompts import GENERATE_SYSTEM_PROMPT, GENERATE_USER_PROMPT
from backend.agent.llm_utils import safe_llm_stream, get_generate_llm
from backend.agent.retrieval_utils import format_docs_for_llm, clean_answer, format_history
from backend.utils.security import sanitize_output
from backend.utils.tool_logger import call_and_log
from backend.services.product_service import query_product, format_product_result
from backend.retrieval.hybrid_search import hybrid_search

# 知识库检索降级阈值（仅在产品节点用，避免循环导入）
RETRIEVAL_THRESHOLD_FALLBACK = 0.3

logger = logging.getLogger(__name__)


async def product_query_node(state: AgentState) -> dict:
    """商品咨询节点：优先调用 API，失败则降级为知识库检索"""
    messages = state["messages"]
    current_message = (messages[-1].content or "") if messages else ""
    tenant_id = state.get("tenant_id", "")
    tenant_name = state.get("tenant_name", "平台")
    entities = state.get("intent_entities", {})
    product_name = entities.get("product_name", "")
    product_id = entities.get("product_id", "")
    # 优先用 product_name，回退到 LLM 提取的 search_query 简短版，最后用原始消息
    search_query = state.get("search_query", "")
    # search_query 是多词格式（如"椰水 商品"），取第一个词作为搜索关键词
    short_query = search_query.split()[0] if search_query else ""
    search_name = product_name or short_query or current_message
    thread_id = state.get("thread_id", "")

    # 尝试第一次搜索
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

    # 如果短词搜索没结果且没用 product_name，尝试用原始消息再搜一次
    if (not api_result.get("success") or api_result.get("total", 0) == 0) and not product_name and short_query:
        logger.info(f"商品短词搜索无结果: {short_query}, 尝试完整搜索词: {search_query}")
        api_result = await call_and_log(
            tenant_id=tenant_id,
            tool_name="query_product_retry",
            tool_params={
                "tenant_id": tenant_id,
                "product_name": search_query,
                "product_id": product_id,
            },
            func=query_product,
            conversation_id=thread_id,
        )

    if api_result.get("success", False) and api_result.get("total", 0) > 0:
        formatted = format_product_result(api_result)
        logger.info(f"商品查询成功: tenant={tenant_id}, total={api_result.get('total', 0)}")

        # 追问检测：当前消息很短（≤15字）说明用户在对商品追问细节
        # （如"多少钱？""有货吗？"），需要用LLM提取精准答案
        is_followup = len(current_message.strip()) <= 15

        if is_followup:
            history_text = format_history(messages[:-1])
            followup_prompt = (
                f"## 对话历史\n{history_text}\n\n"
                f"## 商品信息\n{formatted}\n\n"
                f"用户追问：{current_message}\n\n"
                f"请根据商品信息，直接回答用户的追问。只给出简洁的答案，不要重复完整的商品信息。"
            )
            try:
                llm = get_generate_llm(streaming=True)
                followup_answer = await safe_llm_stream(
                    llm,
                    [
                        SystemMessage(content=GENERATE_SYSTEM_PROMPT.format(tenant_name=tenant_name)),
                        HumanMessage(content=followup_prompt)
                    ],
                    fallback_text=formatted,
                    node_name="product_query_node"
                )
                answer = clean_answer(followup_answer)
                answer = sanitize_output(answer)
                logger.info(f"商品追问回答: '{current_message}' → '{answer[:50]}...'")
                return {"final_answer": answer, "current_product": formatted}
            except Exception as e:
                logger.warning(f"追问LLM调用失败，回退完整商品信息: {e}")

        return {"final_answer": formatted, "current_product": formatted}

    # 商品 API 未配置或查询失败 → 回退到知识库检索
    if "暂未配置" in api_result.get("message", "") or not api_result.get("success"):
        logger.info(f"商品API未配置/失败，回退知识库检索: tenant={tenant_id}, query={search_name}")
        try:
            docs = await asyncio.to_thread(
                hybrid_search, query=search_name, tenant_id=tenant_id,
                kb_types=["product", "faq"], relevance_threshold=RETRIEVAL_THRESHOLD_FALLBACK,
            )
        except Exception as e:
            logger.exception(f"知识库检索回退异常: {e}")
            docs = []

        if docs:
            context = format_docs_for_llm(docs)
            llm = get_generate_llm(streaming=True)
            raw = await safe_llm_stream(
                llm,
                [
                    SystemMessage(content=GENERATE_SYSTEM_PROMPT.format(tenant_name=tenant_name)),
                    HumanMessage(content=GENERATE_USER_PROMPT.format(message=current_message, context=context))
                ],
                fallback_text="抱歉，我暂时无法查询该商品信息，请稍后重试或联系人工客服。",
                node_name="product_query_node"
            )
            answer = clean_answer(raw)
            answer = sanitize_output(answer)
            logger.info(f"商品查询降级→知识库: tenant={tenant_id}, 召回{len(docs)}条")
            return {"final_answer": answer}

        if product_name:
            reply = f'抱歉，暂未找到"{product_name}"的相关信息，建议您联系人工客服获取帮助。'
        else:
            reply = "抱歉，暂未找到相关商品信息，请提供更具体的商品名称，或联系人工客服。"
        return {"final_answer": reply}

    answer = clean_answer(api_result.get("message", ""))
    answer = sanitize_output(answer)
    return {"final_answer": answer}
