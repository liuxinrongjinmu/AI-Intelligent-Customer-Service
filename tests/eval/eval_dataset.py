"""
检索评估测试集

每条包含：
  - query: 用户问题
  - expected_doc_ids: 期望检索到的文档ID列表（至少命中其中一个即算成功）
  - tenant_id: 所属租户
  - kb_type: 期望检索的知识库类型

注意：expected_doc_ids 需与 data/chroma_db/ 中实际同步的知识条目 ID 一致。
当前基于 2026-06-26 同步的 58 条测试知识库数据。
"""
EVALUATION_DATASET = [
    {
        "query": "X200手机多少钱",
        "expected_doc_ids": ["prod_phone_x200"],
        "tenant_id": "demo_001",
        "kb_type": "product",
        "description": "手机价格查询"
    },
    {
        "query": "跑步鞋推荐",
        "expected_doc_ids": ["prod_sneaker_air"],
        "tenant_id": "demo_001",
        "kb_type": "product",
        "description": "运动鞋商品查询"
    },
    {
        "query": "退货政策是什么",
        "expected_doc_ids": ["faq_return_policy"],
        "tenant_id": "demo_001",
        "kb_type": "faq",
        "description": "退货政策FAQ查询"
    },
    {
        "query": "怎么使用优惠券",
        "expected_doc_ids": ["faq_coupon_use"],
        "tenant_id": "demo_001",
        "kb_type": "faq",
        "description": "优惠券FAQ查询"
    },
    {
        "query": "几天能送到",
        "expected_doc_ids": ["faq_delivery_time"],
        "tenant_id": "demo_001",
        "kb_type": "faq",
        "description": "配送时效查询"
    },
    {
        "query": "你好",
        "expected_doc_ids": [],
        "tenant_id": "demo_001",
        "kb_type": "",
        "description": "问候（不触发检索）"
    },
    {
        "query": "平台服务协议是什么",
        "expected_doc_ids": ["rule_platform_tos"],
        "tenant_id": "demo_001",
        "kb_type": "rule",
        "description": "规则文档查询"
    },
]
