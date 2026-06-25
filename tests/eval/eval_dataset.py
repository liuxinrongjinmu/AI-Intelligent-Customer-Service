"""
检索评估测试集

每条包含：
  - query: 用户问题
  - expected_doc_ids: 期望检索到的文档ID列表（至少命中其中一个即算成功）
  - tenant_id: 所属租户
  - kb_type: 期望检索的知识库类型
"""
EVALUATION_DATASET = [
    {
        "query": "燕麦片保质期多久",
        "expected_doc_ids": ["a_oat_original", "b_oat_original", "b_oat_nut"],
        "tenant_id": "demo_001",
        "kb_type": "product",
        "description": "A商家燕麦片查询"
    },
    {
        "query": "面包多少钱",
        "expected_doc_ids": ["a_bread"],
        "tenant_id": "demo_001",
        "kb_type": "product",
        "description": "A商家面包价格查询"
    },
    {
        "query": "面包多少钱",
        "expected_doc_ids": ["b_bread"],
        "tenant_id": "demo_002",
        "kb_type": "product",
        "description": "B商家面包价格查询（多租户隔离）"
    },
    {
        "query": "燕麦片怎么保存",
        "expected_doc_ids": ["a_oat_original", "b_oat_original", "b_oat_nut"],
        "tenant_id": "demo_001",
        "kb_type": "product",
        "description": "保存方式查询"
    },
    {
        "query": "麦香园的燕麦片有哪些口味",
        "expected_doc_ids": ["b_oat_original", "b_oat_nut"],
        "tenant_id": "demo_002",
        "kb_type": "product",
        "description": "B商家口味查询"
    },
    {
        "query": "你好",
        "expected_doc_ids": [],
        "tenant_id": "demo_001",
        "kb_type": "",
        "description": "问候（不触发检索）"
    },
    {
        "query": "退货流程是怎样的",
        "expected_doc_ids": [],
        "tenant_id": "demo_001",
        "kb_type": "faq",
        "description": "FAQ查询"
    },
]
