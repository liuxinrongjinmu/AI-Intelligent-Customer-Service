"""
配置管理：基于 Pydantic Settings 的类型安全配置

所有配置项通过 Settings 类定义（自动从环境变量 / .env 文件加载），
然后以模块级变量形式重新导出，保持 import 兼容性。

使用方式：
    from backend.config import DEEPSEEK_API_KEY, DATABASE_URL, ...
    from backend.config import settings          # 获取完整 Settings 对象
    from backend.config import validate_config    # 启动时校验
"""
import logging
from typing import Optional, Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """应用配置（Pydantic Settings，自动从 .env / 环境变量加载）"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ─── 运行环境 ────────────────────────────────────────────────
    env: Literal["dev", "test", "prod"] = Field(default="dev", description="运行环境")

    # ─── LLM 配置 ─────────────────────────────────────────────────
    deepseek_api_key: str = Field(default="", description="DeepSeek API 密钥（必填）")
    deepseek_base_url: str = Field(default="https://api.deepseek.com")
    llm_model: str = Field(default="deepseek-chat", description="LLM 模型名称")
    llm_temperature_classify: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_temperature_generate: float = Field(default=0.7, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=2048, ge=1, le=65536)

    # ─── Embedding 模型 ───────────────────────────────────────────
    embedding_model: str = Field(default="BAAI/bge-small-zh-v1.5")
    embedding_device: str = Field(default="cpu")
    hf_endpoint: str = Field(default="https://hf-mirror.com")

    # ─── 存储路径 ─────────────────────────────────────────────────
    chroma_path: str = Field(default="data/chroma_db")
    database_url: str = Field(default="", description="PostgreSQL 连接串（必填）")

    # ─── 检索参数 ─────────────────────────────────────────────────
    retrieval_top_k: int = Field(default=5, ge=1, le=100)
    retrieval_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    max_history_turns: int = Field(default=10, ge=1, le=50)
    doc_chunk_size: int = Field(default=800, ge=100, le=10000)
    doc_chunk_overlap: int = Field(default=100, ge=0, le=1000)

    # ─── Token 预算 ───────────────────────────────────────────────
    context_total_budget: int = Field(default=8000, ge=1000, le=128000)
    system_prompt_budget: int = Field(default=1500, ge=100, le=32000)
    history_message_budget: int = Field(default=2500, ge=100, le=32000)
    knowledge_context_budget: int = Field(default=2500, ge=100, le=32000)
    response_reserved_tokens: int = Field(default=2048, ge=128, le=32768)
    history_max_turns_fallback: int = Field(default=6, ge=1, le=50)

    # ─── 服务配置 ─────────────────────────────────────────────────
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8081, ge=1, le=65535)
    swagger_server_url: str = Field(default="")
    enable_docs: bool = Field(default=True)
    admin_api_key: str = Field(default="change-me-admin-key")
    allowed_origins: str = Field(default="", description="CORS 允许域名（逗号分隔）")
    workers: int = Field(default=1, ge=1, le=16)

    # ─── Gateway 认证 ─────────────────────────────────────────────
    # 认证模式：jwt（JWT 验签）/ static（静态令牌）/ both（兼容两种）
    gateway_auth_mode: str = Field(default="both")
    # JWT 签名密钥（HS256），可从 Nacos 配置 jwt.secret 获取，也可直接配置
    jwt_secret: str = Field(default="")
    # 是否信任 Gateway 注入的身份 Header（X-Tenant-Id / X-Buyer-Id 等）
    gateway_trust_headers: bool = Field(default=True)
    # 静态令牌模式（兼容旧版）
    gateway_verified_header: str = Field(default="X-Gateway-Verified")
    gateway_verified_value: str = Field(default="")
    gateway_ip_whitelist: str = Field(
        default="10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    )

    # ─── Nacos ────────────────────────────────────────────────────
    nacos_server_addr: str = Field(default="127.0.0.1:8848")
    nacos_namespace: str = Field(default="")
    nacos_group: str = Field(default="DEFAULT_GROUP")
    nacos_username: str = Field(default="")
    nacos_password: str = Field(default="")
    service_ip: str = Field(default="")
    service_port: int = Field(default=8081, ge=1, le=65535)

    # ─── 业务 API 超时（秒）──────────────────────────────────────
    order_api_timeout: int = Field(default=10, ge=1, le=120)
    logistics_api_timeout: int = Field(default=10, ge=1, le=120)
    product_api_timeout: int = Field(default=10, ge=1, le=120)
    coupon_api_timeout: int = Field(default=10, ge=1, le=120)
    user_profile_api_timeout: int = Field(default=10, ge=1, le=120)

    # ─── Nacos 服务名 ─────────────────────────────────────────────
    merchant_service_name: str = Field(default="tenant-service")
    order_service_name: str = Field(default="")
    product_service_name: str = Field(default="")
    logistics_service_name: str = Field(default="")
    coupon_service_name: str = Field(default="")
    user_profile_service_name: str = Field(default="")
    tenant_id_map: str = Field(default="")

    # ─── Redis ────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_password: str = Field(default="")
    rate_limit_window: int = Field(default=60, ge=10, le=3600)

    # ─── Agent 行为阈值 ──────────────────────────────────────────
    # AI连续识别失败多少次后自动转人工（避免无限循环）
    ai_failed_threshold: int = Field(default=2, ge=1, le=10)
    # AI回答最短长度（字符），低于此值不缓存
    min_answer_length_cache: int = Field(default=10, ge=1, le=100)
    # 请求体最大大小（字节），可通过 MAX_BODY_SIZE 环境变量覆盖
    max_body_size: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    # SSE 流式连接总超时（秒）
    sse_total_timeout: int = Field(default=120, ge=30, le=600)
    # 知识库同步单批最大条目数
    max_sync_batch_size: int = Field(default=1000, ge=1, le=10000)
    # 用户消息最大长度（字符）
    max_message_length: int = Field(default=4000, ge=100, le=50000)

    # ─── 缓存容量 ──────────────────────────────────────────────────
    intent_cache_max_size: int = Field(default=500, ge=50, le=10000)
    answer_cache_max_size: int = Field(default=200, ge=50, le=10000)
    embed_cache_max_size: int = Field(default=1000, ge=100, le=50000)


# ─── 全局单例 ────────────────────────────────────────────────────


def _load_jwt_secret_from_nacos() -> str:
    """
    尝试从 Nacos 读取 jwt.secret（gateway-service.yaml）
    失败时返回空字符串，由调用方回退到其他来源
    """
    try:
        from nacos import NacosClient
        client = NacosClient(
            server_addresses=settings.nacos_server_addr,
            namespace=settings.nacos_namespace or "",
            username=settings.nacos_username or None,
            password=settings.nacos_password or None,
        )
        config = client.get_config(
            data_id="gateway-service.yaml",
            group=settings.nacos_group or "DEFAULT_GROUP",
            timeout=5,
        )
        if config:
            # gateway-service.yaml 是 YAML 格式，简单解析 jwt.secret
            for line in config.split("\n"):
                line = line.strip()
                if line.startswith("jwt.secret:") or line.startswith("jwt.secret="):
                    secret = line.split(":", 1)[-1].strip() if ":" in line else line.split("=", 1)[-1].strip()
                    if secret and secret != '""':
                        logger.info("已从 Nacos gateway-service.yaml 加载 jwt.secret")
                        return secret
    except Exception as e:
        logger.debug(f"从 Nacos 读取 jwt.secret 失败（将使用 JWT_SECRET 环境变量）: {e}")
    return ""


def _init_settings() -> Settings:
    """延迟初始化 Settings，捕获错误并友好提示"""
    try:
        return Settings()
    except Exception as e:
        logger.error(f"配置加载失败: {e}")
        raise RuntimeError(f"无法加载配置，请检查 .env 文件: {e}") from e


# ─── JWT 密钥加载（优先级：Nacos > 环境变量 > 开发默认密钥）───────────────

_DEV_JWT_SECRET = "default-secret-key-for-local-development-256-bits!"


def _resolve_jwt_secret() -> str:
    """按优先级解析 JWT 签名密钥"""
    # 1. 环境变量显式配置
    if settings.jwt_secret and settings.jwt_secret != _DEV_JWT_SECRET:
        return settings.jwt_secret

    # 2. 尝试从 Nacos 读取
    nacos_secret = _load_jwt_secret_from_nacos()
    if nacos_secret:
        return nacos_secret

    # 3. 开发环境使用默认密钥
    if settings.env != "prod":
        logger.warning(f"JWT_SECRET 未配置，使用开发默认密钥（仅限非生产环境）")
        return _DEV_JWT_SECRET

    # 4. 生产环境无密钥 → 留空（启动时 validate_config 会报错）
    return ""


settings = _init_settings()
_JWT_SECRET_RESOLVED = _resolve_jwt_secret()


# ─── 向后兼容：模块级变量重导出 ──────────────────────────────────

ENV: str = settings.env

DEEPSEEK_API_KEY: str = settings.deepseek_api_key
DEEPSEEK_BASE_URL: str = settings.deepseek_base_url
LLM_MODEL: str = settings.llm_model
DEEPSEEK_MODEL: str = settings.llm_model  # 别名
LLM_TEMPERATURE_CLASSIFY: float = settings.llm_temperature_classify
LLM_TEMPERATURE_GENERATE: float = settings.llm_temperature_generate
LLM_MAX_TOKENS: int = settings.llm_max_tokens

EMBEDDING_MODEL: str = settings.embedding_model
EMBEDDING_DEVICE: str = settings.embedding_device
HF_ENDPOINT: str = settings.hf_endpoint

CHROMA_PATH: str = settings.chroma_path
DATABASE_URL: str = settings.database_url

RETRIEVAL_TOP_K: int = settings.retrieval_top_k
RETRIEVAL_THRESHOLD: float = settings.retrieval_threshold
MAX_HISTORY_TURNS: int = settings.max_history_turns
DOC_CHUNK_SIZE: int = settings.doc_chunk_size
DOC_CHUNK_OVERLAP: int = settings.doc_chunk_overlap

CONTEXT_TOTAL_BUDGET: int = settings.context_total_budget
SYSTEM_PROMPT_BUDGET: int = settings.system_prompt_budget
HISTORY_MESSAGE_BUDGET: int = settings.history_message_budget
KNOWLEDGE_CONTEXT_BUDGET: int = settings.knowledge_context_budget
RESPONSE_RESERVED_TOKENS: int = settings.response_reserved_tokens
HISTORY_MAX_TURNS_FALLBACK: int = settings.history_max_turns_fallback

HOST: str = settings.host
PORT: int = settings.port
SWAGGER_SERVER_URL: str = settings.swagger_server_url
ADMIN_API_KEY: str = settings.admin_api_key
ALLOWED_ORIGINS: str = settings.allowed_origins
ENABLE_DOCS: bool = settings.enable_docs
WORKERS: int = settings.workers

GATEWAY_AUTH_MODE: str = settings.gateway_auth_mode
JWT_SECRET: str = _JWT_SECRET_RESOLVED
JWT_SECRET_RAW: str = settings.jwt_secret  # 环境变量原始值（不含 Nacos/默认解析）
GATEWAY_TRUST_HEADERS: bool = settings.gateway_trust_headers
GATEWAY_VERIFIED_HEADER: str = settings.gateway_verified_header
GATEWAY_VERIFIED_VALUE: str = settings.gateway_verified_value
GATEWAY_IP_WHITELIST: str = settings.gateway_ip_whitelist

NACOS_SERVER_ADDR: str = settings.nacos_server_addr
NACOS_NAMESPACE: str = settings.nacos_namespace
NACOS_GROUP: str = settings.nacos_group
NACOS_USERNAME: str = settings.nacos_username
NACOS_PASSWORD: str = settings.nacos_password
SERVICE_IP: str = settings.service_ip
SERVICE_PORT: int = settings.service_port

ORDER_API_TIMEOUT: int = settings.order_api_timeout
LOGISTICS_API_TIMEOUT: int = settings.logistics_api_timeout
PRODUCT_API_TIMEOUT: int = settings.product_api_timeout
COUPON_API_TIMEOUT: int = settings.coupon_api_timeout
USER_PROFILE_API_TIMEOUT: int = settings.user_profile_api_timeout

MERCHANT_SERVICE_NAME: str = settings.merchant_service_name
ORDER_SERVICE_NAME: str = settings.order_service_name or settings.merchant_service_name
PRODUCT_SERVICE_NAME: str = settings.product_service_name or settings.merchant_service_name
LOGISTICS_SERVICE_NAME: str = settings.logistics_service_name or settings.merchant_service_name
COUPON_SERVICE_NAME: str = settings.coupon_service_name or settings.merchant_service_name
USER_PROFILE_SERVICE_NAME: str = settings.user_profile_service_name or settings.merchant_service_name
TENANT_ID_MAP: str = settings.tenant_id_map

REDIS_URL: str = settings.redis_url
REDIS_PASSWORD: str = settings.redis_password
RATE_LIMIT_WINDOW: int = settings.rate_limit_window

# ─── Agent 行为阈值 ─────────────────────────────────────────
AI_FAILED_THRESHOLD: int = settings.ai_failed_threshold
MIN_ANSWER_LENGTH_CACHE: int = settings.min_answer_length_cache
MAX_BODY_SIZE: int = settings.max_body_size
SSE_TOTAL_TIMEOUT: int = settings.sse_total_timeout
MAX_SYNC_BATCH_SIZE: int = settings.max_sync_batch_size
MAX_MESSAGE_LENGTH: int = settings.max_message_length

# ─── 缓存容量 ────────────────────────────────────────────────
INTENT_CACHE_MAX_SIZE: int = settings.intent_cache_max_size
ANSWER_CACHE_MAX_SIZE: int = settings.answer_cache_max_size
EMBED_CACHE_MAX_SIZE: int = settings.embed_cache_max_size


# ─── 校验函数 ────────────────────────────────────────────────────


def validate_config():
    """
    启动时配置校验，返回 (warnings, errors)。

    校验规则：
    - errors：阻断启动的致命错误（缺少必填项、生产环境弱凭证）
    - warnings：建议修复但不阻断启动的问题
    """
    warnings = []
    errors = []

    # 必填项
    if not settings.database_url:
        errors.append("DATABASE_URL 未配置，PostgreSQL 连接串为必填项")
    if not settings.deepseek_api_key:
        errors.append("DEEPSEEK_API_KEY 未配置，LLM 调用将全部失败")

    # Gateway 安全
    if settings.gateway_auth_mode in ("jwt", "both") and not _JWT_SECRET_RESOLVED:
        if settings.env == "prod":
            errors.append("JWT_SECRET 未配置（环境变量/Nacos 均无），生产环境 JWT 认证拒绝启动")
        else:
            warnings.append("JWT_SECRET 未配置，JWT 认证将无法验签")
    if not settings.gateway_ip_whitelist:
        warnings.append("建议配置 GATEWAY_IP_WHITELIST")
    if settings.gateway_ip_whitelist == "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16":
        warnings.append(
            "GATEWAY_IP_WHITELIST 使用默认值（覆盖所有内网段），"
            "生产环境建议缩小为 Gateway 实际网段"
        )

    # Admin API Key
    if settings.admin_api_key in ("", "change-me-admin-key"):
        if settings.env == "prod":
            errors.append("ADMIN_API_KEY 使用默认弱密钥，生产环境拒绝启动")
        else:
            warnings.append("ADMIN_API_KEY 使用默认弱密钥，生产环境必须修改")

    # Gateway 令牌
    if not settings.gateway_verified_value:
        if settings.env == "prod":
            errors.append("GATEWAY_VERIFIED_VALUE 未配置，生产环境拒绝启动")
        else:
            warnings.append("GATEWAY_VERIFIED_VALUE 未配置，生产环境必须设置")
    elif settings.gateway_verified_value.lower() == "true":
        warnings.append("GATEWAY_VERIFIED_VALUE 使用弱默认值，生产环境必须修改")

    # Token 预算
    total = (
        settings.system_prompt_budget + settings.history_message_budget
        + settings.knowledge_context_budget + settings.response_reserved_tokens
    )
    if total > 65536:
        warnings.append(f"Token 预算总和 ({total}) 超过 DeepSeek 64K 上下文限制")

    return warnings, errors
