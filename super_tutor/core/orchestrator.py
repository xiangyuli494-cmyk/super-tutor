"""Workflow orchestrator — Super Tutor 教学流水线引擎。

实现状态机驱动的三 AI 角色协作流水线：

    IDLE → PARSING → QUIZ_GEN → EVALUATING → PLANNING → DONE

三个 AI 角色各司其职：

* **Tutor**（主导师）— 解析 PDF 资料 + 制定学习计划
* **Assistant**（助教）— 根据知识库生成题目 + 组卷
* **Evaluator**（评估者）— 批改作答 + 迷思概念诊断

各阶段实现在 ``orchestrator_phases.py``（``_PhaseHandlers`` mixin）中，
Prompt 构建在 ``orchestrator_prompts.py`` 中，
通用工具在 ``orchestrator_utils.py`` 中。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from super_tutor.core.database import Database
from super_tutor.core.exceptions import LLMClientError, TutorError, VALID_ROLES
from super_tutor.core.llm_client import LLMClient
from super_tutor.core.orchestrator_phases import _PhaseHandlers
from super_tutor.core.orchestrator_utils import _estimate_tokens, _hydrate_models
from super_tutor.core.role_manager import RoleManager
from super_tutor.models.enums import AIRole, PipelinePhase
from super_tutor.models.knowledge import KnowledgeChunk
from super_tutor.models.mastery import ReviewItem
from super_tutor.models.quiz import MisconceptionTag, Question, QuizAttempt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_MAX_STEP_RETRIES: int = 3
"""单步最大连续重试次数，超过后停留 ERROR 等待人工介入。"""

_VALID_PHASE_VALUES: set[str] = {p.value for p in PipelinePhase}
"""所有合法 PipelinePhase 枚举值，用于 DB 恢复时的校验。"""

# AIRole → RoleManager 文件名 的映射
_ROLE_TO_PROMPT_FILE: dict[AIRole, str] = {
    AIRole.TUTOR: "tutor",
    AIRole.ASSISTANT: "assistant",
    AIRole.EVALUATOR: "evaluator",
}


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------


class OrchestratorError(TutorError):
    """Orchestrator 层错误。"""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator(_PhaseHandlers):
    """教学流水线状态机编排器。

    协调三个 AI 角色按序推进：

    1. **PARSING** — Tutor 解析 PDF，生成知识片段和摘要。
    2. **QUIZ_GEN** — Assistant 基于知识库生成测验题目。
    3. **EVALUATING** — Evaluator 批改学生作答，诊断迷思概念。
    4. **PLANNING** — Tutor 综合掌握数据，生成 SM-2 排期计划。

    使用方式::

        orch = Orchestrator(database=db, llm_client=llm, role_manager=rm)
        await orch.initialize(session_context={"material_id": "xxx"})

        # Phase 1: PDF 解析
        await orch.start()          # IDLE → PARSING
        await orch.proceed()        # PARSING → QUIZ_GEN

        # 学生作答（断点：等待真实学生提交）
        await orch.submit_answers([
            {"question_id": "q1", "student_answer": "B"},
        ])

        # Phase 2-4: 批改 → 排期 → 完成
        await orch.proceed()        # QUIZ_GEN → EVALUATING
        await orch.proceed()        # EVALUATING → PLANNING
        await orch.proceed()        # PLANNING → DONE

        status = await orch.get_status()

    Attributes:
        state: 当前工作流状态（只读属性）。
        session_id: 当前教学会话标识。
    """

    def __init__(
        self,
        database: Database,
        llm_client: LLMClient,
        role_manager: RoleManager,
    ) -> None:
        """初始化编排器。

        Args:
            database: 数据库管理器（必须已调用 ``initialize()``）。
            llm_client: 已配置的 LLM 客户端。
            role_manager: AI 角色系统提示词管理器。
        """
        self._db: Database = database
        self._llm: LLMClient = llm_client
        self._roles: RoleManager = role_manager

        # ------------------------------------------------------------------
        # 会话上下文 — 贯穿整个流水线的运行时数据
        # ------------------------------------------------------------------
        self._session_context: dict[str, Any] = {}

        # ------------------------------------------------------------------
        # 流水线阶段
        # ------------------------------------------------------------------
        self._phase: PipelinePhase = PipelinePhase.IDLE
        self._previous_phase: PipelinePhase = PipelinePhase.IDLE
        self._paused: bool = False
        self._error_message: Optional[str] = None
        self._step_retry_count: int = 0
        self._in_progress: bool = False

        # ------------------------------------------------------------------
        # 阶段产出物 — 上游阶段写入，下游阶段读取
        # ------------------------------------------------------------------
        self._artifacts: dict[str, Any] = {}

        # ------------------------------------------------------------------
        # AI 角色状态追踪
        # ------------------------------------------------------------------
        self._role_statuses: dict[str, str] = {
            role.value: "idle" for role in AIRole
        }
        self._role_tasks: dict[str, Optional[str]] = {
            role.value: None for role in AIRole
        }

        # ------------------------------------------------------------------
        # 测验生命周期状态（QuizStatus 枚举推进）
        # ------------------------------------------------------------------
        self._quiz_status: str = "draft"  # draft→ready→in_progress→submitted→graded→reviewed

        # ------------------------------------------------------------------
        # Token 追踪器 — 可选注入，不注入时走 DB 直写（回退路径）
        # ------------------------------------------------------------------
        self._token_tracker: Optional[Any] = None

    # ==================================================================
    # Properties
    # ==================================================================

    @property
    def state(self) -> PipelinePhase:
        """返回当前流水线阶段。"""
        return self._phase

    @property
    def is_done(self) -> bool:
        """流水线是否已完成全部阶段。"""
        return (
            self._phase == PipelinePhase.PLANNING
            and not self._paused
            and self._error_message is None
        )

    @property
    def session_id(self) -> Optional[str]:
        """返回当前会话 ID。"""
        return self._session_context.get("session_id")

    def inject_token_tracker(self, tracker: Any) -> None:
        """注入 TokenTracker 用于预算管控和用量统计。

        注入后在 ``_invoke_role`` 中自动使用 tracker 记录用量
        并在每次 LLM 调用前检查预算。不注入则回退到 DB 直写。

        Args:
            tracker: :class:`TokenTracker` 实例。
        """
        self._token_tracker = tracker
        logger.debug("TokenTracker injected into Orchestrator.")

    # ==================================================================
    # 初始化
    # ==================================================================

    async def initialize(self, session_context: dict[str, Any]) -> None:
        """设置流水线的运行时上下文。

        必须在 ``start()`` 之前调用。

        Args:
            session_context: 会话上下文，至少包含：
                - ``material_id``: 学习材料 ID
                - ``session_id``: 可选会话标识
                - ``student_id``: 可选学生标识
        """
        self._session_context = session_context
        logger.info(
            "Orchestrator session context set: material=%s",
            session_context.get("material_id"),
        )

    # ==================================================================
    # 状态机控制（公开 API）
    # ==================================================================

    async def start(self) -> None:
        """启动流水线：IDLE → PARSING。

        由 Parser 角色（Tutor）解析 PDF 材料，生成知识片段。

        状态机采用 **DB 作为唯一真相源** 模式：
        ① 读取 DB 确认当前状态
        ② 修改内存状态
        ③ 写入 DB（崩溃恢复边界）
        ④ 执行 Agent

        Raises:
            OrchestratorError: 若不是从 IDLE 阶段调用。
        """
        if self._phase != PipelinePhase.IDLE:
            raise OrchestratorError(
                f"无法从 '{self._phase.value}' 启动，"
                f"需要 '{PipelinePhase.IDLE.value}' 阶段。"
            )
        if self._paused:
            raise OrchestratorError("流水线已暂停，请先调用 resume()。")

        # ① 以 DB 为唯一真相源，确认当前状态
        if self.session_id:
            db_state = await self._db.load_session(self.session_id)
            if db_state is not None:
                db_phase_raw = db_state.get("state", db_state.get("phase", "idle"))
                if db_phase_raw != PipelinePhase.IDLE.value:
                    self._phase = PipelinePhase(db_phase_raw)
                    raise OrchestratorError(
                        f"会话已在 '{db_phase_raw}' 阶段，无法从 IDLE 重新启动。"
                        f"请通过 GET /sessions/{self.session_id}/questions 自动恢复。"
                    )

        # ② 修改状态（内存）
        self._previous_phase = self._phase
        self._phase = PipelinePhase.PARSING
        self._in_progress = True
        logger.info("阶段推进: %s → %s", self._previous_phase.value, self._phase.value)

        # ③ 状态先写入 DB（崩溃恢复边界：DB 先落地，再执行 Agent）
        await self.save()

        # ④ 执行 Agent
        await self._parsing_phase()

    async def submit_answers(
        self,
        answers: list[dict[str, Any]],
        *,
        quiz_session_id: Optional[str] = None,
    ) -> int:
        """提交学生作答，作为 EVALUATING 阶段的输入。

        必须在 QUIZ_GEN 阶段完成之后调用。该方法将作答数据存入
        会话上下文供 ``_evaluating_phase`` 消费，并同时创建
        ``QuizAttempt`` Pydantic 模型实例用于后续持久化。

        Args:
            answers: 学生作答列表，每项可包含：
                - ``question_id``: 题目 ID（必填）
                - ``student_answer``: 学生提交的答案（必填）
                - ``time_spent_seconds``: 本题耗时（可选，默认 0）
                - ``hints_used``: 查看提示次数（可选，默认 0）
                - ``attempt_number``: 第几次尝试（可选，默认 1）
                - ``confidence``: 自评置信度 0-1（可选）
            quiz_session_id: 关联的 QuizSession ID（可选）。

        Returns:
            成功提交的作答条数。

        Raises:
            OrchestratorError: 若当前阶段不允许提交作答。
        """
        if self._phase != PipelinePhase.QUIZ_GEN:
            raise OrchestratorError(
                f"无法在 '{self._phase.value}' 阶段提交作答，"
                f"请先完成 QUIZ_GEN 阶段（当前需要 '{PipelinePhase.QUIZ_GEN.value}'）。"
            )

        # 存入上下文供 _evaluating_phase 使用
        self._session_context["student_answers"] = answers
        self._session_context["quiz_session_id"] = quiz_session_id

        # 反序列化为 Pydantic 模型（P1：模型脱节修复）
        questions_index: dict[str, dict[str, Any]] = {}
        for q in self._artifacts.get("questions", []):
            qid = q.get("question_id", "")
            if qid:
                questions_index[qid] = q

        attempts: list[QuizAttempt] = []
        for i, ans in enumerate(answers):
            qid = ans.get("question_id", f"unknown_{i}")
            try:
                attempt = QuizAttempt(
                    session_id=quiz_session_id or self.session_id or "unknown",
                    question_id=qid,
                    student_answer=ans.get("student_answer"),
                    time_spent_seconds=ans.get("time_spent_seconds", 0),
                    hints_used=ans.get("hints_used", 0),
                    attempt_number=ans.get("attempt_number", 1),
                    confidence=ans.get("confidence"),
                )
                attempts.append(attempt)
            except Exception as exc:
                logger.warning(
                    "QuizAttempt 构造失败 (question_id=%s): %s", qid, exc
                )

        self._artifacts["submitted_attempts"] = attempts
        self._quiz_status = "submitted"  # 学生已提交作答
        logger.info(
            "提交 %d 条学生作答（%d 条成功反序列化为 QuizAttempt）。",
            len(answers),
            len(attempts),
        )
        return len(attempts)

    async def proceed(self) -> None:
        """推进流水线一步。

        状态机采用 **DB 作为唯一真相源** 模式：
        ① 读取 DB 同步当前状态（修复内存/DB 不一致）
        ② 计算下一阶段并修改内存状态
        ③ 写入 DB（崩溃恢复边界）
        ④ 执行 Agent

        Raises:
            OrchestratorError: 若从 IDLE / 暂停 / 错误 / 已完成 状态调用。
        """
        if self._paused:
            raise OrchestratorError("流水线已暂停，请先调用 resume()。")
        if self._error_message is not None:
            raise OrchestratorError(
                f"流水线处于错误状态: {self._error_message}。请先调用 retry_step()。"
            )

        # ① 以 DB 为唯一真相源，同步当前状态
        if self.session_id:
            db_state = await self._db.load_session(self.session_id)
            if db_state is not None:
                db_phase_raw = db_state.get("state", db_state.get("phase", "idle"))
                if db_phase_raw not in _VALID_PHASE_VALUES:
                    db_phase_raw = PipelinePhase.IDLE.value
                db_phase = PipelinePhase(db_phase_raw)
                if db_phase != self._phase:
                    logger.warning(
                        "内存状态 %s 与 DB 状态 %s 不一致，以 DB 为准。",
                        self._phase.value, db_phase.value,
                    )
                    self._phase = db_phase

        if self._phase == PipelinePhase.IDLE:
            raise OrchestratorError("请先调用 start() 启动流水线。")
        if self._phase == PipelinePhase.PLANNING:
            raise OrchestratorError("流水线已完成全部阶段，无需再推进。")

        # ② 计算下一阶段并修改内存状态
        _NEXT_PHASE: dict[PipelinePhase, PipelinePhase] = {
            PipelinePhase.PARSING: PipelinePhase.QUIZ_GEN,
            PipelinePhase.QUIZ_GEN: PipelinePhase.EVALUATING,
            PipelinePhase.EVALUATING: PipelinePhase.PLANNING,
        }
        next_phase = _NEXT_PHASE[self._phase]
        self._previous_phase = self._phase
        self._phase = next_phase
        self._in_progress = True
        logger.info("阶段推进: %s → %s", self._previous_phase.value, next_phase.value)

        # ③ 状态先写入 DB（崩溃恢复边界：DB 先落地，再执行 Agent）
        await self.save()

        # ④ 执行 Agent
        _PHASE_HANDLER = {
            PipelinePhase.PARSING: self._parsing_phase,
            PipelinePhase.QUIZ_GEN: self._quiz_gen_phase,
            PipelinePhase.EVALUATING: self._evaluating_phase,
            PipelinePhase.PLANNING: self._planning_phase,
        }
        handler = _PHASE_HANDLER.get(next_phase)
        if handler:
            await handler()

        # 成功后重置重试计数器
        self._step_retry_count = 0

    async def pause(self) -> None:
        """暂停流水线。

        保存当前阶段以便 ``resume()`` 恢复。已暂停时调用为幂等操作。
        """
        if self._paused:
            return
        if self._phase == PipelinePhase.IDLE:
            raise OrchestratorError("流水线尚未启动，无法暂停。")

        self._paused = True
        await self.save()
        logger.info("流水线已暂停（当前阶段: %s）。", self._phase.value)

    async def resume(self) -> None:
        """从暂停恢复。

        Raises:
            OrchestratorError: 若当前未暂停。
        """
        if not self._paused:
            raise OrchestratorError("流水线未处于暂停状态。")
        self._paused = False
        logger.info("流水线已恢复（当前阶段: %s）。", self._phase.value)

    async def save(self) -> None:
        """持久化当前编排器状态到 ``sessions`` 表。

        每个阶段完成后自动调用。仅保存原始 dict 类型的 artifacts，
        Pydantic 模型列表在 restore 时通过 ``_hydrate_models()`` 重建。
        """
        session_id = self.session_id
        if not session_id:
            logger.warning("无法保存会话：未设置 session_id")
            return

        # 仅保留原始 dict list（跳过 Pydantic model list 和纯字符串/非列表值）
        raw_artifacts: dict[str, Any] = {}
        for key, value in self._artifacts.items():
            if isinstance(value, list):
                if not value:
                    raw_artifacts[key] = value
                elif isinstance(value[0], dict):
                    raw_artifacts[key] = value
                # else: Pydantic model list — 跳过，restore 时重建

        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.save_session({
            "session_id": session_id,
            "user_id": self._session_context.get("student_id", ""),
            "quiz_status": self._quiz_status,
            "state": self._phase.value,
            "previous_state": self._previous_phase.value,
            "in_progress": 1 if self._in_progress else 0,
            "error_message": self._error_message,
            "step_retry_count": self._step_retry_count,
            "session_context": self._session_context,
            "artifacts": raw_artifacts,
            "role_statuses": self._role_statuses,
            "role_tasks": {k: v for k, v in self._role_tasks.items()},
            "created_at": now_iso,
            "updated_at": now_iso,
        })
        logger.debug("会话 %s 已持久化（phase=%s）。", session_id, self._phase.value)

    # ==================================================================
    # 阶段生命周期钩子
    # ==================================================================

    async def _start_phase(
        self, phase: PipelinePhase, role: AIRole, task: str,
    ) -> None:
        """阶段开始前的角色状态更新。

        注意：状态转换（phase + in_progress）已由调用方
        ``start()`` / ``proceed()`` / ``retry_step()`` 在调用本方法前
        写入 DB。本方法仅更新运行时角色追踪状态（内存）。

        Args:
            phase: 即将执行的流水线阶段。
            role: 负责该阶段的 AI 角色。
            task: 角色当前任务的简短描述。
        """
        self._set_role_status(role, "active", task)
        logger.debug("阶段 %s 已开始（role=%s, task=%s）", phase.value, role.value, task)

    async def _end_phase(
        self, phase: PipelinePhase, role: AIRole,
    ) -> None:
        """阶段完成后的保存点。

        标记 ``_in_progress=False``，将角色状态设为空闲，
        并立即持久化。

        Args:
            phase: 刚刚完成的流水线阶段。
            role: 负责该阶段的 AI 角色。
        """
        self._in_progress = False
        self._set_role_status(role, "idle", None)
        await self.save()
        logger.debug("阶段 %s 已完成（in_progress=False）", phase.value)

    @classmethod
    async def restore(
        cls,
        session_id: str,
        *,
        database: Database,
        llm_client: LLMClient,
        role_manager: RoleManager,
    ) -> Optional["Orchestrator"]:
        """从数据库恢复一个已持久化的编排器会话。

        Args:
            session_id: 要恢复的会话 ID。
            database: 数据库实例（已初始化）。
            llm_client: LLM 客户端。
            role_manager: AI 角色管理器。

        Returns:
            恢复的 Orchestrator 实例，若 session_id 不存在则返回 ``None``。
        """
        data = await database.load_session(session_id)
        if data is None:
            return None

        orch = cls(
            database=database,
            llm_client=llm_client,
            role_manager=role_manager,
        )

        # 还原流水线阶段（向后兼容旧字段名 state/previous_state）
        raw_phase = data.get("phase", data.get("state", "idle"))
        raw_prev = data.get("previous_phase", data.get("previous_state", "idle"))
        # 旧数据中可能有 "done"/"paused"/"error" 等已移除的枚举值，回退到 idle
        if raw_phase not in _VALID_PHASE_VALUES:
            raw_phase = PipelinePhase.IDLE.value
        if raw_prev not in _VALID_PHASE_VALUES:
            raw_prev = PipelinePhase.IDLE.value
        orch._phase = PipelinePhase(raw_phase)
        orch._previous_phase = PipelinePhase(raw_prev)
        orch._paused = data.get("paused", False)
        orch._error_message = data.get("error_message")
        orch._step_retry_count = data.get("step_retry_count", 0)
        orch._in_progress = bool(data.get("in_progress", 0))
        orch._quiz_status = data.get("quiz_status", "draft")
        orch._session_context = data.get("session_context", {})

        # 还原 AI 角色状态
        default_statuses = {role.value: "idle" for role in AIRole}
        orch._role_statuses = data.get("role_statuses", default_statuses)
        default_tasks = {role.value: None for role in AIRole}
        orch._role_tasks = data.get("role_tasks", default_tasks)

        # 还原原始 dict artifacts
        raw_artifacts = data.get("artifacts", {})
        orch._artifacts = dict(raw_artifacts)

        # 重新水合 Pydantic 模型列表
        material_id = orch._session_context.get("material_id", "")
        session_id_ctx = orch._session_context.get("session_id", "")
        student_id = orch._session_context.get("student_id", "")

        if "chunks" in raw_artifacts:
            orch._artifacts["chunk_models"] = _hydrate_models(
                raw_artifacts["chunks"], KnowledgeChunk,
                defaults={"material_id": material_id},
            )
        if "questions" in raw_artifacts:
            orch._artifacts["question_models"] = _hydrate_models(
                raw_artifacts["questions"], Question,
            )
        if "attempts" in raw_artifacts:
            orch._artifacts["attempt_models"] = _hydrate_models(
                raw_artifacts["attempts"], QuizAttempt,
                defaults={"session_id": session_id_ctx, "student_id": student_id},
            )
        if "misconceptions" in raw_artifacts:
            orch._artifacts["misconception_models"] = _hydrate_models(
                raw_artifacts["misconceptions"], MisconceptionTag,
            )
        if "plan_items" in raw_artifacts:
            orch._artifacts["plan_item_models"] = _hydrate_models(
                raw_artifacts["plan_items"], ReviewItem,
            )

        # -- 崩溃恢复：若上次运行时在阶段中途崩溃，回退到上一阶段 ----
        if orch._in_progress:
            logger.warning(
                "会话 %s 上次运行在 %s 阶段中途崩溃（in_progress=1），"
                "回退到 %s 等待重试。",
                session_id, orch._phase.value, orch._previous_phase.value,
            )
            orch._error_message = (
                f"上次 {orch._phase.value} 阶段执行中断（服务器重启或崩溃）。"
                f"将在下次推进时自动重试。"
            )
            orch._phase = orch._previous_phase  # 回退到上一阶段
            orch._in_progress = False  # 重置标记，让重试正常进行

        logger.info(
            "会话 %s 已恢复（phase=%s, artifacts=%d keys）。",
            session_id, orch._phase.value, len(raw_artifacts),
        )
        return orch

    async def retry_step(self) -> None:
        """重试当前失败步骤。

        状态机采用 **DB 作为唯一真相源** 模式：
        ① 清除错误、标记 in_progress、写入 DB
        ② 执行 Agent

        限制连续重试 ``_MAX_STEP_RETRIES`` 次，超过后保持错误。

        Raises:
            OrchestratorError: 若当前不在错误状态。
        """
        if self._error_message is None:
            raise OrchestratorError("流水线未处于错误状态，无需重试。")

        self._step_retry_count += 1
        if self._step_retry_count > _MAX_STEP_RETRIES:
            self._error_message = (
                f"步骤重试已达上限（{_MAX_STEP_RETRIES} 次），请人工介入。"
            )
            await self.save()  # 持久化最终失败状态
            logger.error(self._error_message)
            return

        failed_phase = self._phase
        logger.info(
            "重试步骤（%d/%d），目标阶段: %s。",
            self._step_retry_count,
            _MAX_STEP_RETRIES,
            failed_phase.value,
        )
        self._error_message = None
        self._in_progress = True

        # ① 状态先写入 DB（崩溃恢复边界：DB 先落地，再执行 Agent）
        await self.save()

        # ② 执行 Agent
        _PHASE_HANDLER = {
            PipelinePhase.PARSING: self._parsing_phase,
            PipelinePhase.QUIZ_GEN: self._quiz_gen_phase,
            PipelinePhase.EVALUATING: self._evaluating_phase,
            PipelinePhase.PLANNING: self._planning_phase,
        }
        handler = _PHASE_HANDLER.get(failed_phase)
        if handler:
            await handler()

    async def get_status(self) -> dict[str, Any]:
        """返回当前流水线阶段快照。

        Returns:
            包含阶段、暂停状态、产物摘要及各 AI 角色状态的字典。
        """
        return {
            "phase": self._phase.value,
            "quiz_status": self._quiz_status,
            "paused": self._paused,
            "is_done": self.is_done,
            "session_id": self.session_id,
            "error_message": self._error_message,
            "artifacts": {
                "chunk_count": len(self._artifacts.get("chunks", [])),
                "question_count": len(self._artifacts.get("questions", [])),
                "attempt_count": len(self._artifacts.get("attempts", [])),
                "plan_item_count": len(self._artifacts.get("plan_items", [])),
            },
            "roles": {
                role.value: {
                    "status": self._role_statuses.get(role.value, "idle"),
                    "current_task": self._role_tasks.get(role.value),
                }
                for role in AIRole
            },
        }

    # ==================================================================
    # LLM 调用封装
    # ==================================================================

    async def _invoke_role(
        self,
        role: str,
        user_message: str,
        system_prompt: Optional[str] = None,
        tier: str = "medium",
    ) -> str:
        """调用 AI 角色并记录 token 用量。

        封装 ``LLMClient.chat_with_file_context``，增加角色校验、
        token 日志和错误传播。

        Args:
            role: 角色标识（``"tutor"`` / ``"assistant"`` / ``"evaluator"``）。
            user_message: 给 AI 角色的指令或上下文。
            system_prompt: 系统提示词。None 时由 RoleManager 自动加载。
            tier: 算力档位（``"heavy"`` / ``"medium"`` / ``"light"``）。

        Returns:
            AI 角色的完整响应文本。

        Raises:
            LLMClientError: API 调用失败（重试耗尽后）。
        """
        if role not in VALID_ROLES:
            raise OrchestratorError(
                f"未知角色 '{role}'。有效角色: {sorted(VALID_ROLES)}"
            )

        # Token 预算检查（仅当 TokenTracker 注入时）
        if self._token_tracker is not None:
            budget_status = await self._token_tracker.check_budget(
                self.session_id or "unknown"
            )
            if budget_status["exhausted"]:
                raise OrchestratorError(
                    f"Token 预算已耗尽（budget={budget_status.get('budget', '?')}）。"
                    f"请联系管理员增加预算或等待下个周期。"
                )
            if budget_status["warning"]:
                logger.warning(
                    "Token 预算使用率 >= 80%%（remaining=%d）",
                    budget_status.get("remaining", 0),
                )

        try:
            response = await self._llm.chat_with_file_context(
                role=role,
                user_message=user_message,
                files=[],
                tier=tier,
                system_prompt=system_prompt,
            )

            prompt_tokens = _estimate_tokens(user_message)
            completion_tokens = _estimate_tokens(response)

            # 优先走 TokenTracker（含预算管控 + 内存聚合），
            # 否则回退到 DB 直写。
            if self._token_tracker is not None:
                await self._token_tracker.record(
                    project_id=self.session_id or "unknown",
                    role=role,
                    task_id="",
                    model_tier=tier,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            else:
                await self._db.log_token_usage(
                    {
                        "project_id": self.session_id or "unknown",
                        "role": role,
                        "tier": tier,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

            return response

        except LLMClientError:
            raise
        except Exception as exc:
            logger.error("调用角色 '%s' 时发生异常: %s", role, exc)
            raise LLMClientError(
                f"调用角色 '{role}' 失败: {exc}"
            ) from exc

    # ==================================================================
    # 状态机辅助方法
    # ==================================================================

    async def _handle_phase_error(self, exc: Exception) -> None:
        """记录阶段异常并持久化错误状态。

        注意：不重置 ``_in_progress``，保留崩溃标记以便恢复时回退。
        """
        self._error_message = str(exc)
        self._previous_phase = self._phase
        await self.save()
        logger.error("阶段执行失败: %s", exc)

    # ==================================================================
    # 持久化 & 角色状态辅助
    # ==================================================================

    async def _on_step_complete(
        self, role: str, artifact: dict[str, Any]
    ) -> None:
        """阶段完成回调：将产出物写入数据库。"""
        try:
            await self._db.insert_artifact(
                {
                    "project_id": self.session_id or "unknown",
                    "role": role,
                    "type": artifact.get("type", "generic"),
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
                "产出物持久化失败 (role=%s): %s", role, exc
            )

        # 自动持久化会话状态
        await self.save()

    def _set_role_status(
        self, role: AIRole, status: str, task: Optional[str] = None
    ) -> None:
        """更新 AI 角色的追踪状态。"""
        self._role_statuses[role.value] = status
        self._role_tasks[role.value] = task
