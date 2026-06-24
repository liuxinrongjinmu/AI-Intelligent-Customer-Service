"""全场景本地测试脚本"""
import httpx
import json

BASE = "http://localhost:8080"
GW = {"X-Gateway-Verified": "true"}
ADMIN = {"X-Admin-Key": "change-me-admin-key"}

passed = 0
failed = 0

def t(name, method, path, headers=None, json_body=None, expect=200):
    global passed, failed
    try:
        fn = {"get": httpx.get, "post": httpx.post, "put": httpx.put, "delete": httpx.delete}[method]
        kw = {"headers": headers or {}, "timeout": 30}
        if json_body:
            kw["json"] = json_body
        r = fn(f"{BASE}{path}", **kw)
        ok = r.status_code == expect
        if ok:
            passed += 1
        else:
            failed += 1
        tag = "PASS" if ok else f"FAIL({r.status_code}!={expect})"
        print(f"  [{tag}] {name}: {r.status_code} {r.text[:120]}")
        return r
    except Exception as e:
        failed += 1
        print(f"  [FAIL] {name}: {e}")
        return None


print("=" * 60)
print("1. 系统接口")
print("=" * 60)
t("健康检查", "get", "/api/v1/system/health")
t("Prometheus指标", "get", "/api/v1/system/metrics")
t("对话统计", "get", "/api/v1/system/stats", headers=GW)
t("知识库健康", "get", "/api/v1/system/stats/kb-health?tenant_id=test_shop", headers=GW)

print()
print("=" * 60)
print("2. 工单管理(新接口)")
print("=" * 60)
t("查询工单列表", "get", "/api/v1/handoff/test_shop/tickets", headers=ADMIN)
t("解决不存在的工单", "put", "/api/v1/handoff/tickets/nonexistent/resolve?assigned_to=test", headers=ADMIN, expect=404)

print()
print("=" * 60)
print("3. 知识库同步")
print("=" * 60)
t("同步历史", "get", "/api/v1/knowledge/sync/test_shop/history", headers=GW)
t("增量同步FAQ", "post", "/api/v1/knowledge/sync/test_shop/faq", headers=GW,
  json_body={"sync_type": "incremental", "items": [{"id": "faq_test1", "content": "测试FAQ内容", "metadata": {"kb_type": "faq"}}]})

print()
print("=" * 60)
print("4. Gateway认证安全")
print("=" * 60)
t("无Gateway头-聊天(开发放行)", "post", "/api/v1/chat/test_shop/stream",
  json_body={"message": "hi", "session_id": "sec1", "user_id": "u1"})
t("无Gateway头-同步(拒绝)", "post", "/api/v1/knowledge/sync/test_shop/faq",
  json_body={"sync_type": "incremental", "items": []}, expect=401)
t("错误Gateway值(拒绝)", "post", "/api/v1/knowledge/sync/test_shop/faq",
  headers={"X-Gateway-Verified": "wrong"}, json_body={"sync_type": "incremental", "items": []}, expect=401)

print()
print("=" * 60)
print("5. 边界条件")
print("=" * 60)
t("空消息(422)", "post", "/api/v1/chat/test_shop/stream",
  json_body={"message": "", "session_id": "b1", "user_id": "u1"}, expect=422)
t("超长消息4001字符(422)", "post", "/api/v1/chat/test_shop/stream",
  json_body={"message": "A" * 4001, "session_id": "b2", "user_id": "u1"}, expect=422)
t("不存在租户(404)", "post", "/api/v1/chat/nonexistent/stream",
  json_body={"message": "hello", "session_id": "b3", "user_id": "u1"}, expect=404)

print()
print("=" * 60)
print("6. SSE聊天 - 问候")
print("=" * 60)
r = httpx.post(f"{BASE}/api/v1/chat/test_shop/stream",
    json={"message": "你好", "session_id": "chat_s1", "user_id": "u1", "user_name": "测试用户", "channel": "app"},
    timeout=60)
print(f"  Status: {r.status_code}")
events = [l for l in r.text.split("\n") if l.startswith("data:")]
for e in events[:6]:
    print(f"  SSE: {e[:120]}")
print(f"  ... 共 {len(events)} 个事件")
if r.status_code == 200:
    passed += 1
else:
    failed += 1

print()
print("=" * 60)
print("7. SSE聊天 - 知识检索")
print("=" * 60)
r = httpx.post(f"{BASE}/api/v1/chat/test_shop/stream",
    json={"message": "燕麦片保质期多久", "session_id": "chat_s2", "user_id": "u1", "user_name": "测试用户", "channel": "app"},
    timeout=60)
print(f"  Status: {r.status_code}")
events = [l for l in r.text.split("\n") if l.startswith("data:")]
for e in events[:6]:
    print(f"  SSE: {e[:120]}")
print(f"  ... 共 {len(events)} 个事件")
if r.status_code == 200:
    passed += 1
else:
    failed += 1

print()
print("=" * 60)
print("8. SSE聊天 - 转人工")
print("=" * 60)
r = httpx.post(f"{BASE}/api/v1/chat/test_shop/stream",
    json={"message": "我要找人工客服", "session_id": "chat_s3", "user_id": "u1", "user_name": "测试用户", "channel": "app"},
    timeout=60)
print(f"  Status: {r.status_code}")
events = [l for l in r.text.split("\n") if l.startswith("data:")]
for e in events[:6]:
    print(f"  SSE: {e[:120]}")
print(f"  ... 共 {len(events)} 个事件")
if r.status_code == 200:
    passed += 1
else:
    failed += 1

print()
print("=" * 60)
print("9. 聊天历史 & 前端调试页")
print("=" * 60)
t("获取聊天历史", "get", "/api/v1/chat/test_shop/history/chat_s1", headers=GW)
r = httpx.get(f"{BASE}/chat/test_shop", timeout=10)
tag = "PASS" if r.status_code == 200 else "FAIL"
print(f"  [{tag}] 前端调试页: {r.status_code}")
if r.status_code == 200:
    passed += 1
else:
    failed += 1

print()
print("=" * 60)
total = passed + failed
print(f"测试结果: {passed}/{total} 通过, {failed} 失败")
print("=" * 60)
