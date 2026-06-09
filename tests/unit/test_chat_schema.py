"""
ChatRequest Schema 单元测试

测试 session_id、user_id、message 字段的校验规则及默认值。
"""
import pytest
from pydantic import ValidationError

from backend.schemas.chat import ChatRequest


class TestChatRequestSchema:
    """ChatRequest Schema 校验测试"""

    # ==================== session_id 校验 ====================

    def test_session_id_valid_alphanumeric(self):
        """有效 session_id（字母数字下划线连字符点号）→ 通过"""
        req = ChatRequest(
            message="你好",
            session_id="abc123_ABC-xyz.test",
            user_id="user001",
        )
        assert req.session_id == "abc123_ABC-xyz.test"

    def test_session_id_empty(self):
        """空 session_id → 校验失败"""
        with pytest.raises(ValidationError):
            ChatRequest(message="你好", session_id="", user_id="user001")

    def test_session_id_whitespace_only(self):
        """只有空格 → 校验失败"""
        with pytest.raises(ValidationError):
            ChatRequest(message="你好", session_id="   ", user_id="user001")

    def test_session_id_special_chars(self):
        """包含特殊字符如 @#$ → 校验失败"""
        with pytest.raises(ValidationError):
            ChatRequest(message="你好", session_id="abc@#$def", user_id="user001")

    def test_session_id_length_exceeds_128(self):
        """长度超过 128 → 校验失败"""
        with pytest.raises(ValidationError):
            ChatRequest(
                message="你好",
                session_id="a" * 129,
                user_id="user001",
            )

    def test_session_id_length_exactly_128(self):
        """长度刚好 128 → 通过"""
        sid = "A" * 128
        req = ChatRequest(message="你好", session_id=sid, user_id="user001")
        assert req.session_id == sid
        assert len(req.session_id) == 128

    # ==================== user_id 校验 ====================

    def test_user_id_valid(self):
        """有效 user_id → 通过"""
        req = ChatRequest(
            message="你好",
            session_id="sess001",
            user_id="user_123-abc.xyz",
        )
        assert req.user_id == "user_123-abc.xyz"

    def test_user_id_empty(self):
        """空 user_id → 校验失败"""
        with pytest.raises(ValidationError):
            ChatRequest(message="你好", session_id="sess001", user_id="")

    def test_user_id_special_chars(self):
        """包含特殊字符 → 校验失败"""
        with pytest.raises(ValidationError):
            ChatRequest(message="你好", session_id="sess001", user_id="user@#$name")

    # ==================== message 校验 ====================

    def test_message_valid(self):
        """有效 message → 通过"""
        req = ChatRequest(
            message="你好，我想查询订单",
            session_id="sess001",
            user_id="user001",
        )
        assert req.message == "你好，我想查询订单"

    def test_message_empty(self):
        """空 message → 校验失败"""
        with pytest.raises(ValidationError):
            ChatRequest(message="", session_id="sess001", user_id="user001")

    def test_message_length_exceeds_4000(self):
        """长度超过 4000 → 校验失败"""
        with pytest.raises(ValidationError):
            ChatRequest(
                message="哈" * 4001,
                session_id="sess001",
                user_id="user001",
            )

    def test_message_length_exactly_4000(self):
        """长度刚好 4000 → 通过"""
        msg = "哈" * 4000
        req = ChatRequest(message=msg, session_id="sess001", user_id="user001")
        assert req.message == msg
        assert len(req.message) == 4000

    # ==================== 默认值 ====================

    def test_user_name_default(self):
        """user_name 默认值为 '匿名用户'"""
        req = ChatRequest(
            message="你好",
            session_id="sess001",
            user_id="user001",
        )
        assert req.user_name == "匿名用户"

    def test_channel_default(self):
        """channel 默认值为 'unknown'"""
        req = ChatRequest(
            message="你好",
            session_id="sess001",
            user_id="user001",
        )
        assert req.channel == "unknown"