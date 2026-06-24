"""Orchestrator — 阶段实现 Mixin。

包含 PARSING / QUIZ_GEN / EVALUATING / PLANNING 四个流水线阶段的
具体实现，以及掌握度记录持久化逻辑。

作为 ``_PhaseHandlers`` mixin 被 ``Orchestrator`` 继承，方法内通过
``self`` 访问编排器的完整运行时状态（DB、LLM、artifacts 等）。
"""

from __future__ import annotations

import json as _json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from super_tutor.core.orchestrator_prompts import (
    _build_evaluating_prompt,
    _build_parsing_prompt,
    _build_planning_prompt,
    _build_quiz_gen_prompt,
)
from super_tutor.core.orchestrator_utils import (
    _build_knowledge_graph,
    _hydrate_models,
    _safe_parse_json_list,
)
from super_tutor.models.enums import AIRole, PipelinePhase
from super_tutor.models.knowledge import KnowledgeChunk
from super_tutor.models.mastery import ReviewItem
from super_tutor.models.quiz import MisconceptionTag, Question, QuizAttempt

if TYPE_CHECKING:
    from super_tutor.core.orchestrator import Orchestrator  # noqa: F401

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 各阶段使用的 LLM 算力档位
# ---------------------------------------------------------------------------

_PARSING_MODEL_TIER: str = "heavy"       # PDF 解析需要强理解能力
_QUIZ_GEN_MODEL_TIER: str = "heavy"      # 出题需要高质量输出
_EVALUATING_MODEL_TIER: str = "medium"    # 批改中等算力即可
_PLANNING_MODEL_TIER: str = "medium"      # 排期计算中等算力即可


# ======================================================================
# _PhaseHandlers Mixin
# ======================================================================


class _PhaseHandlers:
    """Mixin 提供四个流水线阶段的实现方法。

    所有方法通过 ``self`` 访问 ``Orchestrator`` 的完整状态：
    ``_db``、``_llm``、``_roles``、``_session_context``、``_artifacts`` 等。
    """

    # ==================================================================
    # PARSING
    # ==================================================================

    async def _parsing_phase(self: "Orchestrator") -> None:
        """PARSING 阶段：Tutor 解析 PDF 材料。

        输入：session_context 中的 material_id → 从 DB 读取全文
        产出：KnowledgeChunk 列表 + KnowledgeGraph，写入 _artifacts
        下一状态：QUIZ_GEN
        """
        role = AIRole.TUTOR
        await self._start_phase(PipelinePhase.PARSING, role, "解析 PDF 材料，生成知识片段")

        material_id = self._session_context.get("material_id", "unknown")

        # -- 从数据库读取材料全文 ------------------------------------------
        material_content = ""
        try:
            material = await self._db.get_material(material_id)
            if material is not None:
                material_content = material.get("content", "")
                logger.info(
                    "PARSING: 已从 DB 读取材料全文 (%d 字符)。",
                    len(material_content),
                )
            else:
                logger.warning(
                    "PARSING: material_id=%s 在数据库中未找到，"
                    "LLM 将收到空文档。",
                    material_id,
                )
        except Exception as exc:
            logger.warning(
                "PARSING: 无法从 DB 读取材料全文: %s。将使用空文档继续。",
                exc,
            )

        if not material_content.strip():
            logger.error(
                "PARSING: 材料全文为空！material_id=%s。"
                "请确认材料上传时内容已正确保存。",
                material_id,
            )

        try:
            prompt = _build_parsing_prompt(material_id, material_content)

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

            # -- 构建知识图谱（F? — PARSING 阶段后从 chunks 自动构建） --
            graph = _build_knowledge_graph(chunks_raw)
            self._artifacts["knowledge_graph"] = graph.model_dump()
            logger.info(
                "KnowledgeGraph: %d nodes, %d edges constructed.",
                len(graph.nodes),
                len(graph.edges),
            )

            await self._on_step_complete(
                role=role.value,
                artifact={
                    "type": "parsing_result",
                    "title": "PDF 解析结果",
                    "summary_256": f"生成 {len(chunks)} 个知识片段",
                    "full_text": response[:2000],
                },
            )

            await self._end_phase(PipelinePhase.PARSING, role)
            logger.info("PARSING 阶段完成：%d 个知识片段。", len(chunks))

        except Exception as exc:
            self._set_role_status(role, "error", str(exc))
            await self._handle_phase_error(exc)
            raise

    # ==================================================================
    # QUIZ_GEN
    # ==================================================================

    async def _quiz_gen_phase(self: "Orchestrator") -> None:
        """QUIZ_GEN 阶段：Assistant 基于知识库生成测验题目。

        输入：_artifacts["chunks"]
        产出：Question 列表 + QuizSession，写入 _artifacts["questions"]
        下一状态：EVALUATING
        """
        role = AIRole.ASSISTANT
        await self._start_phase(PipelinePhase.QUIZ_GEN, role, "基于知识库生成测验题目")

        chunks = self._artifacts.get("chunks", [])
        question_count = int(
            self._session_context.get("question_count", 10)
        )
        difficulty = str(
            self._session_context.get("difficulty", "medium")
        )

        try:
            prompt = _build_quiz_gen_prompt(
                chunks,
                question_count=question_count,
                difficulty=difficulty,
            )

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

            # -- 持久化题目到 questions 表（避免丢失后重新消耗 Token）--
            session_id = self.session_id or "unknown"
            now_iso = datetime.now(timezone.utc).isoformat()
            persisted_q = 0
            for i, q_raw in enumerate(questions_raw):
                try:
                    qid = q_raw.get("question_id", str(uuid4()))
                    await self._db.insert_question({
                        "question_id": qid,
                        "session_id": session_id,
                        "type": q_raw.get("type", "multiple_choice"),
                        "difficulty": q_raw.get("difficulty", "medium"),
                        "subject": q_raw.get("subject", ""),
                        "topic": q_raw.get("topic", ""),
                        "stem": q_raw.get("stem", ""),
                        "options": q_raw.get("options", []),
                        "correct_answer": q_raw.get("correct_answer", ""),
                        "explanation": q_raw.get("explanation", ""),
                        "chunk_ids": q_raw.get("chunk_ids", chunk_id_list),
                        "knowledge_node_ids": q_raw.get("knowledge_node_ids", []),
                        "estimated_seconds": q_raw.get("estimated_seconds", 120),
                        "points": q_raw.get("points", 1.0),
                        "tags": q_raw.get("tags", []),
                        "metadata": q_raw.get("metadata", {}),
                        "created_at": now_iso,
                    })
                    persisted_q += 1
                except Exception as exc:
                    logger.warning(
                        "题目 %s 持久化失败: %s",
                        q_raw.get("question_id", f"#{i}"), exc,
                    )
            logger.info(
                "QUIZ_GEN: %d/%d 道题目已持久化到 questions 表。",
                persisted_q, len(questions_raw),
            )

            await self._on_step_complete(
                role=role.value,
                artifact={
                    "type": "quiz_generation",
                    "title": "题目生成结果",
                    "summary_256": f"生成 {len(questions)} 道题目",
                    "full_text": response[:2000],
                },
            )

            self._quiz_status = "ready"  # 题目已生成，等待学生作答
            await self._end_phase(PipelinePhase.QUIZ_GEN, role)
            logger.info("QUIZ_GEN 阶段完成：%d 道题目。", len(questions))

        except Exception as exc:
            self._set_role_status(role, "error", str(exc))
            await self._handle_phase_error(exc)
            raise

    # ==================================================================
    # EVALUATING
    # ==================================================================

    async def _evaluating_phase(self: "Orchestrator") -> None:
        """EVALUATING 阶段：Evaluator 批改学生作答。

        输入：_artifacts["questions"] + 学生作答数据
        产出：批改结果 + MisconceptionTag 列表 + SocraticHints，写入 _artifacts
        下一状态：PLANNING
        """
        role = AIRole.EVALUATOR
        await self._start_phase(PipelinePhase.EVALUATING, role, "批改作答，诊断迷思概念")

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

            # -- 提取 summary（用于前端展示） --
            summary_raw: dict[str, Any] = {}
            try:
                data = _json.loads(response)
                if isinstance(data, dict) and "summary" in data:
                    summary_raw = data["summary"]
            except (_json.JSONDecodeError, TypeError):
                pass

            session_id = self.session_id or "unknown"
            student_id = self._session_context.get("student_id", "")
            attempts = _hydrate_models(
                attempts_raw,
                QuizAttempt,
                defaults={"session_id": session_id, "student_id": student_id},
            )
            misconceptions = _hydrate_models(
                misconceptions_raw,
                MisconceptionTag,
            )

            # -- 提取苏格拉底式渐进提示（F8） --
            socratic_hints_raw: list[dict[str, Any]] = []
            for i, m_raw in enumerate(misconceptions_raw):
                tag_id = m_raw.get("tag_id", str(uuid4()))
                hints_data = m_raw.get("socratic_hints", [])
                if isinstance(hints_data, list):
                    for h in hints_data:
                        if isinstance(h, dict):
                            socratic_hints_raw.append({
                                "hint_id": str(uuid4()),
                                "question_id": m_raw.get("knowledge_node_ids", [""])[0]
                                if m_raw.get("knowledge_node_ids") else "",
                                "misconception_tag_id": tag_id,
                                "level": h.get("level", 1),
                                "content": h.get("content", ""),
                                "trigger_after_failures": h.get("trigger_after_failures", 1),
                                "difficulty_adapt": h.get("difficulty_adapt", True),
                            })

            # 持久化苏格拉底提示到 DB
            if socratic_hints_raw:
                try:
                    await self._db.insert_socratic_hints_batch(socratic_hints_raw)
                    logger.info(
                        "EVALUATING: %d socratic hints persisted.",
                        len(socratic_hints_raw),
                    )
                except Exception as exc:
                    logger.warning("Failed to persist socratic hints: %s", exc)

            self._artifacts["attempts"] = attempts_raw
            self._artifacts["misconceptions"] = misconceptions_raw
            self._artifacts["socratic_hints"] = socratic_hints_raw
            self._artifacts["evaluating_summary"] = summary_raw
            self._artifacts["attempt_models"] = attempts
            self._artifacts["misconception_models"] = misconceptions
            self._artifacts["evaluating_output"] = response

            # -- 持久化作答记录到 quiz_attempts 表 -------------------------
            now_iso = datetime.now(timezone.utc).isoformat()
            persisted = 0
            for raw_attempt in attempts_raw:
                try:
                    await self._db.insert_attempt(
                        {
                            "attempt_id": raw_attempt.get("attempt_id", str(uuid4())),
                            "session_id": session_id,
                            "student_id": student_id,
                            "question_id": raw_attempt.get("question_id", ""),
                            "student_answer": raw_attempt.get("student_answer"),
                            "is_correct": raw_attempt.get("is_correct"),
                            "score": raw_attempt.get("score"),
                            "time_spent_seconds": raw_attempt.get("time_spent_seconds", 0),
                            "hints_used": raw_attempt.get("hints_used", 0),
                            "attempt_number": raw_attempt.get("attempt_number", 1),
                            "confidence": raw_attempt.get("confidence"),
                            "misconception_ids": raw_attempt.get("misconception_ids", []),
                            "note": raw_attempt.get("note", ""),
                            "started_at": raw_attempt.get("started_at", now_iso),
                            "submitted_at": raw_attempt.get("submitted_at", now_iso),
                            "metadata": raw_attempt.get("metadata", {}),
                        }
                    )
                    persisted += 1
                except Exception as exc:
                    logger.warning(
                        "Failed to persist attempt %s: %s",
                        raw_attempt.get("attempt_id", "?"),
                        exc,
                    )
            logger.info(
                "EVALUATING: %d/%d attempts persisted to DB (student_id=%r).",
                persisted,
                len(attempts_raw),
                student_id,
            )

            # -- 更新掌握度记录 (mastery_records) ---------------------------
            if student_id:
                await self._persist_mastery_records(
                    student_id=student_id,
                    attempts_raw=attempts_raw,
                    session_id=session_id,
                )

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

            self._quiz_status = "graded"  # 批改完成
            await self._end_phase(PipelinePhase.EVALUATING, role)
            logger.info(
                "EVALUATING 阶段完成：%d 题已批改，%d 个迷思概念。",
                len(attempts),
                len(misconceptions),
            )

        except Exception as exc:
            self._set_role_status(role, "error", str(exc))
            await self._handle_phase_error(exc)
            raise

    # ==================================================================
    # PLANNING
    # ==================================================================

    async def _planning_phase(self: "Orchestrator") -> None:
        """PLANNING 阶段：Tutor 生成 SM-2 排期学习计划。

        输入：_artifacts 中的批改结果 + 迷思概念
        产出：StudyPlan（ReviewItem 列表），写入 _artifacts["plan_items"]
        下一状态：DONE
        """
        role = AIRole.TUTOR
        await self._start_phase(PipelinePhase.PLANNING, role, "生成 SM-2 排期学习计划")

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
                defaults={},  # mastery_record_id 由后续 DB 关联决定，不在此硬编码
            )
            self._artifacts["plan_items"] = plan_items_raw
            self._artifacts["plan_item_models"] = plan_items
            self._artifacts["planning_output"] = response

            # -- 持久化排期计划到 study_plans + review_items 表 -----------
            student_id = self._session_context.get("student_id", "")
            if student_id and plan_items_raw:
                try:
                    plan_id = str(uuid4())
                    today_str = date.today().isoformat()
                    now_iso = datetime.now(timezone.utc).isoformat()

                    # 查询学生已有的 mastery_records，用于关联
                    mastery_records = await self._db.list_mastery_records(student_id)
                    node_to_record: dict[str, str] = {
                        r["knowledge_node_id"]: r["record_id"]
                        for r in mastery_records
                    }

                    plan_dict = {
                        "plan_id": plan_id,
                        "student_id": student_id,
                        "title": self._session_context.get("title", "学习计划"),
                        "description": "由 Tutor 角色基于测验批改结果自动生成",
                        "subject": "",
                        "goal": "",
                        "start_date": today_str,
                        "end_date": None,
                        "status": "active",
                        "created_at": now_iso,
                        "updated_at": now_iso,
                    }

                    items_to_persist: list[dict[str, Any]] = []
                    for i, item in enumerate(plan_items_raw):
                        node_id = item.get("knowledge_node_id", "")
                        raw_date = item.get("scheduled_date", today_str)
                        try:
                            parsed = date.fromisoformat(raw_date[:10])
                            if parsed < date.today():
                                actual_date = (date.today() + timedelta(days=i // 2)).isoformat()
                            else:
                                actual_date = raw_date[:10]
                        except Exception:
                            actual_date = (date.today() + timedelta(days=i // 2)).isoformat()

                        items_to_persist.append({
                            "item_id": item.get("item_id", str(uuid4())),
                            "plan_id": plan_id,
                            "student_id": student_id,
                            "knowledge_node_id": node_id,
                            "mastery_record_id": node_to_record.get(node_id),
                            "scheduled_date": actual_date,
                            "activity_type": item.get("activity_type", "review"),
                            "estimated_minutes": item.get("estimated_minutes", 15),
                            "completed": False,
                            "completed_at": None,
                            "notes": item.get("notes", ""),
                            "metadata": item.get("metadata", {}),
                        })

                    await self._db.create_study_plan(plan_dict, items_to_persist)
                    logger.info(
                        "PLANNING: study plan %s with %d items persisted (student_id=%r).",
                        plan_id,
                        len(items_to_persist),
                        student_id,
                    )
                except Exception as exc:
                    logger.warning("Failed to persist study plan: %s", exc)

            await self._on_step_complete(
                role=role.value,
                artifact={
                    "type": "study_plan",
                    "title": "SM-2 排期学习计划",
                    "summary_256": f"生成 {len(plan_items)} 个复习条目",
                    "full_text": response[:2000],
                },
            )

            self._quiz_status = "reviewed"  # 复习计划已生成，测验闭环完成
            await self._end_phase(PipelinePhase.PLANNING, role)
            logger.info("PLANNING 阶段完成：%d 个排期条目。", len(plan_items))

        except Exception as exc:
            self._set_role_status(role, "error", str(exc))
            await self._handle_phase_error(exc)
            raise

    # ==================================================================
    # 掌握度记录持久化
    # ==================================================================

    async def _persist_mastery_records(
        self: "Orchestrator",
        *,
        student_id: str,
        attempts_raw: list[dict[str, Any]],
        session_id: str,
    ) -> None:
        """从批改结果更新学生的知识点掌握度记录（含 SM-2 参数）。

        对每个 attempt 涉及的 knowledge_node，汇总该学生在此次
        会话中的表现，与数据库中已有记录合并后 upsert。
        """
        # -- 汇总本次会话的节点级统计 ---------------------------------------
        node_stats: dict[str, dict[str, Any]] = {}
        for attempt in attempts_raw:
            question_id = attempt.get("question_id", "")
            is_correct = attempt.get("is_correct", False)
            score = attempt.get("score") or (1.0 if is_correct else 0.0)
            time_spent = attempt.get("time_spent_seconds", 0)
            hints_used = attempt.get("hints_used", 0)
            mis_ids = attempt.get("misconception_ids", [])

            # 查找题目对应的知识点
            question_rows = []
            try:
                q = await self._db.get_question(question_id)
                if q:
                    question_rows.append(q)
            except Exception:
                pass

            # 如果找不到题目，使用 question_id 本身作为 node
            if not question_rows:
                node_ids = [f"node:{question_id}"]
            else:
                raw_ids = question_rows[0].get("knowledge_node_ids", "[]")
                try:
                    parsed = _json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
                    node_ids = parsed if parsed else [f"node:{question_id}"]
                except Exception:
                    node_ids = [f"node:{question_id}"]

            for node_id in node_ids:
                if node_id not in node_stats:
                    node_stats[node_id] = {
                        "total": 0,
                        "correct": 0,
                        "total_score": 0.0,
                        "total_time": 0,
                        "total_hints": 0,
                        "misconception_ids": set(),
                        "last_attempt_at": "",
                    }
                s = node_stats[node_id]
                s["total"] += 1
                if is_correct:
                    s["correct"] += 1
                s["total_score"] += score
                s["total_time"] += time_spent
                s["total_hints"] += hints_used
                s["misconception_ids"].update(mis_ids if isinstance(mis_ids, list) else [])
                s["last_attempt_at"] = attempt.get("submitted_at", "")

        # -- 查询已有记录，合并后 upsert -----------------------------------
        existing_records = await self._db.list_mastery_records(student_id)
        existing_map: dict[str, dict[str, Any]] = {
            r["knowledge_node_id"]: r for r in existing_records
        }

        now_iso = datetime.now(timezone.utc).isoformat()
        for node_id, stats in node_stats.items():
            existing = existing_map.get(node_id)

            total = stats["total"] + (existing.get("total_attempts", 0) if existing else 0)
            correct = stats["correct"] + (existing.get("correct_attempts", 0) if existing else 0)
            mastery_level = correct / total if total > 0 else 0.0
            avg_score = stats["total_score"] / stats["total"] if stats["total"] > 0 else 0.0

            # SM-2 quality: 0-5 scale based on score
            if avg_score >= 0.9:
                quality = 5
            elif avg_score >= 0.7:
                quality = 4
            elif avg_score >= 0.5:
                quality = 3
            elif avg_score >= 0.3:
                quality = 2
            elif avg_score >= 0.1:
                quality = 1
            else:
                quality = 0

            # SM-2 algorithm
            if existing:
                sm2_reps = existing.get("sm2_repetitions", 0)
                sm2_ef = existing.get("sm2_ease_factor", 2.5)
                sm2_interval = existing.get("sm2_interval_days", 0)
            else:
                sm2_reps = 0
                sm2_ef = 2.5
                sm2_interval = 0

            if quality >= 3:
                if sm2_reps == 0:
                    sm2_interval = 1
                elif sm2_reps == 1:
                    sm2_interval = 6
                else:
                    sm2_interval = int(round(sm2_interval * sm2_ef))
                sm2_reps += 1
            else:
                sm2_reps = 0
                sm2_interval = 1

            # Ease factor update
            sm2_ef = sm2_ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
            sm2_ef = max(1.3, sm2_ef)

            # Next review date
            next_review = (date.today() + timedelta(days=sm2_interval)).isoformat()

            # Determine state
            if mastery_level >= 0.85:
                state = "mastered"
            elif mastery_level >= 0.6:
                state = "reviewing"
            elif total > 0:
                state = "learning"
            else:
                state = "new"

            record_id = existing["record_id"] if existing else str(uuid4())
            existing_mis = set()
            if existing and existing.get("misconception_ids"):
                try:
                    existing_mis = set(_json.loads(existing["misconception_ids"])
                        if isinstance(existing["misconception_ids"], str)
                        else existing["misconception_ids"])
                except Exception:
                    pass

            all_mis = list(stats["misconception_ids"] | existing_mis)

            await self._db.upsert_mastery_record({
                "record_id": record_id,
                "student_id": student_id,
                "knowledge_node_id": node_id,
                "mastery_level": round(mastery_level, 3),
                "confidence": min(0.9, 0.3 + total * 0.05),
                "total_attempts": total,
                "correct_attempts": correct,
                "last_attempt_at": stats["last_attempt_at"] or now_iso,
                "last_score": round(avg_score, 3),
                "streak": stats["correct"] if stats["correct"] == stats["total"] else 0,
                "time_spent_total_seconds": stats["total_time"],
                "hints_used_total": stats["total_hints"],
                "misconception_ids": all_mis,
                "state": state,
                "sm2_repetitions": sm2_reps,
                "sm2_ease_factor": round(sm2_ef, 3),
                "sm2_interval_days": sm2_interval,
                "sm2_next_review": next_review,
                "sm2_last_quality": quality,
                "created_at": existing.get("created_at", now_iso) if existing else now_iso,
                "updated_at": now_iso,
            })

        logger.info(
            "EVALUATING: mastery_records updated for %d knowledge nodes (student_id=%r).",
            len(node_stats),
            student_id,
        )
