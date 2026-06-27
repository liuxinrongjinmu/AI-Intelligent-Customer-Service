"""
监控 API — 健康检查 + Prometheus 指标
"""
import logging
from fastapi import APIRouter, Depends
from sqlalchemy import text as sa_text
from backend.utils.metrics import get_metrics_text
from backend.utils.auth import verify_chat_api_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/health")
async def health_check():
    """
    深度健康检查：探测所有依赖组件的连通性
    返回各组件状态，任一组件异常则整体状态为 degraded
    """
    checks = {}

    # 1. PostgreSQL
    try:
        from backend.database import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
        checks["postgresql"] = {"status": "ok"}
    except Exception as e:
        checks["postgresql"] = {"status": "error", "detail": str(e)[:200]}

    # 2. Redis
    try:
        from backend.utils.redis_client import get_redis
        redis = await get_redis()
        if redis:
            await redis.ping()
            checks["redis"] = {"status": "ok"}
        else:
            checks["redis"] = {"status": "degraded", "detail": "using memory fallback"}
    except Exception as e:
        checks["redis"] = {"status": "degraded", "detail": f"connection failed: {str(e)[:100]}"}

    # 3. ChromaDB
    try:
        from backend.retrieval.vector_store import get_chroma_client
        client = get_chroma_client()
        client.list_collections()
        checks["chromadb"] = {"status": "ok"}
    except Exception as e:
        checks["chromadb"] = {"status": "error", "detail": str(e)[:200]}

    # 4. Nacos
    try:
        from backend.nacos.registry import is_registered
        registered = is_registered()
        checks["nacos"] = {"status": "ok" if registered else "not_registered"}
    except Exception as e:
        checks["nacos"] = {"status": "error", "detail": str(e)[:200]}

    has_error = any(c["status"] == "error" for c in checks.values())
    has_degraded = any(c["status"] in ("degraded", "not_registered") for c in checks.values())

    if has_error:
        overall = "unhealthy"
    elif has_degraded:
        overall = "degraded"
    else:
        overall = "ok"

    return {"status": overall, "checks": checks}


@router.get("/metrics")
def get_metrics(_auth: str = Depends(verify_chat_api_key)):
    """获取 Prometheus 格式的系统运行指标"""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=get_metrics_text(), media_type="text/plain; charset=utf-8")
