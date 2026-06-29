"""
Prometheus 指标采集模块

使用 prometheus_client 标准指标，支持多 Worker 模式（multiprocess）。
- 请求计数（Counter，按路径、方法、状态码）
- 请求延迟（Histogram）
- 活跃请求数（Gauge）
- 聊天消息计数（Counter）
- LLM 调用计数（Counter）
"""
import time
from contextvars import ContextVar

from prometheus_client import Counter, Gauge, Histogram, generate_latest

# 请求开始时间（ContextVar，用于计算延迟）
_request_start_time: ContextVar[float] = ContextVar("request_start_time")

# ─── Prometheus 标准指标定义 ─────────────────────────────────────────────

# 请求计数：按 method, path, status 维度
_request_count = Counter(
    "kefu_requests_total",
    "HTTP 请求总数（按 method, path, status）",
    ["method", "path", "status"],
)

# 请求延迟直方图
_request_duration = Histogram(
    "kefu_request_duration_ms",
    "请求延迟（毫秒）",
    ["method", "path"],
    buckets=(10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)

# 当前活跃请求数
_active_requests = Gauge(
    "kefu_active_requests",
    "当前活跃请求数",
)

# 聊天消息计数
_chat_message_count = Counter(
    "kefu_chat_messages_total",
    "聊天消息总数",
)

# LLM 调用计数：按 node_name 维度
_llm_call_count = Counter(
    "kefu_llm_calls_total",
    "LLM 调用次数（按节点）",
    ["node"],
)

# 错误计数：按 error_type 维度
_error_count = Counter(
    "kefu_errors_total",
    "错误次数（按类型）",
    ["type"],
)

# 缓存命中/未命中计数
_cache_count = Counter(
    "kefu_cache_total",
    "缓存命中计数",
    ["result"],
)

# 检索结果计数
_retrieval_count = Counter(
    "kefu_retrieval_total",
    "检索结果计数",
    ["result"],
)

# 转人工计数
_handoff_count = Counter(
    "kefu_handoff_total",
    "转人工次数",
)

# 请求处理耗时计数
_timing_count = Counter(
    "kefu_timing_total",
    "请求处理耗时计数",
    ["intent"],
)

# A/B 测试分桶计数
_ab_variant_count = Counter(
    "kefu_ab_test_total",
    "A/B 测试分桶命中次数",
    ["variant"],
)

# 启动时间
_start_time = time.time()

# 运行时间 Gauge
_uptime_gauge = Gauge(
    "kefu_uptime_seconds",
    "服务运行时间（秒）",
)


# ─── 采集函数（在中间件/业务代码中调用） ────────────────────────────────


def mark_request_start():
    """标记请求开始时间"""
    _request_start_time.set(time.time())


def _get_request_latency_ms() -> float:
    """获取当前请求的延迟（毫秒）"""
    start = _request_start_time.get(0)
    return (time.time() - start) * 1000 if start > 0 else 0


def record_request(method: str, path: str, status_code: int, latency_ms: float):
    """
    记录一次 HTTP 请求

    :param method: HTTP 方法
    :param path: 请求路径
    :param status_code: 响应状态码
    :param latency_ms: 请求延迟（毫秒）
    """
    _request_count.labels(method=method, path=path, status=str(status_code)).inc()
    _request_duration.labels(method=method, path=path).observe(latency_ms)


def increment_active():
    """活跃请求数 +1"""
    _active_requests.inc()


def decrement_active():
    """活跃请求数 -1"""
    _active_requests.dec()


def record_chat_message():
    """记录一条聊天消息"""
    _chat_message_count.inc()


def record_llm_call(node_name: str):
    """
    记录一次 LLM 调用

    :param node_name: 节点名称
    """
    _llm_call_count.labels(node=node_name).inc()


def record_error(error_type: str):
    """
    记录一次错误

    :param error_type: 错误类型
    """
    _error_count.labels(type=error_type).inc()


def record_cache(hit: bool):
    """
    记录缓存命中/未命中

    :param hit: 是否命中
    """
    _cache_count.labels(result="hit" if hit else "miss").inc()


def record_retrieval(has_results: bool):
    """
    记录检索结果

    :param has_results: 是否有检索结果
    """
    _retrieval_count.labels(result="found" if has_results else "empty").inc()


def record_handoff():
    """记录转人工次数"""
    _handoff_count.inc()


def record_request_timing(elapsed: float, intent: str = ""):
    """
    记录意图分类耗时及计数

    :param elapsed: 耗时（秒），预留用于未来 Histogram 指标
    :param intent: 意图名称（如 order_query/history_order），空值记为 total
    """
    # 当前仅计数，elapsed 预留用于后续改为 Histogram 时按 intent 分桶记录实际耗时
    _ = elapsed  # 标记为有意未使用，避免 linter 告警
    _timing_count.labels(intent=intent if intent else "total").inc()


def record_ab_variant(variant: str):
    """
    记录 A/B 测试分桶命中

    :param variant: 分桶名称（如 v1/v2/v3）
    """
    _ab_variant_count.labels(variant=variant).inc()


# ─── Prometheus 格式输出 ──────────────────────────────────────────────────


def get_metrics_text() -> str:
    """
    生成 Prometheus 格式的指标文本

    使用 prometheus_client.generate_latest() 生成标准输出，
    额外注入 uptime 指标。

    :return: Prometheus 格式的指标字符串
    """
    # 更新 uptime gauge
    _uptime_gauge.set(time.time() - _start_time)
    return generate_latest().decode("utf-8")
