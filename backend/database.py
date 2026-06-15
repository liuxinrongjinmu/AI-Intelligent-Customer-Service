import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from backend.config import SQLITE_PATH

os.makedirs(os.path.dirname(SQLITE_PATH) or ".", exist_ok=True)

# 使用 QueuePool 替代 SQLite 默认的 StaticPool，支持多连接复用
# pool_size=5: 保持 5 个连接常驻
# max_overflow=10: 高峰时最多额外创建 10 个连接
# pool_recycle=300: 5 分钟回收连接，避免 SQLite 长连接问题
engine = create_engine(
    f"sqlite:///{SQLITE_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=300,
    pool_timeout=30,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    """每个新连接设置 SQLite PRAGMA"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-2000")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    # 确保所有模型已导入，Base.metadata 才能识别
    from backend.knowledge.sync_log import SyncLog  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _ensure_indexes()


def _ensure_indexes():
    """确保已有表补上缺失的索引（兼容旧数据库）"""
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
                for col in idx["column_names"]:
                    indexed_cols.add(col)
            for col in columns:
                if col not in indexed_cols:
                    idx_name = f"ix_{table}_{col}"
                    conn.execute(
                        text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({col})")
                    )
