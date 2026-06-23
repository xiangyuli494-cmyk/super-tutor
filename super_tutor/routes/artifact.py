"""Artifact query API routes.

Provides structured and semantic search over AI-produced artifacts within a
project: requirements, constitutions, API specs, code, audits, and acceptance
reports.
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from super_tutor.config import ForgeConfig
from super_tutor.core.database import Database
from super_tutor.models import Artifact, ArtifactType, Role, StandardResponse

router = APIRouter(tags=["artifacts"])

# Valid filter values for query-parameter validation.
_VALID_ROLES = {"claude-a", "codex", "claude-b"}
_VALID_TYPES = {"requirement", "constitution", "api-spec", "code", "audit", "acceptance"}


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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/artifacts",
    response_model=StandardResponse[list[Artifact]],
)
async def query_artifacts(
    project_id: str,
    role: Optional[str] = Query(
        None, description="Filter by role: claude-a, codex, claude-b"
    ),
    artifact_type: Optional[str] = Query(
        None,
        alias="type",
        description=(
            "Filter by artifact type: requirement, constitution, "
            "api-spec, code, audit, acceptance"
        ),
    ),
    module: Optional[str] = Query(None, description="Filter by module name"),
    limit: int = Query(20, ge=1, le=200, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
) -> StandardResponse[list[Artifact]]:
    """Query artifacts with structured filters.

    All filter parameters are optional — omit them to retrieve every artifact
    for the project.  Results are ordered by creation time (newest first).
    """
    if role is not None and role not in _VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": 1001,
                "message": (
                    f"Invalid role filter: '{role}'. "
                    f"Expected one of: {', '.join(sorted(_VALID_ROLES))}."
                ),
                "data": None,
            },
        )
    if artifact_type is not None and artifact_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": 1001,
                "message": (
                    f"Invalid type filter: '{artifact_type}'. "
                    f"Expected one of: {', '.join(sorted(_VALID_TYPES))}."
                ),
                "data": None,
            },
        )

    config = ForgeConfig.get_instance()
    db = await _get_project_db(config, project_id)
    try:
        rows = await db.query_artifacts(
            project_id=project_id,
            role=role,
            type=artifact_type,
            module=module,
            limit=limit,
            offset=offset,
        )
        # Transform database rows to match the Artifact model shape.
        artifacts = _db_rows_to_artifacts(rows)
        return StandardResponse(code=0, message="ok", data=artifacts)
    finally:
        await db.close()


@router.get(
    "/projects/{project_id}/artifacts/search",
    response_model=StandardResponse[list[Artifact]],
)
async def search_artifacts(
    project_id: str,
    q: str = Query(..., min_length=1, description="Natural-language search query"),
    limit: int = Query(5, ge=1, le=50, description="Maximum number of results"),
) -> StandardResponse[list[Artifact]]:
    """Semantic (vector) search over artifacts.

    When sqlite-vec is available, generates an embedding for *q* and performs
    a KNN lookup against artifact embeddings.  Otherwise falls back to
    keyword-based SQL ``LIKE`` matching.  Results are ordered by relevance.
    """
    config = ForgeConfig.get_instance()
    db = await _get_project_db(config, project_id)
    try:
        rows = await db.search_artifacts(
            project_id=project_id,
            query=q,
            limit=limit,
        )
        artifacts = _db_rows_to_artifacts(rows)
        return StandardResponse(code=0, message="ok", data=artifacts)
    finally:
        await db.close()


@router.get(
    "/projects/{project_id}/artifacts/{aid}",
    response_model=StandardResponse[Artifact],
)
async def get_artifact(project_id: str, aid: str) -> StandardResponse[Artifact]:
    """Return a single artifact by its unique identifier."""
    config = ForgeConfig.get_instance()
    db = await _get_project_db(config, project_id)
    try:
        row = await db.get_artifact(aid)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": 1002,
                    "message": f"Artifact '{aid}' not found in project '{project_id}'.",
                    "data": None,
                },
            )
        artifact = _db_row_to_artifact(row)
        return StandardResponse(code=0, message="ok", data=artifact)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Internal: database row → Artifact model mapping
# ---------------------------------------------------------------------------


def _db_row_to_artifact(row: dict) -> dict:
    """Map a database artifact row to the Pydantic Artifact model shape.

    Validates *role* and *type* against their respective Pydantic enums so
    that FastAPI response serialisation never fails with a 500.  If a value
    is missing or invalid, a safe default is substituted.
    """
    # Validate role — must be a recognised Role enum member.
    role_val = row.get("role", "")
    try:
        Role(role_val)
    except ValueError:
        role_val = Role.CLAUDE_A.value  # safe default

    # Validate artifact type — must be a recognised ArtifactType enum member.
    type_val = row.get("type", "")
    try:
        ArtifactType(type_val)
    except ValueError:
        type_val = ArtifactType.CODE.value  # safe default

    return {
        "id": row.get("artifact_uuid", row.get("id", "")),
        "role": role_val,
        "type": type_val,
        "module": row.get("module"),
        "title": row.get("title", ""),
        "summary_256": row.get("summary_256", ""),
        "file_path": row.get("file_path"),
        "version": row.get("version", 1),
        "created_at": row.get("created_at", ""),
    }


def _db_rows_to_artifacts(rows: list[dict]) -> list[dict]:
    """Map a list of database artifact rows to Artifact model dicts."""
    return [_db_row_to_artifact(r) for r in rows]
