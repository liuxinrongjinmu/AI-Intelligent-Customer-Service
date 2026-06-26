"""
知识库同步 API — 接收聚宝赞系统推送的知识库数据

认证方式: 内网 VPN + Gateway 网关认证（校验 X-Gateway-Verified 头 + IP 白名单）

设计说明：
  聚宝赞端将单次批量操作控制在 10 条左右，因此接口直接实时处理并返回结果，
  不再使用异步 task_id + 轮询模式。

接口列表：
  POST   /sync/{tenant_id}/{kb_type}          全量/增量同步（实时）
  POST   /sync/{tenant_id}/{kb_type}/batch    批量增删操作（实时，支持单条删除）
  DELETE /sync/{tenant_id}/{kb_type}          清空知识库（实时）
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.retrieval.vector_store import (
    clear_collection, delete_from_collection, KB_COLLECTIONS
)
from backend.schemas.knowledge import (
    KnowledgeSyncRequest, KnowledgeBatchRequest, KnowledgeSyncResponse
)
from backend.services.sync_service import process_sync, process_batch
from backend.utils.auth import verify_sync_api_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge_sync"])


def _validate_kb_type(kb_type: str):
    """验证知识库类型是否合法"""
    if kb_type not in KB_COLLECTIONS:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_KB_TYPE", "message": f"无效的知识库类型: {kb_type}，支持: {', '.join(KB_COLLECTIONS)}"}
        )


def _validate_tenant(tenant_id: str, db: Session):
    """验证租户是否存在"""
    from backend.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(tenant_id=tenant_id, is_active=True).first()
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail={"code": "TENANT_NOT_FOUND", "message": f"租户不存在: {tenant_id}"}
        )
    return tenant


# ============================================================
# 全量 / 增量同步（实时返回）
# ============================================================

@router.post("/sync/{tenant_id}/{kb_type}")
def sync_knowledge(
    tenant_id: str,
    kb_type: str,
    body: KnowledgeSyncRequest,
    _api_key: str = Depends(verify_sync_api_key),
    db: Session = Depends(get_db),
):
    """
    全量 / 增量同步知识库（实时处理，直接返回结果）

    聚宝赞系统在商家知识库变更时调用此接口。
    - full：先清空该租户该类型的知识库，再写入新数据
    - incremental：追加/更新数据（不删除已有）

    示例请求：
    POST /api/v1/knowledge/sync/shop_001/product
    Header: X-Gateway-Verified: true
    {
      "sync_type": "full",
      "items": [
        {"id": "prod_001", "content": "燕麦片 500g 38.8元 ...", "metadata": {...}},
        ...
      ]
    }
    """
    if kb_type != "public":
        _validate_tenant(tenant_id, db)
    _validate_kb_type(kb_type)

    VALID_SYNC_TYPES = {"full", "incremental"}
    if body.sync_type not in VALID_SYNC_TYPES:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_SYNC_TYPE", "message": f"无效的同步类型: {body.sync_type}，仅支持 full/incremental"}
        )

    is_full = body.sync_type == "full"
    sync_type = "full" if is_full else "incremental"

    items_dict = [item.model_dump() for item in (body.items or [])]

    result = await process_sync(
        tenant_id=tenant_id,
        kb_type=kb_type,
        sync_type=sync_type,
        items=items_dict,
        full_replace=is_full,
    )

    logger.info(
        f"同步完成: tenant={tenant_id}, kb_type={kb_type}, "
        f"sync_type={sync_type}, processed={result['processed_count']}, "
        f"deleted={result['deleted_count']}"
    )

    return KnowledgeSyncResponse(
        success=True,
        kb_type=kb_type,
        tenant_id=tenant_id,
        synced_count=result["processed_count"],
        deleted_count=result["deleted_count"],
        message=f"同步完成，共处理 {result['processed_count']} 条"
    )


# ============================================================
# 批量增删操作（实时返回，支持单条删除）
# ============================================================

@router.post("/sync/{tenant_id}/{kb_type}/batch")
def sync_knowledge_batch(
    tenant_id: str,
    kb_type: str,
    body: KnowledgeBatchRequest,
    _api_key: str = Depends(verify_sync_api_key),
    db: Session = Depends(get_db),
):
    """
    批量增删知识库（实时处理，直接返回结果）

    支持同时新增/更新和删除文档。聚宝赞端单次批量操作控制在 10 条左右，
    因此接口直接实时处理，不再使用异步 task_id。

    可通过 delete_ids 传入单个 ID 实现单条删除，无需单独接口。

    示例请求：
    POST /api/v1/knowledge/sync/shop_001/faq/batch
    Header: X-Gateway-Verified: true
    {
      "add": [{"id": "faq_new_001", "content": "新增FAQ...", "metadata": {...}}],
      "delete_ids": ["faq_old_001", "faq_old_002"]
    }
    """
    if kb_type != "public":
        _validate_tenant(tenant_id, db)
    _validate_kb_type(kb_type)

    items_dict = [item.model_dump() for item in (body.add or [])]

    result = await process_batch(
        tenant_id=tenant_id,
        kb_type=kb_type,
        items=items_dict,
        delete_ids=list(body.delete_ids) if body.delete_ids else None,
    )

    logger.info(
        f"批量操作完成: tenant={tenant_id}, kb_type={kb_type}, "
        f"add={result['processed_count']}, delete={result['deleted_count']}"
    )

    return KnowledgeSyncResponse(
        success=True,
        kb_type=kb_type,
        tenant_id=tenant_id,
        synced_count=result["processed_count"],
        deleted_count=result["deleted_count"],
        message=f"批量操作完成，新增 {result['processed_count']} 条，删除 {result['deleted_count']} 条"
    )


# ============================================================
# 清空知识库（实时）
# ============================================================

@router.delete("/sync/{tenant_id}/{kb_type}")
def clear_knowledge_base(
    tenant_id: str,
    kb_type: str,
    _api_key: str = Depends(verify_sync_api_key),
    db: Session = Depends(get_db),
):
    """
    清空某个租户的某类知识库（实时操作）
    """
    if kb_type != "public":
        _validate_tenant(tenant_id, db)
    _validate_kb_type(kb_type)

    clear_collection(tenant_id, kb_type)

    logger.info(f"知识库清空: tenant={tenant_id}, kb_type={kb_type}")

    return KnowledgeSyncResponse(
        success=True,
        kb_type=kb_type,
        tenant_id=tenant_id,
        message=f"已清空 {tenant_id}/{kb_type} 知识库"
    )


# ============================================================
# 同步历史（版本管理）
# ============================================================

@router.get("/sync/{tenant_id}/history")
def get_sync_history(
    tenant_id: str,
    kb_type: str = None,
    limit: int = Query(20, le=200),
    _api_key: str = Depends(verify_sync_api_key),
    db: Session = Depends(get_db),
):
    """
    获取知识库同步历史记录

    :param tenant_id: 租户ID
    :param kb_type: 知识库类型（可选，为空返回所有类型）
    :param limit: 返回条数
    """
    if kb_type != "public":
        _validate_tenant(tenant_id, db)
    from backend.knowledge.sync_log import get_sync_history
    history = get_sync_history(tenant_id, kb_type, limit)
    return {"success": True, "tenant_id": tenant_id, "history": history}


@router.post("/sync/{tenant_id}/{kb_type}/rollback")
def rollback_knowledge(
    tenant_id: str,
    kb_type: str,
    _api_key: str = Depends(verify_sync_api_key),
    db: Session = Depends(get_db),
):
    """
    回滚知识库到上一次成功同步的快照

    从 sync_logs 中取出最近一次 status=success 且含 snapshot 的记录，
    重新写入 ChromaDB（全量替换）。

    :param tenant_id: 租户ID
    :param kb_type: 知识库类型
    """
    if kb_type != "public":
        _validate_tenant(tenant_id, db)
    _validate_kb_type(kb_type)

    from backend.knowledge.sync_log import get_last_sync_snapshot
    snapshot = get_last_sync_snapshot(tenant_id, kb_type)
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NO_SNAPSHOT",
                "message": f"未找到 {tenant_id}/{kb_type} 的历史快照，无法回滚",
            },
        )

    # 使用快照数据重新全量同步
    result = await process_sync(
        tenant_id=tenant_id,
        kb_type=kb_type,
        sync_type="rollback",
        items=snapshot,
        full_replace=True,
    )

    logger.info(
        f"知识库回滚完成: tenant={tenant_id}, kb_type={kb_type}, "
        f"restored={result['processed_count']}"
    )

    return KnowledgeSyncResponse(
        success=True,
        kb_type=kb_type,
        tenant_id=tenant_id,
        synced_count=result["processed_count"],
        deleted_count=result["deleted_count"],
        message=f"已回滚到上一次成功同步的快照，共恢复 {result['processed_count']} 条",
    )