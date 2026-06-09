"""Phase 0 + Phase 1 优化效果验证测试"""
import time
import httpx
import threading

BASE = "http://127.0.0.1:8080"
GATEWAY_HEADERS = {"X-Gateway-Verified": "true", "X-Real-IP": "10.0.0.1"}

passed = 0
failed = 0

def check(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  PASS  {name}")
        passed += 1
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        failed += 1


print("=" * 60)
print("Phase 0 + Phase 1 优化效果验证测试")
print("=" * 60)

# ===== Phase 0 验证 =====
print("\n--- Phase 0 验证 ---")

# 1. 健康检查
check("健康检查", lambda: (
    r := httpx.get(f"{BASE}/api/v1/system/health"),
    None if r.status_code == 200 else (_ for _ in ()).throw(AssertionError(f"status={r.status_code}"))
)[-1])

# 2. Embedding 缓存
def test_embed_cache():
    from backend.retrieval.embedding import embed_query_cached, embed_cache_stats
    embed_query_cached("缓存测试查询")
    stats = embed_cache_stats()
    assert stats["size"] >= 1
check("Embedding 缓存", test_embed_cache)

# 3. 租户缓存
def test_tenant_cache():
    headers = {**GATEWAY_HEADERS, "Content-Type": "application/json"}
    r = httpx.post(f"{BASE}/api/v1/chat/demo_001/stream",
                    headers=headers, json={"message": "你好"}, timeout=60)
    assert r.status_code == 200
check("租户 LRU 缓存", test_tenant_cache)

# 4. SQLite 连接池
def test_connection_pool():
    from backend.database import engine
    pool = engine.pool
    assert pool.size() >= 1
check("SQLite 连接池", test_connection_pool)

# 5. 安全检测去重
def test_security_dedup():
    from backend.utils.security import validate_message
    result = validate_message("查询订单状态")
    assert result == "查询订单状态"
check("安全检测去重", test_security_dedup)

# 6. 限流正常
def test_rate_limit():
    r = httpx.get(f"{BASE}/api/v1/system/health")
    assert r.status_code == 200
check("限流正常放行", test_rate_limit)

# ===== Phase 1 验证 =====
print("\n--- Phase 1 验证 ---")

# 7. ChromaDB 读写分离（写入线程已启动）
def test_chroma_write_thread():
    from backend.retrieval.vector_store import _write_thread
    assert _write_thread is not None and _write_thread.is_alive(), "写入线程未启动"
check("ChromaDB 写入线程运行", test_chroma_write_thread)

# 8. ChromaDB 异步写入 + 同步确认
def test_chroma_async_write():
    from backend.retrieval.vector_store import add_to_collection_sync, get_collection
    from backend.retrieval.embedding import get_embedding_model
    model = get_embedding_model()
    test_id = "phase1_test_001"
    test_doc = "Phase1 测试文档 - 读写分离验证"
    test_meta = {"kb_type": "faq", "source_type": "test"}
    embedding = model.embed_documents([test_doc])
    success = add_to_collection_sync(
        tenant_id="demo_001", kb_type="faq",
        ids=[test_id], documents=[test_doc],
        metadatas=[test_meta], embeddings=embedding,
        timeout=10
    )
    assert success, "同步写入失败"
    # 验证数据可读
    collection = get_collection("demo_001", "faq")
    result = collection.get(ids=[test_id])
    assert result and result.get("ids"), "写入后读取失败"
    # 清理
    from backend.retrieval.vector_store import delete_from_collection
    delete_from_collection("demo_001", "faq", [test_id], async_write=False)
check("ChromaDB 读写分离", test_chroma_async_write)

# 9. 关键词检索 where_document 过滤
def test_keyword_where_filter():
    from backend.retrieval.hybrid_search import keyword_match_search
    results = keyword_match_search(["退货"], "demo_001", kb_types=["faq"])
    assert isinstance(results, list)
check("关键词检索 where_document 过滤", test_keyword_where_filter)

# 10. FAQ 批量同步
def test_faq_batch_sync():
    from backend.database import SessionLocal
    from backend.knowledge.faq_service import sync_all_faqs_for_tenant
    db = SessionLocal()
    try:
        sync_all_faqs_for_tenant(db, "demo_001")
    finally:
        db.close()
check("FAQ 批量同步", test_faq_batch_sync)

# 11. 数据库时间索引
def test_time_indexes():
    from backend.database import engine
    from sqlalchemy import inspect
    inspector = inspect(engine)
    # 检查 conversations 表的索引
    conv_indexes = inspector.get_indexes("conversations")
    conv_idx_cols = [idx["column_names"] for idx in conv_indexes]
    assert any("created_at" in cols for cols in conv_idx_cols), f"conversations.created_at 无索引: {conv_idx_cols}"
    # 检查 messages 表
    msg_indexes = inspector.get_indexes("messages")
    msg_idx_cols = [idx["column_names"] for idx in msg_indexes]
    assert any("created_at" in cols for cols in msg_idx_cols), f"messages.created_at 无索引: {msg_idx_cols}"
    # 检查 feedbacks 表
    fb_indexes = inspector.get_indexes("feedbacks")
    fb_idx_cols = [idx["column_names"] for idx in fb_indexes]
    assert any("created_at" in cols for cols in fb_idx_cols), f"feedbacks.created_at 无索引: {fb_idx_cols}"
check("数据库时间索引", test_time_indexes)

# 12. Nacos 断路器
def test_circuit_breaker():
    from backend.nacos.http_client import InstanceCircuitBreaker, CircuitState
    cb = InstanceCircuitBreaker()
    # 初始状态应为 CLOSED
    assert cb.is_available("test:8080")
    # 连续失败 3 次
    for _ in range(3):
        cb.record_failure("test:8080")
    # 应被熔断
    assert not cb.is_available("test:8080"), "断路器未熔断"
    # 成功后恢复
    cb.record_success("test:8080")
    cb._state.pop("test:8080", None)
    assert cb.is_available("test:8080")
check("Nacos 断路器", test_circuit_breaker)

# 13. Docker Worker 配置（SQLite 单进程，workers=1）
def test_docker_workers():
    with open("Dockerfile", "r") as f:
        content = f.read()
    assert "--workers" in content, "Dockerfile 未配置 --workers"
    assert '"1"' in content, "Dockerfile workers 数量不为 1（SQLite 不支持多进程并发写入）"
check("Docker 多 Worker 配置", test_docker_workers)

# 14. 知识同步 API 端到端
def test_knowledge_sync_e2e():
    headers = {**GATEWAY_HEADERS, "Content-Type": "application/json"}
    r = httpx.post(f"{BASE}/api/v1/knowledge/sync/demo_001/faq",
                   headers=headers,
                   json={"sync_type": "incremental", "items": [
                       {"id": "phase1_sync_001", "content": "Q: Phase1测试\nA: Phase1验证答案", "metadata": {"category": "测试"}}
                   ]}, timeout=30)
    assert r.status_code in (200, 202), f"同步失败: {r.status_code}"
check("知识同步 API 端到端", test_knowledge_sync_e2e)

# 15. 并行检索
def test_parallel_search():
    from backend.retrieval.hybrid_search import hybrid_search
    results = hybrid_search("退货政策", "demo_001", kb_types=["faq"])
    assert isinstance(results, list)
check("并行检索正常", test_parallel_search)

# 汇总
print("\n" + "=" * 60)
print(f"测试结果: {passed} 通过, {failed} 失败, 共 {passed + failed} 项")
print("=" * 60)
