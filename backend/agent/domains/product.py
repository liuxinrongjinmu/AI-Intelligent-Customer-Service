"""
商品咨询节点：API 查询 + 知识库降级
"""
import asyncio
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from backend.agent.state import AgentState
from backend.agent.prompts import GENERATE_SYSTEM_PROMPT, GENERATE_USER_PROMPT
from backend.agent.llm_utils import safe_llm_stream, get_generate_llm
from backend.agent.retrieval_utils import format_docs_for_llm, clean_answer
from backend.utils.security import sanitize_output
from backend.utils.tool_logger import call_and_log
from backend.services.product_service import query_product, format_product_result
from backend.retrieval.hybrid_search import hybrid_search

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
        try:
            docs = await asyncio.to_thread(
                hybrid_search, query=search_name, tenant_id=tenant_id,
                kb_types=["product", "faq"],
            )
            if not docs:
                docs = await asyncio.to_thread(
                    hybrid_search, query=search_name, tenant_id=tenant_id,
                    kb_types=["product", "faq"], relevance_threshold=0.15,
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
