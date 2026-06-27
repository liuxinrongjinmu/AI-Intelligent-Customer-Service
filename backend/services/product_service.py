"""
商品查询服务：对接聚宝赞 tenant-service → ExtMerchantFeignClient

VO 定义（tenant-api/vo/external/product/ProductDetailsVO）：
{
  "productId": str,        // 商品ID
  "name": str,             // 商品名称
  "category": str,         // 分类
  "price": BigDecimal,     // 售价
  "originalPrice": BigDecimal, // 原价
  "images": [str],         // 商品图片列表
  "stock": int,            // 库存
  "status": str,           // 上架/下架
  "supplierId": str,       // 供应商ID
  "supplierName": str,     // 供应商名称
  "goodsType": int,        // 1=实物商品, 2=虚拟商品
  "tags": str,             // 标签
  "skuList": [...]         // 规格列表 (ProductSkuVO[])
}

调用链路：merchant-service → buyer-service → tenant-service → ExtMerchantFeignClient
"""
import logging
import httpx
from typing import Any
from backend.config import (
    PRODUCT_API_TIMEOUT,
    PRODUCT_SERVICE_NAME,
)
from backend.nacos.nacos_client import nacos_request
from backend.utils.retry import retry_on_transient_error
from backend.utils.helpers import resolve_tenant_id

logger = logging.getLogger(__name__)

PRODUCT_DETAILS_PATH = "/api/v1/ext-merchant/product-details"  # 待确认：merchant-service 未暴露此路径，当前走知识库降级
PRODUCT_SEARCH_PATH = "/api/v1/ext-merchant/product-search"    # 待确认


@retry_on_transient_error(max_retries=2)
async def _do_query_product(tenant_id: str, product_id: str) -> dict[str, Any]:
    """
    执行商品详情查询 HTTP 请求（含重试）

    :param tenant_id: 租户ID
    :param product_id: 商品ID
    :return: API 响应 JSON
    """
    body = {"tenantId": resolve_tenant_id(tenant_id), "productId": product_id}
    headers = {"Content-Type": "application/json"}

    response = await nacos_request(
        "POST",
        service_name=PRODUCT_SERVICE_NAME,
        path=PRODUCT_DETAILS_PATH,
        json_data=body,
        headers=headers,
        timeout=httpx.Timeout(PRODUCT_API_TIMEOUT),
    )
    return response.json()


@retry_on_transient_error(max_retries=2)
async def _do_search_product(tenant_id: str, product_name: str, page: int = 1, page_size: int = 5) -> dict[str, Any]:
    """
    执行商品名称搜索 HTTP 请求（含重试）

    :param tenant_id: 租户ID
    :param product_name: 商品名称（模糊匹配）
    :param page: 页码
    :param page_size: 每页数量
    :return: API 响应 JSON
    """
    body = {
        "tenantId": resolve_tenant_id(tenant_id),
        "productName": product_name,
        "page": page,
        "pageSize": page_size,
    }
    headers = {"Content-Type": "application/json"}

    response = await nacos_request(
        "POST",
        service_name=PRODUCT_SERVICE_NAME,
        path=PRODUCT_SEARCH_PATH,
        json_data=body,
        headers=headers,
        timeout=httpx.Timeout(PRODUCT_API_TIMEOUT),
    )
    return response.json()


async def query_product(
    tenant_id: str,
    product_id: str = "",
    product_name: str = "",
) -> dict[str, Any]:
    """
    查询商品信息

    优先按 product_id 精确查询（product-details）；
    若仅提供 product_name，则调用 product-search 模糊搜索；
    两者均无则返回提示。

    :param tenant_id: 租户ID
    :param product_id: 商品ID（精确查询 → product-details）
    :param product_name: 商品名称（模糊搜索 → product-search）
    :return: {success: bool, data: dict | list | None, total: int, message: str}
    """
    if product_id:
        try:
            result = await _do_query_product(tenant_id, product_id)
            success = result.get("success", result.get("code", -1) == 0)
            data = result.get("data")
            return {
                "success": success,
                "data": data,
                "total": 1 if data else 0,
                "message": result.get("message", ""),
            }
        except httpx.TimeoutException:
            logger.error(f"商品查询超时: tenant={tenant_id}, productId={product_id}")
            return {"success": False, "data": None, "total": 0, "message": "商品查询超时，请稍后重试"}
        except httpx.HTTPStatusError as e:
            logger.error(f"商品查询HTTP错误: tenant={tenant_id}, status={e.response.status_code}")
            return {"success": False, "data": None, "total": 0, "message": f"商品查询服务异常（{e.response.status_code}），请联系管理员"}
        except Exception as e:
            logger.error(f"商品查询异常: tenant={tenant_id}, error={e}")
            return {"success": False, "data": None, "total": 0, "message": "商品查询服务暂时不可用，请稍后重试或联系人工客服"}

    if product_name:
        try:
            result = await _do_search_product(tenant_id, product_name)
            success = result.get("success", result.get("code", -1) == 0)
            data = result.get("data")
            # 兼容 list / {list: [...]} / {records: [...]} / {items: [...]} 等常见分页结构
            if isinstance(data, dict):
                records = []
                for key in ("list", "records", "items", "data"):
                    if key in data:
                        records = data.get(key) or []
                        break
                else:
                    records = [data] if data else []
            elif isinstance(data, list):
                records = data
            else:
                records = [data] if data else []
            return {
                "success": success,
                "data": records,
                "total": len(records),
                "message": result.get("message", ""),
            }
        except httpx.TimeoutException:
            logger.error(f"商品搜索超时: tenant={tenant_id}, name={product_name}")
            return {"success": False, "data": None, "total": 0, "message": "商品搜索超时，请稍后重试"}
        except httpx.HTTPStatusError as e:
            logger.error(f"商品搜索HTTP错误: tenant={tenant_id}, status={e.response.status_code}")
            return {"success": False, "data": None, "total": 0, "message": f"商品搜索服务异常（{e.response.status_code}），请联系管理员"}
        except Exception as e:
            logger.error(f"商品搜索异常: tenant={tenant_id}, error={e}")
            return {"success": False, "data": None, "total": 0, "message": "商品搜索服务暂时不可用，请稍后重试或联系人工客服"}

    return {
        "success": False, "data": None, "total": 0,
        "message": "请提供商品ID或商品名称进行查询",
    }


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

    搜索结果（list）时展示前 5 条摘要。
    """
    if not result.get("success"):
        return result.get("message", "商品查询失败")

    data = result.get("data")
    if not data:
        return "未找到相关商品，请尝试其他商品ID或名称查询。"

    # 搜索结果为列表
    if isinstance(data, list):
        if not data:
            return "未找到相关商品，请尝试其他关键词查询。"
        total = result.get("total", len(data))
        parts = [f"为您找到 {total} 个相关商品：\n"]
        for i, item in enumerate(data[:5]):
            name = item.get("name", "未知商品") if isinstance(item, dict) else str(item)
            price = item.get("price") if isinstance(item, dict) else None
            desc = f"{i + 1}. {name}"
            if price is not None:
                desc += f"（¥{price}）"
            parts.append(desc)
        if total > 5:
            parts.append(f"\n（仅展示前 5 条，共 {total} 条结果）")
        return "\n".join(parts)

    # 单个商品详情
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
