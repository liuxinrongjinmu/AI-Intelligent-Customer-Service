"""
敏感信息过滤模块：在日志输出前对手机号、订单号、身份证等 PII 做掩码处理
"""
import re
import logging


def _mask_phone(match_str: str) -> str:
    return match_str[:3] + "****" + match_str[-4:]


def _mask_order_no(match_str: str) -> str:
    if len(match_str) <= 6:
        return match_str[:2] + "****"
    return match_str[:3] + "***" + match_str[-3:]


def _mask_api_key(match_str: str) -> str:
    if len(match_str) <= 8:
        return "****"
    return match_str[:4] + "****" + match_str[-4:]


def _mask_session_id(match_str: str) -> str:
    """session_id 截断，仅保留前8位，防止会话劫持"""
    if len(match_str) <= 8:
        return match_str[:4] + "****"
    return match_str[:8] + "****"


def _mask_session_id_match(match_str: str) -> str:
    """
    session_id 正则匹配掩码：保留 "session_id=" 前缀，仅掩码 ID 值

    接收完整匹配字符串（如 'session_id=abc123def456'），
    通过正则提取前缀、ID值、后缀，分别处理后拼接，避免 str.replace 误替换。

    :param match_str: 完整匹配字符串
    :return: 掩码后的完整字符串（如 'session_id=abc123de****'）
    """
    m = re.match(
        r'(session_id[=:]\s*["\']?)([A-Za-z0-9_\-]{8,128})(["\']?)',
        match_str,
        re.IGNORECASE,
    )
    if not m:
        return match_str
    prefix, sid, suffix = m.group(1), m.group(2), m.group(3)
    return prefix + _mask_session_id(sid) + suffix


def _mask_id_card(match_str: str) -> str:
    """身份证号脱敏：保留前6后4"""
    if len(match_str) <= 10:
        return match_str[:2] + "****"
    return match_str[:6] + "********" + match_str[-4:]


def _mask_email(match_str: str) -> str:
    """邮箱脱敏：保留首字母和域名"""
    if "@" not in match_str:
        return "****"
    local, domain = match_str.split("@", 1)
    if len(local) <= 1:
        return local + "***@" + domain
    return local[0] + "***@" + domain


def _mask_bank_card(match_str: str) -> str:
    """银行卡号脱敏：保留前4后4"""
    if len(match_str) <= 8:
        return "****"
    return match_str[:4] + "****" + match_str[-4:]


class SensitiveDataFilter(logging.Filter):
    """
    日志过滤器：自动掩码敏感信息

    掩码规则：
      - 手机号: 138****5678（保留前3后4）
      - 订单号: ORD***890（保留前3后3）
      - 身份证号: 110101****1234（保留前6后4）
      - 银行卡号: 6222****5678（保留前4后4）
      - 邮箱: a***@example.com（保留首字母和域名）
      - API Key: 截断只显示前后各4位
      - session_id: 截断仅保留前8位
    """

    PATTERNS = [
        (re.compile(r'\b1[3-9]\d{9}\b'), _mask_phone),
        (re.compile(r'\b(?:ORD|DD|order|NO\.?)\s*[A-Za-z0-9\-]{4,30}\b', re.IGNORECASE), _mask_order_no),
        (re.compile(r'\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b'), _mask_id_card),
        (re.compile(r'\b622\d{12,18}\b'), _mask_bank_card),
        (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), _mask_email),
        (re.compile(r'\b(?:sk-|key-|token-)[A-Za-z0-9\-_]{16,60}\b'), _mask_api_key),
        # session_id 格式：字母数字下划线连字符，长度 8-128
        # 掩码时保留 "session_id=" 前缀，仅掩码 ID 值
        (re.compile(
            r'\bsession_id[=:]\s*["\']?([A-Za-z0-9_\-]{8,128})["\']?',
            re.IGNORECASE
        ), _mask_session_id_match),
    ]

    def filter(self, record):
        if isinstance(record.msg, str):
            msg = record.msg
            for pattern, mask_func in self.PATTERNS:
                msg = pattern.sub(lambda m: mask_func(m.group()), msg)
            record.msg = msg
        return True


def mask_sensitive(text: str) -> str:
    """
    对文本中的敏感信息进行掩码处理

    覆盖类型：手机号、订单号、身份证号、银行卡号、邮箱、API Key

    :param text: 原始文本
    :return: 脱敏后的文本
    """
    if not text:
        return text
    # 手机号
    text = re.sub(r'1[3-9]\d{9}', lambda m: _mask_phone(m.group()), text)
    # 订单号
    text = re.sub(
        r'\b(?:ORD|DD|order|NO\.?)\s*[A-Za-z0-9\-]{4,30}\b',
        lambda m: _mask_order_no(m.group()),
        text,
        flags=re.IGNORECASE
    )
    # 身份证号
    text = re.sub(
        r'\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b',
        lambda m: _mask_id_card(m.group()),
        text,
    )
    # 银行卡号
    text = re.sub(r'\b622\d{12,18}\b', lambda m: _mask_bank_card(m.group()), text)
    # 邮箱
    text = re.sub(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        lambda m: _mask_email(m.group()),
        text,
    )
    # API Key
    text = re.sub(
        r'\b(?:sk-|key-|token-)[A-Za-z0-9\-_]{16,60}\b',
        lambda m: _mask_api_key(m.group()),
        text,
    )
    return text


def install_sensitive_filter():
    """
    安装全局日志脱敏过滤器
    """
    root_logger = logging.getLogger()
    if not any(isinstance(f, SensitiveDataFilter) for f in root_logger.filters):
        root_logger.addFilter(SensitiveDataFilter())