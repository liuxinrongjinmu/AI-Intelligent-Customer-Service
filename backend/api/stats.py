"""
监控与统计 API
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, Body, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.utils.metrics import get_metrics_text, get_metrics_json
from backend.utils.response_cache import cache_stats
from backend.models.conversation import Conversation, Message
from backend.models.handoff import HandoffTicket
from backend.models.feedback import Feedback
from backend.utils.auth import verify_chat_api_key
from backend.schemas.stats import FeedbackRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/health")
def health_check():
    """健康检查"""
    return {"status": "ok"}


@router.get("/metrics")
def get_metrics(_auth: str = Depends(verify_chat_api_key)):
    """获取 Prometheus 格式的系统运行指标"""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=get_metrics_text(), media_type="text/plain; charset=utf-8")


@router.get("/metrics/json")
def get_metrics_json_endpoint(_auth: str = Depends(verify_chat_api_key)):
    """获取 JSON 格式的系统运行指标"""
    return get_metrics_json()


@router.get("/cache")
def get_cache_info(_auth: str = Depends(verify_chat_api_key)):
    """获取缓存统计"""
    return cache_stats()


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


@router.get("/stats/tickets")
def get_ticket_stats(
    tenant_id: str = Query(..., description="租户ID"),
    _auth: str = Depends(verify_chat_api_key),
    db: Session = Depends(get_db),
):
    """获取工单统计"""
    tickets = (
        db.query(
            HandoffTicket.reason,
            func.count(HandoffTicket.id).label("count")
        )
        .filter(HandoffTicket.tenant_id == tenant_id)
        .group_by(HandoffTicket.reason)
        .all()
    )
    return {
        "tenant_id": tenant_id,
        "tickets_by_reason": {(r.reason or "未分类"): r.count for r in tickets},
    }


@router.get("/stats/kb-health")
def kb_health_check(
    tenant_id: str = Query(..., description="租户ID"),
    _auth: str = Depends(verify_chat_api_key),
):
    """知识库健康检查"""
    from backend.retrieval.vector_store import get_collection
    from backend.config import CHROMA_PATH

    health = {"tenant_id": tenant_id, "collections": {}}

    kb_types = ["faq", "product", "rule", "public"]
    for kb_type in kb_types:
        try:
            collection = get_collection(tenant_id, kb_type)
            count = collection.count()
            health["collections"][kb_type] = {
                "count": count,
                "status": "healthy" if count > 0 else "empty",
            }
        except Exception as e:
            health["collections"][kb_type] = {
                "count": 0,
                "status": "error",
                "error": str(e),
            }

    total = sum(c.get("count", 0) for c in health["collections"].values())
    health["total_documents"] = total
    health["overall_status"] = "healthy" if total > 0 else "warning"

    return health


@router.post("/feedback")
def submit_feedback(
    body: FeedbackRequest = Body(...),
    _auth: str = Depends(verify_chat_api_key),
    db: Session = Depends(get_db),
):
    """提交对话满意度评价"""
    conv = db.query(Conversation).filter_by(thread_id=body.thread_id).first()
    if not conv:
        raise HTTPException(
            status_code=404,
            detail={"code": "CONVERSATION_NOT_FOUND", "message": "会话不存在"}
        )

    feedback = Feedback(
        tenant_id=body.tenant_id or conv.tenant_id,
        conversation_id=conv.id,
        thread_id=body.thread_id,
        rating=body.rating,
        comment=body.comment,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return {"success": True, "feedback": feedback.to_dict()}


@router.get("/feedback")
def get_feedback_stats(
    tenant_id: str = Query(..., description="租户ID"),
    days: int = Query(30, ge=1, le=365),
    _auth: str = Depends(verify_chat_api_key),
    db: Session = Depends(get_db),
):
    """获取满意度统计"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    q = db.query(Feedback).filter(
        Feedback.tenant_id == tenant_id,
        Feedback.created_at >= cutoff,
    )
    total = q.count()
    if total == 0:
        return {"tenant_id": tenant_id, "total": 0, "avg_rating": 0, "distribution": {}}

    avg_rating = db.query(func.avg(Feedback.rating)).filter(
        Feedback.tenant_id == tenant_id,
        Feedback.created_at >= cutoff,
    ).scalar()

    dist = (
        db.query(Feedback.rating, func.count(Feedback.id))
        .filter(Feedback.tenant_id == tenant_id, Feedback.created_at >= cutoff)
        .group_by(Feedback.rating)
        .all()
    )

    return {
        "tenant_id": tenant_id,
        "period_days": days,
        "total": total,
        "avg_rating": round(float(avg_rating), 2),
        "distribution": {r: c for r, c in dist},
    }
