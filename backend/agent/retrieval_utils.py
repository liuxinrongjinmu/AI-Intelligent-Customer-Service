"""
检索工具：RRF 融合、关键词加成、文档格式化、回答清理、历史格式化
"""
import re
import copy
import logging

from backend.config import HISTORY_MESSAGE_BUDGET, KNOWLEDGE_CONTEXT_BUDGET, HISTORY_MAX_TURNS_FALLBACK
from backend.utils.token_budget import format_history_token_aware, format_knowledge_token_aware

logger = logging.getLogger(__name__)

# 回答后处理：禁止匹配的模式（正则）
BANNED_PATTERNS = [
    r"\[\d+\]",
    r"明细来源[:：]\s*\S+",
    r"\(来源[:：]\s*\S+\)",
    r"信息来源[:：]\s*\S+",
]

# 回答后处理：禁止出现的短语（精确匹配替换）
BANNED_PHRASES = [
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


def format_history(messages: list, max_turns: int = 4) -> str:
    """格式化对话历史（token 感知的动态裁剪版本）"""
    return format_history_token_aware(
        messages=messages,
        max_tokens=HISTORY_MESSAGE_BUDGET,
        max_turns_fallback=max_turns,
    )


def reciprocal_rank_fusion(
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


def keyword_boost(
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


def format_docs_for_llm(docs: list[dict]) -> str:
    """将检索结果格式化为 LLM 可读的上下文（token 感知版本）"""
    return format_knowledge_token_aware(
        docs=docs,
        max_tokens=KNOWLEDGE_CONTEXT_BUDGET,
    )


def clean_answer(answer: str) -> str:
    """后处理：移除禁止短语、引用标记、多余空行"""
    for phrase in BANNED_PHRASES:
        answer = answer.replace(phrase, "")
    for pattern in BANNED_PATTERNS:
        answer = re.sub(pattern, "", answer)
    answer = re.sub(r"[。.]\s*$", "", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer)
    answer = answer.strip()
    return answer
