"""File-system and token-usage API routes.

Provides file-tree browsing, file-content reading, token-consumption
statistics, and sandbox-vs-src diffing for a given project.
"""

import difflib
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from super_tutor.config import ForgeConfig
from super_tutor.core.database import Database
from super_tutor.core.filesystem import FileSystem
from super_tutor.models import StandardResponse, TokenUsage

router = APIRouter(tags=["files"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_project_db(config: ForgeConfig, project_id: str) -> Database:
    """Open and initialise the project database, or raise 404."""
    projects_root = Path(config.projects_root)
    project_dir = projects_root / project_id
    db_path = project_dir / "forge.db"

    if not project_dir.is_dir() or not db_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "code": 1002,
                "message": f"Project '{project_id}' not found.",
                "data": None,
            },
        )

    db = Database(str(db_path), config=config, projects_root=str(projects_root))
    await db.initialize()
    return db


def _get_filesystem(config: ForgeConfig, project_id: str) -> FileSystem:
    """Return a ``FileSystem`` instance for *project_id*, or raise 404."""
    projects_root = Path(config.projects_root)
    project_dir = projects_root / project_id

    if not project_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail={
                "code": 1002,
                "message": f"Project '{project_id}' not found.",
                "data": None,
            },
        )
    return FileSystem(str(project_dir))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/files",
    response_model=StandardResponse[dict],
)
async def browse_files(
    project_id: str,
    path: str = Query(
        "",
        description="Relative subdirectory path within the project (empty = root)",
    ),
) -> StandardResponse[dict]:
    """Browse the project file tree.

    Returns a nested directory structure.  When *path* is non-empty the
    response is scoped to that subdirectory.  Hidden files and directories
    (names starting with ``.``) are excluded.
    """
    config = ForgeConfig.get_instance()
    fs = _get_filesystem(config, project_id)

    try:
        if path:
            # Return a flat listing for the requested subdirectory.
            entries = fs.list_dir("claude-a", path)
            return StandardResponse(code=0, message="ok", data={"entries": entries})
        else:
            # Return the full nested tree.
            tree = fs.get_file_tree(include_hidden=False)
            return StandardResponse(code=0, message="ok", data=tree)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": 1002,
                "message": str(exc),
                "data": None,
            },
        )
    except NotADirectoryError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": 1001,
                "message": str(exc),
                "data": None,
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": 3001,
                "message": f"Failed to browse files: {exc}",
                "data": None,
            },
        )


@router.get(
    "/projects/{project_id}/files/content",
    response_model=StandardResponse[dict],
)
async def read_file_content(
    project_id: str,
    path: str = Query(..., min_length=1, description="Relative file path within the project"),
    start_line: Optional[int] = Query(
        None, ge=1, description="1-based inclusive start line"
    ),
    end_line: Optional[int] = Query(
        None, ge=1, description="1-based inclusive end line"
    ),
) -> StandardResponse[dict]:
    """Read the contents of a file within the project.

    Supports optional line-range slicing via *start_line* and *end_line*
    (both 1-based and inclusive).
    """
    config = ForgeConfig.get_instance()
    fs = _get_filesystem(config, project_id)

    try:
        content = fs.read_file(
            role="claude-a",
            path=path,
            start_line=start_line,
            end_line=end_line,
        )
        total_lines = content.count("\n") + (0 if content.endswith("\n") else 1) if content else 0

        return StandardResponse(
            code=0,
            message="ok",
            data={
                "path": path,
                "content": content,
                "total_lines": total_lines,
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": 1002,
                "message": str(exc),
                "data": None,
            },
        )
    except IsADirectoryError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": 1001,
                "message": str(exc),
                "data": None,
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": 3001,
                "message": f"Failed to read file: {exc}",
                "data": None,
            },
        )


@router.get(
    "/projects/{project_id}/files/diff",
    response_model=StandardResponse[dict],
)
async def files_diff(project_id: str) -> StandardResponse[dict]:
    """Compare files between the sandbox/ and src/ directories.

    Walks both directories recursively, collects the set of relative file
    paths in each, and produces:

    * ``only_in_sandbox`` — files present in sandbox/ but not yet promoted
      to src/
    * ``only_in_src`` — files present in src/ but not in sandbox/
    * ``diffs`` — for files in both directories that differ, a unified diff
      generated by :py:mod:`difflib`.

    Files whose content is identical in both trees are not included in the
    diff output.
    """
    config = ForgeConfig.get_instance()
    fs = _get_filesystem(config, project_id)
    project_root = Path(fs.project_root)

    sandbox_dir = project_root / "sandbox"
    src_dir = project_root / "src"

    sandbox_files: dict[str, Path] = {}
    src_files: dict[str, Path] = {}

    # Collect all regular files recursively from each tree.
    if sandbox_dir.is_dir():
        for f in sandbox_dir.rglob("*"):
            if f.is_file():
                sandbox_files[str(f.relative_to(sandbox_dir))] = f

    if src_dir.is_dir():
        for f in src_dir.rglob("*"):
            if f.is_file():
                src_files[str(f.relative_to(src_dir))] = f

    sandbox_keys = set(sandbox_files.keys())
    src_keys = set(src_files.keys())

    only_in_sandbox = sorted(sandbox_keys - src_keys)
    only_in_src = sorted(src_keys - sandbox_keys)
    common = sorted(sandbox_keys & src_keys)

    diffs: list[dict[str, str]] = []
    for rel_path in common:
        try:
            sandbox_content = sandbox_files[rel_path].read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            src_content = src_files[rel_path].read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if sandbox_content == src_content:
            continue

        diff_lines = list(
            difflib.unified_diff(
                sandbox_content.splitlines(keepends=True),
                src_content.splitlines(keepends=True),
                fromfile=f"sandbox/{rel_path}",
                tofile=f"src/{rel_path}",
            )
        )
        diffs.append({"path": rel_path, "diff": "".join(diff_lines)})

    return StandardResponse(
        code=0,
        message="ok",
        data={
            "only_in_sandbox": only_in_sandbox,
            "only_in_src": only_in_src,
            "diffs": diffs,
        },
    )


@router.get(
    "/projects/{project_id}/token-usage",
    response_model=StandardResponse[TokenUsage],
)
async def get_token_usage(project_id: str) -> StandardResponse[TokenUsage]:
    """Return token consumption statistics for a project.

    Includes the total budget, tokens used so far, remaining budget, and a
    per-role breakdown (claude-a, codex, claude-b).
    """
    config = ForgeConfig.get_instance()
    db = await _get_project_db(config, project_id)
    try:
        stats = await db.get_token_stats(project_id)
        budget = config.token_budget_default
        used: int = stats.get("total_tokens", 0)
        remaining = max(0, budget - used)
        by_role_raw: dict[str, int] = stats.get("by_role", {})

        token_usage_data: dict[str, Any] = {
            "project_id": project_id,
            "budget": budget,
            "used": used,
            "remaining": remaining,
            "by_role": {
                "claude-a": by_role_raw.get("claude-a", 0),
                "codex": by_role_raw.get("codex", 0),
                "claude-b": by_role_raw.get("claude-b", 0),
            },
        }

        return StandardResponse(code=0, message="ok", data=token_usage_data)
    finally:
        await db.close()
