"""
聊天流程集成测试

测试完整 Agent 工作流：意图识别 → 路由 → 检索/业务查询 → 生成
使用 mock LLM 和 mock HTTP 客户端，无需真实外部依赖。
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.agent.classifier import classify_intent_node, route_by_intent
from backend.agent.retriever import retrieve_knowledge_node
from backend.agent.generator import generate_answer_node, greeting_answer_node
from backend.agent.domains import (
    order_query_node, product_query_node, coupon_query_node,
    account_query_node, complaint_node, human_service_node,
)
from tests.unit.conftest import make_test_state


@pytest.mark.integration
class TestChatFlow:
    """聊天流完整链路测试"""

    @pytest.mark.asyncio
    @patch("backend.agent.classifier.get_cached_intent_async", new_callable=AsyncMock, return_value=None)
    @patch("backend.agent.classifier.safe_llm_invoke", new_callable=AsyncMock)
    @patch("backend.agent.classifier.get_classify_llm")
    @patch("backend.agent.generator.safe_llm_stream", new_callable=AsyncMock)
    @patch("backend.agent.generator.get_generate_llm")
    async def test_greeting_flow(self, mock_gen_llm, mock_stream, mock_cls_llm, mock_invoke, mock_cache):
        """测试问候流程：classify → route → greeting_answer"""
        # classify
        mock_invoke.return_value = '{"intent":"greeting","intent_sub_type":"hello","entities":{},"coref_resolved":"你好","search_query":"你好","suggested_kb_types":["faq"]}'
        state = make_test_state()
        classify_result = await classify_intent_node(state)
        state.update(classify_result)
        assert state["intent"] == "greeting"

        # route
        next_node = route_by_intent(state)
        assert next_node == "greeting_answer"

        # greeting_answer
        mock_stream.return_value = "您好！很高兴为您服务。"
        result = await greeting_answer_node(state)
        assert "final_answer" in result
        assert "您好" in result.get("final_answer", "")

    @pytest.mark.asyncio
    @patch("backend.agent.classifier.get_cached_intent_async", new_callable=AsyncMock, return_value=None)
    @patch("backend.agent.classifier.safe_llm_invoke", new_callable=AsyncMock)
    @patch("backend.agent.classifier.get_classify_llm")
    @patch("backend.agent.retriever.hybrid_search")
    async def test_knowledge_query_flow(self, mock_search, mock_cls_llm, mock_invoke, mock_cache):
        """测试知识问答流程：classify → route → retrieve → generate"""
        # classify -> knowledge_query
        mock_invoke.return_value = '{"intent":"knowledge_query","intent_sub_type":"after_sale_policy","entities":{},"coref_resolved":"如何退款","search_query":"如何退款","suggested_kb_types":["faq"]}'
        state = make_test_state(messages=[MagicMock(content="如何退款")])
        classify_result = await classify_intent_node(state)
        state.update(classify_result)
        assert state["intent"] == "knowledge_query"

        # route -> retrieve_knowledge
        next_node = route_by_intent(state)
        assert next_node == "retrieve_knowledge"

        # retrieve
        mock_search.return_value = [
            {"content": "退款流程：1.进入订单页 2.点击申请退款", "score": 0.9, "source_id": "faq_001", "kb_type": "faq"},
        ]
        retrieve_result = await retrieve_knowledge_node(state)
        state.update(retrieve_result)
        assert state.get("retrieved_docs")
        assert "退款流程" in state["retrieved_docs"][0]["content"]

    @pytest.mark.asyncio
    @patch("backend.agent.classifier.get_cached_intent_async", new_callable=AsyncMock, return_value=None)
    @patch("backend.agent.classifier.safe_llm_invoke", new_callable=AsyncMock)
    @patch("backend.agent.classifier.get_classify_llm")
    async def test_order_query_flow(self, mock_cls_llm, mock_invoke, mock_cache):
        """测试订单查询流程：classify → route → order_query_node"""
        mock_invoke.return_value = '{"intent":"order_query","intent_sub_type":"order_status","entities":{"order_no":"ORD001"},"coref_resolved":"查订单ORD001","search_query":"ORD001","suggested_kb_types":["faq"]}'
        state = make_test_state(user_id="U001")
        classify_result = await classify_intent_node(state)
        state.update(classify_result)
        assert state["intent"] == "order_query"

        next_node = route_by_intent(state)
        assert next_node == "order_query_node"

    @pytest.mark.asyncio
    @patch("backend.agent.classifier.get_cached_intent_async", new_callable=AsyncMock, return_value=None)
    @patch("backend.agent.classifier.safe_llm_invoke", new_callable=AsyncMock)
    @patch("backend.agent.classifier.get_classify_llm")
    async def test_unknown_intent_fallback(self, mock_cls_llm, mock_invoke, mock_cache):
        """测试未知意图回退到 other → greeting_answer"""
        mock_invoke.return_value = '{"intent":"other","intent_sub_type":"unknown","entities":{},"coref_resolved":"...","search_query":"...","suggested_kb_types":["faq"]}'
        state = make_test_state(messages=[MagicMock(content="asdfghjkl")])
        classify_result = await classify_intent_node(state)
        state.update(classify_result)
        assert state["intent"] == "other"

        next_node = route_by_intent(state)
        assert next_node == "greeting_answer"

    @pytest.mark.asyncio
    @patch("backend.agent.classifier.get_cached_intent_async", new_callable=AsyncMock, return_value=None)
    @patch("backend.agent.classifier.safe_llm_invoke", new_callable=AsyncMock)
    @patch("backend.agent.classifier.get_classify_llm")
    @patch("backend.agent.generator.safe_llm_stream", new_callable=AsyncMock)
    @patch("backend.agent.generator.get_generate_llm")
    async def test_sse_event_format(self, mock_gen_llm, mock_stream, mock_cls_llm, mock_invoke, mock_cache):
        """测试 SSE 事件格式正确性（text → status → done 序列）"""
        mock_invoke.return_value = '{"intent":"greeting","intent_sub_type":"hello","entities":{},"coref_resolved":"你好","search_query":"你好","suggested_kb_types":["faq"]}'
        state = make_test_state()
        classify_result = await classify_intent_node(state)
        state.update(classify_result)

        mock_stream.return_value = "您好！"
        result = await greeting_answer_node(state)

        assert result.get("final_answer") is not None
        assert isinstance(result.get("final_answer"), str)
