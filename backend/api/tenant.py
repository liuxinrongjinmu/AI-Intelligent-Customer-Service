"""
租户管理 API
"""
from fastapi import APIRouter, Depends, HTTPException
from backend.database import get_db
from sqlalchemy.orm import Session
from backend.models.tenant import Tenant, generate_api_key
from backend.schemas.tenant import TenantCreate, TenantResponse
from backend.utils.auth import verify_admin_key

router = APIRouter(prefix="/api/v1/tenant", tags=["租户管理"])


@router.post("/create", response_model=TenantResponse)
def create_tenant(
    data: TenantCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_key),
):
    """
    平台创建租户（MVP阶段管理端操作）
    """
    existing = db.query(Tenant).filter_by(tenant_id=data.tenant_id).first()
    if existing:
        raise HTTPException(status_code=409, detail={"code": "TENANT_EXISTS", "message": f"租户 {data.tenant_id} 已存在"})

    raw_key, hashed, prefix = generate_api_key()
    tenant = Tenant(
        tenant_id=data.tenant_id,
        name=data.name,
        api_key_hash=hashed,
        api_key_prefix=prefix,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    return TenantResponse(
        tenant_id=tenant.tenant_id,
        name=tenant.name,
        api_key=raw_key,
        is_active=tenant.is_active,
    )