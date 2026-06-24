"""
聊天相关的 Pydantic Schema

聚宝赞端调用我方聊天接口时，始终传递三个关键参数：
- tenant_id（路径参数）：商家身份确认
- user_id（请求体）：消费者身份确认
- session_id（请求体）：会话身份确认
"""
import re
from pydantic import BaseModel, Field, field_validator


# 参数格式校验规则
_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_\-.]{1,128}$')
_CHANNEL_VALUES = {"app", "miniapp", "pc", "h5", "unknown"}


class ChatRequest(BaseModel):
    """
    消费者聊天请求

    :param message: 消费者消息内容，最长 4000 字符
    :param session_id: 会话 ID，聚宝赞端生成并管理。已存在则继续对话，不存在则自动创建新会话
    :param user_id: 消费者用户 ID，用于关联订单/优惠券等业务数据
    :param user_name: 消费者姓名，默认"匿名用户"
    :param channel: 来源渠道，默认"unknown"
    """
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": "我的订单什么时候发货？",
                    "session_id": "sess_20240101_001",
                    "user_id": "user_10086",
                    "user_name": "张三",
                    "channel": "h5",
                }
            ]
        }
    }

    message: str = Field(..., min_length=1, max_length=4000, description="消费者消息内容")
    session_id: str = Field(..., description="会话 ID，聚宝赞端生成并管理")
    user_id: str = Field(..., description="消费者用户 ID")
    user_name: str = Field(default="匿名用户", description="消费者姓名")
    channel: str = Field(default="unknown", description="来源渠道")

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        """
        校验 session_id 格式：1-128位字母数字下划线连字符点号
        """
        v = v.strip()
        if not v:
            raise ValueError("session_id 不能为空")
        if not _ID_PATTERN.match(v):
            raise ValueError("session_id 格式无效，仅允许字母、数字、下划线、连字符、点号，长度1-128")
        return v

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """
        校验 user_id 格式：1-128位字母数字下划线连字符点号
        """
        v = v.strip()
        if not v:
            raise ValueError("user_id 不能为空")
        if not _ID_PATTERN.match(v):
            raise ValueError("user_id 格式无效，仅允许字母、数字、下划线、连字符、点号，长度1-128")
        return v

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        """
        校验 channel 取值范围
        """
        if v not in _CHANNEL_VALUES:
            raise ValueError(f"channel 无效，允许值: {', '.join(sorted(_CHANNEL_VALUES))}")
        return v


class ChatHistoryMessage(BaseModel):
    """
    历史消息条目
    """
    role: str
    content: str
    time: str


class ChatHistoryResponse(BaseModel):
    """
    历史消息响应
    """
    session_id: str
    messages: list[ChatHistoryMessage]
