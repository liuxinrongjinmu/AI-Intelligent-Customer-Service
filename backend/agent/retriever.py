"""
知识检索节点：混合检索（向量 + 关键词）+ RRF 融合
"""
import asyncio
import logging

from backend.agent.state import AgentState
from backend.agent.retrieval_utils import reciprocal_rank_fusion, keyword_boost
from backend.utils.metrics import record_retrieval
from backend.retrieval.hybrid_search import hybrid_search, keyword_match_search, ALL_KB_TYPES

logger = logging.getLogger(__name__)


async def retrieve_knowledge_node(state: AgentState) -> dict:
    """知识检索节点：定向检索知识库 collection（faq/product/rule/public）"""
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
            results = await asyncio.to_thread(
                hybrid_search, query=query, tenant_id=tenant_id, kb_types=kb_types
            )
            if not results:
                results = await asyncio.to_thread(
                    hybrid_search, query=query, tenant_id=tenant_id,
                    kb_types=kb_types, relevance_threshold=0.15
                )
        except Exception as e:
            logger.exception(f"向量检索异常(tenant={tenant_id}): {e}")
            results = []
        if results:
            vector_groups.append(results)

    kw_docs = []
    if keywords:
        try:
            kw_docs = await asyncio.to_thread(
                keyword_match_search,
                keywords=keywords, tenant_id=tenant_id,
                kb_types=kb_types, min_hits=1
            )
        except Exception as e:
            logger.exception(f"关键词检索异常: {e}")

    if len(vector_groups) == 0 and not kw_docs:
        logger.info(f"知识检索: 无结果, tenant={tenant_id}, kb_types={kb_types}")
        return {"retrieved_docs": []}

    vector_fused = (
        vector_groups[0]
        if len(vector_groups) == 1
        else reciprocal_rank_fusion(vector_groups)
    )

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

    final_docs = keyword_boost(final_docs, keywords)

    has_results = len(final_docs) > 0
    record_retrieval(has_results)
    logger.info(
        f"知识检索: query={search_query[:50]}, 召回 {len(final_docs)} 条, tenant={tenant_id}"
    )
    return {"retrieved_docs": final_docs}
