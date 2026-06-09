"""
商品查询服务：对接聚宝赞 ext-merchant API

接口：
- POST /api/v1/ext-merchant/product-details 商品详情
"""
import logging
import httpx
from typing import Any
from backend.config import (
    PRODUCT_API_TIMEOUT,
    PRODUCT_SERVICE_NAME,
)
from backend.middleware.http_client import get_shared_client
from backend.nacos.http_client import nacos_request

logger = logging.getLogger(__name__)

PRODUCT_DETAILS_PATH = "/api/v1/ext-merchant/product-details"


async def query_product(
    tenant_id: str,
    product_id: str = "",
    product_name: str = "",
) -> dict[str, Any]:
    """
    查询商品信息，调用聚宝赞 product-details 接口

    请求参数映射 (ProductDetailQueryDTO):
    - tenantId: 租户ID
    - productId: 商品ID

    :param tenant_id: 租户ID
    :param product_id: 商品ID（精确查询 → product-details）
    :param product_name: 商品名称（不传给API，用于降级知识库检索）
    :return: {success: bool, data: dict | None, message: str}
    """
    if not product_id:
        return {
            "success": False, "data": None,
            "message": "请提供商品ID进行查询",
        }

    try:
        body = {"tenantId": tenant_id, "productId": product_id}
        headers = {"Content-Type": "application/json"}

        client = get_shared_client()
        response = await nacos_request(
            "POST",
            service_name=PRODUCT_SERVICE_NAME,
            path=PRODUCT_DETAILS_PATH,
            json_data=body,
            headers=headers,
            timeout=httpx.Timeout(PRODUCT_API_TIMEOUT),
        )

        result = response.json()

        # 解析 ResultProductDetailsVO 响应
        success = result.get("success", result.get("code", -1) == 0)
        data = result.get("data")

        return {
            "success": success,
            "data": data,
            "message": result.get("message", ""),
        }
    except httpx.TimeoutException:
        logger.error(f"商品查询超时: tenant={tenant_id}, productId={product_id}")
        return {"success": False, "data": None, "message": "商品查询超时，请稍后重试"}
    except httpx.HTTPStatusError as e:
        logger.error(f"商品查询HTTP错误: tenant={tenant_id}, status={e.response.status_code}")
        return {"success": False, "data": None, "message": f"商品查询服务异常（{e.response.status_code}），请联系管理员"}
    except Exception as e:
        logger.error(f"商品查询异常: tenant={tenant_id}, error={e}")
        return {"success": False, "data": None, "message": "商品查询服务暂时不可用，请稍后重试或联系人工客服"}


def format_product_result(result: dict[str, Any]) -> str:
    """
    格式化商品查询结果为用户可读文本

    适配 ProductDetailsVO 字段：
    - name → 商品名
    - price → 价格
    - originalPrice → 原价
    - stock → 库存
    - category → 分类
    - status → 状态
    - images → 图片列表（取第一张作为展示）
    - supplierName → 供应商名
    """
    if not result.get("success"):
        return result.get("message", "商品查询失败")

    data = result.get("data")
    if not data:
        return "未找到相关商品，请尝试其他商品ID查询。"

    parts = []

    name = data.get("name", "未知商品")
    parts.append(f"商品名：{name}")

    price = data.get("price")
    if price is not None:
        parts.append(f"价格：¥{price}")

    original_price = data.get("originalPrice")
    if original_price is not None:
        parts.append(f"原价：¥{original_price}")

    stock = data.get("stock")
    if stock is not None:
        stock_str = "有货" if (isinstance(stock, int) and stock > 0) else "暂时缺货"
        parts.append(f"库存：{stock}（{stock_str}）")

    category = data.get("category")
    if category:
        parts.append(f"分类：{category}")

    status = data.get("status")
    if status:
        parts.append(f"状态：{status}")

    images = data.get("images")
    if images and isinstance(images, list) and len(images) > 0:
        parts.append(f"商品图片：{images[0]}")

    supplier_name = data.get("supplierName")
    if supplier_name:
        parts.append(f"供应商：{supplier_name}")

    return "\n".join(parts)