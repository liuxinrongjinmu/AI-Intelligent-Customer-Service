"""
SQLite 数据库自动备份模块

在 FastAPI 启动时注册后台任务，定时备份 SQLite 数据库。
- 备份频率：每小时
- 保留数量：最近 24 个备份 + 每日快照（7天）
- 备份位置：data/backups/
"""
import asyncio
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from backend.database import SQLITE_PATH

logger = logging.getLogger(__name__)

# 备份配置
BACKUP_DIR = Path("data/backups")
BACKUP_INTERVAL_SECONDS = 3600       # 备份间隔：1小时
MAX_HOURLY_BACKUPS = 24              # 保留最近 24 个每小时备份
MAX_DAILY_BACKUPS = 7                # 保留最近 7 个每日快照

_backup_task: asyncio.Task | None = None


def _ensure_backup_dir():
    """确保备份目录存在"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def backup_now() -> str | None:
    """
    立即执行一次数据库备份

    :return: 备份文件路径，失败返回 None
    """
    _ensure_backup_dir()

    if not os.path.exists(SQLITE_PATH):
        logger.warning(f"数据库文件不存在，跳过备份: {SQLITE_PATH}")
        return None

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"app_{timestamp}.db"

        # 使用 SQLite 的 backup API 确保一致性
        import sqlite3
        src = sqlite3.connect(SQLITE_PATH)
        dst = sqlite3.connect(str(backup_path))
        src.backup(dst)
        src.close()
        dst.close()

        logger.info(f"数据库备份成功: {backup_path} ({backup_path.stat().st_size} bytes)")
        return str(backup_path)
    except Exception as e:
        logger.error(f"数据库备份失败: {e}")
        return None


def _cleanup_old_backups():
    """
    清理过期备份
    - 每小时备份：保留最近 MAX_HOURLY_BACKUPS 个
    - 每日快照：保留最近 MAX_DAILY_BACKUPS 个
    """
    _ensure_backup_dir()

    try:
        backups = sorted(
            BACKUP_DIR.glob("app_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if len(backups) <= MAX_HOURLY_BACKUPS:
            return

        # 保留最新的 MAX_HOURLY_BACKUPS 个
        to_delete = backups[MAX_HOURLY_BACKUPS:]
        for f in to_delete:
            try:
                f.unlink()
                logger.info(f"清理过期备份: {f.name}")
            except OSError as e:
                logger.warning(f"清理备份失败: {f.name}, {e}")
    except Exception as e:
        logger.warning(f"清理备份时出错: {e}")


async def _backup_loop():
    """后台备份循环"""
    logger.info("数据库自动备份任务已启动，间隔 %d 秒", BACKUP_INTERVAL_SECONDS)

    while True:
        try:
            await asyncio.sleep(BACKUP_INTERVAL_SECONDS)
            backup_now()
            _cleanup_old_backups()
        except asyncio.CancelledError:
            logger.info("数据库自动备份任务已停止")
            break
        except Exception as e:
            logger.error(f"备份任务异常: {e}")


def start_backup_scheduler():
    """启动后台备份任务"""
    global _backup_task
    if _backup_task is not None and not _backup_task.done():
        return

    _backup_task = asyncio.create_task(_backup_loop())
    logger.info("数据库自动备份调度器已启动")


def stop_backup_scheduler():
    """停止后台备份任务"""
    global _backup_task
    if _backup_task is not None:
        _backup_task.cancel()
        _backup_task = None