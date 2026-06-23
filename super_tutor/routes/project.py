"""Project CRUD API routes.

Provides endpoints for listing, creating, viewing, and deleting Forge projects.
"""

import asyncio
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from super_tutor.config import ForgeConfig
from super_tutor.core.database import Database
from super_tutor.core.filesystem import FileSystem
from super_tutor.models import CreateProjectRequest, Project, StandardResponse

router = APIRouter(prefix="/projects", tags=["projects"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _scan_projects(
    config: ForgeConfig, status: Optional[str] = None
) -> list[Project]:
    """Scan *projects_root* for directories that contain a ``forge.db``.

    Opens each project database, reads the project record, and returns a list
    of ``Project`` model instances sorted by creation time (newest first).
    Directories whose database is missing, unreadable, or whose record fails
    Pydantic validation are silently skipped.
    """
    from pydantic import ValidationError

    projects_root = Path(config.projects_root)
    projects: list[Project] = []
    if not projects_root.is_dir():
        return projects

    for entry in sorted(projects_root.iterdir()):
        if not entry.is_dir():
            continue
        db_path = entry / "forge.db"
        if not db_path.exists():
            continue

        db = Database(str(db_path), config=config, projects_root=str(projects_root))
        await db.initialize()
        try:
            record = await db.get_project(entry.name)
            if record and (status is None or record.get("status") == status):
                try:
                    projects.append(Project(**record))
                except ValidationError:
                    continue
        finally:
            await db.close()

    # Sort newest-first by created_at.
    projects.sort(key=lambda p: p.created_at, reverse=True)
    return projects


async def _get_project_db(config: ForgeConfig, project_id: str) -> Database:
    """Open and initialise the project database, or raise 404.

    Args:
        config: ForgeConfig singleton.
        project_id: Project UUID / directory name.

    Returns:
        An initialised ``Database`` instance.  The caller **must** close it.

    Raises:
        HTTPException(404): When the project directory or ``forge.db`` is
            missing.
    """
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


@router.get("", response_model=StandardResponse[list[Project]])
async def list_projects(
    status: Optional[str] = Query(
        None,
        description="Filter by lifecycle status: active, archived, completed",
    ),
) -> StandardResponse[list[Project]]:
    """List all Forge projects, optionally filtered by status."""
    if status is not None and status not in ("active", "archived", "completed"):
        raise HTTPException(
            status_code=400,
            detail={
                "code": 1001,
                "message": f"Invalid status filter: '{status}'. "
                f"Expected one of: active, archived, completed.",
                "data": None,
            },
        )

    config = ForgeConfig.get_instance()
    projects = await _scan_projects(config, status)
    return StandardResponse(code=0, message="ok", data=projects)


@router.post("", response_model=StandardResponse[Project], status_code=201)
async def create_project(body: CreateProjectRequest) -> StandardResponse[Project]:
    """Create a new Forge project.

    When *description* is provided, Claude-A planning is triggered in the
    background immediately after the project record is persisted.  The
    response returns the project metadata without waiting for planning to
    finish — use the workflow status endpoint to monitor progress.
    """
    if not body.name.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "code": 1001,
                "message": "Project name must not be empty.",
                "data": None,
            },
        )

    config = ForgeConfig.get_instance()
    projects_root = Path(config.projects_root)
    projects_root.mkdir(parents=True, exist_ok=True)

    project_id = str(uuid.uuid4())
    project_path = projects_root / project_id
    project_path.mkdir(parents=True, exist_ok=True)

    # Initialise the six-zone directory structure.
    fs = FileSystem(str(project_path))
    fs.init_project_structure()

    # Create the project database and insert the initial record.
    db_path = project_path / "forge.db"
    db = Database(str(db_path), config=config, projects_root=str(projects_root))
    await db.initialize()

    now = datetime.now(timezone.utc).isoformat()
    project_data: dict = {
        "id": project_id,
        "name": body.name.strip(),
        "path": str(project_path),
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "repo_url": None,
        "summary": body.description[:256] if body.description else "",
    }

    try:
        await db.create_project(project_data)

        # Kick off Claude-A planning in the background when a description is
        # supplied.  The task runs independently of the HTTP response.
        if body.description.strip():
            asyncio.create_task(
                _launch_planning(
                    project_id, str(project_path), config, body.description.strip()
                )
            )

        return StandardResponse(code=0, message="ok", data=project_data)
    finally:
        await db.close()


@router.get("/{project_id}", response_model=StandardResponse[Project])
async def get_project(project_id: str) -> StandardResponse[Project]:
    """Return a single project's details."""
    config = ForgeConfig.get_instance()
    db = await _get_project_db(config, project_id)
    try:
        project = await db.get_project(project_id)
        if project is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": 1002,
                    "message": f"Project '{project_id}' not found.",
                    "data": None,
                },
            )
        return StandardResponse(code=0, message="ok", data=project)
    finally:
        await db.close()


@router.delete("/{project_id}", response_model=StandardResponse[dict])
async def delete_project(project_id: str) -> StandardResponse[dict]:
    """Delete a project and all its files.

    Stops any running orchestrator, closes the database connection, and
    removes the entire project directory tree from disk.
    """
    config = ForgeConfig.get_instance()
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

    # Stop and clean up any running orchestrator for this project.
    from super_tutor.routes import _orchestrators

    orch = _orchestrators.pop(project_id, None)
    if orch is not None:
        try:
            await orch._db.close()
        except Exception:
            pass

    shutil.rmtree(str(project_dir))
    return StandardResponse(code=0, message="ok", data={"id": project_id})


# ---------------------------------------------------------------------------
# Background planning launcher
# ---------------------------------------------------------------------------


async def _launch_planning(
    project_id: str, project_root: str, config: ForgeConfig, description: str
) -> None:
    """Launch Claude-A planning in the background for a newly created project.

    Constructs the Orchestrator and shared dependencies (LLMClient,
    RoleManager), stores the orchestrator in the shared registry, and
    calls ``start()`` to begin the planning phase.

    Failures are logged but not re-raised — the background task is
    fire-and-forget from the HTTP handler's perspective.
    """
    import logging

    from super_tutor.core.llm_client import LLMClient
    from super_tutor.core.orchestrator import Orchestrator
    from super_tutor.core.role_manager import RoleManager
    from super_tutor.routes import _orchestrators

    logger = logging.getLogger(__name__)

    try:
        # Resolve the prompts directory relative to the super_tutor package.
        import super_tutor

        engine_dir = Path(super_tutor.__file__).parent  # type: ignore[attr-defined]
        prompts_dir = engine_dir / "prompts"

        llm_client = LLMClient(config, project_root=project_root)
        role_manager = RoleManager(str(prompts_dir))
        fs = FileSystem(project_root)
        db_path = Path(project_root) / "forge.db"
        db = Database(str(db_path), config=config, projects_root=config.projects_root)
        await db.initialize()

        orch = Orchestrator(
            project_root=project_root,
            llm_client=llm_client,
            role_manager=role_manager,
            filesystem=fs,
            database=db,
            project_id=project_id,
        )

        _orchestrators[project_id] = orch
        logger.info("Starting Claude-A planning for project %s.", project_id)
        await orch.start()
        logger.info("Claude-A planning completed for project %s.", project_id)

    except Exception as exc:
        logger.error(
            "Background planning failed for project %s: %s", project_id, exc
        )
