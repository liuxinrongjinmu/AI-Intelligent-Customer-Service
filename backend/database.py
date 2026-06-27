import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

logger = logging.getLogger(__name__)

# ==================== PostgreSQL 数据库引擎 ====================
# 生产环境统一使用 PostgreSQL，支持高并发写入和连接池
# 使用延迟初始化，避免导入时立即连接（测试环境可能不需要真实数据库）

_engine = None
_SessionLocal = None


def _get_database_url() -> str:
    """
    获取数据库连接串

    :return: PostgreSQL 连接串
    """
    from backend.config import DATABASE_URL
    return DATABASE_URL


def _init_engine():
    """
    延迟初始化数据库引擎（首次访问时创建）
    """
    global _engine, _SessionLocal
    if _engine is not None:
        return

    DATABASE_URL = _get_database_url()
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL 未配置，PostgreSQL 连接串为必填项")

    _engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
        pool_timeout=30,
    )
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    logger.info("数据库引擎：PostgreSQL")


class Base(DeclarativeBase):
    pass


def get_engine():
    """
    获取数据库引擎（显式调用，触发延迟初始化）

    :return: SQLAlchemy Engine 实例
    """
    _init_engine()
    return _engine


def get_session_local():
    """
    获取 SessionLocal 工厂（显式调用，触发延迟初始化）

    :return: sessionmaker 实例
    """
    _init_engine()
    return _SessionLocal


def get_db():
    """
    获取数据库会话（FastAPI 依赖注入）

    :yield: SQLAlchemy Session 实例
    """
    session_factory = get_session_local()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


# 保持 SessionLocal / engine 向后兼容（延迟属性）
def __getattr__(name):
    if name == "SessionLocal":
        return get_session_local()
    if name == "engine":
        return get_engine()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def init_db():
    """
    初始化数据库：创建所有表 + 补全索引

    注意：生产环境推荐使用 Alembic 迁移工具管理 schema 变更，
    此处 create_all 仅用于首次启动或开发环境。
    """
    from backend.models import conversation  # noqa: F401
    from backend.models import feedback  # noqa: F401
    from backend.models import handoff  # noqa: F401
    from backend.models import knowledge  # noqa: F401
    from backend.models import tenant  # noqa: F401
    from backend.knowledge.sync_log import SyncLog  # noqa: F401

    real_engine = get_engine()
    Base.metadata.create_all(bind=real_engine)
    _ensure_indexes(real_engine)


def _ensure_indexes(real_engine):
    """
    确保已有表补上缺失的索引（兼容旧数据库）

    使用 IF NOT EXISTS 语法，PostgreSQL 支持。
    """
    from sqlalchemy import inspect, text

    _required_indexes = {
        "conversations": ["created_at", "ended_at", "user_id"],
        "messages": ["created_at"],
        "handoff_tickets": ["created_at"],
    }

    inspector = inspect(real_engine)
    with real_engine.begin() as conn:
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
                        text(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{table}" ("{col}")')
                    )
