"""
Agent 核心节点函数扩展测试

覆盖 classify_intent_node / retrieve_knowledge_node / generate_answer_node /
greeting_answer_node / order_query_node / product_query_node /
coupon_query_node / account_query_node / complaint_node / human_service_node
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from backend.agent.state import AgentState


def _make_state(**overrides) -> dict:
    """构造测试用 AgentState"""
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


class TestClassifyIntentNode:
    """意图识别节点测试"""

    @pytest.mark.asyncio
    @patch("backend.agent.nodes.get_cached_intent", return_value=None)
    @patch("backend.agent.nodes._safe_llm_invoke", new_callable=AsyncMock)
    @patch("backend.agent.nodes._get_classify_llm")
    async def test_classify_returns_valid_intent(self, mock_llm_func, mock_invoke, mock_cache):
        """正常意图识别返回有效意图"""
        from backend.agent.nodes import classify_intent_node
        mock_invoke.return_value = '{"intent":"order_query","intent_sub_type":"order_status","entities":{},"coref_resolved":"查订单","search_query":"查订单","suggested_kb_types":["faq"]}'
        result = await classify_intent_node(_make_state())
        assert result["intent"] == "order_query"
        assert result["intent_sub_type"] == "order_status"

    @pytest.mark.asyncio
    @patch("backend.agent.nodes.get_cached_intent", return_value={"intent": "greeting", "intent_sub_type": "hello"})
    async def test_classify_cache_hit(self, mock_cache):
        """意图缓存命中时直接返回"""
        from backend.agent.nodes import classify_intent_node
        result = await classify_intent_node(_make_state())
        assert result["intent"] == "greeting"

    @pytest.mark.asyncio
    @patch("backend.agent.nodes.get_cached_intent", return_value=None)
    @patch("backend.agent.nodes._safe_llm_invoke", new_callable=AsyncMock)
    @patch("backend.agent.nodes._get_classify_llm")
    async def test_classify_llm_failure_returns_other(self, mock_llm_func, mock_invoke, mock_cache):
        """LLM 返回无效 JSON 时回退到 other"""
        from backend.agent.nodes import classify_intent_node
        mock_invoke.return_value = "invalid json"
        result = await classify_intent_node(_make_state())
        assert result["intent"] == "other"

    @pytest.mark.asyncio
    @patch("backend.agent.nodes.get_cached_intent", return_value=None)
    @patch("backend.agent.nodes._safe_llm_invoke", new_callable=AsyncMock)
    @patch("backend.agent.nodes._get_classify_llm")
    async def test_classify_consecutive_failure_triggers_human(self, mock_llm_func, mock_invoke, mock_cache):
        """连续 2 次识别失败自动转人工"""
        from backend.agent.nodes import classify_intent_node
        mock_invoke.return_value = '{"intent":"other","intent_sub_type":"unknown","entities":{},"coref_resolved":"","search_query":""}'
        # 第一次失败
        result1 = await classify_intent_node(_make_state(ai_failed_count=1))
        assert result1["intent"] == "human_service"


class TestRetrieveKnowledgeNode:
    """知识检索节点测试"""

    @pytest.mark.asyncio
    @patch("backend.agent.nodes.hybrid_search")
    async def test_retrieve_with_results(self, mock_search):
        """检索到知识时返回上下文"""
        from backend.agent.nodes import retrieve_knowledge_node
        mock_search.return_value = [{"content": "测试知识", "score": 0.9, "source_id": "doc1", "kb_type": "faq"}]
        result = await retrieve_knowledge_node(_make_state(intent="knowledge_query", search_query="测试"))
        assert "knowledge_context" in result or "retrieved_docs" in result

    @pytest.mark.asyncio
    @patch("backend.agent.nodes.hybrid_search")
    async def test_retrieve_empty_results(self, mock_search):
        """检索无结果时返回空上下文"""
        from backend.agent.nodes import retrieve_knowledge_node
        mock_search.return_value = []
        result = await retrieve_knowledge_node(_make_state(intent="knowledge_query", search_query="不存在的知识"))
        assert result.get("knowledge_context", "") == "" or result.get("retrieved_docs", []) == []


class TestGreetingNode:
    """问候节点测试"""

    @pytest.mark.asyncio
    @patch("backend.agent.nodes._safe_llm_stream", new_callable=AsyncMock)
    @patch("backend.agent.nodes._get_generate_llm")
    async def test_greeting_returns_answer(self, mock_llm_func, mock_stream):
        """问候节点返回友好回复"""
        from backend.agent.nodes import greeting_answer_node
        mock_stream.return_value = "您好！很高兴为您服务。"
        result = await greeting_answer_node(_make_state(intent="greeting"))
        assert "final_answer" in result
        assert len(result["final_answer"]) > 0


class TestOrderQueryNode:
    """订单查询节点测试"""

    @pytest.mark.asyncio
    @patch("backend.agent.nodes.call_and_log", new_callable=AsyncMock)
    async def test_order_query_success(self, mock_call):
        """订单查询成功返回格式化结果"""
        from backend.agent.nodes import order_query_node
        mock_call.return_value = {"success": True, "data": {"orderNo": "ORD001", "status": "paid"}, "total": 1}
        with patch("backend.agent.nodes.format_order_result", return_value="订单ORD001已支付"):
            result = await order_query_node(_make_state(intent="order_query"))
            assert "final_answer" in result

    @pytest.mark.asyncio
    @patch("backend.agent.nodes.call_and_log", new_callable=AsyncMock)
    async def test_order_query_failure(self, mock_call):
        """订单查询失败返回兜底提示"""
        from backend.agent.nodes import order_query_node
        mock_call.return_value = {"success": False, "message": "服务不可用"}
        result = await order_query_node(_make_state(intent="order_query"))
        assert "final_answer" in result


class TestCouponQueryNode:
    """优惠券查询节点测试"""

    @pytest.mark.asyncio
    async def test_coupon_no_userid(self):
        """user_id 为空时返回登录提示"""
        from backend.agent.nodes import coupon_query_node
        result = await coupon_query_node(_make_state(intent="coupon_query", user_id=""))
        assert "登录" in result["final_answer"] or "登录" in result.get("final_answer", "")


class TestAccountQueryNode:
    """账户查询节点测试"""

    @pytest.mark.asyncio
    @patch("backend.agent.nodes.call_and_log", new_callable=AsyncMock)
    async def test_account_membership_success(self, mock_call):
        """会员等级查询成功"""
        from backend.agent.nodes import account_query_node
        mock_call.return_value = {"success": True, "data": {"nickname": "测试", "levelName": "gold", "memberNo": "M001"}}
        with patch("backend.agent.nodes.format_user_profile_result", return_value="您是黄金会员"):
            result = await account_query_node(_make_state(intent="account_query", intent_sub_type="membership_level"))
            assert "final_answer" in result

    @pytest.mark.asyncio
    async def test_account_address_manage(self):
        """地址管理子类返回 APP 操作指引"""
        from backend.agent.nodes import account_query_node
        result = await account_query_node(_make_state(intent="account_query", intent_sub_type="address_manage"))
        assert "APP" in result["final_answer"] or "收货地址" in result["final_answer"]


class TestHumanServiceNode:
    """转人工节点测试"""

    @pytest.mark.asyncio
    @patch("backend.agent.nodes.create_handoff_ticket")
    @patch("backend.agent.nodes.asyncio.to_thread", new_callable=AsyncMock)
    async def test_human_service_creates_ticket(self, mock_to_thread, mock_create):
        """转人工成功创建工单"""
        from backend.agent.nodes import human_service_node
        mock_create.return_value = {"success": True, "ticket": {"id": "t1"}}
        mock_to_thread.return_value = mock_create.return_value
        with patch("backend.agent.nodes.record_handoff"):
            with patch("backend.agent.nodes._safe_llm_stream", new_callable=AsyncMock) as mock_stream:
                with patch("backend.agent.nodes._get_generate_llm"):
                    mock_stream.return_value = "正在为您转接人工客服"
                    result = await human_service_node(_make_state(intent="human_service", intent_sub_type="user_request"))
                    assert "final_answer" in result
