"""
Prometheus 指标采集模块

提供轻量级 Prometheus 指标采集，无需额外依赖。
- 请求计数（按路径、方法、状态码）
- 请求延迟（直方图）
- 活跃请求数
- 聊天消息计数
- LLM 调用计数
"""
import logging
import threading
import time
from collections import defaultdict
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# 请求开始时间（ContextVar，用于计算延迟）
_request_start_time: ContextVar[float] = ContextVar("request_start_time")

# ─── 指标存储 ────────────────────────────────────────────────────────────

_lock = threading.Lock()

# 请求计数：{method:path:status -> count}
_request_count: dict[str, int] = defaultdict(int)

# 请求延迟：{method:path -> [latencies]}
_request_latency: dict[str, list[float]] = defaultdict(list)

# 当前活跃请求数
_active_requests = 0

# 聊天消息计数
_chat_message_count = 0

# LLM 调用计数：{node_name -> count}
_llm_call_count: dict[str, int] = defaultdict(int)

# 错误计数：{error_type -> count}
_error_count: dict[str, int] = defaultdict(int)

# A/B 测试分桶计数：{variant_name -> count}
_ab_variant_count: dict[str, int] = defaultdict(int)

# 启动时间
_start_time = time.time()


# ─── 采集函数（在中间件/业务代码中调用） ────────────────────────────────


def mark_request_start():
    """标记请求开始时间"""
    _request_start_time.set(time.time())


def _get_request_latency_ms() -> float:
    """获取当前请求的延迟（毫秒）"""
    start = _request_start_time.get(0)
    return (time.time() - start) * 1000 if start > 0 else 0


def record_request(method: str, path: str, status_code: int, latency_ms: float):
    """记录一次 HTTP 请求"""
    with _lock:
        key = f"{method}:{path}:{status_code}"
        _request_count[key] += 1

        latency_key = f"{method}:{path}"
        _latencies = _request_latency[latency_key]
        _latencies.append(latency_ms)
        # 只保留最近 1000 个样本
        if len(_latencies) > 1000:
            _request_latency[latency_key] = _latencies[-1000:]


def increment_active():
    """活跃请求数 +1"""
    global _active_requests
    with _lock:
        _active_requests += 1


def decrement_active():
    """活跃请求数 -1"""
    global _active_requests
    with _lock:
        _active_requests = max(0, _active_requests - 1)


def record_chat_message():
    """记录一条聊天消息"""
    global _chat_message_count
    with _lock:
        _chat_message_count += 1


def record_llm_call(node_name: str):
    """记录一次 LLM 调用"""
    with _lock:
        _llm_call_count[node_name] += 1


def record_error(error_type: str):
    """记录一次错误"""
    with _lock:
        _error_count[error_type] += 1


def record_cache(hit: bool):
    """记录缓存命中/未命中"""
    with _lock:
        if hit:
            _request_count["cache:hit"] = _request_count.get("cache:hit", 0) + 1
        else:
            _request_count["cache:miss"] = _request_count.get("cache:miss", 0) + 1


def record_retrieval(has_results: bool):
    """记录检索结果"""
    with _lock:
        if has_results:
            _request_count["retrieval:found"] = _request_count.get("retrieval:found", 0) + 1
        else:
            _request_count["retrieval:empty"] = _request_count.get("retrieval:empty", 0) + 1


def record_handoff():
    """记录转人工次数"""
    with _lock:
        _request_count["handoff:count"] = _request_count.get("handoff:count", 0) + 1


def record_request_timing(elapsed: float, intent: str = ""):
    """记录请求处理耗时"""
    with _lock:
        key = f"timing:intent:{intent}" if intent else "timing:total"
        _request_count[key] = _request_count.get(key, 0) + 1


def record_ab_variant(variant: str):
    """
    记录 A/B 测试分桶命中

    :param variant: 分桶名称（如 v1/v2/v3）
    """
    with _lock:
        _ab_variant_count[variant] += 1


# ─── Prometheus 格式输出 ──────────────────────────────────────────────────


def _compute_latency_stats(latencies: list[float]) -> dict[str, float]:
    """计算延迟统计"""
    if not latencies:
        return {"avg": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0}
    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    return {
        "avg": sum(sorted_lat) / n,
        "p50": sorted_lat[int(n * 0.5)],
        "p95": sorted_lat[int(n * 0.95)],
        "p99": sorted_lat[int(n * 0.99)],
        "max": sorted_lat[-1],
    }


def get_metrics_text() -> str:
    """
    生成 Prometheus 格式的指标文本

    :return: Prometheus 格式的指标字符串
    """
    with _lock:
        uptime = time.time() - _start_time
        lines = [
            "# HELP kefu_uptime_seconds 服务运行时间（秒）",
            "# TYPE kefu_uptime_seconds gauge",
            f"kefu_uptime_seconds {uptime:.1f}",
            "",
            "# HELP kefu_active_requests 当前活跃请求数",
            "# TYPE kefu_active_requests gauge",
            f"kefu_active_requests {_active_requests}",
            "",
            "# HELP kefu_chat_messages_total 聊天消息总数",
            "# TYPE kefu_chat_messages_total counter",
            f"kefu_chat_messages_total {_chat_message_count}",
            "",
            "# HELP kefu_requests_total HTTP 请求总数（按 method, path, status）",
            "# TYPE kefu_requests_total counter",
        ]
        for key, count in sorted(_request_count.items()):
            parts = key.split(":", 2)
            # 仅处理 HTTP 请求键（method:path:status 三段式）
            # 非 HTTP 键（cache:hit、retrieval:found、handoff:count、timing:total 等）跳过
            if len(parts) < 3 or parts[0] in ("cache", "retrieval", "handoff", "timing"):
                continue
            method, path, status = parts[0], parts[1], parts[2]
            lines.append(
                f'kefu_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
            )

        # 输出非 HTTP 计数指标（缓存、检索、转人工、计时）
        for metric_name, label_keys in [
            ("kefu_cache_total", ["cache"]),
            ("kefu_retrieval_total", ["retrieval"]),
            ("kefu_handoff_total", ["handoff"]),
            ("kefu_timing_total", ["timing"]),
        ]:
            related = {k: v for k, v in _request_count.items() if k.startswith(label_keys[0] + ":")}
            if not related:
                continue
            lines.extend([
                "",
                f"# HELP {metric_name} {label_keys[0]} 计数",
                f"# TYPE {metric_name} counter",
            ])
            for k, v in sorted(related.items()):
                sub_key = k.split(":", 1)[1] if ":" in k else "total"
                lines.append(f'{metric_name}{{type="{sub_key}"}} {v}')

        lines.extend([
            "",
            "# HELP kefu_request_latency_ms 请求延迟（毫秒）",
            "# TYPE kefu_request_latency_ms summary",
        ])
        for key, latencies in sorted(_request_latency.items()):
            parts = key.split(":", 1)
            method, path = parts[0], parts[1]
            stats = _compute_latency_stats(latencies)
            lines.append(
                f'kefu_request_latency_ms{{method="{method}",path="{path}",quantile="0.5"}} {stats["p50"]:.1f}'
            )
            lines.append(
                f'kefu_request_latency_ms{{method="{method}",path="{path}",quantile="0.95"}} {stats["p95"]:.1f}'
            )
            lines.append(
                f'kefu_request_latency_ms{{method="{method}",path="{path}",quantile="0.99"}} {stats["p99"]:.1f}'
            )

        lines.extend([
            "",
            "# HELP kefu_llm_calls_total LLM 调用次数（按节点）",
            "# TYPE kefu_llm_calls_total counter",
        ])
        for node, count in sorted(_llm_call_count.items()):
            lines.append(f'kefu_llm_calls_total{{node="{node}"}} {count}')

        lines.extend([
            "",
            "# HELP kefu_errors_total 错误次数（按类型）",
            "# TYPE kefu_errors_total counter",
        ])
        for error_type, count in sorted(_error_count.items()):
            lines.append(f'kefu_errors_total{{type="{error_type}"}} {count}')

        lines.extend([
            "",
            "# HELP kefu_ab_test_total A/B 测试分桶命中次数",
            "# TYPE kefu_ab_test_total counter",
        ])
        for variant, count in sorted(_ab_variant_count.items()):
            lines.append(f'kefu_ab_test_total{{variant="{variant}"}} {count}')

        lines.append("")
        return "\n".join(lines)


def get_metrics_json() -> dict:
    """
    获取 JSON 格式的指标（用于内部监控）

    :return: 指标字典
    """
    with _lock:
        latency_stats = {}
        for key, latencies in _request_latency.items():
            latency_stats[key] = _compute_latency_stats(latencies)

        return {
            "uptime_seconds": time.time() - _start_time,
            "active_requests": _active_requests,
            "chat_messages_total": _chat_message_count,
            "requests": dict(_request_count),
            "latency": latency_stats,
            "llm_calls": dict(_llm_call_count),
            "errors": dict(_error_count),
            "ab_test": dict(_ab_variant_count),
        }