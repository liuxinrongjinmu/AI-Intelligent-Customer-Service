"""
Nacos 服务发现的 HTTP 请求封装

统一封装服务发现 + 实例级重试 + 断路器逻辑。
各 service 层通过 nacos_request() 函数发起请求，所有业务 API 调用全部通过 Nacos 服务发现。

断路器机制：
- 连续失败 N 次（默认 3 次）后自动熔断该实例
- 熔断持续时间默认 30 秒，之后进入半开状态
- 半开状态下允许 1 次请求探测，成功则恢复，失败则继续熔断
"""
import logging
import time
from typing import Optional
import httpx
from backend.middleware.http_client import get_shared_client

logger = logging.getLogger(__name__)

# 最大重试次数（实例级）
# 注意：service 层已有 @retry_on_transient_error(max_retries=2) 装饰器，
# 此处的重试用于尝试不同实例（服务发现），两者叠加后总请求上限 = (1+_MAX_RETRIES) × (1+service_retries)
# 设为 1 以控制总延迟：最多尝试 2 个实例 × 3 次 service 重试 = 6 次，避免数十秒阻塞
_MAX_RETRIES = 1

# 断路器配置
_CIRCUIT_FAILURE_THRESHOLD = 3   # 连续失败次数触发熔断
_CIRCUIT_OPEN_DURATION = 30      # 熔断持续时间（秒）
_CIRCUIT_HALF_OPEN_MAX = 1       # 半开状态最大探测次数


class CircuitState:
    """断路器状态"""
    CLOSED = "closed"       # 正常
    OPEN = "open"           # 熔断
    HALF_OPEN = "half_open" # 半开（探测）


class InstanceCircuitBreaker:
    """
    单实例断路器

    状态转换：
    CLOSED → (连续 N 次失败) → OPEN → (等待冷却) → HALF_OPEN → (探测成功) → CLOSED
                                                     → (探测失败) → OPEN
    """

    def __init__(self):
        self._failure_count: dict[str, int] = {}       # 实例 → 连续失败次数
        self._state: dict[str, str] = {}                # 实例 → 断路器状态
        self._open_since: dict[str, float] = {}         # 实例 → 熔断开始时间
        self._half_open_count: dict[str, int] = {}      # 实例 → 半开探测次数
        # 启动冷却期：服务刚启动时 Nacos 注册可能尚未生效，短暂冷却避免无效失败计数
        self._startup_deadline: float = time.time() + 10.0

    def is_available(self, instance_key: str) -> bool:
        """
        检查实例是否可用（未被熔断）

        :param instance_key: 实例标识（如 "ip:port"）
        :return: 是否可用
        """
        state = self._state.get(instance_key, CircuitState.CLOSED)

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            # 检查冷却时间是否已过
            elapsed = time.time() - self._open_since.get(instance_key, 0)
            if elapsed >= _CIRCUIT_OPEN_DURATION:
                # 进入半开状态
                self._state[instance_key] = CircuitState.HALF_OPEN
                self._half_open_count[instance_key] = 0
                logger.info(f"断路器半开: {instance_key}")
                return True
            return False

        if state == CircuitState.HALF_OPEN:
            # 半开状态只允许有限次探测
            if self._half_open_count.get(instance_key, 0) < _CIRCUIT_HALF_OPEN_MAX:
                return True
            return False

        return True

    def record_success(self, instance_key: str):
        """记录请求成功，重置断路器"""
        self._failure_count[instance_key] = 0
        if self._state.get(instance_key) == CircuitState.HALF_OPEN:
            self._state[instance_key] = CircuitState.CLOSED
            logger.info(f"断路器恢复: {instance_key}")

    def record_failure(self, instance_key: str):
        """记录请求失败，可能触发熔断（启动冷却期内不计入失败）"""
        # 启动冷却期：服务刚启动时 Nacos 可能尚未生效，失败不计入
        if time.time() < self._startup_deadline:
            logger.debug(f"启动冷却期内忽略失败: {instance_key}")
            return

        count = self._failure_count.get(instance_key, 0) + 1
        self._failure_count[instance_key] = count

        state = self._state.get(instance_key, CircuitState.CLOSED)

        if state == CircuitState.HALF_OPEN:
            # 半开状态下探测失败，重新熔断
            self._state[instance_key] = CircuitState.OPEN
            self._open_since[instance_key] = time.time()
            logger.warning(f"断路器重新熔断: {instance_key}")
        elif count >= _CIRCUIT_FAILURE_THRESHOLD:
            # 连续失败达到阈值，触发熔断
            self._state[instance_key] = CircuitState.OPEN
            self._open_since[instance_key] = time.time()
            logger.warning(f"断路器熔断: {instance_key}, 连续失败 {count} 次")

    def get_stats(self) -> dict:
        """获取断路器统计信息"""
        return {
            key: {
                "state": self._state.get(key, CircuitState.CLOSED),
                "failures": self._failure_count.get(key, 0),
            }
            for key in self._state
        }


# 全局断路器实例
_circuit_breaker = InstanceCircuitBreaker()


async def nacos_request(
    method: str,
    service_name: str,
    path: str,
    *,
    params: Optional[dict] = None,
    json_data: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: Optional[httpx.Timeout] = None,
) -> httpx.Response:
    """
    通过 Nacos 服务发现发起 HTTP 请求（断路器保护）

    请求流程：
    1. 通过 Nacos 服务发现获取实例 → 断路器过滤 → 请求 → 失败则重试下一个实例
    2. 所有实例都失败时抛出异常

    :param method: HTTP 方法（GET / POST / PUT / DELETE）
    :param service_name: Nacos 中注册的服务名
    :param path: 接口路径
    :param params: URL 查询参数
    :param json_data: JSON 请求体
    :param headers: 请求头
    :param timeout: 超时配置
    :return: httpx.Response
    :raises Exception: 所有实例均不可用时抛出
    """
    client = get_shared_client()

    from backend.nacos.discovery import get_service_discovery
    discovery = get_service_discovery()

    last_error = None
    for attempt in range(_MAX_RETRIES):
        base_url = discovery.get_base_url(service_name)
        if not base_url:
            raise Exception(f"服务 {service_name} 无可用实例（Nacos 中未发现健康实例）")

        # 断路器检查
        instance_key = base_url.replace("http://", "")
        if not _circuit_breaker.is_available(instance_key):
            # 当前实例被熔断，尝试刷新缓存获取下一个实例
            discovery.invalidate_cache(service_name)
            continue

        url = f"{base_url}{path}"
        try:
            response = await _do_request(client, method, url, params, json_data, headers, timeout)
            _circuit_breaker.record_success(instance_key)
            return response
        except Exception as e:
            _circuit_breaker.record_failure(instance_key)
            last_error = e
            logger.warning(
                f"Nacos 请求失败 (attempt {attempt + 1}/{_MAX_RETRIES}): "
                f"service={service_name}, url={url}, error={e}"
            )
            # 清除故障实例缓存，下次重试会获取不同实例
            discovery.invalidate_cache(service_name)

    raise Exception(f"服务 {service_name} 所有实例均不可用: {last_error}")


async def _do_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    params: Optional[dict],
    json_data: Optional[dict],
    headers: Optional[dict],
    timeout: Optional[httpx.Timeout],
) -> httpx.Response:
    """
    执行单次 HTTP 请求
    """
    kwargs = {}
    if params:
        kwargs["params"] = params
    if json_data:
        kwargs["json"] = json_data
    if headers:
        kwargs["headers"] = headers
    if timeout:
        kwargs["timeout"] = timeout

    response = await client.request(method, url, **kwargs)
    response.raise_for_status()
    return response
