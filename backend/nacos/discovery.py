"""
Nacos 服务发现 + 客户端负载均衡

提供根据服务名发现可用实例、轮询负载均衡、实例缓存等功能。
"""
import logging
import time
from nacos import NacosClient
from backend.config import NACOS_GROUP

logger = logging.getLogger(__name__)

# 缓存 TTL（秒）：减少对 Nacos 的查询频率
_CACHE_TTL = 30


class ServiceDiscovery:
    """
    Nacos 服务发现管理器

    特性：
    - 服务实例列表缓存（30 秒 TTL）
    - 轮询（Round-Robin）负载均衡
    - 健康实例自动过滤
    """

    def __init__(self, client: NacosClient, group: str = NACOS_GROUP):
        self._client = client
        self._group = group
        self._cache: dict[str, list[dict]] = {}
        self._cache_time: dict[str, float] = {}
        self._rr_index: dict[str, int] = {}

    def _get_healthy_instances(self, service_name: str) -> list[dict]:
        """
        获取健康的服务实例列表（带缓存）

        :param service_name: Nacos 中注册的服务名
        :return: 实例列表 [{ip, port, healthy, ...}]
        """
        now = time.time()
        cached_time = self._cache_time.get(service_name, 0)
        if now - cached_time < _CACHE_TTL and service_name in self._cache:
            return self._cache[service_name]

        try:
            instances = self._client.list_naming_instance(
                service_name=service_name,
                group_name=self._group,
                healthy_only=True,
            )
            hosts = instances.get("hosts", []) if instances else []
            healthy = [h for h in hosts if h.get("healthy", True) and h.get("enabled", True)]
            self._cache[service_name] = healthy
            self._cache_time[service_name] = now
            logger.debug(f"服务发现刷新: {service_name} → {len(healthy)} 个实例")
            return healthy
        except Exception as e:
            logger.warning(f"服务发现失败: {service_name}, error={e}")
            # 返回过期缓存作为降级
            return self._cache.get(service_name, [])

    def get_instance(self, service_name: str) -> dict | None:
        """
        获取一个可用服务实例（轮询策略）

        :param service_name: Nacos 中注册的服务名
        :return: 实例信息 {ip, port, ...} 或 None
        """
        instances = self._get_healthy_instances(service_name)
        if not instances:
            return None

        idx = self._rr_index.get(service_name, 0)
        self._rr_index[service_name] = (idx + 1) % len(instances)
        return instances[idx]

    def get_base_url(self, service_name: str) -> str | None:
        """
        获取服务的基础 URL（http://ip:port）

        :param service_name: Nacos 中注册的服务名
        :return: 基础 URL 或 None
        """
        instance = self.get_instance(service_name)
        if not instance:
            return None
        return f"http://{instance['ip']}:{instance['port']}"

    def invalidate_cache(self, service_name: str | None = None):
        """
        主动清除缓存（用于实例故障后强制刷新）

        :param service_name: 指定服务名，为 None 时清除全部缓存
        """
        if service_name:
            self._cache.pop(service_name, None)
            self._cache_time.pop(service_name, None)
        else:
            self._cache.clear()
            self._cache_time.clear()


# 全局服务发现单例
_service_discovery: ServiceDiscovery | None = None


def get_service_discovery() -> ServiceDiscovery:
    """
    获取全局 ServiceDiscovery 实例

    （延迟导入 registry 模块避免循环依赖）
    """
    global _service_discovery
    if _service_discovery is None:
        from backend.nacos.registry import get_nacos_client
        _service_discovery = ServiceDiscovery(get_nacos_client(), NACOS_GROUP)
    return _service_discovery