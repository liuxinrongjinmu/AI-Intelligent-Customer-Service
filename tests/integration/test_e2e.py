"""
端到端验证：知识库检索 + 意图路由（覆盖全部 12 种意图）

需要运行中的服务（默认 http://localhost:8080）。
设置环境变量 SKIP_E2E=true 可跳过本文件全部用例。
"""
import json
import os

import httpx
import pytest

SKIP_E2E = os.getenv("SKIP_E2E", "").lower() == "true"
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")
GATEWAY_TOKEN = os.getenv("GATEWAY_VERIFIED_VALUE", "true")

TEST_CASES = [
    ("客户经理被投诉扣几分？", "knowledge_query → 检索退货扣分规则"),
    ("客户经理被投诉有什么影响？", "knowledge_query → 语义改写后检索扣分规则"),
    ("你好", "greeting → greeting_answer"),
    ("我的订单到哪了", "order_query → order_query_node"),
    ("快递什么时候到", "logistics_query → logistics_query_node"),
    ("我要投诉", "complaint → complaint_node"),
    ("转人工", "human_service → human_service_node"),
    ("这款商品有什么规格？", "product_query → product_query_node"),
    ("我有什么优惠券？", "coupon_query → coupon_query_node"),
    ("我的积分有多少？", "account_query → account_query_node"),
    ("谢谢你的帮助", "feedback → feedback_node"),
]


@pytest.mark.skipif(
    SKIP_E2E,
    reason="SKIP_E2E=true，跳过端到端测试（需要运行中的服务）",
)
@pytest.mark.asyncio
@pytest.mark.parametrize("query,description", TEST_CASES)
async def test_e2e_intent_routing(query, description):
    """
    端到端测试：验证每个意图的完整链路
    :param query: 用户输入查询
    :param description: 测试用例描述（意图 → 节点）
    :return: None
    """
    full_answer = ""
    has_error = False
    error_message = ""

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            'POST',
            f'{BASE_URL}/api/v1/chat/demo_001/stream',
            json={
                'message': query,
                'session_id': f'e2e_test_{abs(hash(query))}',
                'user_id': 'e2e_test_user',
            },
            headers={"X-Gateway-Verified": GATEWAY_TOKEN}
        ) as resp:
            assert resp.status_code == 200, (
                f"[{description}] HTTP 状态码异常: {resp.status_code}"
            )
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                event_type = data.get("type")
                if event_type == "text":
                    full_answer += data.get("content", "")
                elif event_type == "error":
                    has_error = True
                    error_message = data.get("message", "未知错误")
                elif event_type == "done":
                    break

    assert not has_error, (
        f"[{description}] 流式响应中出现 error 事件: {error_message}"
    )
    assert full_answer, (
        f"[{description}] full_answer 为空，查询: {query}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
