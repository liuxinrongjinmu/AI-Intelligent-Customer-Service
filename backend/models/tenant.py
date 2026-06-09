"""
租户表：每个商家作为一个独立租户
"""
import hashlib
import secrets
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from backend.database import Base
from backend.utils.helpers import utcnow


def generate_api_key() -> tuple[str, str, str]:
    """
    生成 API Key，返回 (原始Key, 哈希值, 前缀)
    """
    raw = f"jbz-{secrets.token_hex(12)}"
    prefix = raw[:11]
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed, prefix


def hash_api_key(raw_key: str) -> str:
    if not raw_key:
        raise ValueError("raw_key cannot be empty")
    return hashlib.sha256(raw_key.encode()).hexdigest()


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    api_key_hash = Column(String(256), nullable=False)
    api_key_prefix = Column(String(16), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self):
        return f"<Tenant(tenant_id={self.tenant_id}, name={self.name})>"