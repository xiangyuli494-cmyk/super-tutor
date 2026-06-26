"""Super Tutor — FastAPI 依赖注入提供者。

轻量级模块，只包含 ``use_db``、``use_llm_client`` 两个核心依赖提供者。
被 ``main.py`` 和所有路由文件引用。
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from super_tutor.core.database import Database
from super_tutor.core.llm_client import LLMClient

# ---------------------------------------------------------------------------
# State keys — stored on ``app.state`` at startup
# ---------------------------------------------------------------------------
_S_DB: str = "tutor_database"
_S_LLM: str = "tutor_llm_client"


def use_db(request: Request) -> Database:
    """回传已初始化的 Database 实例。"""
    return getattr(request.app.state, _S_DB)


def use_llm_client(request: Request) -> LLMClient:
    """回传 LLMClient 实例。

    Raises:
        HTTPException(503): 若 API Key 未配置导致 LLM 不可用。
    """
    client = getattr(request.app.state, _S_LLM, None)
    if client is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "LLM 服务不可用：API Key 未配置。"
                "请设置环境变量 TUTOR_API_KEY。"
            ),
        )
    return client
