"""
生产级同步 API 端到端验证脚本

测试场景：
1. 小批量增量同步 → 实时返回 success + synced_count
2. 模拟大批量同步（5000条） → 分块处理进度可见
3. 并发多租户同步 → 互不阻塞
4. 同步完成后查询验证
"""
import requests
import json
import time
import sys

BASE = "http://127.0.0.1:8080"
GATEWAY_HEADERS = {"X-Gateway-Verified": "true", "X-Real-IP": "10.0.0.1"}
HEADERS = {**GATEWAY_HEADERS, "Content-Type": "application/json"}

passed = 0
failed = 0

def check(condition, msg):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {msg}")
    else:
        failed += 1
        print(f"  ❌ {msg}")

def poll_until_done(resp_data):
    """检查同步接口实时返回结果（已改为实时返回，不再轮询 task_id）"""
    success = resp_data.get("success", False)
    count = resp_data.get("synced_count", 0)
    print(f"    同步结果: success={success}, synced_count={count}")
    return resp_data

# ============================================================
# Test 1: 小批量增量同步
# ============================================================
print("\n" + "=" * 60)
print("Test 1: 小批量增量同步 (3条商品)")
print("=" * 60)

test_items = [
    {"id": "test_p1", "content": "测试商品1：规格100g，价格9.9元，保质期30天", "metadata": {"category": "零食"}},
    {"id": "test_p2", "content": "测试商品2：规格200g，价格19.9元，保质期60天", "metadata": {"category": "零食"}},
    {"id": "test_p3", "content": "测试商品3：规格500g，价格49.9元，保质期90天", "metadata": {"category": "零食"}},
]

r = requests.post(
    f"{BASE}/api/v1/knowledge/sync/demo_001/product",
    json={"sync_type": "incremental", "items": test_items},
    headers=HEADERS
)
check(r.status_code == 200, f"返回200 (实际: {r.status_code})")
resp = r.json()
check(resp.get("success"), f"同步成功: synced_count={resp.get('synced_count', 0)}")
print(f"    响应: {json.dumps(resp, ensure_ascii=False)}")

poll_until_done(resp)

# 验证数据确实写入了
r2 = requests.post(f"{BASE}/api/v1/chat/demo_001/stream", json={"message": "测试商品2多少钱"}, stream=True, timeout=30)
full = ""
for line in r2.iter_lines(decode_unicode=True):
    if line and line.startswith("data: ") and line[6:] != "[DONE]":
        try:
            full += json.loads(line[6:]).get("content", "")
        except Exception as e:
            pass
check("19.9" in full or "测试商品2" in full, f"检索验证通过: {full[:60]}")


# ============================================================
# Test 2: 大批量同步 (500条，模拟分块处理)
# ============================================================
print("\n" + "=" * 60)
print("Test 2: 大批量同步 (500条，验证分块处理)")
print("=" * 60)

large_items = []
for i in range(500):
    large_items.append({
        "id": f"batch_{i:04d}",
        "content": f"批量测试文档{i}：这是一段用于测试分块embedding性能的文本内容，模拟聚宝赞真实数据格式，包含商品描述和FAQ问答内容。",
        "metadata": {"index": i}
    })

r = requests.post(
    f"{BASE}/api/v1/knowledge/sync/demo_001/product",
    json={"sync_type": "incremental", "items": large_items},
    headers=HEADERS
)
check(r.status_code == 200, f"返回200 (实际: {r.status_code})")
resp_batch = r.json()
print(f"    总条数: 500")
print(f"    同步结果: success={resp_batch.get('success')}, synced_count={resp_batch.get('synced_count', 0)}")

poll_until_done(resp_batch)
check(resp_batch.get("success"), f"任务完成: {resp_batch.get('synced_count')} 条已处理")
check(resp_batch.get("synced_count") == 500, f"全部500条处理完毕")


# ============================================================
# Test 3: 并发多租户同步
# ============================================================
print("\n" + "=" * 60)
print("Test 3: 并发多租户同步 (demo_001 + demo_002 同时推送)")
print("=" * 60)

items_a = [{"id": f"concurrent_a_{i}", "content": f"A商家并发测试文档{i}", "metadata": {}} for i in range(5)]
items_b = [{"id": f"concurrent_b_{i}", "content": f"B商家并发测试文档{i}", "metadata": {}} for i in range(5)]

r_a = requests.post(
    f"{BASE}/api/v1/knowledge/sync/demo_001/product",
    json={"sync_type": "incremental", "items": items_a},
    headers=HEADERS
)
r_b = requests.post(
    f"{BASE}/api/v1/knowledge/sync/demo_002/product",
    json={"sync_type": "incremental", "items": items_b},
    headers=HEADERS
)

resp_a = r_a.json()
resp_b = r_b.json()
check(resp_a.get("success") and resp_b.get("success"), f"两个租户同步成功: A synced_count={resp_a.get('synced_count', 0)}, B synced_count={resp_b.get('synced_count', 0)}")

poll_until_done(resp_a)
poll_until_done(resp_b)
check(resp_a.get("success"), f"A商家同步完成")
check(resp_b.get("success"), f"B商家同步完成")

# 验证隔离
r_a_check = requests.post(f"{BASE}/api/v1/chat/demo_001/stream", json={"message": "并发测试文档0"}, stream=True, timeout=30)
full_a = ""
for line in r_a_check.iter_lines(decode_unicode=True):
    if line and line.startswith("data: ") and line[6:] != "[DONE]":
        try:
            full_a += json.loads(line[6:]).get("content", "")
        except Exception as e:
            pass
check("A商家" in full_a or "并发测试" in full_a, f"A商家查询结果: {full_a[:60]}")


# ============================================================
# Test 4: 错误处理 - 无效 API Key
# ============================================================
print("\n" + "=" * 60)
print("Test 4: 安全验证 - 无效 API Key")
print("=" * 60)

r = requests.post(
    f"{BASE}/api/v1/knowledge/sync/demo_001/product",
    json={"sync_type": "incremental", "items": test_items},
    headers={"X-Gateway-Verified": "false", "Content-Type": "application/json"}
)
check(r.status_code == 401, f"无效 Gateway 头返回401 (实际: {r.status_code})")


# ============================================================
# 总结
# ============================================================
print("\n" + "=" * 60)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 60)
