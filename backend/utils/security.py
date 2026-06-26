"""
安全防护模块：Prompt 注入检测 + 输出过滤 + 敏感词审核
"""
import logging
import os
import re as _re
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4000

INJECTION_PATTERNS = [
    r'(?i)ignore\s+(all\s+)?(previous|above|prior)\s+instructions?',
    r'(?i)forget\s+(all\s+)?(previous|above|prior)\s+instructions?',
    r'(?i)disregard\s+(all\s+)?(previous|above|prior)\s+instructions?',
    r'(?i)do\s+not\s+follow\s+(previous|above|prior)\s+instructions?',
    r'(?i)you\s+are\s+now\s+(a\s+)?(different|new)\s+(role|persona|system|assistant)',
    r'(?i)act\s+as\s+(if\s+you\s+are\s+)?(a\s+)?(different|new)\s+(role|persona|system)',
    r'(?i)system\s*(prompt|message|instruction)s?\s*(is|was|are|were)?\s*:',
    r'(?i)reveal\s+(your\s+)?(system\s+)?(prompt|instructions?)',
    r'(?i)print\s+(your\s+)?(system\s+)?(prompt|instructions?)',
    r'(?i)show\s+(me\s+)?(your\s+)?(system\s+)?(prompt|instructions?)',
    r'(?i)from\s+now\s+on\s+you\s+are',
    r'(?i)你的(系统)?(提示词|指令|prompt)',
    r'(?i)忽略(所有)?(之前|上面|以上)的(指令|提示|规则)',
    r'(?i)忘记(所有)?(之前|上面|以上)的(指令|提示|规则)',
    r'(?i)从现在开始你是',
    r'(?i)现在你扮演',
    r'(?i)你是一个全新的',
    r'(?i)```system',
    r'(?i)```user',
    r'(?i)```assistant',
]

OUTPUT_FILTER_PATTERNS = [
    r'(?i)system\s*(prompt|message|instruction)s?\s*(is|was|are|were)?\s*:"?\s*你是一个',
    r'(?i)CLASSIFY_SYSTEM_PROMPT',
    r'(?i)GENERATE_SYSTEM_PROMPT',
]

ZERO_WIDTH_CHARS = _re.compile(r'[\u200b\u200c\u200d\ufeff\u00ad]')


def _normalize_unicode(text: str) -> str:
    """
    Unicode 归一化：将同形字统一为标准形式，防止视觉欺骗绕过

    NFKC 会将全角字符、兼容性字符统一为标准形式，
    例如西里尔字母 і → 拉丁字母 i
    """
    return unicodedata.normalize('NFKC', text)


def _strip_zero_width(text: str) -> str:
    """移除零宽字符，防止在关键词间插入不可见字符绕过检测"""
    return ZERO_WIDTH_CHARS.sub('', text)


def _preprocess(text: str) -> str:
    """预处理文本：归一化 + 去零宽字符"""
    text = _normalize_unicode(text)
    text = _strip_zero_width(text)
    return text


def detect_injection(message: str) -> tuple[bool, str]:
    """
    检测 Prompt 注入攻击

    :param message: 用户输入消息
    :return: (是否检测到注入, 匹配的规则描述)
    """
    if not message:
        return False, ""

    if len(message) > MAX_MESSAGE_LENGTH:
        return True, f"消息长度超过限制 ({len(message)} > {MAX_MESSAGE_LENGTH})"

    processed = _preprocess(message)

    for pattern in INJECTION_PATTERNS:
        if _re.search(pattern, processed):
            return True, f"检测到潜在注入模式: {pattern[:60]}..."

    return False, ""


def sanitize_output(text: str) -> str:
    """
    过滤输出中的系统提示词泄露

    改进：仅移除匹配的部分，而非整段替换，避免误杀正常回答

    :param text: LLM 生成的文本
    :return: 过滤后的文本
    """
    if not text:
        return text

    for pattern in OUTPUT_FILTER_PATTERNS:
        text = _re.sub(pattern, '[内容已过滤]', text)

    return text


def validate_message(message: str) -> str:
    """
    校验用户消息的合法性

    优化：预处理只执行一次，注入检测和敏感词检测共享结果

    :param message: 用户输入消息
    :return: 通过校验的原始消息
    :raises ValueError: 检测到注入攻击或消息不合法
    """
    if not message or not message.strip():
        raise ValueError("消息不能为空")

    if len(message) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"消息过长，最多允许 {MAX_MESSAGE_LENGTH} 字符")

    # 预处理只执行一次，后续检测共享
    processed = _preprocess(message)

    # 注入检测（使用已预处理的结果）
    for pattern in INJECTION_PATTERNS:
        if _re.search(pattern, processed):
            raise ValueError(f"检测到不安全的输入: 检测到潜在注入模式: {pattern[:60]}...")

    # 敏感词检测（使用已预处理的结果）
    for word in SENSITIVE_WORDS:
        normalized_word = _preprocess(word)
        if normalized_word in processed:
            raise ValueError("输入包含违规内容")

    return message.strip()


# 敏感词默认列表（当配置文件不存在时使用）
_DEFAULT_SENSITIVE_WORDS = [
    "赌博", "博彩", "赌场", "六合彩", "彩票预测",
    "色情", "成人", "裸聊", "一夜情",
    "毒品", "大麻", "冰毒", "海洛因",
    "枪支", "弹药", "管制刀具",
    "传销", "洗钱", "非法集资",
    "诈骗", "钓鱼网站", "虚假中奖",
    "政治敏感", "反动", "暴恐",
]


def _load_sensitive_words() -> list[str]:
    """
    从配置文件加载敏感词列表

    配置文件路径：项目根目录 config/sensitive_words.txt
    每行一个敏感词，# 开头为注释，空行忽略。
    文件不存在时使用内置默认列表。

    :return: 敏感词列表
    """
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "sensitive_words.txt"
    if not config_path.exists():
        logger.info(f"敏感词配置文件不存在，使用内置默认列表: {config_path}")
        return list(_DEFAULT_SENSITIVE_WORDS)

    words = []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                words.append(line)
        logger.info(f"从 {config_path} 加载了 {len(words)} 个敏感词")
        return words if words else list(_DEFAULT_SENSITIVE_WORDS)
    except Exception as e:
        logger.error(f"加载敏感词配置文件失败，使用内置默认列表: {e}")
        return list(_DEFAULT_SENSITIVE_WORDS)


SENSITIVE_WORDS = _load_sensitive_words()


def check_sensitive_content(text: str) -> tuple[bool, str]:
    """
    检测文本中是否包含敏感词

    :param text: 待检测文本
    :return: (是否包含敏感词, 命中的敏感词)
    """
    if not text:
        return False, ""

    processed = _preprocess(text)

    for word in SENSITIVE_WORDS:
        normalized_word = _preprocess(word)
        if normalized_word in processed:
            return True, word

    return False, ""


def mask_mobile(mobile: str) -> str:
    """
    手机号脱敏：保留前3后4，中间用 **** 替代

    统一脱敏规则，避免各 service 文件重复实现导致规则不一致。
    长度不足 7 位时全部替换为 ****，防止泄露短号。

    :param mobile: 原始手机号字符串
    :return: 脱敏后的手机号
    """
    if not mobile:
        return ""
    if len(mobile) < 7:
        return "****"
    return mobile[:3] + "****" + mobile[-4:]
