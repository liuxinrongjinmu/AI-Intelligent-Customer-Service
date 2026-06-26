"""
单元测试公共 fixtures

提供：
- 内存 SQLite 数据库（隔离测试，不污染生产数据）
- FastAPI TestClient（已覆盖认证和数据库依赖）
- Mock 外部服务（LLM、ChromaDB、Nacos）
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.database import Base, get_db
from backend.utils.auth import verify_chat_api_key, verify_sync_api_key, verify_admin_key

# 确保所有模型在 create_all 之前被导入
from backend.models.tenant import Tenant  # noqa: F401
from backend.models.conversation import Conversation, Message, ToolCallLog  # noqa: F401
from backend.models.knowledge import FAQ, Document  # noqa: F401
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

    :yield: TestClient 实例
    """
    app = _create_test_app(db_session)
    yield TestClient(app)


@pytest.fixture(scope="function")
def client_with_seed(db_with_seed):
    """
    FastAPI TestClient（预填充租户和会话数据）

    :yield: TestClient 实例
    """
    app = _create_test_app(db_with_seed)
    yield TestClient(app)
