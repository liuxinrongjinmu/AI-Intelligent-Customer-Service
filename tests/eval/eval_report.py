"""
智能客服Agent 全面性能评估测试脚本
"""
import requests
import json
import time
import statistics
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:8080/api/v1/chat"
TENANT = "demo_001"

results = []

def measure(label, question, expected_intent, category):
    start = time.time()
    node_path = []
    full_text = ""
    error = None
    intent = None
    kb_types = None

    try:
        r = requests.post(
            f"{BASE}/{TENANT}/stream",
            json={"message": question},
            headers={"X-Gateway-Verified": "true"},
            stream=True,
            timeout=120,
        )
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = json.loads(line[5:].strip())
            t = data.get("type", "")
            if t == "status":
                node_path.append(data["node"])
            elif t == "text":
                full_text += data.get("content", "")
            elif t == "error":
                error = data.get("message", "")
    except Exception as e:
        error = str(e)

    elapsed = round(time.time() - start, 2)
    intent_match = expected_intent in node_path if expected_intent else True

    bad_phrases = [
        "建议联系人工客服", "建议咨询人工客服", "建议您联系人工",
        "建议转人工处理", "请联系人工", "[1]", "[2]",
        "信息来源:", "来源:",
    ]
    has_bad = [p for p in bad_phrases if p in full_text]

    results.append({
        "label": label,
        "question": question,
        "category": category,
        "expected_intent": expected_intent,
        "node_path": " -> ".join(node_path),
        "intent_match": intent_match,
        "time": elapsed,
        "answer_len": len(full_text),
        "answer": full_text[:100],
        "bad_phrases": has_bad,
        "error": error,
    })

# ============================================================
# 测试用例设计
# ============================================================

# 类别1: RAG知识检索 - 精准匹配
measure("RAG-精准-扣分规则", "客户经理被投诉一次扣几分？", "retrieve_knowledge", "RAG-精准")
measure("RAG-精准-同义改写1", "客户经理被投诉有什么影响？", "retrieve_knowledge", "RAG-同义")
measure("RAG-精准-同义改写2", "投诉客户经理会有什么后果？", "retrieve_knowledge", "RAG-同义")
measure("RAG-精准-口语化", "有人投诉客户经理的话，会扣他几分啊？", "retrieve_knowledge", "RAG-同义")

# 类别2: 意图识别边界测试
measure("意图-问候", "你好", "greeting_answer", "意图-边界")
measure("意图-感谢", "谢谢你的回答", "greeting_answer", "意图-边界")
measure("意图-投诉", "你们的服务太差了，我要投诉", "complaint_node", "意图-边界")
measure("意图-转人工", "转人工", "human_service_node", "意图-边界")

# 类别3: 订单查询（无API时LLM降级）
measure("意图-订单查询", "帮我查一下订单号ORD12345678", "order_query_node", "意图-订单")
measure("意图-物流查询归订单", "我的快递到哪了", "order_query_node", "意图-订单")

# 类别4: 检索覆盖 - 不同知识库类型
measure("RAG-规则类", "积分怎么获取？", "retrieve_knowledge", "RAG-覆盖-规则")
measure("RAG-规则类2", "会员等级怎么提升？", "retrieve_knowledge", "RAG-覆盖-规则")

# 类别5: 模糊/边界
measure("边界-无意义", "asdfghjkl", None, "边界-异常")
measure("边界-空消息", "", None, "边界-异常")

# ============================================================
# 汇总统计
# ============================================================

print("\n" + "=" * 80)
print("                   智能客服Agent 性能评估测试报告")
print("=" * 80)

# 1. 意图识别准确率
rag_tests = [r for r in results if r["category"].startswith("RAG-")]
intent_tests = [r for r in results if r["category"].startswith("意图-")]
edge_tests = [r for r in results if r["category"].startswith("边界-")]

correct = sum(1 for r in rag_tests if r["intent_match"]) + sum(1 for r in intent_tests if r["intent_match"])
total = len(rag_tests) + len(intent_tests)
print(f"\n{'=' * 60}")
print(f"1. 意图识别准确率")
print(f"{'=' * 60}")
print(f"  RAG检索类: {sum(1 for r in rag_tests if r['intent_match'])}/{len(rag_tests)} 正确")
for r in rag_tests:
    print(f"    [{r['intent_match'] and 'PASS' or 'FAIL'}] {r['label']}: {r['node_path']}")
print(f"  意图边界类: {sum(1 for r in intent_tests if r['intent_match'])}/{len(intent_tests)} 正确")
for r in intent_tests:
    print(f"    [{r['intent_match'] and 'PASS' or 'FAIL'}] {r['label']}: {r['node_path']}")

# 2. 响应时间
all_times = [r["time"] for r in results if not r["error"]]
print(f"\n{'=' * 60}")
print(f"2. 响应时间分析")
print(f"{'=' * 60}")
print(f"  样本数: {len(all_times)}")
print(f"  平均: {statistics.mean(all_times):.2f}s")
print(f"  中位数: {statistics.median(all_times):.2f}s")
print(f"  最快: {min(all_times):.2f}s")
print(f"  最慢: {max(all_times):.2f}s")

# 3. 回答质量
bad_count = sum(1 for r in results if r["bad_phrases"])
print(f"\n{'=' * 60}")
print(f"3. 回答质量 - 禁用套话/标记检查")
print(f"{'=' * 60}")
print(f"  违规样本: {bad_count}/{len(results)}")
for r in results:
    if r["bad_phrases"]:
        print(f"    [FAIL] {r['label']}: 包含禁用词 {r['bad_phrases']}")
    else:
        print(f"    [PASS] {r['label']}")

# 4. 错误率
errors = [r for r in results if r["error"]]
print(f"\n{'=' * 60}")
print(f"4. 异常处理")
print(f"{'=' * 60}")
print(f"  错误数: {len(errors)}/{len(results)}")
for r in errors:
    print(f"    [ERR] {r['label']}: {r['error']}")

# 5. 回答长度合理性
rag_answers = [r for r in results if r["category"].startswith("RAG-") and r["answer_len"] > 0]
print(f"\n{'=' * 60}")
print(f"5. 回答长度分析 (RAG类)")
print(f"{'=' * 60}")
for r in rag_answers:
    print(f"  {r['label']}: {r['answer_len']}字 -> {r['answer'][:80]}...")
    if r["answer_len"] < 10:
        print(f"    [WARN] 回答过短，可能信息不完整")
    elif r["answer_len"] > 200:
        print(f"    [WARN] 回答过长，可能啰嗦")

# 6. 最终评分
print(f"\n{'=' * 60}")
print(f"6. 综合评分")
print(f"{'=' * 60}")
intent_score = correct / total * 100 if total > 0 else 0
quality_score = (len(results) - bad_count) / len(results) * 100 if results else 0
reliability = (len(results) - len(errors)) / len(results) * 100 if results else 0

print(f"  意图识别准确率: {intent_score:.1f}%")
print(f"  回答规范性:     {quality_score:.1f}%")
print(f"  系统可靠性:     {reliability:.1f}%")

# 详细输出每个测试用例
print(f"\n{'=' * 60}")
print(f"7. 详细测试记录")
print(f"{'=' * 60}")
for i, r in enumerate(results):
    print(f"\n  [{i+1}] {r['label']}")
    print(f"    Q: {r['question']}")
    print(f"    Path: {r['node_path']}")
    print(f"    Time: {r['time']}s | Intent OK: {r['intent_match']}")
    print(f"    A({r['answer_len']}字): {r['answer']}...")
    if r["bad_phrases"]:
        print(f"    BAD: {r['bad_phrases']}")
    if r["error"]:
        print(f"    ERR: {r['error']}")

print("\n" + "=" * 80)
print("                              测试结束")
print("=" * 80)
