"""Pytest fixtures and shared helpers for the Super Tutor test suite.

【功能说明】
提供测试基础设施：
1. test_db_path — 临时数据库文件路径（基于 tmp_path fixture）
2. test_db      — 隔离的测试数据库实例（自动创建表 + 自动清理）
3. _create_test_material — 插入最小化学习材料记录的辅助函数
4. _insert_test_kp       — 插入最小化知识点记录的辅助函数

【耦合关系】
- 被所有 test_*.py 测试文件依赖（通过 pytest fixture 注入）
- 依赖 super_tutor.core.database.Database（核心基础设施）
- 不依赖 engine/ 和 models/（轻量级 fixture 层）
- 测试异步模式：pytest-asyncio（asyncio_mode = auto）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from super_tutor.core.database import Database

logger = logging.getLogger(__name__)


# ======================================================================
# Database fixtures
# ======================================================================


@pytest.fixture
def test_db_path(tmp_path: Path) -> str:
    """Create a temporary database file path."""
    return str(tmp_path / "test_super_tutor.db")


@pytest.fixture
async def test_db(test_db_path: str) -> Database:
    """Create and initialise an isolated test database."""
    db = Database(db_path=test_db_path)
    await db.initialize()
    yield db
    await db.close()


# ======================================================================
# Shared helpers
# ======================================================================


async def _create_test_material(db: Database, **kwargs: Any) -> str:
    """Insert a minimal material and return its ID."""
    now = datetime.now(timezone.utc).isoformat()
    mat_id = kwargs.pop("material_id", f"mat-{now}")
    defaults: dict[str, Any] = {
        "material_id": mat_id,
        "title": "Test Material",
        "content": "测试内容。",
        "course_type": "physics",
        "status": "ready",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(kwargs)
    await db.create_material(defaults)
    return mat_id


async def _insert_test_kp(
    db: Database, kp_id: str = "", title: str = "测试知识点", **kwargs: Any
) -> str:
    """Insert a minimal knowledge point and return its kp_id."""
    now = datetime.now(timezone.utc).isoformat()
    kp_id = kp_id or f"kp-{title}"
    defaults: dict[str, Any] = {
        "kp_id": kp_id,
        "material_id": kwargs.pop("material_id", "mat-default"),
        "title": title,
        "content": kwargs.pop("content", f"{title}的详细内容。"),
        "summary": kwargs.pop("summary", title[:80]),
        "difficulty": kwargs.pop("difficulty", "medium"),
        "keywords": json.dumps(kwargs.pop("keywords", ["测试", "知识点"])),
        "prerequisite_ids": json.dumps(kwargs.pop("prerequisite_ids", [])),
        "successor_ids": json.dumps(kwargs.pop("successor_ids", [])),
        "mastery_level": kwargs.pop("mastery_level", 0.0),
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(kwargs)
    await db.insert_knowledge_point(defaults)
    return kp_id
