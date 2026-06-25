"""
多租户中间件：识别和鉴权（含 LRU 缓存，避免每次请求查库）

支持复用请求级 DB 会话：当作为 FastAPI 依赖注入时，
通过 Depends(get_db) 复用同一会话，避免创建额外连接。
"""
import time
import logging
import threading
from collections import OrderedDict
from contextlib import contextmanager
from typing import Optional
from fastapi import Request, HTTPException, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from backend.database import SessionLocal, get_db
from backend.models.tenant import Tenant, hash_api_key

logger = logging.getLogger(__name__)

# 租户信息缓存：LRU + TTL
_tenant_cache: OrderedDict[str, tuple[Tenant, float]] = OrderedDict()
_tenant_cache_lock = threading.Lock()
_TENANT_CACHE_MAX_SIZE = 200
_TENANT_CACHE_TTL = 300  # 5 分钟

# API Key → tenant_id 映射缓存
_key_cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
_key_cache_lock = threading.Lock()
_KEY_CACHE_MAX_SIZE = 200
_KEY_CACHE_TTL = 300  # 5 分钟


def _get_cached_tenant(tenant_id: str) -> Optional[Tenant]:
    """从缓存获取租户信息"""
    with _tenant_cache_lock:
        if tenant_id in _tenant_cache:
            tenant, ts = _tenant_cache[tenant_id]
            if time.time() - ts < _TENANT_CACHE_TTL:
                _tenant_cache.move_to_end(tenant_id)
                return tenant
            else:
                del _tenant_cache[tenant_id]
    return None


def _set_cached_tenant(tenant_id: str, tenant: Tenant):
    """写入租户缓存"""
    with _tenant_cache_lock:
        _tenant_cache[tenant_id] = (tenant, time.time())
        _tenant_cache.move_to_end(tenant_id)
        while len(_tenant_cache) > _TENANT_CACHE_MAX_SIZE:
            _tenant_cache.popitem(last=False)


def _get_cached_key(api_key_hash: str) -> Optional[str]:
    """从缓存获取 API Key → tenant_id 映射"""
    with _key_cache_lock:
        if api_key_hash in _key_cache:
            tenant_id, ts = _key_cache[api_key_hash]
            if time.time() - ts < _KEY_CACHE_TTL:
                _key_cache.move_to_end(api_key_hash)
                return tenant_id
            else:
                del _key_cache[api_key_hash]
    return None


def _set_cached_key(api_key_hash: str, tenant_id: str):
    """写入 API Key 缓存"""
    with _key_cache_lock:
        _key_cache[api_key_hash] = (tenant_id, time.time())
        _key_cache.move_to_end(api_key_hash)
        while len(_key_cache) > _KEY_CACHE_MAX_SIZE:
            _key_cache.popitem(last=False)


def invalidate_tenant_cache(tenant_id: str):
    """使指定租户缓存失效（租户信息变更时调用）"""
    with _tenant_cache_lock:
        _tenant_cache.pop(tenant_id, None)


@contextmanager
def _ensure_db_session(db=None):
    """
    确保数据库会话可用：复用已有会话或创建新会话

    :param db: 已有的数据库会话（可选）
    :yield: 可用的数据库会话
    """
    if db is not None:
        yield db
    else:
        with SessionLocal() as session:
            yield session


async def verify_tenant_api_key(
    request: Request,
    db: Optional[Session] = Depends(get_db),
):
    """
    校验管理端 API Key（含缓存）
    从 X-API-Key Header 获取并验证（仅管理端使用，服务间接口走 Gateway 认证）

    :param request: FastAPI 请求对象
    :param db: 请求级 DB 会话（FastAPI 注入，复用避免额外连接）
    """
    api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if not api_key:
        raise HTTPException(status_code=401, detail="缺少 X-API-Key 请求头")

    hashed = hash_api_key(api_key)

    # 先查缓存
    cached_tenant_id = _get_cached_key(hashed)
    if cached_tenant_id:
        tenant = _get_cached_tenant(cached_tenant_id)
        if tenant and tenant.is_active:
            request.state.tenant = tenant
            return tenant

    # 缓存未命中，查数据库（优先复用请求级会话）
    try:
        with _ensure_db_session(db) as session:
            tenant = session.query(Tenant).filter_by(api_key_hash=hashed, is_active=True).first()
            if not tenant:
                raise HTTPException(status_code=403, detail="无效的 API Key")

            # 脱离 Session，避免 DetachedInstanceError
            session.expunge(tenant)

            # 写入缓存
            _set_cached_key(hashed, tenant.tenant_id)
            _set_cached_tenant(tenant.tenant_id, tenant)

            request.state.tenant = tenant
            return tenant
    except SQLAlchemyError as e:
        logger.error(f"租户鉴权数据库异常: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")


def get_tenant_from_path(
    request: Request,
    tenant_id: str,
    db: Optional[Session] = Depends(get_db),
):
    """
    从 URL 路径提取 tenant_id 并验证（含缓存）

    :param request: FastAPI 请求对象
    :param tenant_id: 租户ID
    :param db: 请求级 DB 会话（FastAPI 注入，复用避免额外连接）
    """
    # 先查缓存
    tenant = _get_cached_tenant(tenant_id)
    if tenant and tenant.is_active:
        request.state.tenant = tenant
        return tenant

    # 缓存未命中，查数据库（优先复用请求级会话）
    try:
        with _ensure_db_session(db) as session:
            tenant = session.query(Tenant).filter_by(tenant_id=tenant_id, is_active=True).first()
            if not tenant:
                raise HTTPException(status_code=404, detail=f"租户 {tenant_id} 不存在")

            # 脱离 Session，避免 DetachedInstanceError
            session.expunge(tenant)

            # 写入缓存
            _set_cached_tenant(tenant_id, tenant)

            request.state.tenant = tenant
            return tenant
    except SQLAlchemyError as e:
        logger.error(f"租户查询数据库异常: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")
