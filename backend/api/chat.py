"""
消费者聊天 API：SSE 流式对话、历史记录

聚宝赞端始终传递三个关键参数：
- tenant_id（路径参数）：商家身份确认
- user_id（请求体）：消费者身份确认
- session_id（请求体）：会话身份确认

会话定位逻辑：
- session_id 已存在 → 自动关联历史记录，继续对话
- session_id 不存在 → 自动创建新会话
"""
import json
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage

from backend.database import get_db, SessionLocal
from backend.models.tenant import Tenant
from backend.models.conversation import Conversation, Message
from backend.schemas.chat import ChatRequest, ChatHistoryResponse, ChatHistoryMessage
from backend.agent.graph import get_agent
from backend.utils.security import validate_message
from backend.utils.auth import verify_chat_api_key
from backend.utils.metrics import record_chat_message, record_error
from backend.utils.request_id import get_request_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["消费者聊天"])

SSE_TOTAL_TIMEOUT = 120  # SSE 流式总超时（秒）


def _get_tenant(tenant_id: str, db: Session) -> Tenant:
    """
    从 URL 路径获取租户

    :param tenant_id: 租户 ID
    :param db: 数据库会话
    :return: 租户对象
    :raises HTTPException: 租户不存在或已停用
    """
    tenant = db.query(Tenant).filter_by(tenant_id=tenant_id, is_active=True).first()
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail={"code": "TENANT_NOT_FOUND", "message": f"租户 {tenant_id} 不存在或已停用"}
        )
    return tenant


def _locate_or_create_session(
    session_id: str, tenant_id: str, user_id: str,
    user_name: str, channel: str, db: Session
) -> Conversation:
    """
    会话定位：根据 session_id 快速查找，不存在则创建

    查找优先级：
    1. 按 thread_id（即 session_id）精确匹配
    2. 额外校验 tenant_id 一致性（安全防护，防止跨租户访问）
    3. 不存在则创建新会话

    :param session_id: 会话 ID（聚宝赞端传入）
    :param tenant_id: 租户 ID
    :param user_id: 用户 ID
    :param user_name: 用户姓名
    :param channel: 来源渠道
    :param db: 数据库会话
    :return: 会话对象
    """
    conversation = db.query(Conversation).filter_by(thread_id=session_id).first()

    if conversation:
        # 安全校验：会话归属的租户必须匹配
        if conversation.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "SESSION_TENANT_MISMATCH", "message": "会话不属于当前租户，无权访问"}
            )
        return conversation

    # session_id 不存在，创建新会话
    conversation = Conversation(
        thread_id=session_id,
        tenant_id=tenant_id,
        channel=channel,
        user_id=user_id,
        user_name=user_name,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.post("/{tenant_id}/stream")
async def chat_stream(
    tenant_id: str,
    body: ChatRequest,
    db: Session = Depends(get_db),
    _api_key: str = Depends(verify_chat_api_key),
):
    """
    消费者发起/继续对话，SSE 流式返回 AI 回复

    聚宝赞端始终传递 session_id 和 user_id：
    - session_id 已存在 → 自动关联历史记录继续对话
    - session_id 不存在 → 自动创建新会话
    """
    tenant = _get_tenant(tenant_id, db)

    try:
        message = validate_message(body.message)
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_MESSAGE", "message": str(e)}
        )

    # 会话定位：session_id 存在则关联，不存在则创建
    session_id = body.session_id
    user_id = body.user_id
    user_name = body.user_name
    channel = body.channel

    conversation = _locate_or_create_session(
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
        user_name=user_name,
        channel=channel,
        db=db,
    )

    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=message,
    )
    db.add(user_msg)
    # 暂不提交：用户消息与 AI 回复在 SSE 完成后一起 commit，保证原子性
    db.flush()

    record_chat_message()

    agent = await get_agent()
    config = {"configurable": {"thread_id": session_id}}
    conv_id = conversation.id

    input_state = {
        "messages": [HumanMessage(content=message)],
        "tenant_id": tenant_id,
        "tenant_name": tenant.name,
        "user_id": user_id,
        "user_name": user_name,
        "channel": channel,
        "thread_id": session_id,
    }

    async def event_generator():
        nonlocal conv_id
        full_answer = ""
        final_intent = ""
        request_id = get_request_id()
        # 复用请求级 DB 会话（由 get_db 依赖注入，StreamingResponse 完成后才清理）
        # 避免创建独立 SessionLocal 导致跨库/跨事务问题
        save_db = db
        # 只有最终输出节点才更新 full_answer，避免中间节点覆盖
        final_output_nodes = {
            "generate_answer", "greeting_answer", "order_query_node",
            "complaint_node", "human_service_node", "product_query_node",
            "coupon_query_node", "account_query_node",
        }
        # 标记当前最终输出节点是否已通过 messages 模式流式输出 token
        has_streamed = False
        try:
            # 使用 stream_mode=["updates", "messages"] 实现真流式：
            # - updates: 节点完成时输出完整 dict（含 final_answer / intent）
            # - messages: LLM token 级别实时推送（仅 streaming=True 的 LLM 调用）
            astream_iter = agent.astream(input_state, config=config, stream_mode=["updates", "messages"])
            # 使用绝对截止时间实现真正的总超时（而非 per-iteration 超时）
            import time as _time
            deadline = _time.monotonic() + SSE_TOTAL_TIMEOUT
            while True:
                remaining = deadline - _time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError(f"SSE 总超时({SSE_TOTAL_TIMEOUT}s)")
                try:
                    mode, data = await asyncio.wait_for(
                        astream_iter.__anext__(),
                        timeout=remaining,
                    )
                except StopAsyncIteration:
                    break

                if mode == "messages":
                    # LLM token 流：data 为 (message_chunk, metadata)
                    chunk, metadata = data
                    node = metadata.get("langgraph_node", "") if isinstance(metadata, dict) else ""
                    # 跳过意图分类节点的 token（不推送给前端）
                    if node == "classify_intent":
                        continue
                    content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                    if content:
                        has_streamed = True
                        yield f"data: {json.dumps({'type': 'text', 'content': content}, ensure_ascii=False)}\n\n"

                elif mode == "updates":
                    # 防御 data 非 dict 时 .items() 崩溃
                    if not isinstance(data, dict):
                        logger.warning(f"updates 模式收到非 dict 数据: {type(data)}")
                        continue
                    for node_name, node_output in data.items():
                        yield f"data: {json.dumps({'type': 'status', 'node': node_name, 'action': 'start'}, ensure_ascii=False)}\n\n"
                        if isinstance(node_output, dict):
                            if "final_answer" in node_output and node_name in final_output_nodes:
                                full_answer = node_output["final_answer"]
                                # 非流式节点（订单/优惠券/账户等 API 结果）未通过 messages 推送 token
                                # 需要将完整答案作为文本事件发送
                                if not has_streamed:
                                    yield f"data: {json.dumps({'type': 'text', 'content': full_answer}, ensure_ascii=False)}\n\n"
                                # 重置标记，为下一个节点准备
                                has_streamed = False
                            if "intent" in node_output:
                                final_intent = node_output["intent"]
                        yield f"data: {json.dumps({'type': 'status', 'node': node_name, 'action': 'end'}, ensure_ascii=False)}\n\n"

            if not full_answer:
                full_answer = "（AI 未能生成有效回复）"
                logger.warning(f"AI回复为空: session={session_id}")

            ai_msg = Message(
                conversation_id=conv_id,
                role="assistant",
                content=full_answer,
                intent=final_intent,
            )
            save_db.add(ai_msg)

            # 原子更新 message_count， AI回复也计入（+1用户 +1 AI = +2）
            save_db.query(Conversation).filter_by(id=conv_id).update(
                {"message_count": Conversation.message_count + 2},
                synchronize_session="fetch"
            )
            save_db.commit()

            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"

        except asyncio.TimeoutError:
            logger.error(f"SSE流式总超时({SSE_TOTAL_TIMEOUT}s): session={session_id}, request_id={request_id}")
            try:
                save_db.rollback()
            except Exception as rollback_e:
                logger.warning(f"SSE回滚失败: {rollback_e}")
            yield f"data: {json.dumps({'type': 'error', 'code': 'TIMEOUT', 'message': '请求处理超时，请稍后重试'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"SSE流式输出异常: session={session_id}, request_id={request_id}, error={e}", exc_info=True)
            try:
                save_db.rollback()
            except Exception as rollback_e:
                logger.warning(f"SSE回滚失败: {rollback_e}")
            yield f"data: {json.dumps({'type': 'error', 'code': 'INTERNAL_ERROR', 'message': '服务暂时不可用，请稍后重试'}, ensure_ascii=False)}\n\n"
        # save_db 由 get_db 依赖统一关闭，此处不再手动 close

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/{tenant_id}/history/{session_id}", response_model=ChatHistoryResponse)
def get_chat_history(
    tenant_id: str,
    session_id: str,
    user_id: str = "",
    db: Session = Depends(get_db),
    _api_key: str = Depends(verify_chat_api_key),
):
    """
    获取指定会话的历史消息

    通过 tenant_id + session_id 定位会话，可选 user_id 做额外归属校验。
    """
    _get_tenant(tenant_id, db)

    conversation = db.query(Conversation).filter_by(
        thread_id=session_id, tenant_id=tenant_id
    ).first()

    if not conversation:
        return ChatHistoryResponse(
            session_id=session_id,
            messages=[]
        )

    # 可选：校验 user_id 归属（传入时校验）
    if user_id and conversation.user_id and conversation.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "SESSION_USER_MISMATCH", "message": "会话不属于当前用户，无权访问"}
        )

    messages = db.query(Message).filter_by(
        conversation_id=conversation.id,
    ).order_by(Message.id.asc()).all()

    return ChatHistoryResponse(
        session_id=session_id,
        messages=[
            ChatHistoryMessage(
                role=msg.role,
                content=msg.content,
                time=msg.created_at.isoformat() if msg.created_at else "",
            ) for msg in messages
        ]
    )
