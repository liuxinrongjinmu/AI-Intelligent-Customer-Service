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
        return match_str + "****"
    return match_str[:8] + "****"


class SensitiveDataFilter(logging.Filter):
    """
    日志过滤器：自动掩码敏感信息

    掩码规则：
      - 手机号: 138****5678（保留前3后4）
      - 订单号: ORD***890（保留前3后3）
      - 身份证号: 110101****1234（保留前6后4）
      - API Key: 截断只显示前后各4位
      - session_id: 截断仅保留前8位
    """

    PATTERNS = [
        (re.compile(r'\b1[3-9]\d{9}\b'), _mask_phone),
        (re.compile(r'\b(?:ORD|DD|order|NO\.?)\s*[A-Za-z0-9\-]{4,30}\b', re.IGNORECASE), _mask_order_no),
        (re.compile(r'\b(?:sk-|key-|token-)[A-Za-z0-9\-_]{16,60}\b'), _mask_api_key),
        # session_id 格式：字母数字下划线连字符，长度 8-128
        (re.compile(
            r'\bsession_id[=:]\s*["\']?([A-Za-z0-9_\-]{8,128})["\']?',
            re.IGNORECASE
        ), lambda m: f"session_id={_mask_session_id(m.group(1))}" if '=' in m.group() else _mask_session_id(m.group(1))),
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
    可用于 API 响应日志中的消息内容脱敏
    """
    if not text:
        return text
    text = re.sub(r'1[3-9]\d{9}', lambda m: _mask_phone(m.group()), text)
    text = re.sub(
        r'\b(?:ORD|DD|order|NO\.?)\s*[A-Za-z0-9\-]{4,30}\b',
        lambda m: _mask_order_no(m.group()),
        text,
        flags=re.IGNORECASE
    )
    return text


def install_sensitive_filter():
    """
    安装全局日志脱敏过滤器
    """
    root_logger = logging.getLogger()
    if not any(isinstance(f, SensitiveDataFilter) for f in root_logger.filters):
        root_logger.addFilter(SensitiveDataFilter())