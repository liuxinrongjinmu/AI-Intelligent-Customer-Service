"""
监控统计相关的请求/响应模型
"""
from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    """提交反馈请求体"""
    thread_id: str = Field(..., description="会话 thread_id")
    rating: int = Field(..., ge=1, le=5, description="评分 1-5")
    comment: str = Field("", description="反馈意见")
    tenant_id: str = Field("", description="租户ID")
