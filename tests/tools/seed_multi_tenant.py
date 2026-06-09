"""
多租户数据录入：将不同商家的商品知识写入向量库
运行一次即可，之后用 _interactive_test.py 提问
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.retrieval.vector_store import clear_collection, add_to_collection
from backend.retrieval.embedding import get_embedding_model

embedding_model = get_embedding_model()

TENANT_A = "demo_001"
TENANT_B = "demo_002"

# ============================================================
# A商家(谷粒多) 商品数据 — 在这里改
# ============================================================
docs_a = [
    "燕麦片（原味）规格500g/袋，38.8元，保质期6个月，阴凉干燥处保存，生产厂家谷粒多食品有限公司",
    "燕麦片（红枣味）规格400g/袋，29.8元，保质期6个月，密封避光保存，生产厂家谷粒多食品有限公司",
    "面包规格300g/袋，保质期7天，28元，常温避光，生产厂家谷粒多食品有限公司",
]

# ============================================================
# B商家(麦香园) 商品数据 — 在这里改
# ============================================================
docs_b = [
    "燕麦片（经典原味）规格600g/罐，保质期8个月，阴凉干燥处开封后请密封保存，生产厂家麦香园食品科技有限公司",
    "燕麦片（坚果混合装）规格500g/袋，保质期8个月，常温保存避免阳光直射，生产厂家麦香园食品科技有限公司",
    "面包规格250g/袋，保质期5天，15元，常温避光，生产厂家麦香园食品科技有限公司",
]


print("=" * 60)
print("  多租户数据录入")
print("=" * 60)

# A商家
ids_a = [f"prod_a_{i}" for i in range(len(docs_a))]
metas_a = [{"kb_type": "product", "source_id": i, "category": "谷物"} for i in ids_a]
embeddings_a = embedding_model.embed_documents(docs_a)
clear_collection(TENANT_A, "product")
add_to_collection(TENANT_A, "product", ids_a, docs_a, metas_a, embeddings_a)
print(f"\n  A商家({TENANT_A}): 写入 {len(docs_a)} 条商品")
for d in docs_a:
    print(f"    {d[:60]}...")

# B商家
ids_b = [f"prod_b_{i}" for i in range(len(docs_b))]
metas_b = [{"kb_type": "product", "source_id": i, "category": "谷物"} for i in ids_b]
embeddings_b = embedding_model.embed_documents(docs_b)
clear_collection(TENANT_B, "product")
add_to_collection(TENANT_B, "product", ids_b, docs_b, metas_b, embeddings_b)
print(f"\n  B商家({TENANT_B}): 写入 {len(docs_b)} 条商品")
for d in docs_b:
    print(f"    {d[:60]}...")

print(f"\n数据录入完成！现在可以运行 _interactive_test.py 开始提问")
