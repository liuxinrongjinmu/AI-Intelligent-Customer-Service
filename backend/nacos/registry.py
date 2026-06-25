"""
Nacos 服务注册管理器

负责服务启动时注册到 Nacos、定时心跳保活、关闭时注销。
"""
import asyncio
import logging
import socket
from typing import Optional
import nacos
from backend.config import (
    NACOS_SERVER_ADDR,
    NACOS_NAMESPACE,
    NACOS_GROUP,
    NACOS_USERNAME,
    NACOS_PASSWORD,
    SERVICE_IP,
    SERVICE_PORT,
)

logger = logging.getLogger(__name__)

# 全局注册客户端实例
_nacos_registry_client: Optional[nacos.NacosClient] = None
# 注册状态标记
_registration_status: bool = False


def _get_local_ip() -> str:
    """获取本机内网 IP，容器环境优先使用 SERVICE_IP 环境变量"""
    if SERVICE_IP:
        return SERVICE_IP
    try:
        # 通过连接外部地址获取本机出口 IP（不会实际发送数据）
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_nacos_client() -> nacos.NacosClient:
    """获取或创建 NacosClient 单例"""
    global _nacos_registry_client
    if _nacos_registry_client is None:
        _nacos_registry_client = nacos.NacosClient(
            NACOS_SERVER_ADDR,
            namespace=NACOS_NAMESPACE,
            username=NACOS_USERNAME or None,
            password=NACOS_PASSWORD or None,
        )
        logger.info(f"NacosClient 已创建: server={NACOS_SERVER_ADDR}, namespace={NACOS_NAMESPACE}")
    return _nacos_registry_client


SERVICE_NAME = "kefu-service"


async def register_service() -> bool:
    """
    注册本服务到 Nacos

    :return: 是否注册成功
    """
    try:
        client = get_nacos_client()
        ip = _get_local_ip()

        client.add_naming_instance(
            service_name=SERVICE_NAME,
            ip=ip,
            port=SERVICE_PORT,
            group_name=NACOS_GROUP,
            healthy=True,
            enable=True,
            metadata={"version": "1.0.0", "language": "python"},
        )
        logger.info(f"服务注册成功: {SERVICE_NAME} @ {ip}:{SERVICE_PORT}, group={NACOS_GROUP}")
        global _registration_status
        _registration_status = True
        return True
    except Exception as e:
        logger.error(f"服务注册失败: {e}")
        return False


async def deregister_service() -> bool:
    """
    从 Nacos 注销本服务

    :return: 是否注销成功
    """
    try:
        client = get_nacos_client()
        ip = _get_local_ip()

        client.remove_naming_instance(
            service_name=SERVICE_NAME,
            ip=ip,
            port=SERVICE_PORT,
            group_name=NACOS_GROUP,
        )
        logger.info(f"服务注销成功: {SERVICE_NAME} @ {ip}:{SERVICE_PORT}")
        global _registration_status
        _registration_status = False
        return True
    except Exception as e:
        logger.error(f"服务注销失败: {e}")
        return False


async def send_heartbeat() -> bool:
    """
    发送心跳到 Nacos

    心跳间隔 5 秒，Nacos 默认超时 15 秒，留足容错空间。

    :return: 是否发送成功
    """
    try:
        client = get_nacos_client()
        ip = _get_local_ip()

        client.send_heartbeat(
            service_name=SERVICE_NAME,
            ip=ip,
            port=SERVICE_PORT,
            group_name=NACOS_GROUP,
        )
        return True
    except Exception as e:
        logger.warning(f"心跳发送失败: {e}")
        return False


async def heartbeat_loop(interval: int = 5):
    """
    心跳循环（后台任务）

    :param interval: 心跳间隔（秒），默认 5 秒
    """
    logger.info(f"心跳循环已启动，间隔 {interval}s")
    while True:
        try:
            await asyncio.sleep(interval)
            await send_heartbeat()
        except asyncio.CancelledError:
            logger.info("心跳循环已取消")
            break
        except Exception as e:
            logger.error(f"心跳循环异常: {e}")


def is_registered() -> bool:
    """
    查询当前服务是否已注册到 Nacos

    :return: 是否已注册
    """
    return _registration_status