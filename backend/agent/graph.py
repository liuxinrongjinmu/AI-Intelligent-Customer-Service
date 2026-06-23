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

多轮对话：通过 AsyncSqliteSaver 持久化 checkpoints，服务重启不丢失对话状态
"""
import asyncio
import logging
import aiosqlite
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.config import CHECKPOINT_PATH

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
_checkpoint_conn = None


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
    构建并编译 Agent 图（异步版本，使用 AsyncSqliteSaver 持久化）
    """
    global _checkpoint_conn
    import os
    os.makedirs(os.path.dirname(CHECKPOINT_PATH) or ".", exist_ok=True)
    try:
        conn = await aiosqlite.connect(CHECKPOINT_PATH)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        _checkpoint_conn = conn
        memory = AsyncSqliteSaver(conn)
        await memory.setup()
        graph = build_graph()
        return graph.compile(checkpointer=memory)
    except Exception as e:
        logger.warning(f"Checkpoint 连接失败: {e}")
        if _checkpoint_conn:
            try:
                await _checkpoint_conn.close()
            except Exception as e2:
                logger.debug(f"关闭 checkpoint 连接失败: {e2}")
        _checkpoint_conn = None
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
    关闭 Agent 资源（aiosqlite 连接）
    在应用 lifespan shutdown 时调用
    """
    global _agent, _checkpoint_conn
    async with _agent_lock:
        if _checkpoint_conn is not None:
            try:
                await _checkpoint_conn.close()
            except Exception as e:
                logger.debug(f"关闭 checkpoint 连接失败: {e}")
            _checkpoint_conn = None
        _agent = None