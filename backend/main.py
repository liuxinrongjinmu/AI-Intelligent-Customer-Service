"""
FastAPI 应用主入口
"""
import asyncio
import logging
import pathlib
import uuid
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from fastapi.responses import RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from backend.database import init_db
from backend.config import HOST, PORT, validate_config, SWAGGER_SERVER_URL, ENV
from backend.utils.json_logger import setup_logging

# 请求体大小限制（防护大请求攻击）
MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB
from backend.api.tenant import router as tenant_router
from backend.api.knowledge import router as knowledge_router
from backend.api.chat import router as chat_router
from backend.api.stats import router as stats_router
from backend.utils.sensitive_filter import install_sensitive_filter
from backend.utils.request_id import request_id_var, get_request_id
from backend.utils.metrics import mark_request_start, record_request, increment_active, decrement_active
from backend.middleware.http_client import RateLimitMiddleware, close_shared_client
from backend.agent.graph import close_agent

import os

# 根据环境配置日志格式（生产环境 JSON，开发环境文本）
setup_logging(ENV)
install_sensitive_filter()
logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    请求链路追踪中间件：注入 X-Request-ID 到每个请求的上下文和响应中

    优先从请求头读取 X-Request-ID（上游传递），否则自动生成 UUID。
    同时将 request_id 注入 ContextVar，供下游 logger 使用。
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_var.set(request_id)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    指标采集中间件：记录所有 HTTP 请求的计数、延迟和活跃连接数
    """

    async def dispatch(self, request: Request, call_next):
        mark_request_start()
        increment_active()
        start = time.time()
        try:
            response = await call_next(request)
            latency_ms = (time.time() - start) * 1000
            record_request(request.method, request.url.path, response.status_code, latency_ms)
            return response
        except Exception:
            latency_ms = (time.time() - start) * 1000
            record_request(request.method, request.url.path, 500, latency_ms)
            raise
        finally:
            decrement_active()


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """
    请求体大小限制中间件：防止大请求攻击（如知识同步接口传入超大 payload）

    默认限制 10MB，可通过环境变量 MAX_BODY_SIZE 调整（单位：字节）
    """

    def __init__(self, app, max_size: int = MAX_BODY_SIZE):
        super().__init__(app)
        self._max_size = max_size

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length", "")
            if content_length and int(content_length) > self._max_size:
                return Response(
                    content='{"code":"REQUEST_TOO_LARGE","message":"请求体过大，请减少数据量后重试"}',
                    status_code=413,
                    media_type="application/json",
                )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    warnings, errors = validate_config()
    for w in warnings:
        logger.warning(f"配置警告: {w}")
    if errors:
        for e in errors:
            logger.error(f"配置错误: {e}")
        logger.warning("配置校验存在错误，请尽快修复")
    logger.info("初始化数据库...")
    init_db()
    # 数据库自动备份
    from backend.utils.backup import start_backup_scheduler, backup_now
    backup_now()  # 启动时立即备份一次
    start_backup_scheduler()
    # Nacos 服务注册
    from backend.nacos.registry import register_service, heartbeat_loop
    registered = await register_service()
    if registered:
        # 保留任务引用，防止被 GC 回收
        _heartbeat_task = asyncio.create_task(heartbeat_loop())
    logger.info("应用启动完成")
    yield
    # 关闭时清理
    from backend.utils.backup import stop_backup_scheduler
    stop_backup_scheduler()
    from backend.nacos.registry import deregister_service
    await deregister_service()
    await close_agent()
    await close_shared_client()
    # 关闭 Redis 连接
    from backend.utils.redis_client import close_redis
    await close_redis()
    # 关闭 ChromaDB 写入线程
    from backend.retrieval.vector_store import shutdown_write_thread
    shutdown_write_thread()
    # 关闭检索线程池
    from backend.retrieval.hybrid_search import shutdown_retrieval_executor
    shutdown_retrieval_executor()
    logger.info("应用关闭")


# 生产环境强制关闭 API 文档
_docs_enabled = os.getenv("ENABLE_DOCS", "1") == "1" and ENV != "prod"
docs_url = "/docs" if _docs_enabled else None
redoc_url = "/redoc" if _docs_enabled else None

app = FastAPI(
    title="聚宝赞AI智能客服Agent",
    description="多租户AI客服系统 - MVP版本",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
    servers=[
        {"url": SWAGGER_SERVER_URL, "description": "内网联调环境"},
        {"url": f"http://localhost:{PORT}", "description": "本地开发环境"},
    ],
)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",")
# 过滤空字符串
ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS if o.strip()] or ["*"]
# CORS 安全：当 origins=["*"] 时，浏览器规范禁止 allow_credentials=True
if ALLOWED_ORIGINS == ["*"]:
    logger.warning("CORS 允许所有来源（*），生产环境请配置 ALLOWED_ORIGINS 为具体域名")
    _cors_allow_credentials = False
else:
    _cors_allow_credentials = True
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RateLimitMiddleware, default_limit=120, chat_limit=60)

app.include_router(tenant_router)
app.include_router(knowledge_router)
app.include_router(chat_router)
app.include_router(stats_router)

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "frontend" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend" / "static")), name="static")


@app.get("/")
def root():
    return RedirectResponse(url="/chat/demo_001")


@app.get("/chat/{tenant_id}")
def consumer_chat_page(request: Request, tenant_id: str):
    return templates.TemplateResponse("consumer/chat.html", {
        "request": request,
        "tenant_id": tenant_id,
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=True)