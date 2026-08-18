from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import AppError, RateLimitError
from app.core.logging import setup_logging
from app.db.session import db, redis_holder
from app.mq.publisher import publisher_holder

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    redis_holder.init()
    if settings.auto_migrate:
        from alembic.config import Config

        from alembic import command

        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    await publisher_holder.connect()
    logger.info("app started (env=%s)", settings.app_env)
    yield
    await publisher_holder.close()
    await redis_holder.close()
    await db.dispose()
    logger.info("app stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="AI 服务后端系统：对话、会话管理与异步任务",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    _ui_file = Path(__file__).resolve().parent / "static" / "index.html"

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/ui")

    @app.get("/ui", include_in_schema=False)
    async def ui():
        return HTMLResponse(_ui_file.read_text(encoding="utf-8"))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        from app.core.logging import request_id_var

        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    def _request_id(request: Request) -> str | None:
        return getattr(request.state, "request_id", None)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        headers = {}
        if isinstance(exc, RateLimitError) and exc.retry_after:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "detail": exc.detail,
                    "request_id": _request_id(request),
                }
            },
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "请求参数校验失败",
                    "detail": jsonable_encoder(exc.errors()),
                    "request_id": _request_id(request),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "服务内部错误",
                    "detail": None,
                    "request_id": _request_id(request),
                }
            },
        )

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    # 探针挂根路径，便于编排工具/负载均衡直接访问
    from app.api.v1 import health as health_api

    app.include_router(health_api.router)
    return app


app = create_app()
