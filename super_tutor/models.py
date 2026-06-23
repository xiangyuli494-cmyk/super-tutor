"""Pydantic v2 data models for the Forge Engine API.

Maps 1:1 to the schemas defined in constitution/api-spec.yaml.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Optional, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProjectStatus(str, Enum):
    """Project lifecycle status."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    COMPLETED = "completed"


class Role(str, Enum):
    """AI role identifiers within the Forge workflow."""

    CLAUDE_A = "claude-a"
    CODEX = "codex"
    CLAUDE_B = "claude-b"


class ArtifactType(str, Enum):
    """Types of artifacts produced during the workflow."""

    REQUIREMENT = "requirement"
    CONSTITUTION = "constitution"
    API_SPEC = "api-spec"
    CODE = "code"
    AUDIT = "audit"
    ACCEPTANCE = "acceptance"


class WorkflowState(str, Enum):
    """States of the workflow state machine."""

    IDLE = "idle"
    PLANNING = "planning"
    CODING = "coding"
    AUDITING = "auditing"
    ACCEPTING = "accepting"
    DONE = "done"
    PAUSED = "paused"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Generic response wrapper
# ---------------------------------------------------------------------------

T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    """Standard API response envelope used by every endpoint.

    Attributes:
        code: Status code (0 = success).
        message: Human-readable status message.
        data: Response payload, typed per-endpoint.
    """

    code: int = 0
    message: str = "ok"
    data: Optional[T] = None


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class Project(BaseModel):
    """A Forge project managed by the AI workflow.

    Attributes:
        id: Unique project identifier (UUID).
        name: Human-readable project name.
        path: Filesystem path where project files reside.
        status: Current lifecycle status.
        created_at: Timestamp of project creation.
        updated_at: Timestamp of last project update.
        repo_url: Optional GitHub repository URL.
        summary: Short project description (max 256 chars).
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    path: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: datetime = Field(default_factory=datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=datetime.now(timezone.utc))
    repo_url: Optional[str] = None
    summary: str = Field(default="", max_length=256)


class RoleStatus(BaseModel):
    """Status of a single AI role within a workflow."""

    status: str = "idle"
    current_task: Optional[str] = None


class RoleStatuses(BaseModel):
    """Collection of role statuses keyed by role name."""

    claude_a: RoleStatus = Field(default_factory=RoleStatus, alias="claude-a")
    codex: RoleStatus = Field(default_factory=RoleStatus)
    claude_b: RoleStatus = Field(default_factory=RoleStatus, alias="claude-b")

    model_config = ConfigDict(populate_by_name=True)


class WorkflowStatus(BaseModel):
    """Real-time status of a project workflow.

    Attributes:
        project_id: The project this status belongs to.
        state: Current state machine state.
        current_module: The module currently being processed (if any).
        roles: Per-role status details.
    """

    project_id: str
    state: WorkflowState = WorkflowState.IDLE
    current_module: Optional[str] = None
    roles: RoleStatuses = Field(default_factory=RoleStatuses)


class Artifact(BaseModel):
    """An artifact (document, code, report) produced by an AI role.

    Attributes:
        id: Unique artifact identifier.
        role: Which AI role produced this artifact.
        type: The kind of artifact.
        module: Optional module name the artifact belongs to.
        title: Human-readable title.
        summary_256: Short summary (max 256 chars).
        file_path: Optional path to the file on disk.
        version: Artifact version number (increments on updates).
        created_at: Timestamp of first creation.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    role: Role
    type: ArtifactType
    module: Optional[str] = None
    title: str = ""
    summary_256: str = Field(default="", max_length=256)
    file_path: Optional[str] = None
    version: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc)().isoformat() + "Z")


class TokenByRole(BaseModel):
    """Token consumption breakdown by role."""

    claude_a: int = Field(default=0, alias="claude-a")
    codex: int = 0
    claude_b: int = Field(default=0, alias="claude-b")

    model_config = ConfigDict(populate_by_name=True)


class TokenUsage(BaseModel):
    """Token budget and consumption for a project.

    Attributes:
        project_id: The project this usage belongs to.
        budget: Total token budget allocated.
        used: Tokens consumed so far.
        remaining: Tokens remaining (budget - used).
        by_role: Breakdown of consumption by AI role.
    """

    project_id: str
    budget: int = 1_000_000
    used: int = 0
    remaining: int = 1_000_000
    by_role: TokenByRole = Field(default_factory=TokenByRole)


class ErrorDetail(BaseModel):
    """Structured error information returned in responses."""

    code: int
    message: str
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateProjectRequest(BaseModel):
    """Request body for creating a new project."""

    name: str
    description: str = ""
    template: str = "default"
