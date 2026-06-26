"""
配置管理：所有配置项从环境变量加载，提供模块级变量访问

使用方式：from backend.config import DEEPSEEK_API_KEY, DATABASE_URL, ...
启动时调用 validate_config() 进行完整校验
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ─── 安全类型转换工具 ───────────────────────────────────────────


def _safe_int(name: str, default: int) -> int:
    """安全读取整型环境变量，非数字值时用默认值并告警"""
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.warning(f"配置 {name}={raw!r} 不是有效整数，使用默认值 {default}")
        return default


def _safe_float(name: str, default: float) -> float:
    """安全读取浮点环境变量，非数字值时用默认值并告警"""
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.warning(f"配置 {name}={raw!r} 不是有效浮点数，使用默认值 {default}")
        return default


# ─── 运行环境 ────────────────────────────────────────────────────

ENV = os.getenv("ENV", "dev")

# ─── LLM 配置 ─────────────────────────────────────────────────────

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
DEEPSEEK_MODEL = LLM_MODEL  # 向后兼容别名
LLM_TEMPERATURE_CLASSIFY = _safe_float("LLM_TEMPERATURE_CLASSIFY", 0.0)
LLM_TEMPERATURE_GENERATE = _safe_float("LLM_TEMPERATURE_GENERATE", 0.7)
LLM_MAX_TOKENS = _safe_int("LLM_MAX_TOKENS", 2048)

# ─── Embedding 模型配置 ───────────────────────────────────────────

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")

# ─── 存储路径 ─────────────────────────────────────────────────────

CHROMA_PATH = os.getenv("CHROMA_PATH", "data/chroma_db")
DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()

# ─── 检索参数 ─────────────────────────────────────────────────────

RETRIEVAL_TOP_K = _safe_int("RETRIEVAL_TOP_K", 5)
RETRIEVAL_THRESHOLD = _safe_float("RETRIEVAL_THRESHOLD", 0.2)
MAX_HISTORY_TURNS = _safe_int("MAX_HISTORY_TURNS", 10)
DOC_CHUNK_SIZE = _safe_int("DOC_CHUNK_SIZE", 800)
DOC_CHUNK_OVERLAP = _safe_int("DOC_CHUNK_OVERLAP", 100)

# ─── Token 预算管理 ──────────────────────────────────────────────

CONTEXT_TOTAL_BUDGET = _safe_int("CONTEXT_TOTAL_BUDGET", 8000)
SYSTEM_PROMPT_BUDGET = _safe_int("SYSTEM_PROMPT_BUDGET", 1500)
HISTORY_MESSAGE_BUDGET = _safe_int("HISTORY_MESSAGE_BUDGET", 2500)
KNOWLEDGE_CONTEXT_BUDGET = _safe_int("KNOWLEDGE_CONTEXT_BUDGET", 2500)
RESPONSE_RESERVED_TOKENS = _safe_int("RESPONSE_RESERVED_TOKENS", 2048)
HISTORY_MAX_TURNS_FALLBACK = _safe_int("HISTORY_MAX_TURNS_FALLBACK", 6)

# ─── 服务配置 ─────────────────────────────────────────────────────

HOST = os.getenv("HOST", "127.0.0.1")
PORT = _safe_int("PORT", 8081)
SWAGGER_SERVER_URL: str = os.getenv("SWAGGER_SERVER_URL", "")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "change-me-admin-key")

# ─── Gateway 认证配置 ────────────────────────────────────────────

GATEWAY_VERIFIED_HEADER: str = os.getenv(
    "GATEWAY_VERIFIED_HEADER", "X-Gateway-Verified"
)
GATEWAY_VERIFIED_VALUE: str = os.getenv("GATEWAY_VERIFIED_VALUE", "")
GATEWAY_IP_WHITELIST: str = os.getenv(
    "GATEWAY_IP_WHITELIST", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
)

# ─── Nacos 服务注册与发现 ────────────────────────────────────────

NACOS_SERVER_ADDR: str = os.getenv("NACOS_SERVER_ADDR", "127.0.0.1:8848")
NACOS_NAMESPACE: str = os.getenv("NACOS_NAMESPACE", "")
NACOS_GROUP: str = os.getenv("NACOS_GROUP", "DEFAULT_GROUP")
NACOS_USERNAME: str = os.getenv("NACOS_USERNAME", "")
NACOS_PASSWORD: str = os.getenv("NACOS_PASSWORD", "")
SERVICE_IP: str = os.getenv("SERVICE_IP", "")
SERVICE_PORT: int = _safe_int("SERVICE_PORT", PORT)

# ─── 业务 API 超时配置 ───────────────────────────────────────────

ORDER_API_TIMEOUT = _safe_int("ORDER_API_TIMEOUT", 10)
LOGISTICS_API_TIMEOUT = _safe_int("LOGISTICS_API_TIMEOUT", 10)
PRODUCT_API_TIMEOUT = _safe_int("PRODUCT_API_TIMEOUT", 10)
COUPON_API_TIMEOUT = _safe_int("COUPON_API_TIMEOUT", 10)
USER_PROFILE_API_TIMEOUT = _safe_int("USER_PROFILE_API_TIMEOUT", 10)

# ─── Nacos 服务名映射 ────────────────────────────────────────────

MERCHANT_SERVICE_NAME: str = os.getenv("MERCHANT_SERVICE_NAME", "merchant-service")
ORDER_SERVICE_NAME: str = os.getenv("ORDER_SERVICE_NAME", MERCHANT_SERVICE_NAME)
PRODUCT_SERVICE_NAME: str = os.getenv("PRODUCT_SERVICE_NAME", MERCHANT_SERVICE_NAME)
LOGISTICS_SERVICE_NAME: str = os.getenv("LOGISTICS_SERVICE_NAME", MERCHANT_SERVICE_NAME)
COUPON_SERVICE_NAME: str = os.getenv("COUPON_SERVICE_NAME", MERCHANT_SERVICE_NAME)
USER_PROFILE_SERVICE_NAME: str = os.getenv(
    "USER_PROFILE_SERVICE_NAME", MERCHANT_SERVICE_NAME
)
TENANT_ID_MAP: str = os.getenv("TENANT_ID_MAP", "")

# ─── Redis 配置 ──────────────────────────────────────────────────

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
RATE_LIMIT_WINDOW: int = _safe_int("RATE_LIMIT_WINDOW", 60)


# ─── 配置校验 ────────────────────────────────────────────────────


def validate_config():
    """
    启动时配置校验，返回 (warnings, errors)。

    校验规则：
    - errors：阻断启动的致命错误（缺少必填项、生产环境弱凭证）
    - warnings：建议修复但不阻断启动的问题
    """
    warnings = []
    errors = []

    # 必填项检查
    if not DATABASE_URL:
        errors.append("DATABASE_URL 未配置，PostgreSQL 连接串为必填项")
    if not DEEPSEEK_API_KEY:
        errors.append("DEEPSEEK_API_KEY 未配置，LLM 调用将全部失败")

    # Gateway 安全
    if not GATEWAY_IP_WHITELIST:
        warnings.append("建议配置 GATEWAY_IP_WHITELIST（Gateway/VPN 网段白名单）")
    if GATEWAY_IP_WHITELIST == "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16":
        warnings.append(
            "GATEWAY_IP_WHITELIST 使用默认值（覆盖所有内网段），"
            "生产环境建议缩小为 Gateway 所在的具体网段"
        )

    # Admin API Key
    if not ADMIN_API_KEY or ADMIN_API_KEY == "change-me-admin-key":
        if ENV == "prod":
            errors.append(
                "ADMIN_API_KEY 使用默认弱密钥 'change-me-admin-key'，生产环境拒绝启动。"
                "请设置高强度随机密钥：python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        else:
            warnings.append(
                "ADMIN_API_KEY 使用默认弱密钥，生产环境必须修改为高强度随机值"
            )

    # Gateway 验证令牌
    if not GATEWAY_VERIFIED_VALUE:
        if ENV == "prod":
            errors.append(
                "GATEWAY_VERIFIED_VALUE 未配置，生产环境拒绝启动。"
                "请与聚宝赞端协商设置唯一令牌"
            )
        else:
            warnings.append("GATEWAY_VERIFIED_VALUE 未配置，生产环境必须设置")
    elif GATEWAY_VERIFIED_VALUE.lower() == "true":
        warnings.append(
            "GATEWAY_VERIFIED_VALUE 使用弱默认值 'true'，"
            "生产环境必须修改为不可猜测的随机值"
        )

    # Token 预算合理性
    total_allocated = (
        SYSTEM_PROMPT_BUDGET + HISTORY_MESSAGE_BUDGET
        + KNOWLEDGE_CONTEXT_BUDGET + RESPONSE_RESERVED_TOKENS
    )
    if total_allocated > 65536:  # DeepSeek 64K 上下文
        warnings.append(
            f"Token 预算总和 ({total_allocated}) 超过 DeepSeek 64K 上下文限制，"
            "LLM 调用可能被截断"
        )

    return warnings, errors
