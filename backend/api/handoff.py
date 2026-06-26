"""
转人工工单管理 API

提供工单查询和解决接口，供人工客服系统调用。
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.handoff_service import query_handoff_tickets, resolve_handoff_ticket
from backend.utils.auth import verify_admin_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/handoff", tags=["转人工工单"])


@router.get("/{tenant_id}/tickets")
def list_handoff_tickets(
    tenant_id: str,
    status: str = Query("", description="状态筛选: pending/assigned/resolved"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_admin_key),
):
    """
    查询转人工工单列表

    :param tenant_id: 租户 ID
    :param status: 状态筛选
    :param limit: 每页数量
    :param offset: 偏移量
    :return: 工单列表
    """
    result = query_handoff_tickets(
        tenant_id=tenant_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail={"code": "QUERY_FAILED", "message": result.get("message", "查询失败")})
    return result


@router.put("/tickets/{ticket_id}/resolve")
def resolve_ticket(
    ticket_id: str,
    assigned_to: str = Query("", description="处理人"),
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_admin_key),
):
    """
    解决转人工工单

    :param ticket_id: 工单 ID
    :param assigned_to: 处理人
    :return: 操作结果
    """
    result = resolve_handoff_ticket(ticket_id=ticket_id, assigned_to=assigned_to)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": result.get("message", "工单不存在")})
    return result
