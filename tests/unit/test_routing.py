"""
意图路由单元测试：route_by_intent / INTENT_HIERARCHY 完整性
"""
import pytest
from backend.agent.state import INTENT_HIERARCHY
from backend.agent.nodes import route_by_intent
from tests.unit.conftest import make_test_state


def _make_state(intent: str, intent_sub_type: str = ""):
    """构造路由测试用最小状态（使用共享工具）"""
    return make_test_state(intent=intent, intent_sub_type=intent_sub_type, messages=[])


class TestRouteByIntent:
    """route_by_intent 路由分发测试"""

    def test_human_service_routes_to_human_service_node(self):
        state = _make_state("human_service")
        target = route_by_intent(state)
        assert target == "human_service_node"

    def test_order_query_routes_to_order_query_node(self):
        state = _make_state("order_query")
        target = route_by_intent(state)
        assert target == "order_query_node"

    def test_logistics_query_routes_to_order_query_node(self):
        state = _make_state("logistics_query")
        target = route_by_intent(state)
        assert target == "order_query_node"

    def test_product_query_routes_to_product_query_node(self):
        state = _make_state("product_query")
        target = route_by_intent(state)
        assert target == "product_query_node"

    def test_coupon_query_routes_to_coupon_query_node(self):
        state = _make_state("coupon_query")
        target = route_by_intent(state)
        assert target == "coupon_query_node"

    def test_account_query_routes_to_account_query_node(self):
        state = _make_state("account_query")
        target = route_by_intent(state)
        assert target == "account_query_node"

    def test_knowledge_query_routes_to_retrieve_knowledge(self):
        state = _make_state("knowledge_query")
        target = route_by_intent(state)
        assert target == "retrieve_knowledge"

    def test_complaint_routes_to_complaint_node(self):
        state = _make_state("complaint")
        target = route_by_intent(state)
        assert target == "complaint_node"

    def test_greeting_routes_to_greeting_answer(self):
        state = _make_state("greeting")
        target = route_by_intent(state)
        assert target == "greeting_answer"

    def test_feedback_routes_to_greeting_answer(self):
        state = _make_state("feedback")
        target = route_by_intent(state)
        assert target == "greeting_answer"

    def test_other_routes_to_greeting_answer(self):
        state = _make_state("other")
        target = route_by_intent(state)
        assert target == "greeting_answer"

    def test_unknown_intent_defaults_to_greeting_answer(self):
        state = _make_state("some_unknown_intent")
        target = route_by_intent(state)
        assert target == "greeting_answer"

    def test_missing_intent_defaults_to_greeting_answer(self):
        state = _make_state("")
        target = route_by_intent(state)
        assert target == "greeting_answer"


class TestIntentHierarchy:
    """INTENT_HIERARCHY 完整性测试"""

    def test_all_intents_have_label(self):
        for intent, config in INTENT_HIERARCHY.items():
            assert "label" in config, f"{intent} missing label"
            assert isinstance(config["label"], str)
            assert config["label"] != ""

    def test_all_intents_have_priority(self):
        for intent, config in INTENT_HIERARCHY.items():
            assert "priority" in config, f"{intent} missing priority"
            assert isinstance(config["priority"], int)
            assert config["priority"] >= 1

    def test_all_intents_have_sub_types(self):
        for intent, config in INTENT_HIERARCHY.items():
            assert "sub_types" in config, f"{intent} missing sub_types"
            assert isinstance(config["sub_types"], dict)

    def test_all_intents_have_tool_chain(self):
        for intent, config in INTENT_HIERARCHY.items():
            assert "tool_chain" in config, f"{intent} missing tool_chain"
            assert isinstance(config["tool_chain"], list)

    def test_route_map_covers_all_intents(self):
        route_map = {
            "human_service": "human_service_node",
            "order_query": "order_query_node",
            "logistics_query": "order_query_node",
            "product_query": "product_query_node",
            "coupon_query": "coupon_query_node",
            "account_query": "account_query_node",
            "knowledge_query": "retrieve_knowledge",
            "complaint": "complaint_node",
            "greeting": "greeting_answer",
            "feedback": "greeting_answer",
            "other": "greeting_answer",
        }
        for intent in INTENT_HIERARCHY:
            assert intent in route_map, f"INTENT_HIERARCHY 中的 {intent} 在 route_map 中缺失"

    def test_priority_unique(self):
        priorities = {}
        for intent, config in INTENT_HIERARCHY.items():
            p = config["priority"]
            if p not in priorities:
                priorities[p] = []
            priorities[p].append(intent)
        for p, intents in priorities.items():
            if len(intents) > 1 and p == 5:
                assert all(i in ("greeting", "feedback", "other") for i in intents)

    def test_no_duplicate_sub_types_within_intent(self):
        for intent, config in INTENT_HIERARCHY.items():
            sub_types = list(config["sub_types"].keys())
            assert len(sub_types) == len(set(sub_types)), f"{intent} 存在重复子类"
