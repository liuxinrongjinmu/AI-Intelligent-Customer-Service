import os
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
DEEPSEEK_MODEL = LLM_MODEL
LLM_TEMPERATURE_CLASSIFY = float(os.getenv("LLM_TEMPERATURE_CLASSIFY", "0.0"))
LLM_TEMPERATURE_GENERATE = float(os.getenv("LLM_TEMPERATURE_GENERATE", "0.7"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")

SQLITE_PATH = os.getenv("SQLITE_PATH", "data/app.db")
CHROMA_PATH = os.getenv("CHROMA_PATH", "data/chroma_db")
CHECKPOINT_PATH = os.getenv("CHECKPOINT_PATH", "data/checkpoints.db")

RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))
RETRIEVAL_THRESHOLD = float(os.getenv("RETRIEVAL_THRESHOLD", "0.2"))
MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "10"))
DOC_CHUNK_SIZE = int(os.getenv("DOC_CHUNK_SIZE", "800"))
DOC_CHUNK_OVERLAP = int(os.getenv("DOC_CHUNK_OVERLAP", "100"))

# Token 预算管理配置
# 总上下文窗口预算（不含模型响应），DeepSeek 支持 64K，留足余量
CONTEXT_TOTAL_BUDGET = int(os.getenv("CONTEXT_TOTAL_BUDGET", "8000"))
# 各分区预算分配
SYSTEM_PROMPT_BUDGET = int(os.getenv("SYSTEM_PROMPT_BUDGET", "1500"))
HISTORY_MESSAGE_BUDGET = int(os.getenv("HISTORY_MESSAGE_BUDGET", "2500"))
KNOWLEDGE_CONTEXT_BUDGET = int(os.getenv("KNOWLEDGE_CONTEXT_BUDGET", "2500"))
# 响应预留 token（不计入上下文总预算，由 LLM max_tokens 控制）
RESPONSE_RESERVED_TOKENS = int(os.getenv("RESPONSE_RESERVED_TOKENS", "2048"))
# 历史格式化时的最大轮数回退（token 估算失败时使用）
HISTORY_MAX_TURNS_FALLBACK = int(os.getenv("HISTORY_MAX_TURNS_FALLBACK", "6"))

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8081"))

# Swagger UI 服务器地址（用于内网联调时 "Try it out" 功能生成正确的请求 URL）
SWAGGER_SERVER_URL: str = os.getenv("SWAGGER_SERVER_URL", f"http://192.168.0.234:{PORT}")

# 管理接口认证密钥（仅管理接口使用，服务间接口走 Gateway 认证）
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "change-me-admin-key")

# ==================== Gateway 认证配置 ====================
# 所有服务间接口（聊天/同步/统计）统一通过内网 VPN + Gateway 认证
# Gateway 会在转发请求时注入验证头，我方校验该头 + 来源 IP 白名单
GATEWAY_VERIFIED_HEADER: str = os.getenv("GATEWAY_VERIFIED_HEADER", "X-Gateway-Verified")
GATEWAY_VERIFIED_VALUE: str = os.getenv("GATEWAY_VERIFIED_VALUE", "true")
# Gateway / VPN 网段 IP 白名单（逗号分隔，必须根据实际部署环境精确配置）
# 默认值覆盖常见内网段，上线前请缩小为 Gateway 所在的具体网段
GATEWAY_IP_WHITELIST: str = os.getenv("GATEWAY_IP_WHITELIST", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16")

# ==================== Nacos 服务注册与发现 ====================
# Nacos 服务端地址（多个用逗号分隔）
NACOS_SERVER_ADDR: str = os.getenv("NACOS_SERVER_ADDR", "127.0.0.1:8848")
# 命名空间 ID（需与聚宝赞端确认）
NACOS_NAMESPACE: str = os.getenv("NACOS_NAMESPACE", "")
# 分组名称（需与 Java 端 spring.cloud.nacos.discovery.group 一致）
NACOS_GROUP: str = os.getenv("NACOS_GROUP", "DEFAULT_GROUP")
# 认证信息（若 Nacos 启用认证）
NACOS_USERNAME: str = os.getenv("NACOS_USERNAME", "")
NACOS_PASSWORD: str = os.getenv("NACOS_PASSWORD", "")
# 我方服务注册信息
SERVICE_IP: str = os.getenv("SERVICE_IP", "")  # 留空则自动获取本机 IP
SERVICE_PORT: int = int(os.getenv("SERVICE_PORT", str(PORT)))

# ==================== 聚宝赞业务 API 超时配置 ====================
ORDER_API_TIMEOUT = int(os.getenv("ORDER_API_TIMEOUT", "10"))
LOGISTICS_API_TIMEOUT = int(os.getenv("LOGISTICS_API_TIMEOUT", "10"))
PRODUCT_API_TIMEOUT = int(os.getenv("PRODUCT_API_TIMEOUT", "10"))
REFUND_API_TIMEOUT = int(os.getenv("REFUND_API_TIMEOUT", "10"))
COUPON_API_TIMEOUT = int(os.getenv("COUPON_API_TIMEOUT", "10"))
USER_PROFILE_API_TIMEOUT = int(os.getenv("USER_PROFILE_API_TIMEOUT", "10"))

# ==================== 聚宝赞端 Nacos 服务名（所有业务 API 调用均通过 Nacos 服务发现） ====================
# 所有 ext-merchant API 部署在同一个服务上，统一使用一个服务名
MERCHANT_SERVICE_NAME: str = os.getenv("MERCHANT_SERVICE_NAME", "merchant-service")
# 以下保留向后兼容，实际均指向 MERCHANT_SERVICE_NAME
ORDER_SERVICE_NAME: str = os.getenv("ORDER_SERVICE_NAME", MERCHANT_SERVICE_NAME)
PRODUCT_SERVICE_NAME: str = os.getenv("PRODUCT_SERVICE_NAME", MERCHANT_SERVICE_NAME)
LOGISTICS_SERVICE_NAME: str = os.getenv("LOGISTICS_SERVICE_NAME", MERCHANT_SERVICE_NAME)
REFUND_SERVICE_NAME: str = os.getenv("REFUND_SERVICE_NAME", MERCHANT_SERVICE_NAME)
COUPON_SERVICE_NAME: str = os.getenv("COUPON_SERVICE_NAME", MERCHANT_SERVICE_NAME)
USER_PROFILE_SERVICE_NAME: str = os.getenv("USER_PROFILE_SERVICE_NAME", MERCHANT_SERVICE_NAME)

def validate_config():
    """配置校验"""
    warnings = []
    errors = []
    if not DEEPSEEK_API_KEY:
        errors.append("DEEPSEEK_API_KEY 未配置")
    if not GATEWAY_IP_WHITELIST:
        warnings.append("建议配置 GATEWAY_IP_WHITELIST（Gateway/VPN 网段白名单）")
    if GATEWAY_IP_WHITELIST == "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16":
        warnings.append("GATEWAY_IP_WHITELIST 使用默认值（覆盖所有内网段），生产环境建议缩小为 Gateway 所在的具体网段")
    if not ADMIN_API_KEY:
        warnings.append("ADMIN_API_KEY 未配置，管理接口将无法使用")
    return warnings, errors