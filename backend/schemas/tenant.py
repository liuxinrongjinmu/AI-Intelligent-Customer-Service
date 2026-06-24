"""
租户相关的 Pydantic Schema
"""
import re
from pydantic import BaseModel, Field, field_validator

_TENANT_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_]{2,64}$')


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="租户名称")
    tenant_id: str = Field(..., description="租户ID（字母、数字、下划线，2-64位）")

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        """校验租户ID格式"""
        if not _TENANT_ID_PATTERN.match(v):
            raise ValueError("tenant_id 仅允许字母、数字、下划线，长度2-64位")
        return v


class TenantResponse(BaseModel):
    tenant_id: str
    name: str
    api_key: str
    is_active: bool

    model_config = {"from_attributes": True}