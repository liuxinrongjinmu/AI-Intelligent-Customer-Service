"""
单元测试公共 fixtures 和工具函数

提供：
- 内存 SQLite 数据库（隔离测试，不污染生产数据）
- FastAPI TestClient（已覆盖认证和数据库依赖）
- make_test_state() 共享测试状态构造器
- Mock 外部服务（LLM、ChromaDB、Nacos）
"""
import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.database import Base, get_db
from backend.utils.auth import verify_chat_api_key, verify_sync_api_key, verify_admin_key


# ─── 共享测试工具 ───────────────────────────────────────────────────────────

def make_test_state(**overrides) -> dict:
    """
    构造测试用 AgentState 字典（共享工具，避免各测试文件重复定义）

    用法：
        state = make_test_state(intent="order_query")
        state = make_test_state(messages=[...], tenant_id="custom")

    :param overrides: 覆盖默认字段
    :return: AgentState 兼容字典
    """
    base = {
        "messages": [MagicMock(content="你好")],
        "tenant_id": "test_tenant",
        "tenant_name": "测试商家",
        "user_id": "user_001",
        "user_name": "测试用户",
        "channel": "app",
        "thread_id": "thread_001",
        "intent": "",
        "intent_sub_type": "",
        "intent_entities": {},
        "ai_failed_count": 0,
    }
    base.update(overrides)
    return base

# 确保所有模型在 create_all 之前被导入
from backend.models.tenant import Tenant  # noqa: F401
from backend.models.conversation import Conversation, Message, ToolCallLog  # noqa: F401
from backend.models.knowledge import FAQ, Document  # noqa: F401
from backend.models.feedback import Feedback  # noqa: F401
from backend.models.handoff import HandoffTicket  # noqa: F401
from backend.knowledge.sync_log import SyncLog  # noqa: F401


# ─── 内存数据库 fixture ──────────────────────────────────────────────────

@pytest.fixture(scope="function")
def db_session():
    """
    每个测试函数独立的内存 SQLite 数据库

    使用 StaticPool 确保跨线程共享同一连接（TestClient 在独立线程运行）

    :yield: SQLAlchemy Session 实例
    """
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(scope="function")
def db_with_seed(db_session):
    """
    预置租户和会话数据的测试数据库

    :yield: 预填充数据的 Session
    """
    from backend.models.tenant import Tenant, generate_api_key
    from backend.models.conversation import Conversation, Message

    # 创建测试租户
    raw_key, hashed, prefix = generate_api_key()
    tenant = Tenant(
        tenant_id="test_tenant",
        name="测试商家",
        api_key_hash=hashed,
        api_key_prefix=prefix,
    )
    db_session.add(tenant)

    # 创建测试会话
    conv = Conversation(
        thread_id="test_session_001",
        tenant_id="test_tenant",
        channel="h5",
        user_id="test_user_001",
        user_name="测试用户",
    )
    db_session.add(conv)
    db_session.commit()

    # 创建测试消息
    msg1 = Message(conversation_id=conv.id, role="user", content="你好")
    msg2 = Message(conversation_id=conv.id, role="assistant", content="您好，有什么可以帮您？")
    db_session.add_all([msg1, msg2])
    db_session.commit()

    yield db_session


# ─── 检查 psycopg（libpq）可用性 ────────────────────────────────────────────

def _has_psycopg() -> bool:
    """检查 libpq 系统库是否可用（macOS 默认未安装）"""
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: F401
        return True
    except ImportError:
        return False


_HAS_LIBPQ = _has_psycopg()


# ─── FastAPI TestApp fixture ─────────────────────────────────────────────

def _create_test_app(db: Session) -> FastAPI:
    """
    创建测试用 FastAPI 应用（不含 lifespan，避免初始化 LLM/ChromaDB）

    :param db: 测试数据库会话
    :return: FastAPI 应用实例
    """
    app = FastAPI()

    # 覆盖数据库依赖
    def override_get_db():
        try:
            yield db
        finally:
            pass

    # 覆盖认证依赖（测试中跳过认证）
    async def override_chat_auth():
        return "test_chat_auth"

    async def override_sync_auth():
        return "test_sync_auth"

    async def override_admin_auth():
        return "test_admin_auth"

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_chat_api_key] = override_chat_auth
    app.dependency_overrides[verify_sync_api_key] = override_sync_auth
    app.dependency_overrides[verify_admin_key] = override_admin_auth

    # 注册路由
    from backend.api.tenant import router as tenant_router
    from backend.api.knowledge import router as knowledge_router
    from backend.api.chat import router as chat_router
    from backend.api.stats import router as stats_router

    app.include_router(tenant_router)
    app.include_router(knowledge_router)
    app.include_router(chat_router)
    app.include_router(stats_router)

    return app


@pytest.fixture(scope="function")
def client(db_session):
    """
    FastAPI TestClient（空数据库）
    当系统缺少 libpq 时自动跳过
    """
    if not _HAS_LIBPQ:
        pytest.skip("libpq 系统库不可用（安装: brew install postgresql）")
    app = _create_test_app(db_session)
    yield TestClient(app)


@pytest.fixture(scope="function")
def client_with_seed(db_with_seed):
    """
    FastAPI TestClient（预填充租户和会话数据）
    当系统缺少 libpq 时自动跳过
    """
    if not _HAS_LIBPQ:
        pytest.skip("libpq 系统库不可用（安装: brew install postgresql）")
    app = _create_test_app(db_with_seed)
    yield TestClient(app)
