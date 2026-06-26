"""
会话模型 + 工具调用日志

会话状态机：
  ai_serving → human_serving (转人工)
  ai_serving → ended (用户结束)
  human_serving → ended (人工结束)
  queued → ai_serving / human_serving (分配)
"""
from typing import Optional
from sqlalchemy import Column, String, DateTime, Integer, Float, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship

from backend.database import Base
from backend.utils.helpers import utcnow, generate_uuid


SESSION_STATUS = {
    "queued": "排队中",
    "ai_serving": "AI接待中",
    "human_serving": "人工接待中",
    "ended": "已结束",
}

SESSION_CHANNELS = {
    "app": "APP",
    "miniapp": "微信小程序",
    "pc": "PC网页",
    "h5": "移动端H5",
    "unknown": "未知",
}


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    thread_id = Column(String(64), unique=True, default=generate_uuid, index=True)
    tenant_id = Column(String(64), nullable=False, default="default", index=True)
    user_id = Column(String(64), default="", index=True)
    user_name = Column(String(128), default="匿名用户")
    channel = Column(String(16), default="unknown")
    status = Column(String(16), default="ai_serving", index=True)
    agent_id = Column(String(64), default="")
    priority = Column(Integer, default=0)
    tags = Column(JSON, default=list)
    summary = Column(Text, default="")
    context_snapshot = Column(JSON, default=dict)
    ai_failed_count = Column(Integer, default=0)
    message_count = Column(Integer, default=0)
    rating = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow, index=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    ended_at = Column(DateTime, nullable=True, index=True)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "channel": self.channel,
            "status": self.status,
            "agent_id": self.agent_id,
            "priority": self.priority,
            "tags": self.tags,
            "summary": self.summary,
            "message_count": self.message_count,
            "rating": self.rating,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }

    def transfer_to_human(self, priority: int = 5, summary: str = "", tags: Optional[list] = None) -> None:
        """转人工"""
        self.status = "human_serving"
        self.priority = max(self.priority, priority)
        if summary:
            self.summary = summary
        if tags:
            current_tags = self.tags or []
            current_tags.extend(tags)
            self.tags = list(set(current_tags))

    def end_session(self) -> None:
        """结束会话"""
        self.status = "ended"
        self.ended_at = utcnow()


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    conversation_id = Column(String(64), ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, default="")
    intent = Column(String(32), default="")
    intent_sub_type = Column(String(32), default="")
    entities = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow, index=True)

    conversation = relationship("Conversation", back_populates="messages")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "intent": self.intent,
            "intent_sub_type": self.intent_sub_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ToolCallLog(Base):
    """工具调用日志"""
    __tablename__ = "tool_call_logs"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    conversation_id = Column(String(64), index=True)
    tenant_id = Column(String(64), nullable=False, default="default", index=True)
    tool_name = Column(String(64), nullable=False)
    tool_params = Column(JSON, default=dict)
    tool_result = Column(JSON, default=dict)
    success = Column(Integer, default=0)
    duration_ms = Column(Float, default=0.0)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "tenant_id": self.tenant_id,
            "tool_name": self.tool_name,
            "success": bool(self.success),
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }