"""Workflow orchestrator — the heart of the Forge AI collaboration engine.

Implements a state-machine-driven pipeline that coordinates three AI roles
(Claude-A, Codex, Claude-B) through a structured software development
workflow: planning → coding → auditing → accepting.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from super_tutor.models import WorkflowState
from super_tutor.core.database import Database
from super_tutor.core.exceptions import ForgeError, LLMClientError, VALID_ROLES
from super_tutor.core.filesystem import FileSystem
from super_tutor.core.llm_client import LLMClient
from super_tutor.core.role_manager import RoleManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_STEP_RETRIES: int = 3
"""Maximum number of consecutive retry attempts before staying in ERROR."""

_PLANNING_MODEL_TIER: str = "heavy"
_CODING_MODEL_TIER: str = "heavy"
_AUDITING_MODEL_TIER: str = "medium"
_ACCEPTING_MODEL_TIER: str = "medium"


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class OrchestratorError(ForgeError):
    """Errors originating from the Orchestrator layer."""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """State-machine-driven workflow orchestrator for Forge projects.

    Coordinates the three AI roles through a structured pipeline:

    1. **Planning** – Claude-A produces requirements, constitution, API spec,
       and task board.
    2. **Coding** – Codex implements each module listed in the task board,
       writing code into the sandbox zone.
    3. **Auditing** – Claude-B reviews the sandbox output against the
       constitution; rejects non-compliant work.
    4. **Accepting** – Claude-A performs final acceptance; either approves
       the module or sends it back to coding.

    Modules are processed one at a time: coding → auditing → accepting forms
    a per-module loop that repeats until every module on the task board
    passes acceptance.

    Attributes:
        project_id: Unique project identifier.
        project_root: Absolute path to the project root directory.
        state: Current workflow state (read-only property).
    """

    def __init__(
        self,
        project_root: str,
        llm_client: LLMClient,
        role_manager: RoleManager,
        filesystem: FileSystem,
        database: Database,
        project_id: str | None = None,
    ) -> None:
        """Initialise the orchestrator.

        Args:
            project_root: Absolute path to the Forge project root.
            llm_client: Configured LLM client for API calls.
            role_manager: Role system-prompt manager.
            filesystem: Permission-aware filesystem manager.
            database: Project database (must already be initialised via
                ``Database.initialize()``).
            project_id: Optional project UUID.  When *None* the project-root
                directory name is used as a fallback identifier.
        """
        self._project_root: Path = Path(project_root).resolve()
        self._project_id: str = project_id or self._project_root.name
        self._llm: LLMClient = llm_client
        self._roles: RoleManager = role_manager
        self._fs: FileSystem = filesystem
        self._db: Database = database

        # ------------------------------------------------------------------
        # State machine
        # ------------------------------------------------------------------
        self._state: WorkflowState = WorkflowState.IDLE
        self._previous_state: WorkflowState = WorkflowState.IDLE
        self._error_message: Optional[str] = None

        # ------------------------------------------------------------------
        # Module iteration
        # ------------------------------------------------------------------
        self._modules: list[dict[str, Any]] = []
        self._module_index: int = 0
        self._current_module: Optional[str] = None

        # ------------------------------------------------------------------
        # Phase results — govern state transitions in ``proceed()``.
        # ------------------------------------------------------------------
        self._audit_passed: bool = False
        self._acceptance_passed: bool = False

        # ------------------------------------------------------------------
        # Retry tracking
        # ------------------------------------------------------------------
        self._step_retry_count: int = 0

        # ------------------------------------------------------------------
        # Per-role status tracking
        # ------------------------------------------------------------------
        self._role_statuses: dict[str, str] = {
            "claude-a": "idle",
            "codex": "idle",
            "claude-b": "idle",
        }
        self._role_tasks: dict[str, Optional[str]] = {
            "claude-a": None,
            "codex": None,
            "claude-b": None,
        }

    # ==================================================================
    # Properties
    # ==================================================================

    @property
    def state(self) -> WorkflowState:
        """Return the current workflow state."""
        return self._state

    @property
    def project_id(self) -> str:
        """Return the project identifier."""
        return self._project_id

    # ==================================================================
    # State-machine controls (public API)
    # ==================================================================

    async def start(self) -> None:
        """Start the workflow: **IDLE → PLANNING**.

        Triggers Claude-A to produce the requirements document, project
        constitution, API specification, and task board.  On success the
        state settles at ``PLANNING``; the caller should then invoke
        ``proceed()`` to advance through the remaining phases.

        Raises:
            OrchestratorError: If called from a state other than ``IDLE``.
        """
        if self._state != WorkflowState.IDLE:
            raise OrchestratorError(
                f"Cannot start from state '{self._state.value}'. "
                f"Expected '{WorkflowState.IDLE.value}'."
            )

        self._transition_to(WorkflowState.PLANNING)
        await self._planning_phase()

    async def proceed(self) -> None:
        """Advance the workflow by one step.

        Reads the current state, determines the next transition, and
        executes the corresponding phase.  Module-level rejections (audit
        or acceptance failure) route back to ``CODING`` for the same
        module so Codex can apply fixes.

        Raises:
            OrchestratorError: If called from ``IDLE``, ``PAUSED``, ``ERROR``,
                or ``DONE`` — use ``start()`` first, or ``resume()`` /
                ``retry_step()`` instead.
        """
        if self._state in (WorkflowState.IDLE, WorkflowState.PAUSED,
                            WorkflowState.ERROR, WorkflowState.DONE):
            raise OrchestratorError(
                f"Cannot proceed from state '{self._state.value}'. "
                f"Use start() first, or resume()/retry_step() instead."
            )

        next_state = self._compute_next_state()
        self._transition_to(next_state)
        await self._execute_phase(next_state)

    async def pause(self) -> None:
        """Pause the workflow from any active state.

        Saves the current state so ``resume()`` can restore it later.
        Calling ``pause()`` while already paused is a no-op.

        Raises:
            OrchestratorError: If called from a terminal state (``DONE``
                or ``ERROR``).
        """
        if self._state == WorkflowState.PAUSED:
            return  # Already paused — idempotent.
        if self._state in (WorkflowState.DONE, WorkflowState.ERROR):
            raise OrchestratorError(
                f"Cannot pause from terminal state '{self._state.value}'."
            )

        self._previous_state = self._state
        self._transition_to(WorkflowState.PAUSED)
        logger.info("Workflow paused (was %s).", self._previous_state.value)

    async def resume(self) -> None:
        """Resume the workflow from ``PAUSED`` back to the previous state.

        Raises:
            OrchestratorError: If not currently ``PAUSED``.
        """
        if self._state != WorkflowState.PAUSED:
            raise OrchestratorError(
                f"Cannot resume from state '{self._state.value}'. "
                f"Expected '{WorkflowState.PAUSED.value}'."
            )

        self._transition_to(self._previous_state)
        logger.info("Workflow resumed to %s.", self._state.value)

    async def retry_step(self) -> None:
        """Retry the current step after an error.

        Resets error state and re-executes the phase that failed.  Limited
        to ``_MAX_STEP_RETRIES`` consecutive retries; exceeding this limit
        leaves the orchestrator in ``ERROR`` to avoid infinite loops.

        Raises:
            OrchestratorError: If not currently in ``ERROR`` state.
        """
        if self._state != WorkflowState.ERROR:
            raise OrchestratorError(
                f"Cannot retry from state '{self._state.value}'. "
                f"Expected '{WorkflowState.ERROR.value}'."
            )

        self._step_retry_count += 1
        if self._step_retry_count > _MAX_STEP_RETRIES:
            self._error_message = (
                f"Step retry limit ({_MAX_STEP_RETRIES}) exceeded. "
                f"Manual intervention required."
            )
            logger.error(self._error_message)
            return  # Stay in ERROR.

        # Restore to the state that failed, then re-execute.
        failed_state = self._previous_state
        self._transition_to(failed_state)
        logger.info(
            "Retrying step (attempt %d/%d) in state %s.",
            self._step_retry_count,
            _MAX_STEP_RETRIES,
            failed_state.value,
        )
        self._error_message = None
        await self._execute_phase(failed_state)

    async def get_status(self) -> dict[str, Any]:
        """Return the current workflow status as a dictionary.

        The returned dict matches the ``WorkflowStatus`` Pydantic model
        shape and is suitable for JSON serialisation.

        Returns:
            A dict with keys ``project_id``, ``state``, ``current_module``,
            ``modules_total``, ``modules_completed``, ``modules_remaining``,
            ``roles``, and ``error_message``.
        """
        modules_total = len(self._modules)
        modules_completed = self._module_index
        modules_remaining = max(0, modules_total - modules_completed)

        return {
            "project_id": self._project_id,
            "state": self._state.value,
            "current_module": self._current_module,
            "modules_total": modules_total,
            "modules_completed": modules_completed,
            "modules_remaining": modules_remaining,
            "roles": {
                "claude-a": {
                    "status": self._role_statuses.get("claude-a", "idle"),
                    "current_task": self._role_tasks.get("claude-a"),
                },
                "codex": {
                    "status": self._role_statuses.get("codex", "idle"),
                    "current_task": self._role_tasks.get("codex"),
                },
                "claude-b": {
                    "status": self._role_statuses.get("claude-b", "idle"),
                    "current_task": self._role_tasks.get("claude-b"),
                },
            },
            "error_message": self._error_message,
        }

    # ==================================================================
    # Phase implementations
    # ==================================================================

    async def _planning_phase(self) -> None:
        """Claude-A produces requirements, constitution, API spec, and task board.

        On completion the planning artifacts are persisted to the
        ``constitution/`` zone and the module list is parsed from the
        generated task board.
        """
        self._set_role_status("claude-a", "active", "生成需求文档与项目宪法")

        try:
            planning_prompt = _build_planning_prompt()

            system_prompt = self._roles.build_context(
                role="claude-a",
                project_path=str(self._project_root),
                extra_context={
                    "phase": "planning",
                    "action": "生成完整项目规划文档集",
                },
            )

            response = await self._invoke_role(
                role="claude-a",
                user_message=planning_prompt,
                system_prompt=system_prompt,
                tier=_PLANNING_MODEL_TIER,
            )

            # Parse the response and write individual constitution files.
            await self._persist_planning_artifacts(response)

            # Parse modules from the generated task board.
            self._modules = await self._parse_task_board()

            # Record the planning artifact.
            await self._on_step_complete(
                role="claude-a",
                artifact={
                    "type": "constitution",
                    "title": "项目规划文档集",
                    "summary_256": "需求文档、项目宪法、接口规范、任务清单",
                    "full_text": response[:2000],
                    "file_path": "constitution/",
                },
            )

            self._set_role_status("claude-a", "idle", None)
            logger.info(
                "Planning phase complete. %d modules parsed from task board.",
                len(self._modules),
            )

        except Exception as exc:
            self._set_role_status("claude-a", "error", str(exc))
            self._handle_phase_error(exc)
            raise

    async def _coding_phase(self) -> None:
        """Codex implements the current module, writing output to ``sandbox/``.

        Reads the module specification from the task board, builds a
        coding prompt augmented with constitution context, and invokes
        Codex to produce the implementation.

        When no more modules remain the phase is a no-op (all modules have
        been accepted).
        """
        if not self._modules or self._module_index >= len(self._modules):
            logger.info("No more modules to code — all modules accepted.")
            return

        module = self._modules[self._module_index]
        self._current_module = module.get("id", f"m{self._module_index + 1}")
        module_name = module.get("name", self._current_module)
        module_tasks = module.get("tasks", "")

        self._set_role_status("codex", "active", f"编码模块: {self._current_module}")

        # Reset phase-result flags for the new (or retried) module round.
        self._audit_passed = False
        self._acceptance_passed = False

        try:
            coding_prompt = _build_coding_prompt(
                module_id=self._current_module,
                module_name=module_name,
                module_tasks=module_tasks,
            )

            context_files = _collect_constitution_files(
                self._project_root, "requirements.md", "api-spec.yaml", "task-board.md"
            )

            system_prompt = self._roles.build_context(
                role="codex",
                project_path=str(self._project_root),
                extra_context={
                    "phase": "coding",
                    "current_module": self._current_module,
                    "output_dir": f"sandbox/{self._current_module}/",
                },
            )

            response = await self._invoke_role(
                role="codex",
                user_message=coding_prompt,
                context_files=context_files,
                system_prompt=system_prompt,
                tier=_CODING_MODEL_TIER,
            )

            # Save Codex response as an artifact.
            await self._on_step_complete(
                role="codex",
                artifact={
                    "type": "code",
                    "module": self._current_module,
                    "title": f"{self._current_module}: {module_name}",
                    "summary_256": f"模块 {self._current_module} 的代码实现",
                    "full_text": response[:2000],
                    "file_path": f"sandbox/{self._current_module}/",
                },
            )

            self._set_role_status("codex", "idle", None)
            logger.info("Coding phase complete for module %s.", self._current_module)

        except Exception as exc:
            self._set_role_status("codex", "error", str(exc))
            self._handle_phase_error(exc)
            raise

    async def _auditing_phase(self) -> None:
        """Claude-B audits the sandbox code produced by Codex.

        Reviews code against the constitution, API spec, and code-style
        rules.  Produces an audit report in ``test/``.  The ``_audit_passed``
        flag is set based on the audit conclusion and governs the next state
        transition.
        """
        if not self._current_module:
            raise OrchestratorError("No current module to audit.")

        self._set_role_status("claude-b", "active", f"审计模块: {self._current_module}")

        try:
            audit_prompt = _build_audit_prompt(self._current_module)

            context_files = _collect_constitution_files(
                self._project_root, "requirements.md", "api-spec.yaml"
            )
            context_files.extend(
                _collect_sandbox_files(self._project_root, self._current_module)
            )

            system_prompt = self._roles.build_context(
                role="claude-b",
                project_path=str(self._project_root),
                extra_context={
                    "phase": "auditing",
                    "current_module": self._current_module,
                    "sandbox_path": f"sandbox/{self._current_module}/",
                },
            )

            response = await self._invoke_role(
                role="claude-b",
                user_message=audit_prompt,
                context_files=context_files,
                system_prompt=system_prompt,
                tier=_AUDITING_MODEL_TIER,
            )

            # Determine pass/fail and persist the audit report.
            self._audit_passed = self._parse_audit_result(response)

            audit_path = f"test/{self._current_module}-audit.md"
            self._fs.write_file("claude-b", audit_path, response)

            await self._on_step_complete(
                role="claude-b",
                artifact={
                    "type": "audit",
                    "module": self._current_module,
                    "title": f"审计报告: {self._current_module}",
                    "summary_256": (
                        f"模块 {self._current_module} 审计"
                        f"{'通过' if self._audit_passed else '驳回'}"
                    ),
                    "full_text": response[:2000],
                    "file_path": audit_path,
                },
            )

            self._set_role_status("claude-b", "idle", None)
            logger.info(
                "Auditing phase complete for module %s: %s.",
                self._current_module,
                "PASS" if self._audit_passed else "FAIL",
            )

        except Exception as exc:
            self._set_role_status("claude-b", "error", str(exc))
            self._handle_phase_error(exc)
            raise

    async def _accepting_phase(self) -> None:
        """Claude-A performs final acceptance of the current module.

        Reviews the sandbox code and audit report, then issues an
        acceptance verdict.  Accepted modules are migrated from ``sandbox/``
        to ``src/`` via ``FileSystem.migrate_to_src()``.  Rejected modules
        return to coding.
        """
        if not self._current_module:
            raise OrchestratorError("No current module to accept.")

        self._set_role_status("claude-a", "active", f"验收模块: {self._current_module}")

        try:
            acceptance_prompt = _build_acceptance_prompt(self._current_module)

            context_files = _collect_constitution_files(
                self._project_root, "requirements.md", "api-spec.yaml"
            )
            # Include the audit report if it exists.
            audit_path = str(
                self._project_root / "test" / f"{self._current_module}-audit.md"
            )
            if Path(audit_path).is_file():
                context_files.append(audit_path)
            context_files.extend(
                _collect_sandbox_files(self._project_root, self._current_module)
            )

            system_prompt = self._roles.build_context(
                role="claude-a",
                project_path=str(self._project_root),
                extra_context={
                    "phase": "accepting",
                    "current_module": self._current_module,
                    "audit_report": audit_path,
                },
            )

            response = await self._invoke_role(
                role="claude-a",
                user_message=acceptance_prompt,
                context_files=context_files,
                system_prompt=system_prompt,
                tier=_ACCEPTING_MODEL_TIER,
            )

            # Determine pass/fail and persist the acceptance report.
            self._acceptance_passed = self._parse_acceptance_result(response)

            self._fs.ensure_zone("review")
            acceptance_path = f"review/acceptance/{self._current_module}.md"
            self._fs.write_file("claude-a", acceptance_path, response)

            await self._on_step_complete(
                role="claude-a",
                artifact={
                    "type": "acceptance",
                    "module": self._current_module,
                    "title": f"验收报告: {self._current_module}",
                    "summary_256": (
                        f"模块 {self._current_module} 验收"
                        f"{'通过' if self._acceptance_passed else '驳回'}"
                    ),
                    "full_text": response[:2000],
                    "file_path": acceptance_path,
                },
            )

            # Migrate sandbox → src when acceptance passes.
            if self._acceptance_passed:
                try:
                    self._fs.migrate_to_src(self._current_module)
                    logger.info(
                        "Module %s migrated from sandbox to src.", self._current_module
                    )
                except Exception as mig_exc:
                    logger.warning(
                        "Migration failed for module %s: %s",
                        self._current_module,
                        mig_exc,
                    )

            self._set_role_status("claude-a", "idle", None)
            logger.info(
                "Acceptance phase complete for module %s: %s.",
                self._current_module,
                "PASS" if self._acceptance_passed else "FAIL",
            )

        except Exception as exc:
            self._set_role_status("claude-a", "error", str(exc))
            self._handle_phase_error(exc)
            raise

    # ==================================================================
    # _invoke_role — LLM call wrapper
    # ==================================================================

    async def _invoke_role(
        self,
        role: str,
        user_message: str,
        context_files: list[str] | None = None,
        system_prompt: str | None = None,
        tier: str = "medium",
    ) -> str:
        """Invoke an AI role with the given message and optional file context.

        Wraps ``LLMClient.chat_with_file_context`` and adds:

        * Token-usage logging via ``Database.log_token_usage``.
        * Error propagation (``LLMClientError`` is re-raised; unexpected
          exceptions are wrapped in ``LLMClientError``).
        * Input validation for the *role* identifier.

        Args:
            role: Role identifier (``"claude-a"``, ``"codex"``, ``"claude-b"``).
            user_message: The instruction or question for the role.
            context_files: Optional list of absolute file paths to include
                as context blocks in the prompt.
            system_prompt: Optional system prompt string.  When *None* the
                role's default system prompt is loaded via ``RoleManager``.
            tier: Computation tier (``"heavy"``, ``"medium"``, ``"light"``).

        Returns:
            The LLM response text.

        Raises:
            LLMClientError: If the API call fails after all retries, or if
                an unexpected exception occurs during the invocation.
        """
        if role not in VALID_ROLES:
            raise OrchestratorError(
                f"Unknown role '{role}'. Expected one of: {sorted(VALID_ROLES)}"
            )

        try:
            response = await self._llm.chat_with_file_context(
                role=role,
                user_message=user_message,
                files=context_files or [],
                tier=tier,
                system_prompt=system_prompt,
            )

            # Record token usage (estimated — the current LLMClient interface
            # does not expose exact prompt/completion token counts).
            await self._db.log_token_usage(
                {
                    "project_id": self._project_id,
                    "role": role,
                    "tier": tier,
                    "total_tokens": _estimate_tokens(user_message, response),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )

            return response

        except LLMClientError:
            raise
        except Exception as exc:
            logger.error("Unexpected error invoking role %s: %s", role, exc)
            raise LLMClientError(
                f"Failed to invoke role '{role}': {exc}"
            ) from exc

    # ==================================================================
    # State-machine helpers
    # ==================================================================

    def _compute_next_state(self) -> WorkflowState:
        """Determine the next state based on the current state and phase results.

        Returns:
            The next ``WorkflowState`` to transition to.
        """
        current = self._state

        if current == WorkflowState.IDLE:
            return WorkflowState.PLANNING

        if current == WorkflowState.PLANNING:
            return WorkflowState.CODING

        if current == WorkflowState.CODING:
            if not self._modules or self._module_index >= len(self._modules):
                return WorkflowState.DONE
            return WorkflowState.AUDITING

        if current == WorkflowState.AUDITING:
            if self._audit_passed:
                return WorkflowState.ACCEPTING
            else:
                return WorkflowState.CODING

        if current == WorkflowState.ACCEPTING:
            if self._acceptance_passed:
                self._module_index += 1
                if self._module_index < len(self._modules):
                    return WorkflowState.CODING
                else:
                    return WorkflowState.DONE
            else:
                return WorkflowState.CODING

        # PAUSED, ERROR, DONE — no automatic transition.
        return current

    def _transition_to(self, new_state: WorkflowState) -> None:
        """Update the state machine to *new_state* and log the transition.

        Args:
            new_state: The target state.
        """
        old_state = self._state
        self._state = new_state
        logger.info("State transition: %s → %s", old_state.value, new_state.value)

    async def _execute_phase(self, state: WorkflowState) -> None:
        """Execute the phase corresponding to *state*.

        Args:
            state: The state whose phase should be executed.
        """
        if state == WorkflowState.CODING:
            await self._coding_phase()
        elif state == WorkflowState.AUDITING:
            await self._auditing_phase()
        elif state == WorkflowState.ACCEPTING:
            await self._accepting_phase()
        elif state == WorkflowState.DONE:
            logger.info("Workflow complete — all modules accepted.")
        # PLANNING is handled by ``start()``, not via ``proceed()``.

        # Reset the per-step retry counter after any successful phase execution
        # so that the limit of _MAX_STEP_RETRIES applies per-step, not globally
        # across the entire workflow lifetime (see audit A3).
        self._step_retry_count = 0

    def _handle_phase_error(self, exc: Exception) -> None:
        """Handle a phase-level error by transitioning to ERROR state.

        Args:
            exc: The exception that caused the error.
        """
        self._error_message = str(exc)
        self._previous_state = self._state
        self._transition_to(WorkflowState.ERROR)
        logger.error("Phase failed with error: %s", exc)

    # ==================================================================
    # Result parsing
    # ==================================================================

    @staticmethod
    def _parse_audit_result(response: str) -> bool:
        """Parse the audit response to determine pass/fail.

        Looks for explicit pass/fail markers near the end of the response.
        When no clear marker is found, a heuristic word-count comparison
        in the final portion of the text is used as a fallback.

        Args:
            response: The full audit report text.

        Returns:
            ``True`` if the audit passed, ``False`` otherwise.
        """
        response_lower = response.lower()

        # Explicit markers (Chinese + English).
        pass_markers = [
            "通过 (pass)",
            "**通过**",
            "结论：通过",
            "结论: 通过",
            "verdict: pass",
        ]
        fail_markers = [
            "驳回 (fail)",
            "**驳回**",
            "结论：驳回",
            "结论: 驳回",
            "verdict: fail",
        ]

        for marker in pass_markers:
            if marker in response_lower:
                return True
        for marker in fail_markers:
            if marker in response_lower:
                return False

        # Heuristic: compare pass/fail keyword frequency in the last 2000 chars.
        tail = response_lower[-2000:]
        pass_score = tail.count("pass") + tail.count("通过")
        fail_score = tail.count("fail") + tail.count("驳回") + tail.count("不通过")
        return pass_score >= fail_score

    @staticmethod
    def _parse_acceptance_result(response: str) -> bool:
        """Parse the acceptance response to determine pass/fail.

        Uses the same logic as ``_parse_audit_result``.

        Args:
            response: The full acceptance report text.

        Returns:
            ``True`` if the module was accepted, ``False`` otherwise.
        """
        return Orchestrator._parse_audit_result(response)

    # ==================================================================
    # Task-board parsing
    # ==================================================================

    async def _parse_task_board(self) -> list[dict[str, Any]]:
        """Parse the task board to extract the module list.

        Reads ``constitution/task-board.md`` and extracts module entries
        — lines matching ``### Mn: ...`` or ``### Mn ...``.  Each module's
        description (all lines between its header and the next header) is
        captured as the ``tasks`` field.

        Returns:
            A list of module dicts, each containing keys ``id`` (e.g.
            ``"M1"``), ``name`` (human-readable title), and ``tasks``
            (the body text under that module heading).  Returns an empty
            list when the task board file is missing or unreadable.
        """
        task_board_path = self._project_root / "constitution" / "task-board.md"
        if not task_board_path.is_file():
            logger.warning("Task board not found at %s", task_board_path)
            return []

        content = task_board_path.read_text(encoding="utf-8")
        modules: list[dict[str, Any]] = []
        current_module: dict[str, Any] | None = None
        tasks_lines: list[str] = []

        for line in content.splitlines():
            stripped = line.strip()

            # Detect module headers: "### Mn" or "### Mn: Title"
            if re.match(r"^###\s+M\d+", stripped, re.IGNORECASE):
                # Save the previous module before starting a new one.
                if current_module is not None:
                    current_module["tasks"] = "\n".join(tasks_lines).strip()
                    modules.append(current_module)

                header = stripped.lstrip("#").strip()
                if ":" in header:
                    parts = header.split(":", 1)
                    mod_id = parts[0].strip()
                    mod_name = parts[1].strip()
                else:
                    mod_id = header
                    mod_name = header

                current_module = {"id": mod_id, "name": mod_name}
                tasks_lines = []
            elif current_module is not None:
                tasks_lines.append(line)

        # Save the last module.
        if current_module is not None:
            current_module["tasks"] = "\n".join(tasks_lines).strip()
            modules.append(current_module)

        logger.info("Parsed %d modules from task board.", len(modules))
        return modules

    # ==================================================================
    # Persistence helpers
    # ==================================================================

    async def _persist_planning_artifacts(self, response: str) -> None:
        """Parse the Claude-A planning response and write individual files.

        Splits the response on markdown headings that specify file paths
        (e.g. ``### constitution/requirements.md``) and writes each
        section to the corresponding path under the project root.  When no
        such headings are detected the entire response is saved as
        ``constitution/planning-output.md``.

        Args:
            response: The full planning response text from Claude-A.
        """
        # Split on headings that name a file inside a known zone.
        zone_pattern = "|".join(self._fs.ZONES)
        section_pattern = re.compile(
            rf"\n(?=##\s+(?:`?)(?:{zone_pattern})/[^\s`\n]+(?:`?)\n)",
        )

        sections = section_pattern.split(response)

        if len(sections) <= 1:
            # No structured sections found — save as a single planning note.
            self._fs.write_file("claude-a", "constitution/planning-output.md", response)
            logger.info("Planning output written to constitution/planning-output.md")
            return

        for section in sections:
            if not section.strip():
                continue

            # Extract the file path from the heading (first line).
            first_line = section.split("\n")[0]
            path_match = re.match(
                r"^##\s+(?:`?)((?:constitution|sandbox|src|test|review|artifacts)/[^\s`\n]+)(?:`?)",
                first_line,
            )
            if path_match:
                file_path = path_match.group(1)
                zone = file_path.split("/")[0]
                if zone in self._fs.ZONES:
                    try:
                        self._fs.write_file("claude-a", file_path, section.strip())
                        logger.info("Planning artifact written to %s", file_path)
                    except Exception as exc:
                        logger.warning(
                            "Failed to write planning artifact %s: %s", file_path, exc
                        )
            else:
                # Section without a recognisable path — append to planning notes.
                existing = ""
                notes_path = "constitution/planning-output.md"
                try:
                    existing = self._fs.read_file("claude-a", notes_path)
                except FileNotFoundError:
                    pass
                self._fs.write_file("claude-a", notes_path, existing + "\n" + section)

    async def _on_step_complete(self, role: str, artifact: dict[str, Any]) -> None:
        """Hook called after each phase step completes.

        Persists the artifact to the database.  (Git auto-commit will be
        wired in when ``git_manager`` is integrated.)

        Args:
            role: The role that produced the artifact.
            artifact: Artifact metadata dict with keys ``type``, ``title``,
                ``summary_256``, ``full_text``, ``file_path``, ``module``
                (optional), and ``version`` (optional).
        """
        try:
            await self._db.insert_artifact(
                {
                    "project_id": self._project_id,
                    "role": role,
                    "type": artifact.get("type", "code"),
                    "module": artifact.get("module"),
                    "title": artifact.get("title", ""),
                    "summary_256": artifact.get("summary_256", ""),
                    "full_text": artifact.get("full_text", ""),
                    "file_path": artifact.get("file_path"),
                    "version": artifact.get("version", 1),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist artifact for role %s (module=%s): %s",
                role,
                artifact.get("module"),
                exc,
            )

    # ==================================================================
    # Role-status helpers
    # ==================================================================

    def _set_role_status(self, role: str, status: str, task: str | None = None) -> None:
        """Update the tracked status for an AI role.

        Args:
            role: Role identifier (``"claude-a"``, ``"codex"``, ``"claude-b"``).
            status: Human-readable status string (``"idle"``, ``"active"``,
                ``"error"``).
            task: Optional description of the current task.
        """
        self._role_statuses[role] = status
        self._role_tasks[role] = task


# ======================================================================
# Module-level helpers (prompt builders + file collectors)
# ======================================================================


def _build_planning_prompt() -> str:
    """Build the user prompt for the planning phase (Claude-A)."""
    return (
        "请为以下新项目生成完整的规划文档集：\n\n"
        "1. **需求文档** — 写入 `constitution/requirements.md`\n"
        "   - 功能需求清单（P0 / P1 / P2 优先级）\n"
        "   - 非功能需求（性能、安全、可用性）\n"
        "   - 用户故事或用例描述\n\n"
        "2. **项目宪法** — 写入 `constitution/constitution.md`\n"
        "   - 技术架构规范（技术栈、架构模式、目录结构）\n"
        "   - 接口 / API 规范\n"
        "   - 代码风格规范（Python + TypeScript）\n"
        "   - 测试规范\n"
        "   - Git 提交规范\n"
        "   - 禁止事项\n\n"
        "3. **接口规范** — 写入 `constitution/api-spec.yaml`\n"
        "   - REST API 端点定义（OpenAPI 3.0 格式）\n"
        "   - 数据模型定义\n"
        "   - 错误码定义\n\n"
        "4. **任务清单** — 写入 `constitution/task-board.md`\n"
        "   - 按模块拆分（M1, M2, M3 …）\n"
        "   - 每个模块标注负责人、预估工时、状态\n"
        "   - 详细任务子项（checkbox 格式）\n\n"
        "请参考已有项目结构和技术栈生成上述文件。每个文件必须完整、可执行，"
        "能够直接作为 Codex 的开发指令。"
    )


def _build_coding_prompt(
    module_id: str,
    module_name: str,
    module_tasks: str,
) -> str:
    """Build the user prompt for the coding phase (Codex)."""
    return (
        f"请实现以下模块：\n\n"
        f"## 模块: {module_id} — {module_name}\n\n"
        f"### 任务描述\n{module_tasks}\n\n"
        f"### 要求\n"
        f"1. 所有代码写入 `sandbox/{module_id}/` 目录\n"
        f"2. 严格遵循 `constitution/constitution.md` 中的规范\n"
        f"3. 参考 `constitution/api-spec.yaml` 中的接口定义\n"
        f"4. 包含完整的类型注解和 docstring\n"
        f"5. 如涉及数据库，参考 constitution 中的数据模型\n\n"
        f"请开始编码。"
    )


def _build_audit_prompt(module_id: str) -> str:
    """Build the user prompt for the auditing phase (Claude-B)."""
    return (
        f"请审计以下模块的代码产出：\n\n"
        f"## 审计目标: {module_id}\n\n"
        f"### 审计标准\n"
        f"1. 对照 `constitution/constitution.md` 检查代码是否符合宪法规范\n"
        f"2. 对照 `constitution/api-spec.yaml` 检查接口实现是否正确\n"
        f"3. 检查代码风格（Black / Ruff 规范）\n"
        f"4. 检查类型注解完整性\n"
        f"5. 检查 docstring 完整性\n"
        f"6. 检查是否有安全漏洞或禁止事项违规\n\n"
        f"### 审计结论\n"
        f"请在报告末尾明确给出结论：\n"
        f"- **通过 (PASS)**: 代码符合所有规范，可以进入验收阶段\n"
        f"- **驳回 (FAIL)**: 代码存在问题，需要 Codex 修改（请列出具体问题）\n\n"
        f"请将审计报告写入 `test/{module_id}-audit.md`。"
    )


def _build_acceptance_prompt(module_id: str) -> str:
    """Build the user prompt for the acceptance phase (Claude-A)."""
    return (
        f"请验收以下模块：\n\n"
        f"## 验收目标: {module_id}\n\n"
        f"### 验收标准\n"
        f"1. 代码输出是否符合需求文档 (`constitution/requirements.md`)\n"
        f"2. 代码是否符合项目宪法 (`constitution/constitution.md`)\n"
        f"3. 接口实现是否符合接口规范 (`constitution/api-spec.yaml`)\n"
        f"4. Claude-B 的审计报告中的问题是否已解决\n"
        f"5. 代码是否可以直接合并到 `src/` 目录\n\n"
        f"### 验收结论\n"
        f"请在报告末尾明确给出结论：\n"
        f"- **通过 (PASS)**: 模块合格，可以合并到 src/\n"
        f"- **驳回 (FAIL)**: 模块存在问题，需要 Codex 修改（请列出具体问题）\n\n"
        f"请将验收报告写入 `review/acceptance/{module_id}.md`。"
    )


def _collect_constitution_files(project_root: Path, *filenames: str) -> list[str]:
    """Collect absolute paths to constitution files that actually exist.

    Args:
        project_root: The project root directory.
        *filenames: File names inside ``constitution/`` to look for.

    Returns:
        A list of absolute path strings for files that exist on disk.
    """
    files: list[str] = []
    for name in filenames:
        path = project_root / "constitution" / name
        if path.is_file():
            files.append(str(path))
    return files


def _collect_sandbox_files(project_root: Path, module_id: str) -> list[str]:
    """Collect absolute paths to all files in a sandbox module directory.

    Args:
        project_root: The project root directory.
        module_id: The module identifier (e.g. ``"M1"``).

    Returns:
        A list of absolute path strings for every regular file under
        ``sandbox/{module_id}/``.  Returns an empty list when the
        directory does not exist.
    """
    sandbox_dir = project_root / "sandbox" / module_id
    if not sandbox_dir.is_dir():
        return []
    return [str(p) for p in sandbox_dir.rglob("*") if p.is_file()]


def _estimate_tokens(user_message: str, response: str) -> int:
    """Rough token-count estimate based on whitespace-delimited word count.

    This is a coarse approximation (words / 0.75).  When an exact token
    count becomes available from the LLM API response it should replace
    this helper.

    Args:
        user_message: The input message text.
        response: The output response text.

    Returns:
        Estimated total token count.
    """
    word_count = len(user_message.split()) + len(response.split())
    return max(1, int(word_count / 0.75))
