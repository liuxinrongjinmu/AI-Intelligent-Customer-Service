"""
Agent 节点单元测试

Mock LLM 调用，验证节点逻辑（路由、兜底、重试、格式化）
"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

from backend.agent.nodes import _safe_llm_invoke, route_by_intent
from backend.agent.state import INTENT_HIERARCHY


class TestSafeLlmInvoke:
    """_safe_llm_invoke 函数测试"""

    @pytest.mark.asyncio
    async def test_success_returns_content(self):
        """LLM 正常返回"""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "您好，有什么可以帮您？"
        mock_llm.ainvoke.return_value = mock_response

        result = await _safe_llm_invoke(mock_llm, [], node_name="test")
        assert result == "您好，有什么可以帮您？"

    @pytest.mark.asyncio
    async def test_success_no_content_attr(self):
        """LLM 返回无 content 属性时转字符串"""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = "plain string response"

        result = await _safe_llm_invoke(mock_llm, [], node_name="test")
        assert result == "plain string response"

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        """第一次失败，重试后成功"""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "重试成功"
        mock_llm.ainvoke.side_effect = [Exception("network error"), mock_response]

        with patch("backend.agent.nodes.asyncio.sleep", new_callable=AsyncMock):
            result = await _safe_llm_invoke(mock_llm, [], node_name="test")
        assert result == "重试成功"
        assert mock_llm.ainvoke.call_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        """所有重试耗尽返回兜底文本"""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("persistent error")

        with patch("backend.agent.nodes.asyncio.sleep", new_callable=AsyncMock):
            result = await _safe_llm_invoke(
                mock_llm, [], fallback_text="兜底回复", node_name="test"
            )
        assert result == "兜底回复"
        assert mock_llm.ainvoke.call_count == 3  # 1 + 2 retries

    @pytest.mark.asyncio
    async def test_default_fallback_text(self):
        """默认兜底文本"""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("error")

        with patch("backend.agent.nodes.asyncio.sleep", new_callable=AsyncMock):
            result = await _safe_llm_invoke(mock_llm, [], node_name="test")
        assert "抱歉" in result or "不可用" in result

    @pytest.mark.asyncio
    async def test_retry_delay_increases(self):
        """重试延迟递增"""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = [Exception("error"), Exception("error"), Exception("error")]

        with patch("backend.agent.nodes.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await _safe_llm_invoke(mock_llm, [], node_name="test")
            # 验证 sleep 被调用了 2 次（第1次和第2次失败后）
            assert mock_sleep.call_count == 2
            # 第1次 sleep(1), 第2次 sleep(2)
            assert mock_sleep.call_args_list[0][0][0] == 1
            assert mock_sleep.call_args_list[1][0][0] == 2


class TestRouteByIntent:
    """route_by_intent 路由函数"""

    @pytest.mark.parametrize("intent,expected_node", [
        ("human_service", "human_service_node"),
        ("refund_operation", "refund_operation_node"),
        ("order_query", "order_query_node"),
        ("logistics_query", "order_query_node"),  # 物流联动到订单
        ("product_query", "product_query_node"),
        ("coupon_query", "coupon_query_node"),
        ("account_query", "account_query_node"),
        ("knowledge_query", "retrieve_knowledge"),
        ("complaint", "complaint_node"),
        ("greeting", "greeting_answer"),
        ("feedback", "greeting_answer"),
        ("other", "greeting_answer"),
    ])
    def test_route_mapping(self, intent, expected_node):
        """12种意图路由映射正确"""
        state = {"intent": intent}
        result = route_by_intent(state)
        assert result == expected_node

    def test_route_unknown_intent_defaults_to_greeting(self):
        """未知意图默认路由到 greeting_answer"""
        state = {"intent": "unknown_intent_xyz"}
        result = route_by_intent(state)
        assert result == "greeting_answer"

    def test_route_missing_intent(self):
        """缺少 intent 字段"""
        state = {}
        result = route_by_intent(state)
        assert result == "greeting_answer"

    def test_route_none_intent(self):
        """intent 为 None"""
        state = {"intent": None}
        result = route_by_intent(state)
        assert result == "greeting_answer"


class TestIntentHierarchy:
    """意图层级体系完整性"""

    def test_all_intents_have_labels(self):
        """所有意图都有中文标签"""
        for intent, info in INTENT_HIERARCHY.items():
            assert "label" in info, f"意图 {intent} 缺少 label"
            assert info["label"], f"意图 {intent} 的 label 为空"

    def test_all_intents_have_priority(self):
        """所有意图都有优先级"""
        for intent, info in INTENT_HIERARCHY.items():
            assert "priority" in info, f"意图 {intent} 缺少 priority"
            assert isinstance(info["priority"], int), f"意图 {intent} 的 priority 不是整数"
            assert 1 <= info["priority"] <= 10, f"意图 {intent} 的 priority 超出合理范围"

    def test_all_intents_have_sub_types(self):
        """所有意图都有子类型"""
        for intent, info in INTENT_HIERARCHY.items():
            assert "sub_types" in info, f"意图 {intent} 缺少 sub_types"
            assert isinstance(info["sub_types"], dict), f"意图 {intent} 的 sub_types 不是字典"

    def test_all_intents_have_tool_chain(self):
        """所有意图都有工具链配置"""
        for intent, info in INTENT_HIERARCHY.items():
            assert "tool_chain" in info, f"意图 {intent} 缺少 tool_chain"

    def test_intent_count(self):
        """意图数量为 11（INTENT_HIERARCHY）"""
        assert len(INTENT_HIERARCHY) == 11

    def test_no_duplicate_sub_types(self):
        """同一意图内子类型不重复"""
        for intent, info in INTENT_HIERARCHY.items():
            sub_types = info.get("sub_types", {})
            assert len(sub_types) == len(set(sub_types.keys())), \
                f"意图 {intent} 的子类型存在重复"

    def test_high_priority_intents(self):
        """高优先级意图（priority 1-3）应该是核心业务"""
        high_priority_intents = []
        for intent, info in INTENT_HIERARCHY.items():
            if info["priority"] <= 3:
                high_priority_intents.append(intent)
        # 至少包含转人工和退款
        assert "human_service" in high_priority_intents
        assert "refund_operation" in high_priority_intents


class TestNodesFallback:
    """节点兜底逻辑"""

    def test_fallback_text_for_llm_failure(self):
        """LLM 失败时的兜底文本包含关键信息"""
        from backend.utils.advanced import get_fallback_response
        text = get_fallback_response("llm", "unavailable")
        assert text is not None
        assert len(text) > 0

    def test_fallback_text_for_tool_failure(self):
        """工具调用失败的兜底文本"""
        from backend.utils.advanced import get_fallback_response
        text = get_fallback_response("knowledge", "no_result")
        assert text is not None
        assert len(text) > 0

    def test_fallback_text_for_user_angry(self):
        """用户愤怒时的情绪安抚"""
        from backend.utils.advanced import get_fallback_response
        text = get_fallback_response("emotion", "angry")
        assert text is not None
        assert len(text) > 0

    def test_fallback_text_unknown_scenario(self):
        """未知场景的兜底"""
        from backend.utils.advanced import get_fallback_response
        text = get_fallback_response("nonexistent_scenario")
        # 应该返回默认错误回复
        assert text is not None
        assert len(text) > 0
