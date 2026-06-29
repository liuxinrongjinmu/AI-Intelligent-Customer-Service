"""
数据库自动备份模块（PostgreSQL）

在 FastAPI 启动时注册后台任务，定时备份数据库。
- 备份频率：每小时
- 保留数量：最近 24 个备份 + 每日快照（7天）
- 备份位置：data/backups/

使用 pg_dump 导出 SQL 文件
"""
import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
from typing import Optional
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)

# 备份配置
BACKUP_DIR = Path("data/backups")
BACKUP_INTERVAL_SECONDS = 3600       # 备份间隔：1小时
MAX_HOURLY_BACKUPS = 24              # 保留最近 24 个每小时备份
MAX_DAILY_BACKUPS = 7                # 保留最近 7 个每日快照

_backup_task: Optional[asyncio.Task] = None


def _ensure_backup_dir():
    """确保备份目录存在"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _safe_mtime(path: Path) -> float:
    """
    安全获取文件修改时间，文件不存在或被删时返回 0.0

    :param path: 文件路径
    :return: 修改时间戳，失败返回 0.0
    """
    try:
        return path.stat().st_mtime
    except (FileNotFoundError, OSError):
        return 0.0


def _parse_pg_conn(url: str) -> dict:
    """
    解析 PostgreSQL 连接串为 pg_dump 所需参数

    :param url: postgresql://user:password@host:port/dbname
    :return: {user, password, host, port, dbname}
    """
    parsed = urlparse(url)
    return {
        "user": parsed.username or os.getenv("PGUSER", "postgres"),
        "password": parsed.password or os.getenv("PGPASSWORD", ""),
        "host": parsed.hostname or os.getenv("PGHOST", "localhost"),
        "port": str(parsed.port or 5432),
        "dbname": parsed.path.lstrip("/") or os.getenv("PGDATABASE", "postgres"),
        "query": parse_qs(parsed.query),
    }


def _backup_postgres(backup_path: Path) -> bool:
    """
    使用 pg_dump 备份 PostgreSQL 数据库

    :param backup_path: 备份文件路径
    :return: 是否成功
    """
    try:
        conn = _parse_pg_conn(DATABASE_URL)
        env = os.environ.copy()
        env["PGPASSWORD"] = conn["password"]
        # 保留 URL query 参数（如 sslmode），通过 PGOPTIONS 传递给 pg_dump
        pg_options = []
        query = conn.get("query", {})
        if "sslmode" in query and query["sslmode"]:
            pg_options.append(f"-c sslmode={query['sslmode'][0]}")
        if pg_options:
            env["PGOPTIONS"] = " ".join(pg_options)

        cmd = [
            "pg_dump",
            "-h", conn["host"],
            "-p", conn["port"],
            "-U", conn["user"],
            "-F", "c",            # 自定义压缩格式
            "-f", str(backup_path),
            conn["dbname"],
        ]

        result = subprocess.run(
            cmd, env=env,
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            logger.error(f"pg_dump 失败: {result.stderr}")
            return False

        logger.info(f"PostgreSQL 备份成功: {backup_path} ({backup_path.stat().st_size} bytes)")
        return True
    except FileNotFoundError:
        logger.error("pg_dump 命令未找到，请确保 PostgreSQL 客户端工具已安装")
        return False
    except subprocess.TimeoutExpired:
        logger.error("pg_dump 超时（>300s），备份失败")
        return False
    except Exception as e:
        logger.error(f"PostgreSQL 备份失败: {e}")
        return False


def backup_now() -> Optional[str]:
    """
    立即执行一次数据库备份

    :return: 备份文件路径，失败返回 None
    """
    _ensure_backup_dir()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"app_{timestamp}.dump"
    # 同秒调用时添加序号后缀，避免覆盖已有备份
    seq = 1
    while backup_path.exists():
        backup_path = BACKUP_DIR / f"app_{timestamp}_{seq}.dump"
        seq += 1

    success = _backup_postgres(backup_path)

    if not success:
        # 清理失败的备份文件
        if backup_path.exists():
            try:
                backup_path.unlink()
            except OSError:
                pass
        return None

    # 备份 ChromaDB 向量库（目录级拷贝）
    chroma_src = Path(os.getenv("CHROMA_PATH", "data/chroma_db"))
    if chroma_src.exists() and chroma_src.is_dir():
        try:
            chroma_backup = BACKUP_DIR / f"chroma_{timestamp}"
            seq_c = 1
            while chroma_backup.exists():
                chroma_backup = BACKUP_DIR / f"chroma_{timestamp}_{seq_c}"
                seq_c += 1
            shutil.copytree(chroma_src, chroma_backup)
            logger.info(f"ChromaDB 备份成功: {chroma_backup}")
        except Exception as e:
            logger.warning(f"ChromaDB 备份失败(不影响数据库备份): {e}")

    return str(backup_path)


def _cleanup_old_backups():
    """
    清理过期备份

    策略：
    - 每小时备份：保留最近 MAX_HOURLY_BACKUPS 个
    - 每日快照：每天保留第一个备份作为快照，保留最近 MAX_DAILY_BACKUPS 天
    """
    _ensure_backup_dir()

    try:
        # 匹配 app_*.dump、chroma_* 目录，以及旧的 app_*.db / checkpoints_*.db 备份
        date_pattern = re.compile(r"(?:app|chroma|checkpoints)_(\d{8})_\d{6}")
        backups = sorted(
            list(BACKUP_DIR.glob("app_*.dump"))
            + list(BACKUP_DIR.glob("app_*.db"))
            + list(BACKUP_DIR.glob("checkpoints_*.db"))
            + [p for p in BACKUP_DIR.glob("chroma_*") if p.is_dir()],
            key=lambda p: _safe_mtime(p),
            reverse=True,
        )

        if len(backups) <= MAX_HOURLY_BACKUPS:
            return

        # 保留最新的 MAX_HOURLY_BACKUPS 个每小时备份
        hourly_keep = set(backups[:MAX_HOURLY_BACKUPS])

        # 从剩余备份中，每天保留第一个作为每日快照
        daily_keep = set()
        seen_dates = set()
        for f in backups[MAX_HOURLY_BACKUPS:]:
            # 用正则校验文件名，跳过异常文件名（复用上方 date_pattern）
            match = date_pattern.match(f.stem)
            if not match:
                continue
            date_str = match.group(1)  # prefix_YYYYMMDD_HHMMSS -> YYYYMMDD
            if date_str not in seen_dates:
                seen_dates.add(date_str)
                daily_keep.add(f)

        # 限制每日快照数量
        if len(daily_keep) > MAX_DAILY_BACKUPS:
            daily_keep = set(sorted(daily_keep, key=lambda p: _safe_mtime(p), reverse=True)[:MAX_DAILY_BACKUPS])

        # 删除既不在每小时保留也不在每日快照中的备份
        to_delete = set(backups) - hourly_keep - daily_keep
        for f in to_delete:
            try:
                if f.is_dir():
                    shutil.rmtree(f)
                else:
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
            # 用 asyncio.to_thread 包装同步阻塞调用，避免卡死事件循环
            await asyncio.to_thread(backup_now)
            await asyncio.to_thread(_cleanup_old_backups)
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
