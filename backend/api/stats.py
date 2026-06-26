"""
监控与统计 API
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.utils.metrics import get_metrics_text
from backend.models.conversation import Conversation, Message
from backend.models.handoff import HandoffTicket
from backend.utils.auth import verify_chat_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/health")
async def health_check():
    """
    深度健康检查：探测所有依赖组件的连通性

    返回各组件状态，任一组件异常则整体状态为 degraded
    """
    checks = {}

    # 1. PostgreSQL 数据库
    try:
        from backend.database import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
        checks["postgresql"] = {"status": "ok"}
    except Exception as e:
        checks["postgresql"] = {"status": "error", "detail": str(e)[:200]}

    # 2. Redis
    try:
        from backend.utils.redis_client import get_redis
        redis = await get_redis()
        if redis:
            await redis.ping()
            checks["redis"] = {"status": "ok"}
        else:
            checks["redis"] = {"status": "degraded", "detail": "using memory fallback"}
    except Exception as e:
        checks["redis"] = {"status": "degraded", "detail": f"connection failed: {str(e)[:100]}"}

    # 3. ChromaDB 向量库
    try:
        from backend.retrieval.vector_store import get_chroma_client
        client = get_chroma_client()
        client.list_collections()
        checks["chromadb"] = {"status": "ok"}
    except Exception as e:
        checks["chromadb"] = {"status": "error", "detail": str(e)[:200]}

    # 4. Nacos 服务注册
    try:
        from backend.nacos.registry import is_registered
        registered = is_registered()
        checks["nacos"] = {"status": "ok" if registered else "not_registered"}
    except Exception as e:
        checks["nacos"] = {"status": "error", "detail": str(e)[:200]}

    # 汇总状态
    has_error = any(c["status"] == "error" for c in checks.values())
    has_degraded = any(c["status"] in ("degraded", "not_registered") for c in checks.values())

    if has_error:
        overall = "unhealthy"
    elif has_degraded:
        overall = "degraded"
    else:
        overall = "ok"

    return {"status": overall, "checks": checks}


@router.get("/metrics")
def get_metrics(_auth: str = Depends(verify_chat_api_key)):
    """获取 Prometheus 格式的系统运行指标"""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=get_metrics_text(), media_type="text/plain; charset=utf-8")


@router.get("/stats")
def get_stats(
    tenant_id: Optional[str] = Query(None, description="租户ID，为空则返回全局统计"),
    days: int = Query(7, ge=1, le=90, description="统计天数"),
    _auth: str = Depends(verify_chat_api_key),
    db: Session = Depends(get_db),
):
    """获取对话数据统计"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    conv_q = db.query(Conversation)
    msg_q = db.query(Message)
    ticket_q = db.query(HandoffTicket)

    if tenant_id:
        conv_q = conv_q.filter(Conversation.tenant_id == tenant_id)
        msg_q = msg_q.filter(Message.conversation_id.in_(
            db.query(Conversation.id).filter(Conversation.tenant_id == tenant_id)
        ))
        ticket_q = ticket_q.filter(HandoffTicket.tenant_id == tenant_id)

    conv_q = conv_q.filter(Conversation.created_at >= cutoff)
    msg_q = msg_q.filter(Message.created_at >= cutoff)
    ticket_q = ticket_q.filter(HandoffTicket.created_at >= cutoff)

    total_conversations = conv_q.count()
    total_messages = msg_q.count()
    total_handoffs = ticket_q.count()

    pending_tickets = 0
    if tenant_id:
        pending_tickets = db.query(HandoffTicket).filter(
            HandoffTicket.tenant_id == tenant_id,
            HandoffTicket.status == "pending"
        ).count()
    else:
        pending_tickets = db.query(HandoffTicket).filter(
            HandoffTicket.status == "pending"
        ).count()

    return {
        "period_days": days,
        "tenant_id": tenant_id or "全局",
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "total_handoffs": total_handoffs,
        "pending_tickets": pending_tickets,
        "avg_messages_per_conversation": round(total_messages / max(total_conversations, 1), 1),
    }
