"""
用户反馈模型
"""
from sqlalchemy import Column, String, Integer, DateTime, Text
from backend.database import Base
from backend.utils.helpers import utcnow, generate_uuid


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    conversation_id = Column(String(64), nullable=False, index=True)
    thread_id = Column(String(64), nullable=False)
    message_id = Column(String(64), default="")
    rating = Column(Integer, nullable=False)
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "conversation_id": self.conversation_id,
            "thread_id": self.thread_id,
            "message_id": self.message_id,
            "rating": self.rating,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }