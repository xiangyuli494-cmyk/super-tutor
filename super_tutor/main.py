"""Super Tutor — FastAPI application entry point.

启动多角色智能教学系统后端服务。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import State as AppState

from super_tutor import __version__
from super_tutor.core.database import Database
from super_tutor.core.exceptions import TutorError
from super_tutor.core.llm_client import LLMClient
from super_tutor.routes import (
    dashboard_router,
    materials_router,
    quizzes_router,
)
from super_tutor.routes.deps import _S_DB, _S_LLM

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("super_tutor.main")


# ===================================================================
# Lifespan helpers
# ===================================================================


async def init_app_state(app_state: AppState) -> None:
    """Initialize shared resources and attach them to ``app.state``.

    Called once during FastAPI startup (inside the ``lifespan`` context
    manager).  After this returns, every route can ``Depends(use_db)`` etc.
    """
    # -- Database -------------------------------------------------------
    db_path = _resolve_db_path()
    database = Database(db_path=db_path)
    await database.initialize()
    setattr(app_state, _S_DB, database)
    logger.info("Database ready: %s", db_path)

    # -- LLM Client -----------------------------------------------------
    try:
        llm_client = LLMClient()
        setattr(app_state, _S_LLM, llm_client)
        logger.info("LLM client ready.")
    except Exception as exc:
        logger.warning(
            "LLM client unavailable (API key not configured?): %s. "
            "LLM-dependent endpoints will return 503.",
            exc,
        )
        setattr(app_state, _S_LLM, None)


async def shutdown_app_state(app_state: AppState) -> None:
    """Clean up shared resources on shutdown."""
    db: Optional[Database] = getattr(app_state, _S_DB, None)
    if db is not None:
        await db.close()
        logger.info("Database connection closed.")


# ===================================================================
# Internal helpers
# ===================================================================


def _resolve_db_path() -> str:
    """Determine the default SQLite database path.

    Priority:
    1. ``TUTOR_DB_PATH`` environment variable.
    2. ``~/.super-tutor/super_tutor.db`` in the user's home directory.
    """
    env_path = os.getenv("TUTOR_DB_PATH")
    if env_path:
        return str(Path(env_path).expanduser().resolve())

    path = Path.home() / ".super-tutor" / "super_tutor.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理。

    - 启动时：初始化 Database、LLMClient，挂载到 app.state。
    - 关闭时：关闭数据库连接。
    """
    logger.info("Super Tutor v%s starting up...", __version__)

    try:
        await init_app_state(app.state)
        logger.info("All services initialized. Ready to accept requests.")
    except Exception as exc:
        logger.critical("Failed to initialize services: %s", exc, exc_info=True)
        raise

    yield

    logger.info("Super Tutor shutting down...")
    await shutdown_app_state(app.state)
    logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Super Tutor",
    description="多角色智能教学系统 — 扔给它一本 PDF，它读、它出题、它批改、它排复习计划。",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Exception handlers — 将业务异常转换为标准 APIResponse
# ---------------------------------------------------------------------------


@app.exception_handler(TutorError)
async def tutor_error_handler(request: Request, exc: TutorError) -> JSONResponse:
    """捕获所有 TutorError 子类，返回标准错误格式。"""
    logger.warning("TutorError handled: %s", exc)
    return JSONResponse(
        status_code=400,
        content={
            "code": 400,
            "message": "请求处理失败",
            "detail": str(exc),
        },
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """参数校验错误。"""
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "message": "参数校验失败",
            "detail": str(exc),
        },
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理。"""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": "服务器内部错误",
            "detail": "请稍后重试或联系管理员。",
        },
    )


# ---------------------------------------------------------------------------
# Health check (always available)
# ---------------------------------------------------------------------------


@app.get("/api/v1/health")
async def health_check(request: Request) -> dict:
    """健康检查端点。"""
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "version": __version__,
        },
    }


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(materials_router)
app.include_router(quizzes_router)
app.include_router(dashboard_router)


# ---------------------------------------------------------------------------
# CLI launcher
# ---------------------------------------------------------------------------


def main() -> None:
    """命令行启动入口。"""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(
        description="Super Tutor — 多角色智能教学系统"
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="服务端口（默认 8765）"
    )
    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="绑定地址（默认 127.0.0.1）"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="启用热重载（开发模式）",
    )
    args = parser.parse_args()

    uvicorn.run(
        "super_tutor.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
