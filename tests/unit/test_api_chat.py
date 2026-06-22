"""
聊天 API 单元测试
"""
import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from backend.models.tenant import Tenant, generate_api_key
from backend.models.conversation import Conversation, Message


class TestChatHistory:
    """GET /api/v1/chat/{tenant_id}/history/{session_id}"""

    def test_get_history_success(self, client_with_seed):
        """获取历史消息"""
        resp = client_with_seed.get("/api/v1/chat/test_tenant/history/test_session_001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "test_session_001"
        assert len(data["messages"]) == 2
        # 验证两条消息存在（顺序可能因 SQLite 内存模式 ID 分配而不同）
        roles = {m["role"] for m in data["messages"]}
        contents = {m["content"] for m in data["messages"]}
        assert "user" in roles
        assert "assistant" in roles
        assert "你好" in contents
        assert "您好，有什么可以帮您？" in contents

    def test_get_history_empty_session(self, client_with_seed):
        """不存在的会话返回空列表"""
        resp = client_with_seed.get("/api/v1/chat/test_tenant/history/nonexistent_session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages"] == []

    def test_get_history_tenant_not_found(self, client):
        """租户不存在"""
        resp = client.get("/api/v1/chat/nonexistent/history/any_session")
        assert resp.status_code == 404

    def test_get_history_user_mismatch(self, client_with_seed):
        """user_id 不匹配返回 403"""
        resp = client_with_seed.get(
            "/api/v1/chat/test_tenant/history/test_session_001",
            params={"user_id": "wrong_user"}
        )
        assert resp.status_code == 403


class TestChatStream:
    """POST /api/v1/chat/{tenant_id}/stream"""

    def test_chat_tenant_not_found(self, client):
        """租户不存在"""
        resp = client.post("/api/v1/chat/nonexistent/stream", json={
            "session_id": "sess_001",
            "user_id": "user_001",
            "message": "你好",
        })
        assert resp.status_code == 404

    def test_chat_empty_message(self, client_with_seed):
        """空消息"""
        resp = client_with_seed.post("/api/v1/chat/test_tenant/stream", json={
            "session_id": "sess_001",
            "user_id": "user_001",
            "message": "",
        })
        assert resp.status_code == 422

    def test_chat_whitespace_message(self, client_with_seed):
        """纯空格消息"""
        resp = client_with_seed.post("/api/v1/chat/test_tenant/stream", json={
            "session_id": "sess_001",
            "user_id": "user_001",
            "message": "   ",
        })
        assert resp.status_code == 422

    def test_chat_missing_session_id(self, client_with_seed):
        """缺少 session_id"""
        resp = client_with_seed.post("/api/v1/chat/test_tenant/stream", json={
            "user_id": "user_001",
            "message": "你好",
        })
        assert resp.status_code == 422

    def test_chat_missing_user_id(self, client_with_seed):
        """缺少 user_id"""
        resp = client_with_seed.post("/api/v1/chat/test_tenant/stream", json={
            "session_id": "sess_001",
            "message": "你好",
        })
        assert resp.status_code == 422

    def test_chat_message_too_long(self, client_with_seed):
        """消息超长"""
        resp = client_with_seed.post("/api/v1/chat/test_tenant/stream", json={
            "session_id": "sess_001",
            "user_id": "user_001",
            "message": "x" * 4001,
        })
        assert resp.status_code == 422

    @patch("backend.api.chat.get_agent")
    def test_chat_creates_new_session(self, mock_get_agent, client_with_seed, db_with_seed):
        """新 session_id 自动创建会话"""
        # Mock agent 返回空流
        mock_agent = AsyncMock()

        async def mock_astream(*args, **kwargs):
            yield {}
        mock_agent.astream = mock_astream
        mock_get_agent.return_value = mock_agent

        resp = client_with_seed.post("/api/v1/chat/test_tenant/stream", json={
            "session_id": "new_session_002",
            "user_id": "user_002",
            "message": "你好",
        })

        # 验证会话已创建
        db_with_seed.expire_all()
        conv = db_with_seed.query(Conversation).filter_by(thread_id="new_session_002").first()
        assert conv is not None
        assert conv.user_id == "user_002"

    @patch("backend.api.chat.get_agent")
    def test_chat_existing_session_reuses(self, mock_get_agent, client_with_seed, db_with_seed):
        """已存在的 session_id 复用会话"""
        mock_agent = AsyncMock()

        async def mock_astream(*args, **kwargs):
            yield {}
        mock_agent.astream = mock_astream
        mock_get_agent.return_value = mock_agent

        resp = client_with_seed.post("/api/v1/chat/test_tenant/stream", json={
            "session_id": "test_session_001",
            "user_id": "test_user_001",
            "message": "再次你好",
        })

        # 验证没有创建新会话
        db_with_seed.expire_all()
        convs = db_with_seed.query(Conversation).filter_by(thread_id="test_session_001").all()
        assert len(convs) == 1

    @patch("backend.api.chat.get_agent")
    def test_chat_saves_user_message(self, mock_get_agent, client_with_seed, db_with_seed):
        """用户消息已保存到数据库"""
        mock_agent = AsyncMock()

        async def mock_astream(*args, **kwargs):
            yield {}
        mock_agent.astream = mock_astream
        mock_get_agent.return_value = mock_agent

        client_with_seed.post("/api/v1/chat/test_tenant/stream", json={
            "session_id": "test_session_001",
            "user_id": "test_user_001",
            "message": "测试消息保存",
        })

        # 刷新 session 缓存，确保看到其他线程的提交
        db_with_seed.expire_all()
        msgs = db_with_seed.query(Message).filter_by(
            role="user", content="测试消息保存"
        ).all()
        assert len(msgs) == 1

    @patch("backend.api.chat.get_agent")
    def test_chat_sse_stream_format(self, mock_get_agent, client_with_seed):
        """SSE 流式响应格式正确"""
        mock_agent = AsyncMock()

        async def mock_astream(*args, **kwargs):
            yield {"generate_answer": {"final_answer": "您好，有什么可以帮您？", "intent": "greeting"}}
        mock_agent.astream = mock_astream
        mock_get_agent.return_value = mock_agent

        resp = client_with_seed.post("/api/v1/chat/test_tenant/stream", json={
            "session_id": "sse_test_001",
            "user_id": "user_001",
            "message": "你好",
        })

        assert resp.status_code == 200
        # 解析 SSE 事件
        events = []
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        # 应该有 status(text)、status(done) 事件
        event_types = [e.get("type") for e in events]
        assert "status" in event_types
        assert "done" in event_types

    @patch("backend.api.chat.get_agent")
    def test_chat_session_tenant_mismatch(self, mock_get_agent, client_with_seed, db_with_seed):
        """跨租户访问会话返回 403"""
        # 先创建另一个租户
        raw_key, hashed, prefix = generate_api_key()
        tenant2 = Tenant(tenant_id="other_tenant", name="其他商家",
                         api_key_hash=hashed, api_key_prefix=prefix)
        db_with_seed.add(tenant2)
        db_with_seed.commit()

        # 用 other_tenant 访问 test_tenant 的会话
        resp = client_with_seed.post("/api/v1/chat/other_tenant/stream", json={
            "session_id": "test_session_001",  # 属于 test_tenant
            "user_id": "test_user_001",
            "message": "你好",
        })
        assert resp.status_code == 403
