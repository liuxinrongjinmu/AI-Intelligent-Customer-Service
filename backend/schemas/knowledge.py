"""
知识库同步 API 的 Pydantic schemas
"""
import re
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Literal
from datetime import datetime, timezone

_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_\-.]{1,128}$')


class KnowledgeItem(BaseModel):
    """
    单条知识库文档

    各 kb_type 的 content 格式：
    - faq:     "{question}\n{answer}"
    - product: "{product_name}(SKU:{sku}) {question}\n{answer}"
    - rule:    "{rule_name}\n{rule_content}"
    - public:  "{question}\n{answer}"
    """
    id: str = Field(..., description="文档唯一ID（聚宝赞系统中的ID）")
    content: str = Field(..., min_length=1, max_length=10000, description="文档内容（用于 embedding 和检索）")
    metadata: Optional[dict] = Field(default_factory=dict, description="元数据（分类、关键词、状态等）")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """校验文档ID格式（防注入）"""
        if not v or not _ID_PATTERN.match(v):
            raise ValueError("id 仅允许字母、数字、下划线、连字符、点号，长度1-128位")
        return v


class KnowledgeSyncRequest(BaseModel):
    """
    知识库同步请求（全量/增量）
    """
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "sync_type": "full",
                    "items": [
                        {"id": "faq_001", "content": "退货政策是什么？\n7天无理由退货，商品需保持原包装完好", "metadata": {"category": "售后"}},
                        {"id": "faq_002", "content": "发货时间\n下单后24小时内发货", "metadata": {"category": "物流"}}
                    ]
                }
            ]
        }
    }

    items: list[KnowledgeItem] = Field(..., min_length=1, max_length=1000, description="知识条目列表")
    sync_type: Literal["full", "incremental"] = Field(default="full", description="同步类型：full=全量覆盖，incremental=增量追加")


class KnowledgeBatchRequest(BaseModel):
    """
    知识库批量操作请求（增量增删，支持单条删除）
    """
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "add": [{"id": "faq_new_001", "content": "新FAQ内容", "metadata": {}}],
                    "delete_ids": ["faq_old_001"]
                }
            ]
        }
    }

    add: list[KnowledgeItem] = Field(default_factory=list, max_length=1000, description="新增/更新的知识条目")
    delete_ids: list[str] = Field(default_factory=list, max_length=1000, description="要删除的文档ID列表（传入单个ID即可实现单条删除）")

    @model_validator(mode="after")
    def validate_not_both_empty(self):
        """校验 add 和 delete_ids 不能同时为空"""
        if not self.add and not self.delete_ids:
            raise ValueError("add 和 delete_ids 不能同时为空")
        return self


class KnowledgeSyncResponse(BaseModel):
    """
    同步结果响应（实时返回）
    """
    success: bool
    kb_type: str
    tenant_id: str
    synced_count: int = 0
    deleted_count: int = 0
    message: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))