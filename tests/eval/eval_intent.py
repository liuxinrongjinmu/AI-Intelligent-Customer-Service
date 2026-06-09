"""
意图路由评估脚本

基于 ai-cs-materials/03-典型对话测试集.md 中的 53 个测试用例，
评估意图分类的准确率（intent + intent_sub_type）
"""
import json
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.agent.graph import get_agent
from langchain_core.messages import HumanMessage


EVAL_DATASET = [
    # ========== 预购咨询 ==========
    {"message": "这个商品什么时候发货啊？", "expected_intent": "knowledge_query", "sub_type": "delivery_policy", "desc": "预购发货时间"},
    {"message": "可以指定周末配送吗？", "expected_intent": "knowledge_query", "sub_type": "delivery_policy", "desc": "指定周末配送"},

    # ========== 优惠券咨询 ==========
    {"message": "我有优惠券吗？哪些可以用？", "expected_intent": "coupon_query", "sub_type": "available_coupons", "desc": "可用优惠券"},
    {"message": "为什么这张优惠券用不了？", "expected_intent": "coupon_query", "sub_type": "coupon_unusable", "desc": "优惠券不可用"},
    {"message": "我的积分有多少？", "expected_intent": "account_query", "sub_type": "points_balance", "desc": "积分查询"},
    {"message": "会员有什么权益？", "expected_intent": "knowledge_query", "sub_type": "membership_policy", "desc": "会员权益"},

    # ========== 商品咨询 ==========
    {"message": "这件衣服有M码吗？", "expected_intent": "product_query", "sub_type": "product_spec", "desc": "尺码查询"},
    {"message": "红色还有货吗？", "expected_intent": "product_query", "sub_type": "product_stock", "desc": "颜色库存"},
    {"message": "能推荐一款适合送礼的商品吗？", "expected_intent": "product_query", "sub_type": "product_recommend", "desc": "商品推荐"},
    {"message": "这两款有什么区别？", "expected_intent": "product_query", "sub_type": "product_compare", "desc": "商品对比"},

    # ========== 账户登录 ==========
    {"message": "密码忘了怎么找回来？", "expected_intent": "knowledge_query", "sub_type": "general_help", "desc": "找回密码"},
    {"message": "怎么修改收货地址？", "expected_intent": "account_query", "sub_type": "address_manage", "desc": "修改地址"},

    # ========== 退款申请 ==========
    {"message": "不想要了，还没发货，帮我退款。", "expected_intent": "refund_operation", "sub_type": "refund_only", "desc": "仅退款"},
    {"message": "收到的东西坏了，我要退货。", "expected_intent": "refund_operation", "sub_type": "return_refund", "desc": "退货退款"},
    {"message": "尺码不合适，能换一个吗？", "expected_intent": "refund_operation", "sub_type": "exchange", "desc": "换货"},
    {"message": "退款怎么还没到账？", "expected_intent": "refund_operation", "sub_type": "refund_progress", "desc": "退款进度"},

    # ========== 订单查询 ==========
    {"message": "帮我查一下订单状态。", "expected_intent": "order_query", "sub_type": "order_status", "desc": "订单状态"},
    {"message": "前两天买的东西到哪了？", "expected_intent": "logistics_query", "sub_type": "logistics_progress", "desc": "物流进度"},
    {"message": "预计什么时候能送到？", "expected_intent": "logistics_query", "sub_type": "estimated_delivery", "desc": "预计送达"},
    {"message": "我想取消订单。", "expected_intent": "order_query", "sub_type": "order_cancel", "desc": "取消订单"},
    {"message": "发的什么快递？", "expected_intent": "logistics_query", "sub_type": "carrier_query", "desc": "快递公司查询"},

    # ========== 促销活动 ==========
    {"message": "最近有什么活动吗？", "expected_intent": "knowledge_query", "sub_type": "promotion_activity", "desc": "促销活动"},
    {"message": "怎么加入会员？", "expected_intent": "knowledge_query", "sub_type": "membership_policy", "desc": "加入会员"},

    # ========== 投诉 ==========
    {"message": "我要投诉！快递员态度太差了！", "expected_intent": "human_service", "sub_type": "complaint", "desc": "投诉快递员"},
    {"message": "你们的东西质量太差了！", "expected_intent": "human_service", "sub_type": "complaint", "desc": "质量投诉"},

    # ========== 转人工 ==========
    {"message": "转人工", "expected_intent": "human_service", "sub_type": "user_request", "desc": "直说转人工"},
    {"message": "人工客服在吗？", "expected_intent": "human_service", "sub_type": "user_request", "desc": "问人工"},
    {"message": "这个问题你们机器人解决不了的。", "expected_intent": "human_service", "sub_type": "user_request", "desc": "质疑机器人"},
    {"message": "之前联系过你们客服，说帮我处理结果没下文了", "expected_intent": "human_service", "sub_type": "complaint", "desc": "投诉跟进不力"},
    {"message": "你再不解决我就去12315投诉", "expected_intent": "human_service", "sub_type": "complaint", "desc": "威胁投诉"},

    # ========== 闲聊 ==========
    {"message": "你好", "expected_intent": "greeting", "sub_type": "hello", "desc": "打招呼"},
    {"message": "谢谢", "expected_intent": "feedback", "sub_type": "positive", "desc": "感谢"},
    {"message": "再见", "expected_intent": "greeting", "sub_type": "goodbye", "desc": "告别"},
    {"message": "今天天气不错", "expected_intent": "greeting", "sub_type": "chitchat", "desc": "天气闲聊"},

    # ========== 支付 ==========
    {"message": "支持哪些支付方式？", "expected_intent": "knowledge_query", "sub_type": "payment_method", "desc": "支付方式"},
    {"message": "可以货到付款吗？", "expected_intent": "knowledge_query", "sub_type": "payment_method", "desc": "货到付款"},

    # ========== 配送 ==========
    {"message": "包邮吗？", "expected_intent": "knowledge_query", "sub_type": "delivery_policy", "desc": "包邮政策"},
    {"message": "多久能到？", "expected_intent": "logistics_query", "sub_type": "estimated_delivery", "desc": "配送时效"},

    # ========== 账户 ==========
    {"message": "我是白金会员有什么特权？", "expected_intent": "account_query", "sub_type": "membership_level", "desc": "会员特权"},
    {"message": "积分怎么获得？", "expected_intent": "knowledge_query", "sub_type": "membership_policy", "desc": "积分获取"},

    # ========== 安全 ==========
    {"message": "我的账号被盗了怎么办？", "expected_intent": "account_query", "sub_type": "account_security", "desc": "账号安全"},

    # ========== 老人/特殊场景 ==========
    {"message": "我不会操作退款，能不能帮我弄", "expected_intent": "refund_operation", "sub_type": "refund_only", "desc": "老人操作退款"},
    {"message": "字太小看不清，能不能告诉我怎么退货", "expected_intent": "refund_operation", "sub_type": "return_refund", "desc": "视力不好问退货"},

    # ========== 极限压力 ==========
    {"message": "订单号忘记了我给你手机号13812345678能不能帮我查一下物流到哪了", "expected_intent": "logistics_query", "sub_type": "logistics_progress", "desc": "手机号查物流"},
    {"message": "前天买了个杯子昨天买的衣服今天买的书这三个订单都到哪了帮我分别查一下", "expected_intent": "order_query", "sub_type": "order_status", "desc": "多订单查询"},

    # ========== 售后政策 ==========
    {"message": "超过7天还能退货吗？", "expected_intent": "knowledge_query", "sub_type": "after_sale_policy", "desc": "超期退货"},
    {"message": "退货的运费谁出？", "expected_intent": "knowledge_query", "sub_type": "after_sale_policy", "desc": "退货运费"},
    {"message": "拆开包装了还能退吗？", "expected_intent": "knowledge_query", "sub_type": "after_sale_policy", "desc": "拆包退货"},

    # ========== 库存与预售 ==========
    {"message": "这个预售什么时候能发货？", "expected_intent": "knowledge_query", "sub_type": "delivery_policy", "desc": "预售发货"},
    {"message": "显示缺货什么时候补货？", "expected_intent": "product_query", "sub_type": "product_stock", "desc": "补货时间"},

    # ========== 额外测试用例（53条中的补充） ==========
    {"message": "支持哪些银行付款？", "expected_intent": "knowledge_query", "sub_type": "payment_method", "desc": "银行支持"},
    {"message": "怎么开发票？", "expected_intent": "knowledge_query", "sub_type": "general_help", "desc": "发票"},
    {"message": "可以换收件人吗？", "expected_intent": "logistics_query", "sub_type": "address_change", "desc": "改收件人"},
]


def evaluate_intent(
    actual_intent: str,
    actual_sub_type: str,
    expected_intent: str,
    expected_sub_type: str,
) -> dict:
    """评估单条意图分类结果"""
    intent_match = actual_intent == expected_intent
    sub_match = actual_sub_type == expected_sub_type

    return {
        "intent_match": intent_match,
        "sub_match": sub_match,
        "correct": intent_match and sub_match,
    }


async def run_evaluation():
    """异步运行评估"""
    agent = await get_agent()
    tenant_name = "演示商家"

    results = []
    total = len(EVAL_DATASET)
    intent_correct = 0
    sub_correct = 0
    overall_correct = 0

    print(f"评估数据集: {total} 条测试用例\n")

    for idx, case in enumerate(EVAL_DATASET):
        message = case["message"]
        expected_intent = case["expected_intent"]
        expected_sub_type = case["sub_type"]
        desc = case["desc"]

        config = {"configurable": {"thread_id": f"eval-test-{idx}"}}
        input_state = {
            "messages": [HumanMessage(content=message)],
            "tenant_id": "demo_001",
            "tenant_name": tenant_name,
        }

        try:
            result = await agent.ainvoke(input_state, config=config)
            actual_intent = result.get("intent", "other")
            actual_sub_type = result.get("intent_sub_type", "")

            eval_result = evaluate_intent(actual_intent, actual_sub_type, expected_intent, expected_sub_type)
            results.append({
                **case,
                "actual_intent": actual_intent,
                "actual_sub_type": actual_sub_type,
                **eval_result,
            })

            if eval_result["intent_match"]:
                intent_correct += 1
            if eval_result["sub_match"]:
                sub_correct += 1
            if eval_result["correct"]:
                overall_correct += 1

            status = "PASS" if eval_result["correct"] else "FAIL"
            print(f"[{status}] {desc}: expected={expected_intent}/{expected_sub_type}, actual={actual_intent}/{actual_sub_type}")
        except Exception as e:
            print(f"[ERROR] {desc}: {e}")
            results.append({**case, "actual_intent": "ERROR", "actual_sub_type": "", "intent_match": False, "sub_match": False, "correct": False})

    print(f"\n{'='*60}")
    print(f"评估结果汇总:")
    print(f"  意图大类准确率: {intent_correct}/{total} = {intent_correct/total*100:.1f}%")
    print(f"  意图子类准确率: {sub_correct}/{total} = {sub_correct/total*100:.1f}%")
    print(f"  综合准确率    : {overall_correct}/{total} = {overall_correct/total*100:.1f}%")

    failed = [r for r in results if not r["correct"]]
    if failed:
        print(f"\n失败用例 ({len(failed)}):")
        for r in failed:
            print(f"  - {r['desc']}: expected={r['expected_intent']}/{r['sub_type']}, actual={r['actual_intent']}/{r['actual_sub_type']}")

    return {
        "intent_accuracy": intent_correct / total,
        "sub_type_accuracy": sub_correct / total,
        "overall_accuracy": overall_correct / total,
        "failed_count": len(failed),
    }


if __name__ == "__main__":
    asyncio.run(run_evaluation())
