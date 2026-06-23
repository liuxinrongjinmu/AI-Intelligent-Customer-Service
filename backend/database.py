import os
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool
from backend.config import SQLITE_PATH, DATABASE_URL, ENABLE_FOREIGN_KEYS

logger = logging.getLogger(__name__)

# ==================== 数据库引擎初始化（双模式：PostgreSQL / SQLite） ====================
# 配置 DATABASE_URL 时使用 PostgreSQL（生产环境推荐，支持高并发写入）
# 否则回退到 SQLite（开发/测试环境，WAL 模式）
USE_POSTGRES: bool = bool(DATABASE_URL)

if USE_POSTGRES:
    # PostgreSQL 模式
    # pool_size=10: 保持 10 个连接常驻
    # max_overflow=20: 高峰时最多额外创建 20 个连接
    # pool_recycle=1800: 30 分钟回收连接，避免长连接被服务端断开
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
        pool_timeout=30,
    )
    logger.info("数据库引擎：PostgreSQL")
else:
    # SQLite 模式（开发/测试）
    # SQLite 写锁为库级锁，多连接并发写入易冲突，使用 StaticPool 单连接复用避免写锁竞争
    os.makedirs(os.path.dirname(SQLITE_PATH) or ".", exist_ok=True)
    engine = create_engine(
        f"sqlite:///{SQLITE_PATH}",
        connect_args={"check_same_thread": False},
        echo=False,
        pool_pre_ping=True,
        poolclass=StaticPool,
        pool_recycle=300,
    )
    logger.info("数据库引擎：SQLite（WAL 模式）")


@event.listens_for(engine, "connect")
def _set_connection_pragma(dbapi_conn, connection_record):
    """
    每个新连接设置数据库特定 PRAGMA / 参数

    - SQLite: WAL 模式 + 外键约束启用
    - PostgreSQL: 外键约束默认启用，无需额外设置
    """
    cursor = None
    try:
        cursor = dbapi_conn.cursor()
        if USE_POSTGRES:
            # PostgreSQL 外键约束默认启用，无需额外设置
            pass
        else:
            # SQLite 优化配置
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-2000")
            # 启用 SQLite 外键约束（默认关闭）
            if ENABLE_FOREIGN_KEYS:
                cursor.execute("PRAGMA foreign_keys=ON")
    except Exception as e:
        logger.warning(f"设置连接 PRAGMA 失败: {e}")
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """
    获取数据库会话（FastAPI 依赖注入）

    :yield: SQLAlchemy Session 实例
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    初始化数据库：创建所有表 + 补全索引

    注意：生产环境推荐使用 Alembic 迁移工具管理 schema 变更，
    此处 create_all 仅用于首次启动或开发环境。
    """
    # 确保所有模型已导入，Base.metadata 才能识别
    from backend.models import conversation  # noqa: F401
    from backend.models import feedback  # noqa: F401
    from backend.models import handoff  # noqa: F401
    from backend.models import knowledge  # noqa: F401
    from backend.models import tenant  # noqa: F401
    from backend.knowledge.sync_log import SyncLog  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _ensure_indexes()


def _ensure_indexes():
    """
    确保已有表补上缺失的索引（兼容旧数据库）

    使用 IF NOT EXISTS 语法，PostgreSQL 和 SQLite 均支持。
    """
    from sqlalchemy import inspect, text

    _required_indexes = {
        "conversations": ["created_at", "ended_at", "user_id"],
        "messages": ["created_at"],
        "feedbacks": ["created_at"],
        "handoff_tickets": ["created_at"],
    }

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _required_indexes.items():
            if not inspector.has_table(table):
                continue
            existing = inspector.get_indexes(table)
            indexed_cols = set()
            for idx in existing:
                for col in (idx["column_names"] or []):
                    indexed_cols.add(col)
            for col in columns:
                if col not in indexed_cols:
                    idx_name = f"ix_{table}_{col}"
                    conn.execute(
                        text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({col})")
                    )
