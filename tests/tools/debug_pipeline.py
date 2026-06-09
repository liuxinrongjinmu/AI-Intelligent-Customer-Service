"""
完整链路调试脚本：追踪"面包多少钱"从意图识别到检索的全过程
注意：此脚本仅供本地调试使用，系统已全面异步化，这里使用同步 API 进行调试
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.retrieval.embedding import get_embedding_model
from backend.retrieval.vector_store import get_collection
from backend.retrieval.hybrid_search import hybrid_search, keyword_match_search
from backend.agent.prompts import CLASSIFY_SYSTEM_PROMPT, CLASSIFY_USER_PROMPT
from backend.config import DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODEL

TENANT_ID = "demo_001"
QUESTION = "面包多少钱"

print("=" * 60)
print(f"调试问题: {QUESTION}")
print(f"租户: {TENANT_ID}")
print("=" * 60)

# ============================================================
# Step 1: 意图识别
# ============================================================
print("\n[Step 1] 意图识别...")
from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import SystemMessage, HumanMessage

llm = ChatDeepSeek(
    model=DEEPSEEK_MODEL,
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
    temperature=0,
    streaming=False,
    request_timeout=30,
)

response = llm.invoke([
    SystemMessage(content=CLASSIFY_SYSTEM_PROMPT),
    HumanMessage(content=CLASSIFY_USER_PROMPT.format(
        history="（无历史对话）",
        message=QUESTION
    ))
])

content = response.content.strip()
if content.startswith("```"):
    content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
result = json.loads(content)

intent = result.get("intent", "other")
entities = result.get("entities", {})
keywords = entities.get("keywords", [])
search_query = result.get("search_query") or QUESTION
kb_types = result.get("suggested_kb_types", ["faq", "product", "rule", "public"])

print(f"  intent         = {intent}")
print(f"  search_query   = {search_query}")
print(f"  keywords       = {keywords}")
print(f"  kb_types       = {kb_types}")
print(f"  原始JSON       = {json.dumps(result, ensure_ascii=False)}")

if intent != "knowledge_query":
    print(f"\n  ⚠ 意图不是 knowledge_query，而是 '{intent}'，不会走检索流程！")
    print("  这可能是面包查不到的根本原因。")
    exit()

# ============================================================
# Step 2: 向量检索
# ============================================================
print("\n[Step 2] 向量检索...")

for query in [search_query, QUESTION]:
    if query == search_query and search_query == QUESTION:
        continue
    print(f"\n  查询: '{query}'")
    results = hybrid_search(
        query=query,
        tenant_id=TENANT_ID,
        kb_types=kb_types,
    )
    if not results:
        print("    → 无结果（阈值过滤后），尝试 threshold=0...")
        results = hybrid_search(
            query=query,
            tenant_id=TENANT_ID,
            kb_types=kb_types,
            relevance_threshold=0.0,
        )
    for i, doc in enumerate(results):
        print(f"    [{i}] score={doc['score']:.4f} kb={doc['kb_type']} | {doc['content'][:80]}")

# ============================================================
# Step 3: 关键词匹配检索 (min_hits=1)
# ============================================================
print(f"\n[Step 3] 关键词匹配检索 (min_hits=1)...")
print(f"  关键词: {keywords}")

if keywords:
    kw_docs = keyword_match_search(
        keywords=keywords,
        tenant_id=TENANT_ID,
        kb_types=kb_types,
        min_hits=1,
    )
    if kw_docs:
        for i, doc in enumerate(kw_docs):
            print(f"    [{i}] hits={doc.get('_keyword_hits', '?')} score={doc['score']:.4f} | {doc['content'][:80]}")
    else:
        print("    → 无匹配结果")

        # 手动测试每个关键词的匹配情况
        print("\n  手动测试每个关键词在各文档中的命中情况:")
        col = get_collection(TENANT_ID, 'product')
        all_data = col.get()
        for i, doc_text in enumerate(all_data.get("documents", [])):
            hits = []
            for kw in keywords:
                if kw.lower() in doc_text.lower():
                    hits.append(kw)
            print(f"    文档{i}: 命中关键词={hits} | {doc_text[:60]}")
else:
    print("  → 没有提取到关键词")
