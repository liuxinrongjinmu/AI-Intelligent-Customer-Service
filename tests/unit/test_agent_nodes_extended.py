"""
Agent 核心节点函数扩展测试

覆盖 classify_intent_node / retrieve_knowledge_node / generate_answer_node /
greeting_answer_node / order_query_node / product_query_node /
coupon_query_node / account_query_node / complaint_node / human_service_node

注意：节点函数已拆分到子模块，mock target 需要指向实际使用位置：
  - LLM 工具 → backend.agent.llm_utils
  - 意图分类 → backend.agent.classifier
  - 知识检索 → backend.agent.retriever
  - 回答生成 → backend.agent.generator
  - 业务域节点 → backend.agent.domains.*
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from tests.unit.conftest import make_test_state as make_state

# 向后兼容别名
_make_state = make_state


class TestClassifyIntentNode:
    """意图识别节点测试 — mock 目标模块: backend.agent.classifier"""

    @pytest.mark.asyncio
    @patch("backend.agent.classifier.get_cached_intent_async", new_callable=AsyncMock, return_value=None)
    @patch("backend.agent.classifier.safe_llm_invoke", new_callable=AsyncMock)
    @patch("backend.agent.classifier.get_classify_llm")
    async def test_classify_returns_valid_intent(self, mock_llm_func, mock_invoke, mock_cache):
        """正常意图识别返回有效意图"""
        from backend.agent.classifier import classify_intent_node
        mock_invoke.return_value = '{"intent":"order_query","intent_sub_type":"order_status","entities":{},"coref_resolved":"查订单","search_query":"查订单","suggested_kb_types":["faq"]}'
        result = await classify_intent_node(_make_state())
        assert result["intent"] == "order_query"
        assert result["intent_sub_type"] == "order_status"

    @pytest.mark.asyncio
    @patch("backend.agent.classifier.get_cached_intent_async", new_callable=AsyncMock, return_value={"intent": "greeting", "intent_sub_type": "hello"})
    async def test_classify_cache_hit(self, mock_cache):
        """意图缓存命中时直接返回"""
        from backend.agent.classifier import classify_intent_node
        result = await classify_intent_node(_make_state())
        assert result["intent"] == "greeting"

    @pytest.mark.asyncio
    @patch("backend.agent.classifier.get_cached_intent_async", new_callable=AsyncMock, return_value=None)
    @patch("backend.agent.classifier.safe_llm_invoke", new_callable=AsyncMock)
    @patch("backend.agent.classifier.get_classify_llm")
    async def test_classify_llm_failure_returns_other(self, mock_llm_func, mock_invoke, mock_cache):
        """LLM 返回无效 JSON 时回退到 other"""
        from backend.agent.classifier import classify_intent_node
        mock_invoke.return_value = "invalid json"
        result = await classify_intent_node(_make_state())
        assert result["intent"] == "other"

    @pytest.mark.asyncio
    @patch("backend.agent.classifier.get_cached_intent_async", new_callable=AsyncMock, return_value=None)
    @patch("backend.agent.classifier.safe_llm_invoke", new_callable=AsyncMock)
    @patch("backend.agent.classifier.get_classify_llm")
    async def test_classify_consecutive_failure_triggers_human(self, mock_llm_func, mock_invoke, mock_cache):
        """连续 2 次识别失败自动转人工"""
        from backend.agent.classifier import classify_intent_node
        mock_invoke.return_value = '{"intent":"other","intent_sub_type":"unknown","entities":{},"coref_resolved":"","search_query":""}'
        result1 = await classify_intent_node(_make_state(ai_failed_count=1))
        assert result1["intent"] == "human_service"


class TestRetrieveKnowledgeNode:
    """知识检索节点测试 — mock 目标模块: backend.agent.retriever"""

    @pytest.mark.asyncio
    @patch("backend.agent.retriever.hybrid_search")
    async def test_retrieve_with_results(self, mock_search):
        """检索到知识时返回上下文"""
        from backend.agent.retriever import retrieve_knowledge_node
        mock_search.return_value = [{"content": "测试知识", "score": 0.9, "source_id": "doc1", "kb_type": "faq"}]
        result = await retrieve_knowledge_node(_make_state(intent="knowledge_query", search_query="测试"))
        assert "knowledge_context" in result or "retrieved_docs" in result

    @pytest.mark.asyncio
    @patch("backend.agent.retriever.hybrid_search")
    async def test_retrieve_empty_results(self, mock_search):
        """检索无结果时返回空上下文"""
        from backend.agent.retriever import retrieve_knowledge_node
        mock_search.return_value = []
        result = await retrieve_knowledge_node(_make_state(intent="knowledge_query", search_query="不存在的知识"))
        assert result.get("knowledge_context", "") == "" or result.get("retrieved_docs", []) == []


class TestGreetingNode:
    """问候节点测试 — mock 目标模块: backend.agent.generator"""

    @pytest.mark.asyncio
    @patch("backend.agent.generator.safe_llm_stream", new_callable=AsyncMock)
    @patch("backend.agent.generator.get_generate_llm")
    async def test_greeting_returns_answer(self, mock_llm_func, mock_stream):
        """问候节点返回友好回复"""
        from backend.agent.generator import greeting_answer_node
        mock_stream.return_value = "您好！很高兴为您服务。"
        result = await greeting_answer_node(_make_state(intent="greeting"))
        assert "final_answer" in result
        assert len(result["final_answer"]) > 0


class TestOrderQueryNode:
    """订单查询节点测试 — mock 目标模块: backend.agent.domains.order"""

    @pytest.mark.asyncio
    @patch("backend.agent.domains.order.call_and_log", new_callable=AsyncMock)
    async def test_order_query_success(self, mock_call):
        """订单查询成功返回格式化结果"""
        from backend.agent.domains import order_query_node
        mock_call.return_value = {"success": True, "data": {"orderNo": "ORD001", "status": "paid"}, "total": 1}
        with patch("backend.agent.domains.order.format_order_result", return_value="订单ORD001已支付"):
            result = await order_query_node(_make_state(intent="order_query"))
            assert "final_answer" in result

    @pytest.mark.asyncio
    @patch("backend.agent.domains.order.call_and_log", new_callable=AsyncMock)
    async def test_order_query_failure(self, mock_call):
        """订单查询失败返回兜底提示"""
        from backend.agent.domains import order_query_node
        mock_call.return_value = {"success": False, "message": "服务不可用"}
        result = await order_query_node(_make_state(intent="order_query"))
        assert "final_answer" in result


class TestCouponQueryNode:
    """优惠券查询节点测试"""

    @pytest.mark.asyncio
    async def test_coupon_no_userid(self):
        """user_id 为空时返回登录提示"""
        from backend.agent.domains import coupon_query_node
        result = await coupon_query_node(_make_state(intent="coupon_query", user_id=""))
        assert "登录" in result["final_answer"] or "登录" in result.get("final_answer", "")


class TestAccountQueryNode:
    """账户查询节点测试 — mock 目标模块: backend.agent.domains.account"""

    @pytest.mark.asyncio
    @patch("backend.agent.domains.account.call_and_log", new_callable=AsyncMock)
    async def test_account_membership_success(self, mock_call):
        """会员等级查询成功"""
        from backend.agent.domains import account_query_node
        mock_call.return_value = {"success": True, "data": {"nickname": "测试", "levelName": "gold", "memberNo": "M001"}}
        with patch("backend.agent.domains.account.format_user_profile_result", return_value="您是黄金会员"):
            result = await account_query_node(_make_state(intent="account_query", intent_sub_type="membership_level"))
            assert "final_answer" in result

    @pytest.mark.asyncio
    async def test_account_address_manage(self):
        """地址管理子类返回 APP 操作指引"""
        from backend.agent.domains import account_query_node
        result = await account_query_node(_make_state(intent="account_query", intent_sub_type="address_manage"))
        assert "APP" in result["final_answer"] or "收货地址" in result["final_answer"]


class TestProductQueryNode:
    """商品查询节点测试 — mock 目标模块: backend.agent.domains.product"""

    @pytest.mark.asyncio
    @patch("backend.agent.domains.product.call_and_log", new_callable=AsyncMock)
    async def test_product_query_success(self, mock_call):
        """商品 API 查询成功返回格式化结果"""
        from backend.agent.domains import product_query_node
        mock_call.return_value = {"success": True, "data": {"productName": "测试商品"}, "total": 1}
        with patch("backend.agent.domains.product.format_product_result", return_value="测试商品 ¥99"):
            result = await product_query_node(_make_state(intent="product_query"))
            assert "final_answer" in result

    @pytest.mark.asyncio
    @patch("backend.agent.domains.product.call_and_log", new_callable=AsyncMock)
    async def test_product_api_unavailable_fallback(self, mock_call):
        """商品 API 未配置时回退到知识库检索"""
        from backend.agent.domains import product_query_node
        mock_call.return_value = {"success": False, "message": "暂未配置"}
        with patch("backend.agent.domains.product.hybrid_search", return_value=[
            {"content": "商品知识", "score": 0.9, "source_id": "doc1", "kb_type": "product"}
        ]):
            with patch("backend.agent.domains.product.safe_llm_stream", new_callable=AsyncMock) as mock_stream:
                with patch("backend.agent.domains.product.get_generate_llm"):
                    mock_stream.return_value = "根据知识库，这是商品信息"
                    result = await product_query_node(_make_state(intent="product_query"))
                    assert "final_answer" in result

    @pytest.mark.asyncio
    @patch("backend.agent.domains.product.call_and_log", new_callable=AsyncMock)
    async def test_product_no_result_friendly_message(self, mock_call):
        """API 和知识库均无结果时返回友好提示"""
        from backend.agent.domains import product_query_node
        mock_call.return_value = {"success": False, "message": "暂未配置"}
        with patch("backend.agent.domains.product.hybrid_search", return_value=[]):
            result = await product_query_node(_make_state(
                intent="product_query",
                intent_entities={"product_name": "不存在商品"}
            ))
            assert "final_answer" in result
            assert "暂未找到" in result["final_answer"]


class TestComplaintNode:
    """投诉处理节点测试 — mock 目标模块: backend.agent.domains.complaint"""

    @pytest.mark.asyncio
    @patch("backend.agent.domains.complaint.safe_llm_stream", new_callable=AsyncMock)
    @patch("backend.agent.domains.complaint.get_generate_llm")
    async def test_complaint_generates_apology(self, mock_llm_func, mock_stream):
        """投诉节点返回道歉并转人工"""
        from backend.agent.domains import complaint_node
        mock_stream.return_value = "非常抱歉给您带来不便，已记录您的投诉并转接人工处理。"
        result = await complaint_node(_make_state(intent="complaint"))
        assert "final_answer" in result
        assert len(result["final_answer"]) > 0

    @pytest.mark.asyncio
    @patch("backend.agent.domains.complaint.safe_llm_stream", new_callable=AsyncMock)
    @patch("backend.agent.domains.complaint.get_generate_llm")
    async def test_complaint_with_reason(self, mock_llm_func, mock_stream):
        """投诉节点处理带原因的投诉"""
        from backend.agent.domains import complaint_node
        mock_stream.return_value = "关于物流延迟的投诉已记录"
        result = await complaint_node(_make_state(
            intent="complaint",
            intent_entities={"reason": "物流延迟"}
        ))
        assert "final_answer" in result


class TestHumanServiceNode:
    """转人工节点测试 — mock 目标模块: backend.agent.domains.human"""

    @pytest.mark.asyncio
    @patch("backend.agent.domains.human.create_handoff_ticket")
    @patch("backend.agent.domains.human.asyncio.to_thread", new_callable=AsyncMock)
    async def test_human_service_creates_ticket(self, mock_to_thread, mock_create):
        """转人工成功创建工单"""
        from backend.agent.domains import human_service_node
        mock_create.return_value = {"success": True, "ticket": {"id": "t1"}}
        mock_to_thread.return_value = mock_create.return_value
        with patch("backend.agent.domains.human.record_handoff"):
            with patch("backend.agent.domains.human.safe_llm_stream", new_callable=AsyncMock) as mock_stream:
                with patch("backend.agent.domains.human.get_generate_llm"):
                    mock_stream.return_value = "正在为您转接人工客服"
                    result = await human_service_node(_make_state(intent="human_service", intent_sub_type="user_request"))
                    assert "final_answer" in result
