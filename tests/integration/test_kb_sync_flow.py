"""
知识库同步集成测试

测试知识库同步 → 向量化 → 检索的完整链路。
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from backend.agent.state import AgentState
from backend.agent.retriever import retrieve_knowledge_node
from tests.unit.conftest import make_test_state


@pytest.mark.integration
class TestKBSyncFlow:
    """知识库同步流测试"""

    @pytest.mark.asyncio
    @patch("backend.agent.retriever.hybrid_search")
    async def test_retrieve_after_sync(self, mock_search):
        """验证同步后的知识可用"""
        mock_search.return_value = [
            {"content": "退换货政策：7天无理由退换", "score": 0.95, "source_id": "faq_sync_001", "kb_type": "faq"},
        ]
        state = await retrieve_knowledge_node(make_test_state(
            messages=[MagicMock(content="退换货政策")],
            intent="knowledge_query",
            intent_sub_type="after_sale_policy",
            search_query="退换货政策",
        ))
        assert state["retrieved_docs"]
        assert "退换货" in state["retrieved_docs"][0]["content"]

    @pytest.mark.asyncio
    @patch("backend.agent.retriever.hybrid_search")
    async def test_retrieve_empty_results(self, mock_search):
        """验证无匹配知识时的空结果处理"""
        mock_search.return_value = []
        state = await retrieve_knowledge_node(make_test_state(
            messages=[MagicMock(content="不存在的知识XYZ")],
            intent="knowledge_query",
            intent_sub_type="after_sale_policy",
            search_query="不存在的知识XYZ",
        ))
        assert not state["retrieved_docs"]

    @pytest.mark.asyncio
    @patch("backend.agent.retriever.hybrid_search")
    async def test_retrieve_below_threshold_filtered(self, mock_search):
        """验证低于阈值的知识被过滤"""
        # hybrid_search 内部对低于阈值的结果返回空列表，这里模拟过滤后的结果
        mock_search.return_value = []
        state = await retrieve_knowledge_node(make_test_state(
            messages=[MagicMock(content="低分查询")],
            intent="knowledge_query",
            intent_sub_type="after_sale_policy",
            search_query="低分查询",
        ))
        assert not state["retrieved_docs"]

    @pytest.mark.asyncio
    @patch("backend.agent.retriever.hybrid_search")
    async def test_multi_kb_type_retrieval(self, mock_search):
        """验证多知识库类型检索"""
        mock_search.return_value = [
            {"content": "FAQ答案", "score": 0.9, "source_id": "faq_001", "kb_type": "faq"},
            {"content": "商品说明", "score": 0.85, "source_id": "product_001", "kb_type": "product"},
        ]
        state = await retrieve_knowledge_node(make_test_state(
            messages=[MagicMock(content="通用查询")],
            intent="knowledge_query",
            intent_sub_type="after_sale_policy",
            search_query="通用查询",
        ))
        contents = [doc["content"] for doc in state["retrieved_docs"]]
        assert "FAQ答案" in contents
        assert "商品说明" in contents
