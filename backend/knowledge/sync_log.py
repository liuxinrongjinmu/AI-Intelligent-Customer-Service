"""
知识库同步版本管理

记录每次同步操作，支持查看变更历史。回滚通过重新同步历史版本的数据实现。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, String, Integer, DateTime, Text, create_engine
from sqlalchemy.orm import Session

from backend.database import SQLITE_PATH, engine, Base

logger = logging.getLogger(__name__)


class SyncLog(Base):
    """
    同步操作日志

    记录每次知识库同步操作的关键信息，用于追溯和回滚。
    """
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    kb_type = Column(String(32), nullable=False)
    sync_type = Column(String(32), nullable=False)  # full / incremental
    item_count = Column(Integer, default=0)
    processed_count = Column(Integer, default=0)
    deleted_count = Column(Integer, default=0)
    snapshot = Column(Text, nullable=True)  # JSON: 同步的快照数据（最多保留 1000 条）
    status = Column(String(16), default="success")  # success / partial / failed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "kb_type": self.kb_type,
            "sync_type": self.sync_type,
            "item_count": self.item_count,
            "processed_count": self.processed_count,
            "deleted_count": self.deleted_count,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def record_sync_log(
    tenant_id: str,
    kb_type: str,
    sync_type: str,
    item_count: int,
    processed_count: int,
    deleted_count: int = 0,
    status: str = "success",
    snapshot: Optional[list[dict]] = None,
):
    """
    记录一次同步操作

    :param tenant_id: 租户ID
    :param kb_type: 知识库类型
    :param sync_type: 同步类型
    :param item_count: 原始条目数
    :param processed_count: 实际处理数
    :param deleted_count: 删除条目数
    :param status: 操作状态
    :param snapshot: 同步数据快照（用于回滚）
    """
    from backend.database import SessionLocal
    db: Session = SessionLocal()
    try:
        log = SyncLog(
            tenant_id=tenant_id,
            kb_type=kb_type,
            sync_type=sync_type,
            item_count=item_count,
            processed_count=processed_count,
            deleted_count=deleted_count,
            status=status,
            snapshot=json.dumps(snapshot, ensure_ascii=False) if snapshot else None,
        )
        db.add(log)
        db.commit()

        # 清理旧日志：每个租户+知识库类型保留最近 50 条
        _cleanup_old_logs(db, tenant_id, kb_type, keep=50)
    except Exception as e:
        logger.error(f"记录同步日志失败: {e}")
        db.rollback()
    finally:
        db.close()


def get_sync_history(
    tenant_id: str,
    kb_type: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """
    获取同步历史记录

    :param tenant_id: 租户ID
    :param kb_type: 知识库类型（为空则返回所有类型）
    :param limit: 返回条数
    :return: 同步日志列表
    """
    from backend.database import SessionLocal
    db: Session = SessionLocal()
    try:
        q = db.query(SyncLog).filter(SyncLog.tenant_id == tenant_id)
        if kb_type:
            q = q.filter(SyncLog.kb_type == kb_type)
        logs = q.order_by(SyncLog.created_at.desc()).limit(limit).all()
        return [log.to_dict() for log in logs]
    finally:
        db.close()


def get_last_sync_snapshot(tenant_id: str, kb_type: str) -> Optional[list[dict]]:
    """
    获取最近一次成功同步的数据快照（用于回滚）

    :param tenant_id: 租户ID
    :param kb_type: 知识库类型
    :return: 快照数据列表，无记录返回 None
    """
    from backend.database import SessionLocal
    db: Session = SessionLocal()
    try:
        log = (
            db.query(SyncLog)
            .filter(
                SyncLog.tenant_id == tenant_id,
                SyncLog.kb_type == kb_type,
                SyncLog.status == "success",
                SyncLog.snapshot.isnot(None),
            )
            .order_by(SyncLog.created_at.desc())
            .first()
        )
        if log and log.snapshot:
            return json.loads(log.snapshot)
        return None
    finally:
        db.close()


def _cleanup_old_logs(db: Session, tenant_id: str, kb_type: str, keep: int = 50):
    """清理旧日志，每个租户+知识库类型保留最近 N 条"""
    old_ids = (
        db.query(SyncLog.id)
        .filter(SyncLog.tenant_id == tenant_id, SyncLog.kb_type == kb_type)
        .order_by(SyncLog.created_at.desc())
        .offset(keep)
        .all()
    )
    if old_ids:
        ids_to_delete = [row[0] for row in old_ids]
        db.query(SyncLog).filter(SyncLog.id.in_(ids_to_delete)).delete(synchronize_session=False)
        db.commit()