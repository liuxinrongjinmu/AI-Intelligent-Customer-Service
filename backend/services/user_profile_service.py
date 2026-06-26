"""
用户画像查询服务：对接聚宝赞 ext-merchant API

接口：
- POST /api/v1/ext-merchant/user-query  查询买家信息
"""
import logging
import httpx
from typing import Any
from backend.config import (
    USER_PROFILE_API_TIMEOUT,
    USER_PROFILE_SERVICE_NAME,
)
from backend.nacos.nacos_client import nacos_request
from backend.utils.retry import retry_on_transient_error
from backend.utils.security import mask_mobile
from backend.utils.helpers import resolve_tenant_id

logger = logging.getLogger(__name__)

USER_QUERY_PATH = "/api/v1/ext-merchant/user-query"


@retry_on_transient_error(max_retries=2)
async def _do_query_user_profile(tenant_id: str, user_id: str) -> dict[str, Any]:
    """
    执行用户画像查询 HTTP 请求（含重试）

    :param tenant_id: 租户ID
    :param user_id: 用户ID
    :return: API 响应 JSON
    """
    body: dict[str, Any] = {"tenantId": resolve_tenant_id(tenant_id), "userId": user_id}
    headers = {"Content-Type": "application/json"}

    response = await nacos_request(
        "POST",
        service_name=USER_PROFILE_SERVICE_NAME,
        path=USER_QUERY_PATH,
        json_data=body,
        headers=headers,
        timeout=httpx.Timeout(USER_PROFILE_API_TIMEOUT),
    )
    return response.json()


async def query_user_profile(
    tenant_id: str,
    user_id: str,
) -> dict[str, Any]:
    """
    查询用户画像信息，调用聚宝赞 user-query 接口

    请求参数映射 (UserInfoQueryDTO):
    - tenantId: 租户ID
    - userId [必填]: 用户ID

    :param tenant_id: 租户ID
    :param user_id: 用户ID（必填）
    :return: {success: bool, data: dict | None, message: str}
    """
    if not user_id:
        return {
            "success": False, "data": None,
            "message": "请提供用户ID",
        }

    try:
        result = await _do_query_user_profile(tenant_id, user_id)
        return {
            "success": result.get("success", result.get("code", -1) == 0),
            "data": result.get("data"),
            "message": result.get("message", ""),
        }
    except httpx.TimeoutException:
        logger.error(f"用户画像查询超时: tenant={tenant_id}, user={user_id}")
        return {"success": False, "data": None, "message": "用户信息查询超时，请稍后重试"}
    except httpx.HTTPStatusError as e:
        logger.error(f"用户画像HTTP错误: tenant={tenant_id}, status={e.response.status_code}")
        return {"success": False, "data": None, "message": f"用户信息查询服务异常（{e.response.status_code}），请联系管理员"}
    except Exception as e:
        logger.error(f"用户画像查询异常: tenant={tenant_id}, error={e}")
        return {"success": False, "data": None, "message": "用户信息查询服务暂时不可用，请稍后重试或联系人工客服"}


def format_user_profile_result(result: dict[str, Any]) -> str:
    """
    格式化用户画像查询结果为用户可读文本

    适配 BuyerInfoVO 字段：
    - nickname → 昵称
    - levelName → 会员等级
    - memberNo → 会员编号
    - phone → 手机号
    """
    if not result.get("success"):
        return result.get("message", "用户信息查询失败")

    data = result.get("data") or {}
    if not data:
        return "暂无用户信息"

    parts = []

    nickname = data.get("nickname", "")
    if nickname:
        parts.append(f"昵称：{nickname}")

    phone = data.get("phone", "")
    if phone:
        # 手机号脱敏（统一调用 mask_mobile，保留前3后4）
        masked_phone = mask_mobile(phone)
        parts.append(f"手机号：{masked_phone}")

    level_name = data.get("levelName", "")
    if level_name:
        parts.append(f"会员等级：{level_name}")

    member_no = data.get("memberNo", "")
    if member_no:
        parts.append(f"会员编号：{member_no}")

    return "\n".join(parts) if parts else "暂无用户信息"