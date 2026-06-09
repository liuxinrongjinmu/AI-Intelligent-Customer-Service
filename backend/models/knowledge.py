"""
知识库模型：FAQ 问答对 + 文档记录
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from backend.database import Base
from backend.utils.helpers import utcnow


class FAQ(Base):
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    category = Column(String(32), default="通用")
    tags = Column(String(256), default="")
    is_enabled = Column(Boolean, default=True)
    chroma_ids = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self):
        return f"<FAQ(id={self.id}, question={(self.question or '')[:30]})>"


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    filename = Column(String(256), nullable=False)
    file_type = Column(String(16), nullable=False)
    file_size = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    is_enabled = Column(Boolean, default=True)
    chroma_ids = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)

    def __repr__(self):
        return f"<Document(id={self.id}, filename={self.filename})>"
