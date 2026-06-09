"""
Agent 图状态定义

意图分类体系（两层结构）：
  大类 → 子类 → 工具调用链
"""
from typing import TypedDict, Annotated, Sequence, NotRequired
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


INTENT_HIERARCHY = {
    "human_service": {
        "label": "转人工服务",
        "priority": 1,
        "sub_types": {
            "user_request": "用户主动要求转人工",
            "complaint": "投诉/纠纷",
            "emotional": "情绪不满",
            "sensitive_operation": "账户安全/敏感操作",
            "ai_limitation": "AI连续失败自动转人工",
        },
        "tool_chain": ["transfer_to_human"],
    },
    "refund_operation": {
        "label": "售后操作",
        "priority": 2,
        "sub_types": {
            "refund_only": "仅退款（未发货）",
            "return_refund": "退货退款（已发货）",
            "exchange": "换货",
            "repair": "维修",
            "refund_progress": "退款进度查询",
            "refund_confirmed": "确认执行退款",
        },
        "tool_chain": ["query_order", "process_refund"],
    },
    "order_query": {
        "label": "订单查询",
        "priority": 3,
        "sub_types": {
            "order_status": "订单状态",
            "order_detail": "订单明细",
            "order_cancel": "订单取消",
            "history_order": "历史订单",
            "pending_payment": "未付款订单",
        },
        "tool_chain": ["query_order"],
    },
    "logistics_query": {
        "label": "物流查询",
        "priority": 3,
        "sub_types": {
            "logistics_progress": "物流进度",
            "estimated_delivery": "预计送达时间",
            "address_change": "修改收货地址",
            "carrier_query": "快递公司查询",
        },
        "tool_chain": ["query_order", "query_logistics"],
    },
    "product_query": {
        "label": "商品咨询",
        "priority": 3,
        "sub_types": {
            "product_price": "商品价格",
            "product_stock": "库存查询",
            "product_spec": "规格参数",
            "product_recommend": "商品推荐",
            "product_compare": "商品对比",
        },
        "tool_chain": ["query_product"],
    },
    "coupon_query": {
        "label": "优惠券咨询",
        "priority": 3,
        "sub_types": {
            "available_coupons": "可用优惠券",
            "coupon_rules": "使用规则",
            "coupon_unusable": "为什么不能用",
            "coupon_expiring": "即将过期",
        },
        "tool_chain": ["query_coupon"],
    },
    "account_query": {
        "label": "账户查询",
        "priority": 3,
        "sub_types": {
            "membership_level": "会员等级",
            "points_balance": "积分余额",
            "address_manage": "收货地址管理",
            "account_security": "账户安全",
        },
        "tool_chain": ["query_user_profile"],
    },
    "knowledge_query": {
        "label": "通用知识查询",
        "priority": 4,
        "sub_types": {
            "after_sale_policy": "售后政策（退货/退款规则）",
            "payment_method": "支付方式",
            "delivery_policy": "配送政策（范围/时效/包邮）",
            "membership_policy": "会员权益说明",
            "promotion_activity": "促销活动",
            "platform_rule": "平台规则",
            "general_help": "通用帮助",
        },
        "tool_chain": ["search_knowledge"],
    },
    "greeting": {
        "label": "闲聊/问候",
        "priority": 5,
        "sub_types": {
            "hello": "打招呼",
            "thanks": "感谢",
            "goodbye": "告别",
            "chitchat": "天气/笑话等无关话题",
        },
        "tool_chain": [],
    },
    "feedback": {
        "label": "反馈/确认",
        "priority": 5,
        "sub_types": {
            "positive": "肯定/确认",
            "suggestion": "建议",
        },
        "tool_chain": [],
    },
    "other": {
        "label": "其他",
        "priority": 5,
        "sub_types": {
            "ambiguous": "模糊问题",
            "unknown": "无法识别",
        },
        "tool_chain": [],
    },
}


class AgentState(TypedDict):
    """
    在各节点之间流转的状态对象
    """
    tenant_id: str
    tenant_name: str
    user_id: str
    user_name: str
    channel: str
    thread_id: str
    messages: Annotated[Sequence[BaseMessage], add_messages]
    intent: NotRequired[str]
    intent_sub_type: NotRequired[str]
    intent_priority: NotRequired[int]
    intent_entities: NotRequired[dict]
    coref_resolved: NotRequired[str]
    search_query: NotRequired[str]
    suggested_kb_types: NotRequired[list[str]]
    retrieved_docs: NotRequired[list]
    final_answer: NotRequired[str]

    user_profile: NotRequired[dict]
    recent_orders: NotRequired[list]
    current_order_id: NotRequired[str]
    current_product_id: NotRequired[str]
    ai_failed_count: NotRequired[int]

    pending_confirmation: NotRequired[dict]