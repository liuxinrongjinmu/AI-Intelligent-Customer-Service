"""
混合检索：向量语义匹配 + 关键词文本匹配 + RRF 融合 + 多知识库类型检索 + 租户隔离

知识库类型（kb_type）：
- faq:     商家FAQ问答对
- product: 商家商品FAQ
- rule:    商家规则文档
- public:  平台公共知识库（跨租户共享）

融合策略：
- 双路并行召回：向量语义检索 + 关键词文本匹配
- RRF（Reciprocal Rank Fusion）融合两路结果
- 向量路权重 0.7，关键词路权重 0.3，可通过环境变量调整
"""
import os
import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from backend.retrieval.embedding import embed_query_cached
from backend.retrieval.vector_store import query_collection, get_collection, KB_COLLECTIONS
from backend.config import RETRIEVAL_TOP_K, RETRIEVAL_THRESHOLD

# 全量扫描降级时的最大扫描数量，可通过环境变量 KEYWORD_SCAN_LIMIT 配置
MAX_SCAN_LIMIT = int(os.getenv("KEYWORD_SCAN_LIMIT", "5000"))

# RRF 融合参数
RRF_K = int(os.getenv("RRF_K", "60"))  # RRF 常数 K，防止排名靠前的文档过度主导
RRF_VECTOR_WEIGHT = float(os.getenv("RRF_VECTOR_WEIGHT", "0.7"))   # 向量路权重
RRF_KEYWORD_WEIGHT = float(os.getenv("RRF_KEYWORD_WEIGHT", "0.3")) # 关键词路权重

logger = logging.getLogger(__name__)

ALL_KB_TYPES = list(KB_COLLECTIONS)

# 并行查询线程池
_query_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="retrieval")


def shutdown_retrieval_executor():
    """优雅关闭检索线程池"""
    # Python 3.9+ 的 ThreadPoolExecutor.shutdown 不再支持 timeout 参数
    _query_executor.shutdown(wait=True)


def _parse_chromadb_result(raw: dict) -> list[dict]:
    """
    将 ChromaDB 原始查询结果转换为统一的文档格式
    """
    if not raw or not raw.get("ids") or not raw["ids"][0]:
        return []

    formatted = []
    ids_list = raw["ids"][0]
    docs_list = raw.get("documents", [[""]])[0]
    metas_list = raw.get("metadatas", [[{}]])[0]
    distances_list = raw.get("distances", [[1.0]])[0]

    for i in range(len(ids_list)):
        distance = distances_list[i] if i < len(distances_list) else 1.0
        similarity = 1.0 - distance
        metadata = metas_list[i] if i < len(metas_list) else {}
        content = docs_list[i] if i < len(docs_list) else ""
        if content is None:
            content = ""

        formatted.append({
            "content": content,
            "score": round(similarity, 4),
            "source": metadata.get("source_type", metadata.get("kb_type", "unknown")),
            "source_id": metadata.get("source_id", ids_list[i]),
            "kb_type": metadata.get("kb_type", "unknown"),
            "metadata": metadata
        })

    return formatted


def keyword_match_search(
    keywords: list[str],
    tenant_id: str,
    kb_types: Optional[list[str]] = None,
    top_k: Optional[int] = None,
    min_hits: int = 2
) -> list[dict]:
    """
    关键词文本匹配检索：优先使用 ChromaDB where 过滤，降级到全量扫描

    优化：先尝试 ChromaDB 的 where_document 过滤，减少内存中扫描的数据量

    :param keywords: 关键词列表
    :param tenant_id: 租户ID
    :param kb_types: 要检索的知识库类型列表，默认全部
    :param top_k: 返回文档数
    :param min_hits: 最低关键词命中数
    :return: 匹配的文档列表
    """
    if top_k is None:
        top_k = RETRIEVAL_TOP_K
    if kb_types is None:
        kb_types = ALL_KB_TYPES
    if not keywords:
        return []

    effective_min_hits = min(min_hits, len(keywords))

    all_scored = []

    for kb_type in kb_types:
        collection = get_collection(tenant_id, kb_type)

        # 优化：尝试用第一个关键词做 where_document 过滤，减少扫描量
        primary_keyword = keywords[0] if keywords else None
        if primary_keyword:
            try:
                filtered_data = collection.get(
                    where_document={"$contains": primary_keyword}
                )
                if not filtered_data or not filtered_data.get("ids"):
                    continue
                ids_list = filtered_data["ids"]
                docs_list = filtered_data.get("documents", [])
                metas_list = filtered_data.get("metadatas", [])
            except Exception:
                # 降级：全量扫描（限制最大数量）
                logger.warning(f"关键词 where_document 过滤失败，降级为全量扫描 (limit={MAX_SCAN_LIMIT}): tenant={tenant_id}, kb_type={kb_type}")
                all_data = collection.get(limit=MAX_SCAN_LIMIT)
                if not all_data or not all_data.get("ids"):
                    continue
                ids_list = all_data["ids"]
                docs_list = all_data.get("documents", [])
                metas_list = all_data.get("metadatas", [])
        else:
            logger.warning(f"无 primary_keyword，降级为全量扫描 (limit={MAX_SCAN_LIMIT}): tenant={tenant_id}, kb_type={kb_type}")
            all_data = collection.get(limit=MAX_SCAN_LIMIT)
            if not all_data or not all_data.get("ids"):
                continue
            ids_list = all_data["ids"]
            docs_list = all_data.get("documents", [])
            metas_list = all_data.get("metadatas", [])

        for i in range(len(ids_list)):
            content = docs_list[i] if i < len(docs_list) else ""
            if not content:
                continue
            content_lower = content.lower()
            hits = sum(1 for kw in keywords if kw.lower() in content_lower)
            if hits < effective_min_hits:
                continue
            metadata = metas_list[i] if i < len(metas_list) else {}
            metadata["kb_type"] = kb_type
            all_scored.append({
                "content": content,
                "score": round(min(hits / len(keywords), 1.0), 4),
                "source": metadata.get("source_type", "keyword_match"),
                "source_id": metadata.get("source_id", ids_list[i]),
                "kb_type": kb_type,
                "metadata": metadata,
                "_keyword_hits": hits,
            })

    all_scored.sort(key=lambda x: (x["_keyword_hits"], x["score"]), reverse=True)
    return all_scored[:top_k]


def _rrf_fuse(
    vector_results: list[dict],
    keyword_results: list[dict],
    rrf_k: int = RRF_K,
    vector_weight: float = RRF_VECTOR_WEIGHT,
    keyword_weight: float = RRF_KEYWORD_WEIGHT,
) -> list[dict]:
    """
    RRF（Reciprocal Rank Fusion）融合向量检索和关键词检索结果

    算法：对每路结果按排名计算 RRF 分数，同一文档的多路分数加权求和
    RRF_score(d) = Σ w_i / (k + rank_i)

    :param vector_results: 向量检索结果列表（已按 score 降序排列）
    :param keyword_results: 关键词检索结果列表（已按 score 降序排列）
    :param rrf_k: RRF 常数 K，默认 60
    :param vector_weight: 向量路权重
    :param keyword_weight: 关键词路权重
    :return: 融合后的文档列表，按 RRF 分数降序排列
    """
    # 以 content 为去重键（同一文档可能被两路同时召回）
    doc_scores: dict[str, dict] = {}

    # 向量路：按排名计算 RRF 分数
    for rank, doc in enumerate(vector_results, start=1):
        key = doc["content"]
        rrf_score = vector_weight / (rrf_k + rank)
        if key not in doc_scores:
            doc_scores[key] = {"doc": doc, "rrf_score": 0.0}
        doc_scores[key]["rrf_score"] += rrf_score
        # 保留向量路的原始 score
        if "vector_score" not in doc_scores[key]["doc"]:
            doc_scores[key]["doc"]["vector_score"] = doc["score"]

    # 关键词路：按排名计算 RRF 分数
    for rank, doc in enumerate(keyword_results, start=1):
        key = doc["content"]
        rrf_score = keyword_weight / (rrf_k + rank)
        if key not in doc_scores:
            doc_scores[key] = {"doc": doc, "rrf_score": 0.0}
        doc_scores[key]["rrf_score"] += rrf_score
        # 保留关键词路的原始 score
        if "keyword_score" not in doc_scores[key]["doc"]:
            doc_scores[key]["doc"]["keyword_score"] = doc.get("score", 0.0)

    # 按 RRF 分数降序排列
    fused = []
    for entry in doc_scores.values():
        doc = entry["doc"]
        doc["rrf_score"] = round(entry["rrf_score"], 6)
        # 最终 score 使用 RRF 融合分数
        doc["score"] = doc["rrf_score"]
        # 清理内部字段
        doc.pop("_keyword_hits", None)
        fused.append(doc)

    fused.sort(key=lambda x: x["rrf_score"], reverse=True)
    return fused


def _query_single_collection(tenant_id: str, kb_type: str,
                              query_embeddings: list[list[float]], n_results: int) -> list[dict]:
    """
    查询单个 collection（用于线程池并行调用）

    :return: 解析后的文档列表
    """
    try:
        raw_results = query_collection(
            tenant_id=tenant_id,
            kb_type=kb_type,
            query_embeddings=query_embeddings,
            n_results=n_results,
        )
        parsed = _parse_chromadb_result(raw_results)
        for doc in parsed:
            doc["kb_type"] = kb_type
        return parsed
    except Exception as e:
        logger.warning(f"检索 collection 失败: tenant={tenant_id}, kb_type={kb_type}, error={e}")
        return []


def hybrid_search(
    query: str,
    tenant_id: str,
    kb_types: Optional[list[str]] = None,
    keywords: Optional[list[str]] = None,
    top_k: Optional[int] = None,
    relevance_threshold: Optional[float] = None
) -> list[dict]:
    """
    混合检索：向量语义检索 + 关键词文本匹配 + RRF 融合

    双路并行召回：
    - 向量路：跨知识库类型的向量语义检索（多 Collection 并行查询）
    - 关键词路：基于关键词的文本匹配检索（仅当 keywords 非空时启用）
    - RRF 融合：将两路结果按 Reciprocal Rank Fusion 算法融合去重

    :param query: 用户问题
    :param tenant_id: 租户ID
    :param kb_types: 要检索的知识库类型列表，默认全部（faq/product/rule/public）
    :param keywords: 意图关键词列表（为空时仅走向量路）
    :param top_k: 返回文档数
    :param relevance_threshold: 最低相关性阈值（仅过滤向量路结果）
    :return: 排序后的文档列表 [{content, score, source, kb_type, source_id, metadata, rrf_score, ...}, ...]
    """
    if top_k is None:
        top_k = RETRIEVAL_TOP_K
    if relevance_threshold is None:
        relevance_threshold = RETRIEVAL_THRESHOLD
    if kb_types is None:
        kb_types = ALL_KB_TYPES

    # ==================== 向量路：语义检索 ====================
    query_embedding = embed_query_cached(query)

    all_docs = []
    if len(kb_types) > 1:
        futures = []
        for kb_type in kb_types:
            future = _query_executor.submit(
                _query_single_collection,
                tenant_id, kb_type, [query_embedding], top_k * 6
            )
            futures.append(future)
        for future in as_completed(futures):
            try:
                all_docs.extend(future.result(timeout=10))
            except Exception as e:
                logger.warning(f"并行检索超时或失败: {e}")
    else:
        all_docs = _query_single_collection(tenant_id, kb_types[0], [query_embedding], top_k * 6)

    # 过滤低相关性向量结果
    vector_results = [d for d in all_docs if d["score"] >= relevance_threshold]
    vector_results.sort(key=lambda x: x["score"], reverse=True)

    # ==================== 关键词路：文本匹配 ====================
    keyword_results = []
    if keywords:
        try:
            keyword_results = keyword_match_search(
                keywords=keywords,
                tenant_id=tenant_id,
                kb_types=kb_types,
                top_k=top_k * 3,  # 关键词路多召回，给融合更多候选
                min_hits=1,
            )
        except Exception as e:
            logger.warning(f"关键词检索失败，仅使用向量结果: {e}")

    # ==================== RRF 融合 ====================
    if keyword_results:
        fused = _rrf_fuse(vector_results, keyword_results)
        logger.debug(
            f"混合检索融合: 向量路 {len(vector_results)} 条, "
            f"关键词路 {len(keyword_results)} 条, "
            f"融合后 {len(fused)} 条"
        )
        return fused[:top_k]

    # 无关键词结果时，直接返回向量结果
    return vector_results[:top_k]
