"""Workflow control and status API routes.

Exposes endpoints to start, pause, resume, retry and stream the AI
collaboration workflow for a given project.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from super_tutor.config import ForgeConfig
from super_tutor.core.database import Database
from super_tutor.core.filesystem import FileSystem
from super_tutor.core.llm_client import LLMClient
from super_tutor.core.orchestrator import Orchestrator, OrchestratorError
from super_tutor.core.role_manager import RoleManager
from super_tutor.models import StandardResponse, WorkflowStatus

router = APIRouter(tags=["workflow"])

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared dependency singletons (lazily initialised)
# ---------------------------------------------------------------------------

_llm_client: Optional[LLMClient] = None
_role_manager: Optional[RoleManager] = None


def _get_llm_client(config: ForgeConfig) -> LLMClient:
    """Return the shared LLMClient singleton, creating it on first call."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(config)
    return _llm_client


def _get_role_manager() -> RoleManager:
    """Return the shared RoleManager singleton, creating it on first call."""
    global _role_manager
    if _role_manager is None:
        import super_tutor

        engine_dir = Path(super_tutor.__file__).parent  # type: ignore[attr-defined]
        prompts_dir = engine_dir / "prompts"
        _role_manager = RoleManager(str(prompts_dir))
    return _role_manager


# ---------------------------------------------------------------------------
# Orchestrator lifecycle helpers
# ---------------------------------------------------------------------------


async def _get_orchestrator(project_id: str) -> Orchestrator:
    """Retrieve or lazily create the Orchestrator for *project_id*.

    When no orchestrator exists yet (e.g. the project was created without
    a description, so no background planning was launched) one is built
    on the fly and stored in the shared registry.

    Raises:
        HTTPException(404): When the project directory or database is missing.
    """
    from super_tutor.routes import _orchestrators

    if project_id in _orchestrators:
        return _orchestrators[project_id]

    # Lazy construction: open the database, wire up dependencies.
    config = ForgeConfig.get_instance()
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

    fs = FileSystem(str(project_dir))
    llm = _get_llm_client(config)
    rm = _get_role_manager()

    orch = Orchestrator(
        project_root=str(project_dir),
        llm_client=llm,
        role_manager=rm,
        filesystem=fs,
        database=db,
        project_id=project_id,
    )

    _orchestrators[project_id] = orch
    logger.info("Lazily created orchestrator for project %s.", project_id)
    return orch


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/status",
    response_model=StandardResponse[WorkflowStatus],
)
async def get_workflow_status(project_id: str) -> StandardResponse[WorkflowStatus]:
    """Return the current workflow status for a project."""
    orch = await _get_orchestrator(project_id)
    status_dict = await orch.get_status()
    return StandardResponse(code=0, message="ok", data=status_dict)


@router.post("/projects/{project_id}/start", response_model=StandardResponse[dict])
async def start_workflow(project_id: str) -> StandardResponse[dict]:
    """Start the workflow: **IDLE → PLANNING**.

    Launches Claude-A to produce requirements, constitution, API spec, and
    task board.  Only valid when the workflow is in ``IDLE`` state.
    """
    orch = await _get_orchestrator(project_id)

    if orch.state.value != "idle":
        raise HTTPException(
            status_code=409,
            detail={
                "code": 1003,
                "message": (
                    f"Cannot start workflow from state '{orch.state.value}'. "
                    f"Expected 'idle'."
                ),
                "data": None,
            },
        )

    try:
        await orch.start()
        return StandardResponse(
            code=0, message="ok", data={"project_id": project_id, "state": orch.state.value}
        )
    except OrchestratorError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": 1003, "message": str(exc), "data": None},
        )


@router.post("/projects/{project_id}/pause", response_model=StandardResponse[dict])
async def pause_workflow(project_id: str) -> StandardResponse[dict]:
    """Pause the workflow from any active state.

    Idempotent: pausing an already-paused workflow is a no-op.  Terminal
    states (``done``, ``error``) cannot be paused.
    """
    orch = await _get_orchestrator(project_id)

    if orch.state.value in ("done", "error"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": 1003,
                "message": (
                    f"Cannot pause workflow from terminal state "
                    f"'{orch.state.value}'."
                ),
                "data": None,
            },
        )

    try:
        await orch.pause()
        return StandardResponse(
            code=0, message="ok", data={"project_id": project_id, "state": orch.state.value}
        )
    except OrchestratorError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": 1003, "message": str(exc), "data": None},
        )


@router.post("/projects/{project_id}/resume", response_model=StandardResponse[dict])
async def resume_workflow(project_id: str) -> StandardResponse[dict]:
    """Resume the workflow from ``paused`` back to its previous state."""
    orch = await _get_orchestrator(project_id)

    if orch.state.value != "paused":
        raise HTTPException(
            status_code=409,
            detail={
                "code": 1003,
                "message": (
                    f"Cannot resume workflow from state '{orch.state.value}'. "
                    f"Expected 'paused'."
                ),
                "data": None,
            },
        )

    try:
        await orch.resume()
        return StandardResponse(
            code=0, message="ok", data={"project_id": project_id, "state": orch.state.value}
        )
    except OrchestratorError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": 1003, "message": str(exc), "data": None},
        )


@router.post("/projects/{project_id}/retry", response_model=StandardResponse[dict])
async def retry_workflow_step(project_id: str) -> StandardResponse[dict]:
    """Retry the current step after an error.

    Resets the error state and re-executes the failed phase.  Limited to 3
    consecutive retries; after that the workflow stays in ``error`` and
    requires manual intervention.
    """
    orch = await _get_orchestrator(project_id)

    if orch.state.value != "error":
        raise HTTPException(
            status_code=409,
            detail={
                "code": 1003,
                "message": (
                    f"Cannot retry from state '{orch.state.value}'. "
                    f"Expected 'error'."
                ),
                "data": None,
            },
        )

    try:
        await orch.retry_step()
        return StandardResponse(
            code=0, message="ok", data={"project_id": project_id, "state": orch.state.value}
        )
    except OrchestratorError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": 1003, "message": str(exc), "data": None},
        )


@router.get("/projects/{project_id}/stream")
async def stream_workflow_status(project_id: str, request: Request):
    """SSE endpoint that pushes workflow status updates in real time.

    The client receives ``data: <json>`` events every second containing the
    full workflow status snapshot.  The stream ends when the workflow reaches
    a terminal state (``done`` or ``error``) or the client disconnects.
    """
    orch = await _get_orchestrator(project_id)

    async def event_generator():
        terminal_states = {"done", "error"}
        while True:
            if await request.is_disconnected():
                break

            status = await orch.get_status()
            yield f"data: {json.dumps(status, ensure_ascii=False)}\n\n"

            if status["state"] in terminal_states:
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
