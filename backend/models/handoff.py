"""
转人工工单模型
"""
from sqlalchemy import Column, String, Text, DateTime, Integer, Index
from backend.database import Base
from backend.utils.helpers import utcnow, generate_uuid


class HandoffTicket(Base):
    __tablename__ = "handoff_tickets"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    conversation_id = Column(String(64), nullable=False, index=True)
    thread_id = Column(String(64), nullable=False)
    user_id = Column(String(128), default="")
    user_name = Column(String(128), default="")
    reason = Column(String(32), nullable=False)
    reason_detail = Column(Text, default="")
    summary = Column(Text, default="")
    status = Column(String(16), default="pending", index=True)
    priority = Column(Integer, default=0)
    assigned_to = Column(String(128), default="")
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_handoff_tenant_status", "tenant_id", "status"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "conversation_id": self.conversation_id,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "reason": self.reason,
            "reason_detail": self.reason_detail,
            "summary": self.summary,
            "status": self.status,
            "priority": self.priority,
            "assigned_to": self.assigned_to,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }