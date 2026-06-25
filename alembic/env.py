"""
Alembic 迁移环境配置

从 backend.config 读取 DATABASE_URL，自动发现所有 SQLAlchemy 模型。
生产环境使用 alembic upgrade head 管理数据库 schema 变更。
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# 将项目根目录加入 sys.path，确保能导入 backend 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从环境变量或 backend.config 读取 DATABASE_URL
# 优先使用环境变量，确保 Docker 部署时正确读取
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)
else:
    try:
        from backend.config import DATABASE_URL
        config.set_main_option("sqlalchemy.url", DATABASE_URL)
    except ImportError:
        pass  # 留给 alembic.ini 中的默认值

# 导入所有模型，使 autogenerate 能发现表结构变更
from backend.database import Base  # noqa: E402
from backend.models.tenant import Tenant  # noqa: F401, E402
from backend.models.conversation import Conversation, Message, ToolCallLog  # noqa: F401, E402
from backend.models.knowledge import FAQ, Document  # noqa: F401, E402
from backend.models.handoff import HandoffTicket  # noqa: F401, E402
from backend.knowledge.sync_log import SyncLog  # noqa: F401, E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    离线模式运行迁移：仅生成 SQL 语句，不连接数据库

    适用于生成迁移脚本供 DBA 审核
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线模式运行迁移：连接数据库并执行迁移

    使用 NullPool 避免连接池与迁移事务冲突
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
