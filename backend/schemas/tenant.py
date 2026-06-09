"""
租户相关的 Pydantic Schema
"""
from pydantic import BaseModel


class TenantCreate(BaseModel):
    name: str
    tenant_id: str


class TenantResponse(BaseModel):
    tenant_id: str
    name: str
    api_key: str
    is_active: bool

    model_config = {"from_attributes": True}