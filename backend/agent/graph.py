"""
LangGraph Agent 图构建：定义节点和路由的完整拓扑

拓扑结构（按优先级从高到低）：
  START → classify_intent → route_by_intent
    ├─ human_service     → human_service_node → END
    ├─ order_query       → order_query_node → END
    ├─ logistics_query   → order_query_node → END（订单+物流联动）
    ├─ product_query     → product_query_node → END
    ├─ coupon_query      → coupon_query_node → END
    ├─ account_query     → account_query_node → END
    ├─ knowledge_query   → retrieve_knowledge → generate_answer → END
    ├─ complaint         → complaint_node → END
    └─ greeting/feedback/other → greeting_answer → END

多轮对话：通过 AsyncPostgresSaver 持久化 checkpoints，服务重启不丢失对话状态
"""
import asyncio
import logging
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)

from backend.agent.state import AgentState
from backend.agent.nodes import (
    classify_intent_node,
    route_by_intent,
    retrieve_knowledge_node,
    generate_answer_node,
    greeting_answer_node,
    order_query_node,
    complaint_node,
    human_service_node,
    product_query_node,
    coupon_query_node,
    account_query_node,
)

_agent = None
_agent_lock = asyncio.Lock()
_checkpointer = None


def build_graph() -> StateGraph:
    """
    构建 Agent 图（同步版本，不含 checkpointer）
    """
    graph = StateGraph(AgentState)

    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("retrieve_knowledge", retrieve_knowledge_node)
    graph.add_node("generate_answer", generate_answer_node)
    graph.add_node("greeting_answer", greeting_answer_node)
    graph.add_node("order_query_node", order_query_node)
    graph.add_node("complaint_node", complaint_node)
    graph.add_node("human_service_node", human_service_node)
    graph.add_node("product_query_node", product_query_node)
    graph.add_node("coupon_query_node", coupon_query_node)
    graph.add_node("account_query_node", account_query_node)

    graph.add_edge(START, "classify_intent")

    graph.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "retrieve_knowledge": "retrieve_knowledge",
            "order_query_node": "order_query_node",
            "complaint_node": "complaint_node",
            "human_service_node": "human_service_node",
            "greeting_answer": "greeting_answer",
            "product_query_node": "product_query_node",
            "coupon_query_node": "coupon_query_node",
            "account_query_node": "account_query_node",
        }
    )

    graph.add_edge("retrieve_knowledge", "generate_answer")

    graph.add_edge("generate_answer", END)
    graph.add_edge("greeting_answer", END)
    graph.add_edge("order_query_node", END)
    graph.add_edge("complaint_node", END)
    graph.add_edge("human_service_node", END)
    graph.add_edge("product_query_node", END)
    graph.add_edge("coupon_query_node", END)
    graph.add_edge("account_query_node", END)

    return graph


async def build_graph_async() -> StateGraph:
    """
    构建并编译 Agent 图（异步版本，使用 AsyncPostgresSaver 持久化）
    """
    global _checkpointer
    try:
        memory = AsyncPostgresSaver.from_conn_string(DATABASE_URL)
        await memory.setup()
        _checkpointer = memory
        graph = build_graph()
        return graph.compile(checkpointer=memory)
    except Exception as e:
        logger.warning(f"Checkpoint 连接失败: {e}")
        _checkpointer = None
        raise


async def get_agent() -> StateGraph:
    """
    获取 Agent 实例（单例，异步初始化，加锁防并发竞态）
    """
    global _agent
    if _agent is None:
        async with _agent_lock:
            if _agent is None:
                _agent = await build_graph_async()
    return _agent


async def close_agent():
    """
    关闭 Agent 资源（AsyncPostgresSaver 无需显式关闭连接）
    在应用 lifespan shutdown 时调用
    """
    global _agent, _checkpointer
    async with _agent_lock:
        _checkpointer = None
        _agent = None