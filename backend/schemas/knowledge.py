"""
知识库同步 API 的 Pydantic schemas
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone


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
    content: str = Field(..., description="文档内容（用于 embedding 和检索）")
    metadata: Optional[dict] = Field(default_factory=dict, description="元数据（分类、关键词、状态等）")


class KnowledgeSyncRequest(BaseModel):
    """
    知识库同步请求（全量/增量）
    """
    items: list[KnowledgeItem] = Field(..., description="知识条目列表")
    sync_type: str = Field(default="full", description="同步类型：full=全量覆盖，incremental=增量追加")


class KnowledgeBatchRequest(BaseModel):
    """
    知识库批量操作请求（增量增删，支持单条删除）
    """
    add: list[KnowledgeItem] = Field(default_factory=list, description="新增/更新的知识条目")
    delete_ids: list[str] = Field(default_factory=list, description="要删除的文档ID列表（传入单个ID即可实现单条删除）")


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