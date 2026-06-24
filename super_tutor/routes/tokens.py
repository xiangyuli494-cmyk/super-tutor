"""Super Tutor — Token 用量统计路由。"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from super_tutor.core.database import Database
from super_tutor.core.token_tracker import TokenTracker
from super_tutor.routes.dependencies import use_db, use_token_tracker
from super_tutor.routes.schemas import APIResponse, TokenStatsResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tokens", tags=["tokens"])


@router.get("/stats", response_model=APIResponse)
async def get_token_stats(
    project_id: Optional[str] = Query(
        default=None,
        description="项目 ID，不传则使用默认值 'global'",
    ),
    db: Database = Depends(use_db),
    tracker: TokenTracker = Depends(use_token_tracker),
) -> APIResponse:
    """获取 Token 用量统计。

    通过 TokenTracker 返回预算状态、按角色/算力档位分组的 Token 用量。
    """
    pid = project_id or "global"

    try:
        stats = await tracker.get_stats(pid)
        # 补充 DB 层的 prompt/completion 拆分（tracker 的 from-role 是 total，
        # prompt/completion 明细仍需从 DB 获取）
        db_stats = await db.get_token_stats(pid)
    except Exception as exc:
        logger.exception("Token stats query failed for project=%s: %s", pid, exc)
        # Fallback: return empty stats instead of 500
        stats = {
            "budget": 0,
            "used": 0,
            "remaining": 0,
            "by_role": {},
            "by_tier": {},
        }
        db_stats = {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "call_count": 0,
        }

    return APIResponse(
        data=TokenStatsResponse(
            total_prompt_tokens=db_stats.get("total_prompt_tokens", 0),
            total_completion_tokens=db_stats.get("total_completion_tokens", 0),
            total_tokens=db_stats.get("total_tokens", 0),
            call_count=db_stats.get("call_count", 0),
            by_role=stats.get("by_role", {}),
            budget=stats.get("budget", 0),
            used=stats.get("used", 0),
            remaining=stats.get("remaining", 0),
            by_tier=stats.get("by_tier", {}),
        ).model_dump()
    )
