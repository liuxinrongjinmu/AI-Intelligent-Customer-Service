"""
LLM 调用工具：安全调用包装 + 模型工厂函数
"""
import asyncio
import logging
from langchain_deepseek import ChatDeepSeek

from backend.config import DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODEL
from backend.utils.advanced import get_ab_config
from backend.utils.metrics import record_llm_call, record_error

logger = logging.getLogger(__name__)

_classify_llm = None
_generate_llm = None
_generate_llm_stream = None


async def safe_llm_invoke(
    llm, messages: list,
    fallback_text: str = "抱歉，服务暂时不可用，请稍后重试。",
    node_name: str = "unknown"
) -> str:
    """安全的 LLM 调用包装（非流式）：含重试 + 异常兜底"""
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = await llm.ainvoke(messages)
            record_llm_call(node_name)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"LLM 调用失败(第{attempt + 1}次重试): {e}")
                await asyncio.sleep(1 * (attempt + 1))
            else:
                logger.error(f"LLM 调用最终失败: {e}")
                record_error("llm_call_failed")
                return fallback_text
    return fallback_text


async def safe_llm_stream(
    llm, messages: list,
    fallback_text: str = "抱歉，服务暂时不可用，请稍后重试。",
    node_name: str = "unknown"
) -> str:
    """流式 LLM 调用：首 token 前失败可重试，首 token 后失败返回已累积文本"""
    max_retries = 2
    accumulated = ""
    for attempt in range(max_retries + 1):
        try:
            async for chunk in llm.astream(messages):
                content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                if content:
                    accumulated += content
            record_llm_call(node_name)
            return accumulated
        except Exception as e:
            if accumulated:
                logger.error(f"LLM 流式中途失败（已发送部分内容）: {e}")
                return accumulated
            if attempt < max_retries:
                logger.warning(f"LLM 流式调用失败(第{attempt + 1}次重试): {e}")
                await asyncio.sleep(1 * (attempt + 1))
            else:
                logger.error(f"LLM 流式调用最终失败: {e}")
                record_error("llm_call_failed")
                return fallback_text
    return accumulated or fallback_text


def get_classify_llm() -> ChatDeepSeek:
    """意图分类 LLM（非流式，temperature=0，单例复用）"""
    global _classify_llm
    if _classify_llm is None:
        _classify_llm = ChatDeepSeek(
            model=DEEPSEEK_MODEL,
            api_key=DEEPSEEK_API_KEY,
            api_base=DEEPSEEK_BASE_URL,
            temperature=0,
            streaming=False,
            request_timeout=30,
        )
    return _classify_llm


def get_generate_llm(streaming: bool = True) -> ChatDeepSeek:
    """回答生成 LLM（支持 A/B 测试配置，单例复用）"""
    global _generate_llm, _generate_llm_stream
    ab_config = get_ab_config()
    if streaming:
        if _generate_llm_stream is None:
            _generate_llm_stream = ChatDeepSeek(
                model=DEEPSEEK_MODEL,
                api_key=DEEPSEEK_API_KEY,
                api_base=DEEPSEEK_BASE_URL,
                temperature=ab_config.get("temperature", 0.7),
                streaming=True,
                request_timeout=60,
                max_tokens=ab_config.get("max_tokens", 2048),
            )
        return _generate_llm_stream
    else:
        if _generate_llm is None:
            _generate_llm = ChatDeepSeek(
                model=DEEPSEEK_MODEL,
                api_key=DEEPSEEK_API_KEY,
                api_base=DEEPSEEK_BASE_URL,
                temperature=ab_config.get("temperature", 0.7),
                streaming=False,
                request_timeout=60,
                max_tokens=ab_config.get("max_tokens", 2048),
            )
        return _generate_llm
