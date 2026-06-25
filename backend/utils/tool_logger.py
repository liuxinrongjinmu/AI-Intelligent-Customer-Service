"""
工具调用日志记录器

在 Agent 节点调用外部服务（订单/商品/优惠券/物流/用户画像）时，
异步写入 ToolCallLog 记录，用于审计、性能分析和问题排查。

写入失败不影响主流程，仅记录警告日志。
"""
import asyncio
import logging
import time
from typing import Any

from backend.database import SessionLocal
from backend.models.conversation import ToolCallLog

logger = logging.getLogger(__name__)


async def log_tool_call(
    *,
    tenant_id: str,
    tool_name: str,
    tool_params: dict[str, Any],
    tool_result: dict[str, Any],
    success: bool,
    duration_ms: float,
    conversation_id: str = "",
    error_message: str = "",
) -> None:
    """
    异步记录工具调用日志（写入数据库）

    :param tenant_id: 租户ID
    :param tool_name: 工具名称（如 query_order）
    :param tool_params: 调用参数
    :param tool_result: 返回结果（仅记录元信息，避免过大）
    :param success: 是否成功
    :param duration_ms: 耗时（毫秒）
    :param conversation_id: 会话ID（可选）
    :param error_message: 错误信息（失败时）
    """
    def _write():
        try:
            with SessionLocal() as db:
                log = ToolCallLog(
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    tool_name=tool_name,
                    tool_params=_truncate(tool_params),
                    tool_result=_truncate(tool_result),
                    success=1 if success else 0,
                    duration_ms=duration_ms,
                    error_message=error_message[:2000] if error_message else "",
                )
                db.add(log)
                db.commit()
        except Exception as e:
            logger.warning(f"写入工具调用日志失败: {e}")

    # 在独立线程执行 DB 写入，避免阻塞事件循环
    await asyncio.to_thread(_write)


def _truncate(data: Any, max_len: int = 4096) -> Any:
    """
    截断过大的数据，避免单条日志占用过多存储

    :param data: 原始数据
    :param max_len: 最大长度
    :return: 截断后的数据
    """
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if isinstance(v, str) and len(v) > max_len:
                result[k] = v[:max_len] + "...[truncated]"
            elif isinstance(v, (bytes, bytearray)):
                # bytes/bytearray 无法 JSON 序列化，转为占位标记
                result[k] = f"<bytes len={len(v)}>"
            elif isinstance(v, (dict, list)):
                result[k] = _truncate(v, max_len)
            elif isinstance(v, (int, float, bool, type(None))):
                # 基础类型直接保留
                result[k] = v
            else:
                # 其他非基础类型（tuple/set/datetime/对象等）兜底转字符串
                result[k] = str(v)[:max_len]
        return result
    if isinstance(data, list):
        if len(data) > 50:
            # 保留前 5 个元素 + 摘要提示，避免丢失审计信息
            head = [_truncate(item, max_len) for item in data[:5]]
            head.append(f"...共 {len(data)} 条，已省略 {len(data) - 5} 条")
            return head
        return [_truncate(item, max_len) for item in data]
    if isinstance(data, str) and len(data) > max_len:
        return data[:max_len] + "...[truncated]"
    if isinstance(data, (bytes, bytearray)):
        return f"<bytes len={len(data)}>"
    if isinstance(data, (int, float, bool, type(None), str)):
        return data
    # 其他非基础类型（tuple/set/datetime/对象等）兜底转字符串
    return str(data)[:max_len]


async def call_and_log(
    *,
    tenant_id: str,
    tool_name: str,
    tool_params: dict[str, Any],
    func,
    conversation_id: str = "",
) -> dict[str, Any]:
    """
    调用工具函数并自动记录日志（便捷封装）

    :param tenant_id: 租户ID
    :param tool_name: 工具名称
    :param tool_params: 调用参数
    :param func: 异步工具函数（callable）
    :param conversation_id: 会话ID（可选）
    :return: 工具返回结果 dict
    """
    start = time.time()
    error_msg = ""
    result: Any = None
    success = False
    try:
        result = await func(**tool_params)
        # 校验返回值类型，非 dict 时包装为标准结构，避免 AttributeError
        if not isinstance(result, dict):
            result = {
                "success": True,
                "data": result,
                "message": f"工具返回非 dict 类型: {type(result).__name__}",
            }
        success = bool(result.get("success", False))
    except Exception as e:
        error_msg = str(e)
        result = {"success": False, "data": [], "total": 0, "message": f"工具调用异常: {e}"}
        logger.exception(f"工具调用异常: {tool_name}, error={e}")
    finally:
        duration_ms = (time.time() - start) * 1000

    await log_tool_call(
        tenant_id=tenant_id,
        tool_name=tool_name,
        tool_params=tool_params,
        tool_result=result,
        success=success,
        duration_ms=duration_ms,
        conversation_id=conversation_id,
        error_message=error_msg,
    )
    return result
