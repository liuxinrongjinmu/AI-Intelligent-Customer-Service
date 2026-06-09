"""
转人工工单服务
"""
import logging
from backend.database import SessionLocal
from backend.models.handoff import HandoffTicket
from backend.utils.helpers import utcnow

logger = logging.getLogger(__name__)

REASON_LABELS = {
    "user_request": "用户要求转人工",
    "complaint": "用户投诉",
    "emotional": "用户情绪激动",
    "safety": "安全问题",
    "ai_limitation": "AI无法处理",
}


def create_handoff_ticket(
    tenant_id: str,
    conversation_id: str,
    thread_id: str,
    reason: str,
    reason_detail: str = "",
    summary: str = "",
    user_id: str = "",
    user_name: str = "",
) -> dict:
    """
    创建转人工工单

    :param tenant_id: 租户 ID
    :param conversation_id: 会话 ID
    :param thread_id: 对话线程 ID
    :param reason: 转人工原因（user_request/complaint/emotional/safety/ai_limitation）
    :param reason_detail: 原因详情
    :param summary: 问题摘要
    :param user_id: 用户 ID
    :param user_name: 用户名称
    :return: 工单信息
    """
    db = None
    try:
        db = SessionLocal()
        ticket = HandoffTicket(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            user_id=user_id,
            user_name=user_name,
            reason=reason,
            reason_detail=reason_detail or REASON_LABELS.get(reason, reason),
            summary=summary,
            status="pending",
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        logger.info(
            f"转人工工单创建成功: ticket_id={ticket.id}, "
            f"tenant={tenant_id}, reason={reason}"
        )
        return {"success": True, "ticket": ticket.to_dict()}
    except Exception as e:
        if db:
            db.rollback()
        logger.error(f"创建转人工工单失败: {e}")
        return {"success": False, "message": str(e)}
    finally:
        if db:
            db.close()


def query_handoff_tickets(
    tenant_id: str,
    status: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    查询转人工工单

    :param tenant_id: 租户 ID
    :param status: 状态筛选（pending/assigned/resolved）
    :param limit: 每页数量
    :param offset: 偏移量
    :return: 工单列表
    """
    db = None
    try:
        db = SessionLocal()
        q = db.query(HandoffTicket).filter(HandoffTicket.tenant_id == tenant_id)
        if status:
            q = q.filter(HandoffTicket.status == status)
        total = q.count()
        tickets = q.order_by(HandoffTicket.created_at.desc()).offset(offset).limit(limit).all()
        return {
            "success": True,
            "total": total,
            "tickets": [t.to_dict() for t in tickets],
        }
    except Exception as e:
        logger.error(f"查询转人工工单失败: {e}")
        return {"success": False, "message": str(e)}
    finally:
        if db:
            db.close()


def resolve_handoff_ticket(ticket_id: str, assigned_to: str = "") -> dict:
    """
    解决转人工工单

    :param ticket_id: 工单 ID
    :param assigned_to: 分配给谁
    :return: 操作结果
    """
    db = None
    try:
        db = SessionLocal()
        ticket = db.query(HandoffTicket).filter_by(id=ticket_id).first()
        if not ticket:
            return {"success": False, "message": "工单不存在"}
        ticket.status = "resolved"
        ticket.resolved_at = utcnow()
        if assigned_to:
            ticket.assigned_to = assigned_to
        db.commit()
        logger.info(f"工单已解决: ticket_id={ticket_id}")
        return {"success": True, "ticket": ticket.to_dict()}
    except Exception as e:
        if db:
            db.rollback()
        logger.error(f"解决工单失败: {e}")
        return {"success": False, "message": str(e)}
    finally:
        if db:
            db.close()