"""Workflow orchestrator — Super Tutor Agent 教学流水线引擎。

实现状态机驱动的 Multi-Agent 协作流水线：

    IDLE → PARSING → QUIZ_GEN → EVALUATING → PLANNING → DONE

三个 AI 角色各司其职：

* **Tutor**（主导师）— 解析 PDF 资料 + 制定学习计划
* **Assistant**（助教）— 根据知识库生成题目 + 组卷
* **Evaluator**（评估者）— 批改作答 + 迷思概念诊断
"""

from __future__ import annotations

import json as _json
import logging
import re as _re
from datetime import datetime, timezone
from typing import Any, Optional

from super_tutor.core.database import Database
from super_tutor.core.exceptions import LLMClientError, TutorError, VALID_ROLES
from super_tutor.core.llm_client import LLMClient
from super_tutor.core.role_manager import RoleManager
from super_tutor.models.enums import AgentRole, WorkflowState
from super_tutor.models.knowledge import KnowledgeChunk
from super_tutor.models.mastery import ReviewItem
from super_tutor.models.quiz import MisconceptionTag, Question, QuizAttempt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_MAX_STEP_RETRIES: int = 3
"""单步最大连续重试次数，超过后停留 ERROR 等待人工介入。"""

# 各阶段使用的 LLM 算力档位
_PARSING_MODEL_TIER: str = "heavy"       # PDF 解析需要强理解能力
_QUIZ_GEN_MODEL_TIER: str = "heavy"      # 出题需要高质量输出
_EVALUATING_MODEL_TIER: str = "medium"    # 批改中等算力即可
_PLANNING_MODEL_TIER: str = "medium"      # 排期计算中等算力即可

# AgentRole → RoleManager 文件名 的映射
_ROLE_TO_PROMPT_FILE: dict[AgentRole, str] = {
    AgentRole.TUTOR: "tutor",
    AgentRole.ASSISTANT: "assistant",
    AgentRole.EVALUATOR: "evaluator",
}


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------


class OrchestratorError(TutorError):
    """Orchestrator 层错误。"""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """教学流水线状态机编排器。

    协调三个 AI Agent 按序推进：

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
            role_manager: Agent 系统提示词管理器。
        """
        self._db: Database = database
        self._llm: LLMClient = llm_client
        self._roles: RoleManager = role_manager

        # ------------------------------------------------------------------
        # 会话上下文 — 贯穿整个流水线的运行时数据
        # ------------------------------------------------------------------
        self._session_context: dict[str, Any] = {}

        # ------------------------------------------------------------------
        # 状态机
        # ------------------------------------------------------------------
        self._state: WorkflowState = WorkflowState.IDLE
        self._previous_state: WorkflowState = WorkflowState.IDLE
        self._error_message: Optional[str] = None
        self._step_retry_count: int = 0

        # ------------------------------------------------------------------
        # 阶段产出物 — 上游阶段写入，下游阶段读取
        # ------------------------------------------------------------------
        self._artifacts: dict[str, Any] = {}

        # ------------------------------------------------------------------
        # Agent 状态追踪
        # ------------------------------------------------------------------
        self._role_statuses: dict[str, str] = {
            role.value: "idle" for role in AgentRole
        }
        self._role_tasks: dict[str, Optional[str]] = {
            role.value: None for role in AgentRole
        }

    # ==================================================================
    # Properties
    # ==================================================================

    @property
    def state(self) -> WorkflowState:
        """返回当前工作流状态。"""
        return self._state

    @property
    def session_id(self) -> Optional[str]:
        """返回当前会话 ID。"""
        return self._session_context.get("session_id")

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

        由 Parser Agent（Tutor 角色）解析 PDF 材料，生成知识片段。

        Raises:
            OrchestratorError: 若不是从 IDLE 状态调用。
        """
        if self._state != WorkflowState.IDLE:
            raise OrchestratorError(
                f"无法从 '{self._state.value}' 启动，"
                f"需要 '{WorkflowState.IDLE.value}' 状态。"
            )

        self._transition_to(WorkflowState.PARSING)
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
            OrchestratorError: 若当前状态不允许提交作答。
        """
        if self._state != WorkflowState.QUIZ_GEN:
            raise OrchestratorError(
                f"无法在 '{self._state.value}' 状态下提交作答，"
                f"请先完成 QUIZ_GEN 阶段（当前需要 '{WorkflowState.QUIZ_GEN.value}'）。"
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
        logger.info(
            "提交 %d 条学生作答（%d 条成功反序列化为 QuizAttempt）。",
            len(answers),
            len(attempts),
        )
        return len(attempts)

    async def proceed(self) -> None:
        """推进流水线一步。

        根据当前状态自动判断下一步并执行对应阶段。

        Raises:
            OrchestratorError: 若从 IDLE / PAUSED / ERROR / DONE 调用。
        """
        if self._state in (
            WorkflowState.IDLE,
            WorkflowState.PAUSED,
            WorkflowState.ERROR,
            WorkflowState.DONE,
        ):
            raise OrchestratorError(
                f"无法从 '{self._state.value}' 推进，"
                f"请先调用 start() / resume() / retry_step()。"
            )

        next_state = self._compute_next_state()
        self._transition_to(next_state)
        await self._execute_phase(next_state)

    async def pause(self) -> None:
        """暂停流水线。

        保存当前状态以便 ``resume()`` 恢复。已暂停时调用为幂等操作。

        Raises:
            OrchestratorError: 若从 DONE / ERROR 等终态调用。
        """
        if self._state == WorkflowState.PAUSED:
            return
        if self._state in (WorkflowState.DONE, WorkflowState.ERROR):
            raise OrchestratorError(
                f"无法从终态 '{self._state.value}' 暂停。"
            )

        self._previous_state = self._state
        self._transition_to(WorkflowState.PAUSED)
        logger.info("流水线已暂停（原状态: %s）。", self._previous_state.value)

    async def resume(self) -> None:
        """从 PAUSED 恢复到之前的状态。

        Raises:
            OrchestratorError: 若当前不是 PAUSED 状态。
        """
        if self._state != WorkflowState.PAUSED:
            raise OrchestratorError(
                f"无法从 '{self._state.value}' 恢复，"
                f"需要 '{WorkflowState.PAUSED.value}' 状态。"
            )

        self._transition_to(self._previous_state)
        logger.info("流水线已恢复到 %s。", self._state.value)

    async def retry_step(self) -> None:
        """重试当前失败步骤。

        限制连续重试 ``_MAX_STEP_RETRIES`` 次，超过后保持 ERROR。

        Raises:
            OrchestratorError: 若当前不是 ERROR 状态。
        """
        if self._state != WorkflowState.ERROR:
            raise OrchestratorError(
                f"无法从 '{self._state.value}' 重试，"
                f"需要 '{WorkflowState.ERROR.value}' 状态。"
            )

        self._step_retry_count += 1
        if self._step_retry_count > _MAX_STEP_RETRIES:
            self._error_message = (
                f"步骤重试已达上限（{_MAX_STEP_RETRIES} 次），请人工介入。"
            )
            logger.error(self._error_message)
            return

        failed_state = self._previous_state
        self._transition_to(failed_state)
        logger.info(
            "重试步骤（%d/%d），目标状态: %s。",
            self._step_retry_count,
            _MAX_STEP_RETRIES,
            failed_state.value,
        )
        self._error_message = None
        await self._execute_phase(failed_state)

    async def get_status(self) -> dict[str, Any]:
        """返回当前流水线状态快照。

        Returns:
            包含状态、阶段产物摘要及各 Agent 状态的字典。
        """
        return {
            "state": self._state.value,
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
                for role in AgentRole
            },
        }

    # ==================================================================
    # 阶段实现
    # ==================================================================

    async def _parsing_phase(self) -> None:
        """PARSING 阶段：Tutor 解析 PDF 材料。

        输入：session_context 中的 material_id
        产出：KnowledgeChunk 列表（摘要形式），写入 _artifacts["chunks"]
        下一状态：QUIZ_GEN
        """
        role = AgentRole.TUTOR
        self._set_role_status(role, "active", "解析 PDF 材料，生成知识片段")

        material_id = self._session_context.get("material_id", "unknown")

        try:
            prompt = _build_parsing_prompt(material_id)

            system_prompt = self._roles.build_context(
                role=role.value,
                project_path="",  # 教学场景无需项目路径
                extra_context={
                    "phase": "parsing",
                    "material_id": material_id,
                    "action": "解析 PDF 内容，输出知识片段列表",
                },
            )

            response = await self._invoke_role(
                role=role.value,
                user_message=prompt,
                system_prompt=system_prompt,
                tier=_PARSING_MODEL_TIER,
            )

            # 防御解析：从 LLM 响应中提取 chunks 列表
            chunks_raw = _safe_parse_json_list(response, "chunks")
            chunks = _hydrate_models(
                chunks_raw,
                KnowledgeChunk,
                defaults={"material_id": material_id},
            )
            self._artifacts["chunks"] = chunks_raw       # 保留原始 dict 供 LLM prompt
            self._artifacts["chunk_models"] = chunks      # Pydantic 模型供内部消费
            self._artifacts["parsing_output"] = response

            await self._on_step_complete(
                role=role.value,
                artifact={
                    "type": "parsing_result",
                    "title": "PDF 解析结果",
                    "summary_256": f"生成 {len(chunks)} 个知识片段",
                    "full_text": response[:2000],
                },
            )

            self._set_role_status(role, "idle", None)
            logger.info("PARSING 阶段完成：%d 个知识片段。", len(chunks))

        except Exception as exc:
            self._set_role_status(role, "error", str(exc))
            self._handle_phase_error(exc)
            raise

    async def _quiz_gen_phase(self) -> None:
        """QUIZ_GEN 阶段：Assistant 基于知识库生成测验题目。

        输入：_artifacts["chunks"]
        产出：Question 列表 + QuizSession，写入 _artifacts["questions"]
        下一状态：EVALUATING
        """
        role = AgentRole.ASSISTANT
        self._set_role_status(role, "active", "基于知识库生成测验题目")

        chunks = self._artifacts.get("chunks", [])

        try:
            prompt = _build_quiz_gen_prompt(chunks)

            system_prompt = self._roles.build_context(
                role=role.value,
                project_path="",
                extra_context={
                    "phase": "quiz_gen",
                    "chunk_count": str(len(chunks)),
                    "action": "根据知识片段生成测验题目",
                },
            )

            response = await self._invoke_role(
                role=role.value,
                user_message=prompt,
                system_prompt=system_prompt,
                tier=_QUIZ_GEN_MODEL_TIER,
            )

            questions_raw = _safe_parse_json_list(response, "questions")
            # 关联 chunk_ids 作为默认字段注入
            chunk_id_list = [
                c.get("chunk_id", "") for c in self._artifacts.get("chunks", [])
            ]
            questions = _hydrate_models(
                questions_raw,
                Question,
                defaults={"chunk_ids": chunk_id_list} if chunk_id_list else None,
            )
            self._artifacts["questions"] = questions_raw     # 保留原始 dict 供 LLM prompt
            self._artifacts["question_models"] = questions    # Pydantic 模型供内部消费
            self._artifacts["quiz_gen_output"] = response

            await self._on_step_complete(
                role=role.value,
                artifact={
                    "type": "quiz_generation",
                    "title": "题目生成结果",
                    "summary_256": f"生成 {len(questions)} 道题目",
                    "full_text": response[:2000],
                },
            )

            self._set_role_status(role, "idle", None)
            logger.info("QUIZ_GEN 阶段完成：%d 道题目。", len(questions))

        except Exception as exc:
            self._set_role_status(role, "error", str(exc))
            self._handle_phase_error(exc)
            raise

    async def _evaluating_phase(self) -> None:
        """EVALUATING 阶段：Evaluator 批改学生作答。

        输入：_artifacts["questions"] + 学生作答数据
        产出：批改结果 + MisconceptionTag 列表，写入 _artifacts["attempts"]
        下一状态：PLANNING
        """
        role = AgentRole.EVALUATOR
        self._set_role_status(role, "active", "批改作答，诊断迷思概念")

        questions = self._artifacts.get("questions", [])
        student_answers = self._session_context.get("student_answers", [])

        try:
            prompt = _build_evaluating_prompt(questions, student_answers)

            system_prompt = self._roles.build_context(
                role=role.value,
                project_path="",
                extra_context={
                    "phase": "evaluating",
                    "question_count": str(len(questions)),
                    "action": "批改学生作答并诊断迷思概念",
                },
            )

            response = await self._invoke_role(
                role=role.value,
                user_message=prompt,
                system_prompt=system_prompt,
                tier=_EVALUATING_MODEL_TIER,
            )

            attempts_raw = _safe_parse_json_list(response, "attempts")
            misconceptions_raw = _safe_parse_json_list(response, "misconceptions")

            session_id = self.session_id or "unknown"
            attempts = _hydrate_models(
                attempts_raw,
                QuizAttempt,
                defaults={"session_id": session_id},
            )
            misconceptions = _hydrate_models(
                misconceptions_raw,
                MisconceptionTag,
            )
            self._artifacts["attempts"] = attempts_raw
            self._artifacts["misconceptions"] = misconceptions_raw
            self._artifacts["attempt_models"] = attempts
            self._artifacts["misconception_models"] = misconceptions
            self._artifacts["evaluating_output"] = response

            await self._on_step_complete(
                role=role.value,
                artifact={
                    "type": "evaluation_result",
                    "title": "批改与诊断结果",
                    "summary_256": (
                        f"批改 {len(attempts)} 题，"
                        f"诊断 {len(misconceptions)} 个迷思概念"
                    ),
                    "full_text": response[:2000],
                },
            )

            self._set_role_status(role, "idle", None)
            logger.info(
                "EVALUATING 阶段完成：%d 题已批改，%d 个迷思概念。",
                len(attempts),
                len(misconceptions),
            )

        except Exception as exc:
            self._set_role_status(role, "error", str(exc))
            self._handle_phase_error(exc)
            raise

    async def _planning_phase(self) -> None:
        """PLANNING 阶段：Tutor 生成 SM-2 排期学习计划。

        输入：_artifacts 中的批改结果 + 迷思概念
        产出：StudyPlan（ReviewItem 列表），写入 _artifacts["plan_items"]
        下一状态：DONE
        """
        role = AgentRole.TUTOR
        self._set_role_status(role, "active", "生成 SM-2 排期学习计划")

        attempts = self._artifacts.get("attempts", [])
        misconceptions = self._artifacts.get("misconceptions", [])

        try:
            prompt = _build_planning_prompt(attempts, misconceptions)

            system_prompt = self._roles.build_context(
                role=role.value,
                project_path="",
                extra_context={
                    "phase": "planning",
                    "attempt_count": str(len(attempts)),
                    "misconception_count": str(len(misconceptions)),
                    "action": "综合评估数据生成 SM-2 间隔重复排期计划",
                },
            )

            response = await self._invoke_role(
                role=role.value,
                user_message=prompt,
                system_prompt=system_prompt,
                tier=_PLANNING_MODEL_TIER,
            )

            plan_items_raw = _safe_parse_json_list(response, "plan_items")
            plan_items = _hydrate_models(
                plan_items_raw,
                ReviewItem,
                defaults={
                    "mastery_record_id": self._session_context.get(
                        "student_id", ""
                    ),
                },
            )
            self._artifacts["plan_items"] = plan_items_raw
            self._artifacts["plan_item_models"] = plan_items
            self._artifacts["planning_output"] = response

            await self._on_step_complete(
                role=role.value,
                artifact={
                    "type": "study_plan",
                    "title": "SM-2 排期学习计划",
                    "summary_256": f"生成 {len(plan_items)} 个复习条目",
                    "full_text": response[:2000],
                },
            )

            self._set_role_status(role, "idle", None)
            logger.info("PLANNING 阶段完成：%d 个排期条目。", len(plan_items))

        except Exception as exc:
            self._set_role_status(role, "error", str(exc))
            self._handle_phase_error(exc)
            raise

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
        """调用 AI Agent 并记录 token 用量。

        封装 ``LLMClient.chat_with_file_context``，增加角色校验、
        token 日志和错误传播。

        Args:
            role: Agent 标识（``"tutor"`` / ``"assistant"`` / ``"evaluator"``）。
            user_message: 给 Agent 的指令或上下文。
            system_prompt: 系统提示词。None 时由 RoleManager 自动加载。
            tier: 算力档位（``"heavy"`` / ``"medium"`` / ``"light"``）。

        Returns:
            Agent 的完整响应文本。

        Raises:
            LLMClientError: API 调用失败（重试耗尽后）。
        """
        if role not in VALID_ROLES:
            raise OrchestratorError(
                f"未知角色 '{role}'。有效角色: {sorted(VALID_ROLES)}"
            )

        try:
            response = await self._llm.chat_with_file_context(
                role=role,
                user_message=user_message,
                files=[],
                tier=tier,
                system_prompt=system_prompt,
            )

            await self._db.log_token_usage(
                {
                    "project_id": self.session_id or "unknown",
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
            logger.error("调用 Agent '%s' 时发生异常: %s", role, exc)
            raise LLMClientError(
                f"调用 Agent '{role}' 失败: {exc}"
            ) from exc

    # ==================================================================
    # 状态机辅助方法
    # ==================================================================

    def _compute_next_state(self) -> WorkflowState:
        """根据当前状态计算下一个状态。"""
        transitions: dict[WorkflowState, WorkflowState] = {
            WorkflowState.PARSING: WorkflowState.QUIZ_GEN,
            WorkflowState.QUIZ_GEN: WorkflowState.EVALUATING,
            WorkflowState.EVALUATING: WorkflowState.PLANNING,
            WorkflowState.PLANNING: WorkflowState.DONE,
        }
        return transitions.get(self._state, self._state)

    def _transition_to(self, new_state: WorkflowState) -> None:
        """执行状态转换并记录日志。"""
        old = self._state
        self._state = new_state
        logger.info("状态转换: %s → %s", old.value, new_state.value)

    async def _execute_phase(self, state: WorkflowState) -> None:
        """根据状态执行对应阶段。"""
        phase_map = {
            WorkflowState.PARSING: self._parsing_phase,
            WorkflowState.QUIZ_GEN: self._quiz_gen_phase,
            WorkflowState.EVALUATING: self._evaluating_phase,
            WorkflowState.PLANNING: self._planning_phase,
        }

        handler = phase_map.get(state)
        if handler:
            await handler()
        elif state == WorkflowState.DONE:
            logger.info("流水线已完成 —— 全部阶段执行完毕。")

        # 成功后重置重试计数器
        self._step_retry_count = 0

    def _handle_phase_error(self, exc: Exception) -> None:
        """将阶段异常转为 ERROR 状态。"""
        self._error_message = str(exc)
        self._previous_state = self._state
        self._transition_to(WorkflowState.ERROR)
        logger.error("阶段执行失败: %s", exc)

    # ==================================================================
    # 持久化 & Agent 状态辅助
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

    def _set_role_status(
        self, role: AgentRole, status: str, task: Optional[str] = None
    ) -> None:
        """更新 Agent 的追踪状态。"""
        self._role_statuses[role.value] = status
        self._role_tasks[role.value] = task


# ======================================================================
# 阶段 Prompt 构建函数（模块级辅助函数）
# ======================================================================


def _build_parsing_prompt(material_id: str) -> str:
    """构建 PDF 解析阶段的用户提示词。"""
    return (
        "你是一位教学资料分析专家。请分析以下学习材料，将其拆分为独立的知识片段。\n\n"
        f"材料 ID: {material_id}\n\n"
        "## 输出要求\n"
        "将材料内容按知识点边界切分为多个 chunk，每个 chunk 包含：\n"
        "1. **content**: 原文片段（保持完整语义，200-2000 字）\n"
        "2. **summary**: 一句话摘要（≤256 字符）\n"
        "3. **topic**: 主题标签（如'牛顿定律'、'矩阵运算'）\n"
        "4. **difficulty**: 难度评估（beginner / easy / medium / hard / expert）\n"
        "5. **keywords**: 3-5 个关键词\n\n"
        "请以 JSON 数组格式输出，格式为：\n"
        '```json\n{"chunks": [{"content": "...", "summary": "...", '
        '"topic": "...", "difficulty": "medium", "keywords": ["..."]}]}\n```\n\n'
        "注意：\n"
        "- 保持原文语义完整，不要截断句子\n"
        "- 数学公式/代码块保持原样\n"
        "- 按原文顺序排列 chunks"
    )


def _build_quiz_gen_prompt(chunks: list[dict[str, Any]]) -> str:
    """构建题目生成阶段的用户提示词。"""
    # 限制 chunks 数量以避免 prompt 过长
    chunks_preview = chunks[:15] if len(chunks) > 15 else chunks
    chunks_json = _safe_truncate_json(chunks_preview, max_items=15)

    return (
        "你是一位资深教学出题专家。请根据以下知识片段生成一套测验题。\n\n"
        f"## 知识片段（共 {len(chunks)} 个）\n"
        f"```json\n{chunks_json}\n```\n\n"
        "## 出题要求\n"
        "1. 每个知识片段至少出 1 道题\n"
        "2. 题型以选择题（multiple_choice）为主，可含少量简答题（short_answer）\n"
        "3. 难度分布：记忆 30% / 理解 40% / 应用 20% / 分析 10%\n"
        "4. 每道题包含：\n"
        "   - **stem**: 题干\n"
        "   - **type**: 题目类型\n"
        "   - **options**: 选项列表 [{'key': 'A', 'text': '...'}, ...]\n"
        "   - **correct_answer**: 正确答案\n"
        "   - **explanation**: 详细解析\n"
        "   - **difficulty**: 难度评估\n"
        "   - **knowledge_node_ids**: 考查的知识点\n\n"
        "请以 JSON 数组格式输出：\n"
        '```json\n{"questions": [{"stem": "...", "type": "multiple_choice", '
        '"options": [...], "correct_answer": "A", "explanation": "...", '
        '"difficulty": "easy", "knowledge_node_ids": ["..."]}]}\n```'
    )


def _build_evaluating_prompt(
    questions: list[dict[str, Any]],
    student_answers: list[dict[str, Any]],
) -> str:
    """构建批改诊断阶段的用户提示词。"""
    questions_json = _safe_truncate_json(questions, max_items=20)
    answers_json = _safe_truncate_json(student_answers, max_items=20)

    return (
        "你是一位严谨的教学评估专家。请批改学生的作答并诊断其迷思概念。\n\n"
        f"## 题目\n```json\n{questions_json}\n```\n\n"
        f"## 学生作答\n```json\n{answers_json}\n```\n\n"
        "## 评估要求\n"
        "1. 逐题判定对错（is_correct）\n"
        "2. 为错题诊断迷思概念（misconception）：\n"
        "   - **label**: 错误标签（如'动量与动能混淆'）\n"
        "   - **category**: 错误类别（conceptual / calculation / careless / "
        "application / logic / notation / incomplete）\n"
        "   - **description**: 错误详细描述\n"
        "   - **remediation_hint**: 补救建议\n"
        "3. 为每道错题提供一条苏格拉底式引导提示（不直接给答案，引导学生自己发现）\n\n"
        "请以 JSON 格式输出：\n"
        '```json\n{\n'
        '  "attempts": [{"question_id": "...", "is_correct": false, '
        '"score": 0.0, "misconception_ids": ["..."]}],\n'
        '  "misconceptions": [{"label": "...", "category": "conceptual", '
        '"description": "...", "remediation_hint": "..."}]\n'
        '}\n```'
    )


def _build_planning_prompt(
    attempts: list[dict[str, Any]],
    misconceptions: list[dict[str, Any]],
) -> str:
    """构建排期计划阶段的用户提示词。"""
    attempts_json = _safe_truncate_json(attempts, max_items=20)
    misconceptions_json = _safe_truncate_json(misconceptions, max_items=10)

    return (
        "你是一位学习规划专家。请根据学生的作答表现和迷思概念诊断，"
        "制定一份基于 SM-2 算法的间隔重复复习计划。\n\n"
        f"## 作答记录\n```json\n{attempts_json}\n```\n\n"
        f"## 迷思概念\n```json\n{misconceptions_json}\n```\n\n"
        "## 排期要求\n"
        "1. 对每个未掌握的知识点，安排复习条目（review item）\n"
        "2. 使用 SM-2 算法计算复习间隔：\n"
        "   - 首次学习: 1 天后复习\n"
        "   - 第二次: 6 天后复习\n"
        "   - 之后: interval = previous_interval × EF\n"
        "3. 优先级规则：薄弱知识点 × 逾期天数（弱且紧急的排前面）\n"
        "4. 每天学习量不超过 2 小时\n"
        "5. 每个复习条目包含：\n"
        "   - **scheduled_date**: 计划复习日期\n"
        "   - **activity_type**: review / practice / quiz\n"
        "   - **estimated_minutes**: 预计耗时\n"
        "   - **knowledge_node_id**: 对应知识点\n\n"
        "请以 JSON 数组格式输出：\n"
        '```json\n{"plan_items": [{"scheduled_date": "2025-01-01", '
        '"activity_type": "review", "estimated_minutes": 15, '
        '"knowledge_node_id": "..."}]}\n```'
    )


# ======================================================================
# 通用辅助函数
# ======================================================================


def _safe_parse_json_list(
    response: str, key: str
) -> list[dict[str, Any]]:
    """从 LLM 响应中安全提取 JSON 列表。

    使用 4 层防御策略：
    1. 直接 ``json.loads`` 整个响应
    2. 正则提取 ```json ... ``` 围栏代码块
    3. 正则提取第一个 ``{...}`` 或 ``[...]``
    4. 返回空列表

    Args:
        response: LLM 原始响应文本。
        key: 期望的 JSON 对象键名（如 ``"chunks"``、``"questions"``）。

    Returns:
        解析出的字典列表，失败时返回空列表。
    """
    # 第 1 层：尝试直接解析整个响应
    try:
        data = _json.loads(response)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and key in data:
            items = data[key]
            return items if isinstance(items, list) else [items]
    except (_json.JSONDecodeError, TypeError):
        pass

    # 第 2 层：提取 ```json ... ``` 围栏代码块
    fence_match = _re.search(
        r"```(?:json)?\s*\n?([\s\S]*?)\n?```", response
    )
    if fence_match:
        try:
            data = _json.loads(fence_match.group(1).strip())
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and key in data:
                items = data[key]
                return items if isinstance(items, list) else [items]
        except (_json.JSONDecodeError, TypeError):
            pass

    # 第 3 层：查找第一个 JSON 对象或数组
    json_match = _re.search(r"(\[.*\]|\{.*\})", response, _re.DOTALL)
    if json_match:
        try:
            data = _json.loads(json_match.group(1))
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and key in data:
                items = data[key]
                return items if isinstance(items, list) else [items]
        except (_json.JSONDecodeError, TypeError):
            pass

    # 第 4 层：放弃，返回空列表
    logger.warning(
        "_safe_parse_json_list: 无法解析 LLM 响应为 JSON，"
        "key=%s，响应前 200 字符: %s",
        key,
        response[:200],
    )
    return []


def _hydrate_models(
    raw_items: list[dict[str, Any]],
    model_cls: type,
    *,
    defaults: Optional[dict[str, Any]] = None,
) -> list[Any]:
    """将 LLM 输出的原始字典列表反序列化为 Pydantic 模型实例。

    逐条尝试 ``model_cls(**defaults, **item)``，验证失败的条目
    记录警告后跳过，确保单个脏数据不影响整批产出物。

    Args:
        raw_items: LLM 输出的原始字典列表。
        model_cls: 目标 Pydantic 模型类（如 ``KnowledgeChunk``）。
        defaults: 注入到每条记录的默认字段值
                  （如 ``material_id``、``session_id`` 等运行时上下文）。

    Returns:
        成功反序列化的模型实例列表（可能短于输入）。
    """
    models: list[Any] = []
    merged_defaults = defaults or {}
    for i, item in enumerate(raw_items):
        try:
            merged = {**merged_defaults, **item}
            models.append(model_cls(**merged))
        except Exception as exc:
            logger.warning(
                "_hydrate_models: 第 %d 条 %s 反序列化失败: %s",
                i,
                model_cls.__name__,
                exc,
            )
    if models:
        logger.debug(
            "_hydrate_models: %d/%d 条成功反序列化为 %s。",
            len(models),
            len(raw_items),
            model_cls.__name__,
        )
    return models


def _safe_truncate_json(
    items: list[dict[str, Any]], max_items: int = 15
) -> str:
    """将列表截断并序列化为 JSON 字符串。

    超过 ``max_items`` 时自动截断并附加占位提示。

    Args:
        items: 待序列化的字典列表。
        max_items: 最大保留条数。

    Returns:
        JSON 字符串。
    """
    truncated = items[:max_items]
    result = _json.dumps(truncated, ensure_ascii=False, indent=2)
    if len(items) > max_items:
        result += f"\n// ... 共 {len(items)} 条，已截断显示前 {max_items} 条"
    return result


def _estimate_tokens(user_message: str, response: str) -> int:
    """粗略估算 token 数（按英文词数 / 0.75）。"""
    word_count = len(user_message.split()) + len(response.split())
    return max(1, int(word_count / 0.75))
