"""
公共辅助函数
"""
import json
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Union, Any, Optional

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """
    返回当前 UTC 时间（时区感知）

    替代已弃用的 datetime.utcnow()，返回带时区信息的 datetime 对象。
    Python 3.12+ 中 datetime.utcnow() 已标记为弃用。
    """
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    """
    生成 UUID 字符串

    统一替代各模型中重复定义的 generate_uuid() 函数。
    """
    return str(uuid.uuid4())


def resolve_tenant_id(tenant_id: str) -> Union[str, int]:
    """
    将我方字符串 tenant_id 映射为聚宝赞端 int64 tenantId

    映射规则：
    1. 若 TENANT_ID_MAP 已配置且包含匹配项，返回对应的 int64 值
    2. 否则尝试将 tenant_id 转为 int（如 "123" → 123）
    3. 转换失败则原样返回字符串（需聚宝赞端兼容）

    :param tenant_id: 我方租户 ID（字符串）
    :return: 映射后的租户 ID（int 或 str）
    """
    from backend.config import TENANT_ID_MAP
    if TENANT_ID_MAP:
        for pair in TENANT_ID_MAP.split(","):
            pair = pair.strip()
            if ":" in pair:
                key, val = pair.split(":", 1)
                if key.strip() == tenant_id:
                    try:
                        return int(val.strip())
                    except ValueError:
                        return val.strip()
    # 尝试直接转 int
    try:
        return int(tenant_id)
    except (ValueError, TypeError):
        return tenant_id


def robust_json_parse(
    text: str,
    default: Optional[dict] = None,
) -> dict:
    """
    鲁棒 JSON 解析：处理 LLM 输出中常见的 JSON 格式问题。

    处理策略（按优先级尝试）：
    1. 直接 json.loads（理想情况）
    2. 去除 markdown 代码块包裹后解析
    3. 从文本中提取最外层 {...} 后解析
    4. 修复尾部逗号后解析
    5. 单引号替换为双引号后解析
    6. 组合修复（尾部逗号 + 单引号）后解析

    :param text: LLM 原始输出文本
    :param default: 解析失败时返回的默认值（None 则返回空 dict）
    :return: 解析后的 dict
    """
    if default is None:
        default = {}

    if not text or not isinstance(text, str):
        return default

    content = text.strip()

    # 阶段1: 预处理（提取纯 JSON 文本）
    # 尝试多种方式提取 JSON 候选文本
    candidates = []
    # 直接原文
    candidates.append(("原文", content))
    # 去 markdown 代码块
    stripped = _strip_markdown_code_block(content)
    if stripped and stripped != content:
        candidates.append(("去 markdown", stripped))
    # 提取最外层 JSON 对象
    extracted = _extract_json_object(content)
    if extracted and extracted not in [c[1] for c in candidates]:
        candidates.append(("提取对象", extracted))
    # 去 markdown 后提取
    if stripped:
        extracted2 = _extract_json_object(stripped)
        if extracted2 and extracted2 not in [c[1] for c in candidates]:
            candidates.append(("去md+提取", extracted2))

    # 阶段2: 对每个候选文本，尝试直接解析 + 修复
    repair_funcs = [
        ("无修复", lambda s: s),
        ("修复尾部逗号", _fix_trailing_commas),
        ("单引号替换", _fix_single_quotes),
        ("尾部逗号+单引号", lambda s: _fix_trailing_commas(_fix_single_quotes(s))),
    ]

    for cand_label, candidate_text in candidates:
        if not candidate_text:
            continue
        for repair_label, repair_fn in repair_funcs:
            try:
                repaired = repair_fn(candidate_text)
                if repaired is None:
                    continue
                result = json.loads(repaired)
                if isinstance(result, dict):
                    logger.debug(
                        f"JSON 解析成功（{cand_label} + {repair_label}）"
                    )
                    return result
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

    logger.warning(f"所有 JSON 解析策略均失败，原文前 200 字符: {content[:200]}")
    return default


def _strip_markdown_code_block(text: str) -> Optional[str]:
    """去除 markdown 代码块标记 """
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```\s*$', '', text)
        return text.strip()
    return text


def _extract_json_object(text: str) -> Optional[str]:
    """从文本中提取最外层的 {...} JSON 对象"""
    # 找到第一个 { 和最后一个 }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return None


def _fix_trailing_commas(text: str) -> Optional[str]:
    """
    修复 JSON 中不合法的尾部逗号：
    - {"key": "value",} → {"key": "value"}
    - [1, 2,] → [1, 2]
    - {"key": "value",\n} → {"key": "value"\n}
    """
    if not re.search(r',\s*[}\]]', text):
        return text  # 没有尾部逗号，直接返回原文
    # 移除 } 或 ] 前的逗号
    fixed = re.sub(r',\s*([}\]])', r'\1', text)
    return fixed


def _fix_single_quotes(text: str) -> Optional[str]:
    """
    将 JSON 中的单引号替换为双引号（仅处理 key 和 string value 的单引号）。
    使用简单启发式：将模式 'key': 和 : 'value' 中的单引号替换为双引号。
    """
    if "'" not in text:
        return text

    # 策略：将单引号包裹的 JSON key 和 string value 替换为双引号
    # 更安全的方法：逐字符遍历，只替换 JSON 上下文中的单引号
    result = []
    i = 0
    in_string = False
    string_char = None
    while i < len(text):
        ch = text[i]
        if not in_string:
            if ch in ('"', "'"):
                in_string = True
                string_char = ch
                result.append('"')  # 统一输出双引号
            else:
                result.append(ch)
        else:
            if ch == '\\' and i + 1 < len(text):
                # 转义字符：保留
                result.append(ch)
                i += 1
                result.append(text[i])
            elif ch == string_char:
                in_string = False
                string_char = None
                result.append('"')  # 闭合也用双引号
            elif ch == '"':
                # 单引号字符串内的双引号需要转义
                if string_char == "'":
                    result.append('\\"')
                else:
                    result.append(ch)
            else:
                result.append(ch)
        i += 1

    return ''.join(result)
