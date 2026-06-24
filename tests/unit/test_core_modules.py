"""
核心模块单元测试

覆盖：
  - auth.py: Admin API Key 认证
  - token_budget.py: Token 预算管理、消息裁剪、知识裁剪
  - response_cache.py: LRU 缓存、TTL 过期
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


# ==================== auth.py 测试 ====================

class TestAuth:
    """verify_admin_key 认证逻辑测试"""

    @pytest.mark.asyncio
    async def test_admin_key_missing(self):
        """缺少 X-Admin-Key 头应返回 403"""
        from backend.utils.auth import verify_admin_key
        from unittest.mock import AsyncMock
        from fastapi import HTTPException

        request = AsyncMock()
        request.headers = {}

        with pytest.raises(HTTPException) as exc:
            await verify_admin_key(request)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_key_wrong(self):
        """错误的 X-Admin-Key 应返回 403"""
        from backend.utils.auth import verify_admin_key
        from unittest.mock import AsyncMock
        from fastapi import HTTPException

        request = AsyncMock()
        request.headers = {"X-Admin-Key": "wrong-key"}

        with pytest.raises(HTTPException) as exc:
            await verify_admin_key(request)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_key_correct(self, monkeypatch):
        """正确的 X-Admin-Key 应通过认证"""
        from unittest.mock import AsyncMock

        import backend.config
        import backend.utils.auth

        # 使用 monkeypatch 设置 ADMIN_API_KEY，测试结束自动恢复
        monkeypatch.setattr(backend.config, "ADMIN_API_KEY", "test-admin-key-12345")
        monkeypatch.setattr(backend.utils.auth, "ADMIN_API_KEY", "test-admin-key-12345")

        request = AsyncMock()
        request.headers = {"X-Admin-Key": "test-admin-key-12345"}
        result = await backend.utils.auth.verify_admin_key(request)
        assert result == "admin_authed"


# ==================== token_budget.py 测试 ====================

class TestEstimateTokens:
    """token 预估测试"""

    def test_empty_text(self):
        from backend.utils.token_budget import estimate_tokens
        assert estimate_tokens("") == 0
        assert estimate_tokens(None) == 0

    def test_english_text(self):
        from backend.utils.token_budget import estimate_tokens
        tokens = estimate_tokens("Hello World")
        assert tokens > 0
        # 英文约 0.3 token/char，11 chars ≈ 3 tokens
        assert 2 <= tokens <= 10

    def test_chinese_text(self):
        from backend.utils.token_budget import estimate_tokens
        tokens = estimate_tokens("你好世界")
        # 4 个中文字符 × 1.8 = 7.2 ≈ 7
        assert 5 <= tokens <= 12

    def test_mixed_text(self):
        from backend.utils.token_budget import estimate_tokens
        tokens = estimate_tokens("你好world")
        # 2 中文 × 1.8 + 5 英文 × 0.3 = 3.6 + 1.5 = 5.1 ≈ 5
        assert 3 <= tokens <= 10


class TestTrimMessages:
    """消息裁剪测试"""

    def test_empty_messages(self):
        from backend.utils.token_budget import trim_messages
        result = trim_messages([], 1000)
        assert result == []

    def test_single_message_kept(self):
        from backend.utils.token_budget import trim_messages
        from unittest.mock import MagicMock

        msg = MagicMock()
        msg.content = "Hello"
        msg.type = "human"

        result = trim_messages([msg], 1000)
        assert len(result) == 1
        assert result[0] is msg

    def test_last_message_always_kept(self):
        from backend.utils.token_budget import trim_messages
        from unittest.mock import MagicMock

        msg1 = MagicMock()
        msg1.content = "A" * 10000  # 超大消息
        msg1.type = "human"
        msg2 = MagicMock()
        msg2.content = "当前消息"
        msg2.type = "human"

        result = trim_messages([msg1, msg2], 100)
        # 最后一条必须保留
        assert len(result) >= 1
        assert result[-1] is msg2

    def test_system_prompt_reserved(self):
        from backend.utils.token_budget import trim_messages
        from unittest.mock import MagicMock

        msg1 = MagicMock()
        msg1.content = "历史消息"
        msg1.type = "human"
        msg2 = MagicMock()
        msg2.content = "当前消息"
        msg2.type = "human"

        # system prompt 占用大量 token，应优先裁剪历史
        sys_prompt = "A" * 5000
        result = trim_messages([msg1, msg2], 100, system_prompt=sys_prompt)
        # 当前消息应保留
        assert result[-1] is msg2


class TestTrimKnowledgeContext:
    """知识文档裁剪测试"""

    def test_empty_docs(self):
        from backend.utils.token_budget import trim_knowledge_context
        result = trim_knowledge_context([], 1000)
        assert result == []

    def test_score_sorting(self):
        from backend.utils.token_budget import trim_knowledge_context
        docs = [
            {"content": "文档A", "score": 0.5},
            {"content": "文档B", "score": 0.9},
            {"content": "文档C", "score": 0.3},
        ]
        result = trim_knowledge_context(docs, 10000)
        # 高分文档应排在前面
        assert result[0]["score"] == 0.9
        assert result[1]["score"] == 0.5
        assert result[2]["score"] == 0.3

    def test_token_budget_respected(self):
        from backend.utils.token_budget import trim_knowledge_context
        docs = [
            {"content": "A" * 5000, "score": 0.9},
            {"content": "B" * 5000, "score": 0.8},
        ]
        result = trim_knowledge_context(docs, 100)
        # 预算很小，应只保留少量文档
        assert len(result) <= 2


# ==================== response_cache.py 测试 ====================

class TestLRUCache:
    """LRU 缓存测试"""

    def test_basic_get_set(self):
        from backend.utils.response_cache import _LRUCache
        cache = _LRUCache(max_size=10, ttl=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_miss(self):
        from backend.utils.response_cache import _LRUCache
        cache = _LRUCache(max_size=10, ttl=60)
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        from backend.utils.response_cache import _LRUCache
        import time

        cache = _LRUCache(max_size=10, ttl=0)  # TTL=0 立即过期
        cache.set("key1", "value1")
        time.sleep(0.01)
        assert cache.get("key1") is None

    def test_lru_eviction(self):
        from backend.utils.response_cache import _LRUCache
        cache = _LRUCache(max_size=3, ttl=3600)

        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k3", "v3")
        cache.set("k4", "v4")  # 触发 LRU 淘汰

        # k1 应被淘汰（最早插入）
        assert cache.get("k1") is None
        assert cache.get("k2") == "v2"
        assert cache.get("k3") == "v3"
        assert cache.get("k4") == "v4"

    def test_lru_access_moves_to_end(self):
        from backend.utils.response_cache import _LRUCache
        cache = _LRUCache(max_size=3, ttl=3600)

        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k3", "v3")

        # 访问 k1，使其移到末尾
        cache.get("k1")
        cache.set("k4", "v4")  # 此时应淘汰 k2

        assert cache.get("k1") == "v1"
        assert cache.get("k2") is None
        assert cache.get("k3") == "v3"
        assert cache.get("k4") == "v4"

    def test_clear(self):
        from backend.utils.response_cache import _LRUCache
        cache = _LRUCache(max_size=10, ttl=60)
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.clear()
        assert cache.get("k1") is None
        assert cache.get("k2") is None

    def test_stats(self):
        from backend.utils.response_cache import _LRUCache
        cache = _LRUCache(max_size=10, ttl=3600)
        cache.set("k1", "v1")
        cache.set("k2", "v2")

        stats = cache.stats()
        assert stats["size"] == 2
        assert stats["alive"] == 2
        assert stats["max_size"] == 10
        assert stats["ttl"] == 3600


class TestIntentCache:
    """意图缓存测试"""

    def test_set_and_get(self):
        from backend.utils.response_cache import set_cached_intent, get_cached_intent, intent_cache
        intent_cache.clear()
        set_cached_intent("test query", {"intent": "order", "confidence": 0.9})
        result = get_cached_intent("test query")
        assert result["intent"] == "order"
        assert result["confidence"] == 0.9

    def test_cache_miss(self):
        from backend.utils.response_cache import get_cached_intent, intent_cache
        intent_cache.clear()
        assert get_cached_intent("unknown query") is None


class TestAnswerCache:
    """答案缓存测试"""

    def test_set_and_get(self):
        from backend.utils.response_cache import set_cached_answer, get_cached_answer, answer_cache
        answer_cache.clear()
        set_cached_answer("问题", "tenant1", "答案")
        result = get_cached_answer("问题", "tenant1")
        assert result == "答案"

    def test_tenant_isolation(self):
        from backend.utils.response_cache import set_cached_answer, get_cached_answer, answer_cache
        answer_cache.clear()
        set_cached_answer("问题", "tenant1", "答案A")
        set_cached_answer("问题", "tenant2", "答案B")
        assert get_cached_answer("问题", "tenant1") == "答案A"
        assert get_cached_answer("问题", "tenant2") == "答案B"


# ==================== sensitive_filter.py 测试 ====================

class TestSensitiveFilter:
    """敏感信息过滤测试"""

    def test_mask_phone(self):
        from backend.utils.sensitive_filter import mask_sensitive
        text = "请联系13812345678咨询"
        result = mask_sensitive(text)
        assert "13812345678" not in result
        assert "****" in result

    def test_mask_order_no(self):
        from backend.utils.sensitive_filter import mask_sensitive
        text = "订单号 ORD20240601001 已发货"
        result = mask_sensitive(text)
        assert "ORD20240601001" not in result
        assert "****" in result or "ORD" not in result or "***" in result

    def test_no_pii_unchanged(self):
        from backend.utils.sensitive_filter import mask_sensitive
        text = "你好，请问有什么可以帮助你的？"
        result = mask_sensitive(text)
        assert result == text

    def test_none_text(self):
        from backend.utils.sensitive_filter import mask_sensitive
        assert mask_sensitive(None) is None
        assert mask_sensitive("") == ""


# ==================== 运行入口 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])