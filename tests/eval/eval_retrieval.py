"""
检索质量评估脚本

评估指标：
  - Hit Rate（命中率）：至少有一篇期望文档出现在检索结果中的查询比例
  - Precision@K：前K个结果中含期望文档的比例（平均）
  - MRR（Mean Reciprocal Rank）：第一个期望文档的倒数排名均值

使用方法：
  python _eval_retrieval.py
"""
import sys
import os
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.retrieval.hybrid_search import hybrid_search, keyword_match_search
from backend.config import RETRIEVAL_TOP_K, RETRIEVAL_THRESHOLD
from backend.data.eval_dataset import EVALUATION_DATASET


def run_evaluation():
    results = []
    total = len(EVALUATION_DATASET)
    hits = 0

    print(f"检索评估开始，共 {total} 条测试用例")
    print(f"参数: top_k={RETRIEVAL_TOP_K}, threshold={RETRIEVAL_THRESHOLD}")
    print("=" * 70)

    for idx, case in enumerate(EVALUATION_DATASET):
        query = case["query"]
        expected = set(case["expected_doc_ids"])
        tenant_id = case["tenant_id"]
        kb_type_hint = case.get("kb_type", "")

        # 跳过问候等无关检索的用例
        if not expected:
            print(f"  [{idx+1}/{total}] {case['description']}: 跳过（非检索类）")
            results.append({"hit": True, "mrr": 1.0, "precision": 1.0, "skipped": True})
            hits += 1
            continue

        # 确定检索的知识库类型
        kb_types = [kb_type_hint] if kb_type_hint else ["faq", "product", "rule", "public"]

        # 向量检索
        t0 = time.time()
        retrieved = hybrid_search(
            query=query,
            tenant_id=tenant_id,
            kb_types=kb_types,
        )
        elapsed = time.time() - t0

        # 计算指标
        retrieved_ids = [doc.get("source_id", doc.get("id", "")) for doc in retrieved] if retrieved else []
        hit = bool(expected & set(retrieved_ids))

        # MRR
        mrr = 0.0
        for rank, rid in enumerate(retrieved_ids):
            if rid in expected:
                mrr = 1.0 / (rank + 1)
                break

        # Precision@K
        hits_in_topk = sum(1 for rid in retrieved_ids[:RETRIEVAL_TOP_K] if rid in expected)
        precision = hits_in_topk / min(len(retrieved_ids), RETRIEVAL_TOP_K) if retrieved_ids else 0.0

        status = "✅ HIT" if hit else "❌ MISS"
        print(f"  [{idx+1}/{total}] {case['description']}: {status} "
              f"(hit_rate={hit}, mrr={mrr:.3f}, p@{RETRIEVAL_TOP_K}={precision:.3f}, "
              f"time={elapsed:.2f}s, docs={len(retrieved_ids)})")

        if hit:
            hits += 1
        results.append({
            "query": query,
            "hit": hit,
            "mrr": round(mrr, 4),
            "precision": round(precision, 4),
        })

    # 汇总
    hit_rate = hits / total if total > 0 else 0
    mrr_avg = sum(r["mrr"] for r in results) / len(results) if results else 0
    prec_avg = sum(r["precision"] for r in results) / len(results) if results else 0

    print("=" * 70)
    print(f"评估汇总:")
    print(f"  总用例数:    {total}")
    print(f"  命中数:      {hits}")
    print(f"  Hit Rate:    {hit_rate:.2%}")
    print(f"  MRR (Mean):  {mrr_avg:.4f}")
    print(f"  P@{RETRIEVAL_TOP_K} (Mean): {prec_avg:.4f}")
    print("=" * 70)

    return {
        "total": total,
        "hits": hits,
        "hit_rate": hit_rate,
        "mrr": mrr_avg,
        f"p@{RETRIEVAL_TOP_K}": prec_avg,
        "results": results,
    }


if __name__ == "__main__":
    run_evaluation()
