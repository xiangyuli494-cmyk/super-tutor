"""诊断性评估引擎 — 基于知识点依赖链的诊断评估。

【功能说明】
按知识点依赖链（前驱 → 后继）生成诊断性题目，逐题批改后
计算每个 KP 的掌握度，并应用 3 条前置规则对评估结果进行校准。

核心流程：
1. generate(): 从 DB 获取 KP → 拓扑排序 → 分配题目数 → LLM 生成诊断性题目
2. grade(): 委托 QuizEngine 批改 → 按 KP 分组 → 计算准确率 → 应用 3 条规则
3. apply_prerequisite_rules(): 3 条纯 Python 规则（不调用 LLM）

3 条前置规则（系统的核心诊断逻辑）：

【规则1 — 置信度折扣】（Confidence Discount）
前驱知识点 mastery ≤ 0.5 → 后继的 confidence × 0.7
含义：前驱没掌握却答对后继 → 可能是猜测，降低后继置信度

【规则2 — 需要复习】（Need Review）
后继 accuracy ≥ 0.6 但前驱 accuracy < 0.5 → 标记前驱为 need_review
含义：学生"看起来"掌握了后继但前驱却错了 → 前驱基础不扎实

【规则3 — 需要重学】（Need Relearn）
某个 KP 的 ≥3 个直接后继全部 accuracy < 0.5 → 标记此 KP 为 need_relearn
含义：多个后继都错了 → 此 KP 的教学可能存在问题，掌握度折半

题目数量分配策略：
每个 KP 至少 1 道题，余数从链尾（后继 KP）开始分配（后继需要更多诊断深度）

【耦合关系】
- 依赖 Database（KP 和题目 CRUD）、LLMClient（LLM 出题）
- 依赖 KnowledgeEngine（KP 查询和关系解析）
- 依赖 QuizEngine（委托批改和错题收录）
- 被 app.py 的诊断评估 Tab 调用
- 输出 AssessmentReport 供 PlanEngine 使用
- 使用 prompts/assessment.md（诊断性评估提示词）
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from super_tutor.core.database import Database
from super_tutor.core.llm_client import LLMClient
from super_tutor.engine.knowledge_engine import KnowledgeEngine, _parse_json_list
from super_tutor.engine.quiz_engine import QuizEngine
from super_tutor.models.assessment import AssessmentReport, KPAssessmentResult
from super_tutor.models.enums import DifficultyLevel, QuestionType
from super_tutor.models.quiz import Question

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 默认 prompt 路径 — 诊断性评估提示词
# ---------------------------------------------------------------------------
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_DEFAULT_ASSESSMENT_PROMPT = _PROMPTS_DIR / "assessment.md"


class AssessmentEngine:
    """诊断性评估引擎。

    与普通 QuizEngine 的区别：
    - 题目按 KP 依赖链递进难度（链首简单 → 链尾困难）
    - 选择题干扰项标注 diagnostic_tags（可诊断的迷思概念类型）
    - 批改后应用 3 条前置规则校准掌握度
    - 输出 AssessmentReport（而非单纯的正确/错误）

    Usage::

        engine = AssessmentEngine(db, llm_client)
        questions = await engine.generate(["kp-001", "kp-002", "kp-003"])
        report = await engine.grade(questions, student_answers)
    """

    def __init__(
        self,
        db: Database,
        llm_client: LLMClient,
        knowledge_engine: KnowledgeEngine | None = None,
        quiz_engine: QuizEngine | None = None,
        assessment_prompt_path: str | None = None,
    ) -> None:
        """初始化诊断性评估引擎。

        Args:
            db: 已初始化的 Database 实例。
            llm_client: LLMClient 实例。
            knowledge_engine: 可选的预建 KnowledgeEngine（缺省时自动创建）。
            quiz_engine: 可选的预建 QuizEngine（缺省时自动创建）。
            assessment_prompt_path: 可选的自定义评估提示词路径。
        """
        self._db = db
        self._llm = llm_client
        self._knowledge_engine = knowledge_engine or KnowledgeEngine(
            db=db, llm_client=llm_client
        )
        self._quiz_engine = quiz_engine or QuizEngine(
            db=db,
            llm_client=llm_client,
            knowledge_engine=self._knowledge_engine,
        )
        self._prompt_path = assessment_prompt_path or str(
            _DEFAULT_ASSESSMENT_PROMPT
        )

    # ==================================================================
    # generate() — 生成诊断性评估题目
    # ==================================================================

    async def generate(
        self,
        kp_ids: list[str],
        student_id: str = "",
        question_count: int = 15,
    ) -> list[Question]:
        """生成一套诊断性评估题目。

        每个 KP 至少 1 道题，按拓扑序从基础到高级递进布置。

        Args:
            kp_ids: 要评估的知识点 ID 列表。
            student_id: 学生标识。
            question_count: 总题目数（必须 ≥ KP 数量）。

        Returns:
            Question 列表（按拓扑/依赖顺序排列）。

        Raises:
            ValueError: kp_ids 为空或 question_count < KP 数量。
        """
        if not kp_ids:
            raise ValueError("kp_ids 不能为空")
        if question_count < len(kp_ids):
            raise ValueError(
                f"question_count ({question_count}) 不能少于 "
                f"知识点数量 ({len(kp_ids)})"
            )

        # -- 第 1 步：获取 KP 并进行拓扑排序 ---------------------------------
        kp_map: dict[str, dict] = {}
        for kid in kp_ids:
            row = await self._db.get_knowledge_point(kid)
            if row is None:
                logger.warning("KP %s 不存在，跳过", kid)
                continue
            kp_map[kid] = row

        if not kp_map:
            raise ValueError("所有指定的 kp_ids 均不存在于数据库中")

        ordered_ids = self._topological_sort(kp_map)

        # -- 第 2 步：分配题目数量（每个 KP 至少 1 道） ----------------------
        per_kp_count = self._distribute_counts(ordered_ids, question_count)

        # -- 第 3 步：构建 KP 上下文（供 LLM 出题参考） -----------------------
        kp_context_parts: list[str] = []
        for i, kid in enumerate(ordered_ids):
            kp = kp_map[kid]
            prereqs = _parse_json_list(kp.get("prerequisite_ids", "[]"))
            succs = _parse_json_list(kp.get("successor_ids", "[]"))
            prereqs_in_scope = [p for p in prereqs if p in kp_map]
            succs_in_scope = [s for s in succs if s in kp_map]

            prereq_titles = []
            for pid in prereqs_in_scope:
                pkp = kp_map.get(pid, {})
                prereq_titles.append(pkp.get("title", pid))

            kp_context_parts.append(
                f"### KP {i + 1}: {kp.get('title', kid)}\n"
                f"- kp_id: {kid}\n"
                f"- 难度: {kp.get('difficulty', 'medium')}\n"
                f"- 内容: {kp.get('content', '')}\n"
                f"- 摘要: {kp.get('summary', '')}\n"
                f"- 前置知识点: {', '.join(prereq_titles) if prereq_titles else '无（链首）'}\n"
                f"- 后继知识点数量: {len(succs_in_scope)}\n"
                f"- 需要出题数量: {per_kp_count.get(kid, 1)} 道\n"
            )

        # -- 第 4 步：加载系统提示词并调用 LLM --------------------------------
        try:
            system_prompt = Path(self._prompt_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(
                f"无法加载评估提示词: {self._prompt_path} ({exc})"
            ) from exc

        user_prompt = (
            "# 知识点链（前驱 → 后继，按依赖关系排列）\n\n"
            + "\n".join(kp_context_parts)
            + f"\n\n请生成 {question_count} 道诊断性评估题目，"
            f"确保每个知识点至少有 {min(per_kp_count.values()) if per_kp_count else 1} 道题，"
            f"按知识点依赖关系从基础到高级递进。"
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(
            "开始生成诊断性评估题目 (kp_count=%d, question_count=%d)",
            len(ordered_ids),
            question_count,
        )

        raw = await self._llm.chat(
            messages=messages,
            temperature=0.7,     # 中等温度保证题目多样性
            max_tokens=8192,
            timeout=180,
        )

        # -- 第 5 步：解析 LLM 响应 --------------------------------------------
        raw = self._strip_markdown_fence(raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("LLM 返回的评估题目 JSON 无法解析: %s", raw[:500])
            raise RuntimeError(
                f"评估题目生成失败 — 无法解析 JSON: {exc}"
            ) from exc

        question_dicts = data.get("assessment_questions", data.get("questions", []))
        if not question_dicts:
            raise RuntimeError("LLM 未返回任何评估题目")

        # -- 第 6 步：构建 Question 模型并持久化 ------------------------------
        questions: list[Question] = []
        now = datetime.now(timezone.utc).isoformat()
        for qd in question_dicts:
            qid = qd.get("question_id") or str(uuid4())
            q = Question(
                question_id=qid,
                type=QuestionType(qd.get("type", "multiple_choice")),
                difficulty=DifficultyLevel(qd.get("difficulty", "medium")),
                subject="",
                topic=qd.get("topic", ""),
                stem=qd.get("stem", ""),
                options=qd.get("options", []),
                correct_answer=qd.get("correct_answer", ""),
                explanation=qd.get("explanation", ""),
                hints=qd.get("hints", []),
                kp_id=qd.get("kp_id", ""),
                kp_context=json.dumps({
                    "diagnostic_tags": qd.get("diagnostic_tags", []),
                    "assessment_generated": True,
                    "student_id": student_id,
                }, ensure_ascii=False),
                estimated_seconds=qd.get("estimated_seconds", 120),
                points=float(qd.get("points", 1.0)),
                tags=qd.get("tags", []),
                metadata={
                    "source": "assessment_engine",
                    "generated_at": now,
                },
                created_at=now,
            )
            await self._db.insert_question(q.model_dump())
            questions.append(q)

        logger.info("已生成 %d 道评估题目", len(questions))
        return questions

    # ==================================================================
    # grade() — 批改 + 掌握度计算 + 前置规则校准
    # ==================================================================

    async def grade(
        self,
        questions: list[Question],
        student_answers: list[dict],
        student_id: str = "",
    ) -> AssessmentReport:
        """批改评估答案并生成掌握度报告。

        完整流程（6 步）：
        1. 委托 QuizEngine.grade_answers() 批改每道题
        2. 将错题自动收录到错题本
        3. 按 kp_id 分组作答记录
        4. 逐 KP 计算准确率 → 初始掌握度
        5. 应用 3 条前置规则校准（apply_prerequisite_rules）
        6. 填充 weak_kps 和 strong_kps 列表

        Args:
            questions: 评估题目列表。
            student_answers: 学生答案列表。
            student_id: 学生标识。

        Returns:
            AssessmentReport: 包含所有 KP 的校准后掌握度和诊断状态。
        """
        if not questions:
            raise ValueError("questions 不能为空")
        if not student_answers:
            raise ValueError("student_answers 不能为空")

        # -- 第 1 步：委托 QuizEngine 批改 ------------------------------------
        attempts = await self._quiz_engine.grade_answers(
            questions=questions,
            student_answers=student_answers,
            student_id=student_id,
        )

        # -- 第 2 步：错题自动收录到错题本 ------------------------------------
        q_map = {q.question_id: q for q in questions}
        wrong_book_failures: list[str] = []
        for attempt in attempts:
            if attempt.is_correct is False:
                try:
                    await self._quiz_engine.add_to_wrong_book(
                        attempt, q_map.get(attempt.question_id)
                    )
                except Exception:
                    logger.warning(
                        "Failed to add assessment wrong-book entry for %s",
                        attempt.question_id,
                        exc_info=True,
                    )
                    wrong_book_failures.append(attempt.question_id)

        # -- 第 3 步：按 kp_id 分组作答记录 -----------------------------------
        kp_attempts: dict[str, list] = {}
        for attempt in attempts:
            kp_id = attempt.kp_id or q_map.get(attempt.question_id, Question()).kp_id
            if not kp_id:
                kp_id = "__unknown__"
            kp_attempts.setdefault(kp_id, []).append(attempt)

        # -- 第 4 步：构建每个 KP 的评估结果 ----------------------------------
        kp_results: list[KPAssessmentResult] = []
        # 保持题目中的 KP 顺序（拓扑序）
        seen_kps: dict[str, None] = {}
        ordered_kp_ids: list[str] = []
        for q in questions:
            kp_id = q.kp_id or "__unknown__"
            if kp_id not in seen_kps:
                seen_kps[kp_id] = None
                ordered_kp_ids.append(kp_id)

        for kp_id in ordered_kp_ids:
            kp_att = kp_attempts.get(kp_id, [])
            correct = sum(1 for a in kp_att if a.is_correct)
            total = len(kp_att)
            accuracy = round(correct / total, 4) if total > 0 else 0.0

            # 获取 KP 信息（标题、前置/后继 ID）
            kp_row = await self._db.get_knowledge_point(kp_id) if kp_id != "__unknown__" else None
            title = kp_row.get("title", kp_id) if kp_row else kp_id
            prereq_ids = _parse_json_list(
                kp_row.get("prerequisite_ids", "[]")
            ) if kp_row else []
            succ_ids = _parse_json_list(
                kp_row.get("successor_ids", "[]")
            ) if kp_row else []

            # 初始掌握度 = 准确率（在评估中，答对 = 掌握）
            initial_mastery = accuracy

            kp_results.append(
                KPAssessmentResult(
                    kp_id=kp_id,
                    title=title,
                    prerequisite_ids=prereq_ids,
                    successor_ids=succ_ids,
                    question_ids=[a.question_id for a in kp_att],
                    correct_count=correct,
                    total_count=total,
                    accuracy=accuracy,
                    initial_mastery=initial_mastery,
                    adjusted_mastery=initial_mastery,  # 下面由规则校准
                )
            )

        # -- 第 5 步：构建初步报告并应用 3 条前置规则 ------------------------
        correct_total = sum(r.correct_count for r in kp_results)
        question_total = sum(r.total_count for r in kp_results)

        warnings: list[str] = []
        if wrong_book_failures:
            warnings.append(
                f"⚠️ {len(wrong_book_failures)} 道错题未能录入错题本: "
                + ", ".join(fid[:8] for fid in wrong_book_failures)
            )

        report = AssessmentReport(
            assessment_id=str(uuid4()),
            student_id=student_id,
            kp_ids=ordered_kp_ids,
            total_questions=question_total,
            correct_count=correct_total,
            accuracy=round(correct_total / question_total, 4) if question_total > 0 else 0.0,
            kp_results=kp_results,
            warnings=warnings,
        )

        # 应用 3 条前置规则（纯 Python 逻辑，不调用 LLM）
        self.apply_prerequisite_rules(report)

        # -- 第 6 步：填充 weak_kps 和 strong_kps 列表 -----------------------
        report.weak_kps = sorted(
            [r for r in report.kp_results if r.adjusted_mastery <= 0.5],
            key=lambda r: r.adjusted_mastery,  # 掌握度升序（最弱的在前）
        )
        report.strong_kps = sorted(
            [r for r in report.kp_results if r.adjusted_mastery >= 0.8],
            key=lambda r: r.adjusted_mastery,
            reverse=True,  # 掌握度降序（最强的在前）
        )

        logger.info(
            "评估完成: %d KPs, 整体正确率 %.1f%%, weak=%d strong=%d rules=%d",
            len(kp_results),
            report.accuracy * 100,
            len(report.weak_kps),
            len(report.strong_kps),
            len(report.rules_applied),
        )

        return report

    # ==================================================================
    # apply_prerequisite_rules() — 3 条前置规则（核心诊断逻辑）
    #     纯 Python 实现，不调用 LLM，就地修改 report
    # ==================================================================

    def apply_prerequisite_rules(self, report: AssessmentReport) -> None:
        """应用 3 条前置校准规则到评估报告（就地修改）。

        规则设计原理：知识学习是分层的（DAG），后继的正确理解
        依赖于前驱的扎实掌握。因此：
        - 前驱薄弱但后继做对 → 后继可能是猜测（Rule 1）
        - 后继做对但前驱做错 → 前驱需要复习（Rule 2）
        - 前驱的多个后继全错 → 前驱教学可能有问题（Rule 3）

        Args:
            report: 待校准的 AssessmentReport（就地修改）。
        """
        if not report.kp_results:
            return

        # 构建 kp_id → 评估结果的快速查找表
        kp_by_id: dict[str, KPAssessmentResult] = {
            r.kp_id: r for r in report.kp_results
        }

        rules_applied: list[str] = []

        # ---- 规则1：置信度折扣 -----------------------------------------------
        # 如果前驱 KP 的掌握度 ≤ 0.5，后继的置信度乘以 0.7
        # 原因：前驱没掌握却答对后继 → 可能是猜测，降低置信度
        for r in report.kp_results:
            for prereq_id in r.prerequisite_ids:
                prereq = kp_by_id.get(prereq_id)
                if prereq is None:
                    continue
                if prereq.adjusted_mastery <= 0.5:
                    old_confidence = r.confidence
                    r.confidence = round(r.confidence * 0.7, 4)
                    r.adjusted_mastery = round(
                        r.initial_mastery * r.confidence, 4
                    )
                    msg = (
                        f"规则1: [{r.kp_id}] {r.title} 的前驱 "
                        f"[{prereq_id}] {prereq.title} 掌握度={prereq.adjusted_mastery:.2f}≤0.5，"
                        f"置信度 {old_confidence}→{r.confidence}，"
                        f"调整后掌握度={r.adjusted_mastery:.2f}"
                    )
                    r.warnings.append(msg)
                    rules_applied.append(msg)
                    logger.info(msg)

        # ---- 规则2：需要复习 -------------------------------------------------
        # 后继 KP 做对了（accuracy ≥ 0.6），但其某个前驱做错了（accuracy < 0.5）
        # → 标记该前驱为 need_review（表面掌握但不扎实）
        for r in report.kp_results:
            if r.accuracy >= 0.6 and r.status not in ("need_review", "need_relearn"):
                for prereq_id in r.prerequisite_ids:
                    prereq = kp_by_id.get(prereq_id)
                    if prereq is None:
                        continue
                    if prereq.accuracy < 0.5 and prereq.status not in (
                        "need_review",
                        "need_relearn",
                    ):
                        prereq.status = "need_review"
                        msg = (
                            f"规则2: [{prereq_id}] {prereq.title} "
                            f"准确率={prereq.accuracy:.2f}<0.5 但后继 "
                            f"[{r.kp_id}] {r.title} 准确率={r.accuracy:.2f}≥0.6，"
                            f"标记前驱为 need_review"
                        )
                        prereq.warnings.append(msg)
                        rules_applied.append(msg)
                        logger.info(msg)

        # ---- 规则3：需要重学 -------------------------------------------------
        # 某个 KP 的 ≥3 个直接后继全部答错（accuracy < 0.5）
        # → 标记此 KP 为 need_relearn，掌握度折半
        for r in report.kp_results:
            failed_successors: list[KPAssessmentResult] = []
            for succ_id in r.successor_ids:
                succ = kp_by_id.get(succ_id)
                if succ is not None and succ.accuracy < 0.5:
                    failed_successors.append(succ)

            if len(failed_successors) >= 3:
                r.status = "need_relearn"
                r.adjusted_mastery = round(r.adjusted_mastery * 0.5, 4)
                succ_labels = ", ".join(
                    f"[{s.kp_id}] {s.title} (准确率={s.accuracy:.2f})"
                    for s in failed_successors
                )
                msg = (
                    f"规则3: [{r.kp_id}] {r.title} 的 "
                    f"{len(failed_successors)} 个后继均答错 → "
                    f"标记为 need_relearn，掌握度折半至 {r.adjusted_mastery:.2f}。"
                    f"失败后继: {succ_labels}"
                )
                r.warnings.append(msg)
                rules_applied.append(msg)
                logger.info(msg)

        # ---- 最终状态赋值：未标记的 KP 按掌握度分级 -------------------------
        for r in report.kp_results:
            if r.status not in (
                "need_review",
                "need_relearn",
                "mastered",
                "learning",
            ):
                if r.adjusted_mastery >= 0.8:
                    r.status = "mastered"    # 掌握度 ≥ 0.8 → 已掌握
                elif r.adjusted_mastery >= 0.5:
                    r.status = "learning"    # 0.5 ≤ mastery < 0.8 → 学习中
                else:
                    r.status = "need_relearn"  # mastery < 0.5 → 需要重新学习

        report.rules_applied = rules_applied

    # ==================================================================
    # 辅助方法
    # ==================================================================

    def _topological_sort(self, kp_map: dict[str, dict]) -> list[str]:
        """Kahn 算法拓扑排序 — 按前置依赖关系排列知识点。

        与 PlanEngine.topological_sort() 逻辑一致，
        独立实现以避免模块间耦合。

        Args:
            kp_map: kp_id → DB 行字典 的映射。

        Returns:
            list[str]: 拓扑排序后的 kp_id 列表。
        """
        kp_ids = set(kp_map.keys())

        # 构建邻接表和入度表（方向：前置 → 后继）
        adj: dict[str, list[str]] = {k: [] for k in kp_ids}
        in_degree: dict[str, int] = {k: 0 for k in kp_ids}

        for kid in kp_ids:
            prereqs = _parse_json_list(kp_map[kid].get("prerequisite_ids", "[]"))
            for pid in prereqs:
                if pid in kp_ids and pid != kid:
                    adj.setdefault(pid, []).append(kid)
                    in_degree[kid] = in_degree.get(kid, 0) + 1

        # Kahn 算法
        queue: deque[str] = deque(
            k for k in kp_ids if in_degree.get(k, 0) == 0
        )
        result: list[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 追加剩余节点（环或孤立引用）
        for k in kp_ids:
            if k not in result:
                result.append(k)

        return result

    @staticmethod
    def _distribute_counts(
        ordered_ids: list[str],
        total: int,
    ) -> dict[str, int]:
        """将 total 道题目分配给各 KP，每个至少 1 道。

        余数按轮询方式从链尾开始分配（后继 KP 需要更多诊断深度）。

        Args:
            ordered_ids: 拓扑排序后的 KP ID 列表。
            total: 总题目数。

        Returns:
            dict[str, int]: kp_id → 题目数量 的映射。
        """
        n = len(ordered_ids)
        if n == 0:
            return {}

        per_kp: dict[str, int] = {k: 1 for k in ordered_ids}
        remaining = total - n

        # 余数按轮询分配，从链尾开始（后继 KP 优先获得额外题目）
        for i in range(remaining):
            idx = i % n
            per_kp[ordered_ids[idx]] += 1

        return per_kp

    @staticmethod
    def _strip_markdown_fence(raw: str) -> str:
        """去除 LLM 响应中的 Markdown 代码围栏。"""
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]       # 去掉开始的 ```json
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]      # 去掉结束的 ```
            raw = "\n".join(lines)
        return raw.strip()
