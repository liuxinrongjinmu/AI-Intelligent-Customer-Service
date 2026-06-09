"""
端到端验证：知识库检索 + 意图路由（覆盖全部 12 种意图）
"""
import asyncio
import json
import httpx

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
    ("我要退款", "refund_operation → refund_operation_node"),
    ("谢谢你的帮助", "feedback → feedback_node"),
]


async def test():
    async with httpx.AsyncClient(timeout=120) as client:
        for q, description in TEST_CASES:
            print(f"\n{'='*60}")
            print(f"[{description}]")
            print(f"查询: {q}")
            print(f"{'='*60}")

            full_answer = ""
            try:
                async with client.stream(
                    'POST',
                    'http://localhost:8080/api/v1/chat/demo_001/stream',
                    json={'message': q},
                    headers={"X-Gateway-Verified": "true"}
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if data.get("type") == "text":
                            full_answer += data.get("content", "")
                        elif data.get("type") == "status":
                            node = data.get("node", "")
                            action = data.get("action", "")
                            if action == "start":
                                print(f"  ▶ [{node}] 开始")
                            elif action == "end":
                                print(f"  ✓ [{node}] 完成")
                        elif data.get("type") == "error":
                            print(f"  ✗ 错误: {data.get('message')}")
                        elif data.get("type") == "done":
                            answer_preview = full_answer[:120] + ("..." if len(full_answer) > 120 else "")
                            print(f"  📝 回答: {answer_preview}")
            except Exception as e:
                print(f"  ✗ 异常: {e}")

    print("\n" + "="*60)
    print("测试完成")


if __name__ == "__main__":
    asyncio.run(test())
