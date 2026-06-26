"""
Agent 节点实现（向后兼容重导出模块）

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

实际实现已拆分到：
  - backend.agent.llm_utils       LLM 调用工具 + 模型工厂
  - backend.agent.retrieval_utils  检索工具（RRF/关键词/格式化/清理）
  - backend.agent.classifier       意图分类 + 路由
  - backend.agent.retriever        知识检索
  - backend.agent.generator        回答生成 + 问候
  - backend.agent.domains.*        业务域节点
"""
from backend.agent.llm_utils import (
    safe_llm_invoke,
    safe_llm_stream,
    get_classify_llm,
    get_generate_llm,
)
from backend.agent.retrieval_utils import (
    BANNED_PATTERNS,
    BANNED_PHRASES,
    format_history,
    reciprocal_rank_fusion,
    keyword_boost,
    format_docs_for_llm,
    clean_answer,
)
from backend.agent.classifier import (
    classify_intent_node,
    route_by_intent,
)
from backend.agent.retriever import (
    retrieve_knowledge_node,
)
from backend.agent.generator import (
    generate_answer_node,
    greeting_answer_node,
)
from backend.agent.domains import (
    order_query_node,
    product_query_node,
    coupon_query_node,
    account_query_node,
    complaint_node,
    human_service_node,
)

# 向后兼容的私有别名
_safe_llm_invoke = safe_llm_invoke
_safe_llm_stream = safe_llm_stream
_get_classify_llm = get_classify_llm
_get_generate_llm = get_generate_llm
_format_history = format_history
_reciprocal_rank_fusion = reciprocal_rank_fusion
_keyword_boost = keyword_boost
_format_docs_for_llm = format_docs_for_llm
_clean_answer = clean_answer
_BANNED_PATTERNS = BANNED_PATTERNS
_BANNED_PHRASES = BANNED_PHRASES

__all__ = [
    "classify_intent_node",
    "route_by_intent",
    "retrieve_knowledge_node",
    "generate_answer_node",
    "greeting_answer_node",
    "order_query_node",
    "product_query_node",
    "coupon_query_node",
    "account_query_node",
    "complaint_node",
    "human_service_node",
]
