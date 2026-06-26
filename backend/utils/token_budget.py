"""
Token 预算管理与上下文动态裁剪

用于控制发送给 LLM 的上下文大小，避免超出模型上下文窗口。

核心能力：
  - estimate_tokens: 预估文本 token 数量（适配 DeepSeek 系列模型）
  - trim_messages: 按 token 预算裁剪对话历史
  - trim_knowledge_context: 按 token 预算裁剪知识文档
"""
import logging

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数量

    优先使用 tiktoken 精确计数（DeepSeek 使用 cl100k_base 词表），
    不可用时回退到字符级粗估。

    :param text: 输入文本
    :return: 估算的 token 数
    """
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except (ImportError, Exception):
        # 回退到字符级估算
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.8 + other_chars * 0.3)


def trim_messages(
    messages: list,
    max_tokens: int,
    system_prompt: str = "",
) -> list:
    """
    按 token 预算动态裁剪对话历史

    策略：
      1. System Prompt 最优先保留（不计入 max_tokens）
      2. 保留最后一条用户消息（当前消息）
      3. 从最近到最远倒序添加历史消息，直到超出预算
      4. 超出预算后丢弃更早的消息

    :param messages: LangChain 消息列表
    :param max_tokens: 对话历史的最大 token 数
    :param system_prompt: System prompt 文本（用于计算已占用 token）
    :return: 裁剪后的消息列表
    """
    if not messages:
        return []

    system_tokens = estimate_tokens(system_prompt)
    available_tokens = max_tokens - system_tokens

    if available_tokens <= 0:
        logger.warning(f"System prompt 已占用 {system_tokens} tokens，超出预算 {max_tokens}")
        return [messages[-1]] if messages else []

    # 最后一条消息（当前消息）优先保留
    if len(messages) <= 1:
        return list(messages)

    last_msg = messages[-1]
    last_tokens = estimate_tokens(_msg_content(last_msg))

    result = [last_msg]
    used_tokens = last_tokens

    # 从倒数第二条开始，倒序添加
    for msg in reversed(messages[:-1]):
        msg_tokens = estimate_tokens(_msg_content(msg))
        overhead = 4  # role 标签等格式开销
        if used_tokens + msg_tokens + overhead > available_tokens:
            skipped = len(messages[:-1]) - len(result) + 1
            if skipped > 0:
                logger.debug(
                    f"对话历史裁剪: 保留 {len(result)} 条, 丢弃 {skipped} 条, "
                    f"已用 {used_tokens}/{available_tokens} tokens"
                )
            break
        result.insert(0, msg)
        used_tokens += msg_tokens + overhead

    return result


def trim_knowledge_context(
    docs: list[dict],
    max_tokens: int,
) -> list[dict]:
    """
    按 token 预算动态裁剪知识文档

    策略：按文档得分降序排列，依次添加直到超出预算

    :param docs: 检索到的文档列表 [{content, score, kb_type, ...}]
    :param max_tokens: 知识上下文的最大 token 数
    :return: 裁剪后的文档列表
    """
    if not docs:
        return []

    sorted_docs = sorted(docs, key=lambda d: d.get("score", 0), reverse=True)
    result = []
    used_tokens = 0

    for doc in sorted_docs:
        content = doc.get("content", "")
        doc_tokens = estimate_tokens(content)
        overhead = 30  # "来源:XXX\n" 等格式开销

        if used_tokens + doc_tokens + overhead > max_tokens:
            skipped = len(sorted_docs) - len(result)
            if skipped > 0:
                logger.debug(
                    f"知识上下文裁剪: 保留 {len(result)} 篇, 丢弃 {skipped} 篇, "
                    f"已用 {used_tokens}/{max_tokens} tokens"
                )
            break

        result.append(doc)
        used_tokens += doc_tokens + overhead

    return result


def format_history_token_aware(
    messages: list,
    max_tokens: int,
    max_turns_fallback: int = 4,
) -> str:
    """
    Token 感知的对话历史格式化

    优先使用 token 预算裁剪，如果无法正确估算则退回到固定轮数。
    注意：参数中 messages 应不包含当前消息（即 messages[:-1]）。

    :param messages: 历史消息列表（不含当前消息）
    :param max_tokens: 对话历史的最大 token 数
    :param max_turns_fallback: token 估算失败时的回退轮数
    :return: 格式化的对话历史文本
    """
    if not messages:
        return "（无历史对话）"

    trimmed = trim_messages(messages, max_tokens)
    if not trimmed:
        return "（历史对话超出上下文窗口，已自动截断）"

    lines = []
    for msg in trimmed:
        role = "用户" if getattr(msg, 'type', 'human') == 'human' else "客服"
        content = _msg_content(msg)
        lines.append(f"{role}: {content}")

    total_tokens = estimate_tokens("\n".join(lines))
    if total_tokens > max_tokens * 1.2:
        # token 预估偏差较大，回退到固定轮数
        return _format_history_fixed_turns(messages, max_turns_fallback)

    return "\n".join(lines)


def format_knowledge_token_aware(
    docs: list[dict],
    max_tokens: int,
) -> str:
    """
    Token 感知的知识文档格式化

    :param docs: 检索到的文档列表
    :param max_tokens: 知识上下文的最大 token 数
    :return: 格式化的知识上下文文本
    """
    trimmed = trim_knowledge_context(docs, max_tokens)
    if not trimmed:
        return "（无相关知识库内容）"

    parts = []
    kb_labels = {
        "faq": "FAQ知识库",
        "product": "商品知识库",
        "rule": "规则文档",
        "public": "平台公共知识库",
    }

    for doc in trimmed:
        kb_type = doc.get("kb_type", "unknown")
        label = kb_labels.get(kb_type, kb_type)
        content = doc.get("content", "")
        # 对单篇文档的超长内容进行截断
        if estimate_tokens(content) > max_tokens // 2:
            content = _truncate_text(content, max_tokens // 2)
        parts.append(f"来源:{label}\n{content}")

    return "\n\n".join(parts)


# ============================================================
# 内部工具函数
# ============================================================

def _msg_content(msg) -> str:
    """安全获取消息文本内容"""
    try:
        return getattr(msg, 'content', str(msg)) or ""
    except Exception as e:
        logger.debug(f"获取消息内容失败: {e}")
        return ""


def _format_history_fixed_turns(messages: list, max_turns: int = 4) -> str:
    """固定轮数格式化（回退方案）"""
    recent = messages[-max_turns * 2:] if len(messages) > max_turns * 2 else messages
    lines = []
    for msg in recent:
        role = "用户" if getattr(msg, 'type', 'human') == 'human' else "客服"
        content = _msg_content(msg)
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _truncate_text(text: str, max_tokens: int) -> str:
    """按 token 预算截断文本"""
    if not text or max_tokens <= 0:
        return ""
    current_tokens = 0
    result_chars = []
    for char in text:
        char_tokens = 1.8 if ('\u4e00' <= char <= '\u9fff' or '\u3000' <= char <= '\u303f') else 0.3
        if current_tokens + char_tokens > max_tokens:
            result_chars.append("...")
            break
        result_chars.append(char)
        current_tokens += char_tokens
    return "".join(result_chars)