"""测验引擎 — 题目生成、自动批改与错题收录。

【功能说明】
将 LLM 出题、程序/LLM 混合批改和错题本维护封装为高层业务逻辑组件。
是 Super Tutor 中使用频率最高的引擎。

核心能力：
1. generate_questions(): LLM 生成题目 → 持久化到 questions 表
2. grade_answers(): 混合批改 — 选择/判断题程序批改（零 LLM 成本），
   其他题型交给 LLM 语义批改
3. add_to_wrong_book(): 自动收录错题 → 重复答错递增 attempt_count

批改分流策略（节约 LLM 成本的关键设计）：
- 程序批改（_grade_programmatic）: multiple_choice、true_false
  → 直接比对答案，正确=1.0分，错误=0.0分
- LLM 批改（_grade_via_llm）: fill_in_blank、short_answer、essay、coding
  → 调用 LLM 按评分标准打分，返回 misconceptions（迷思概念诊断）

题目数量分配策略（_distribute_counts）：
- 将 total 道题均匀分配到 N 个 KP，余数按顺序分配给前面的 KP
- 例：5 道题，3 个 KP → [2, 2, 1]

【耦合关系】
- 依赖 Database（题目和作答记录的 CRUD）、LLMClient（出题和批改 API）
- 依赖 KnowledgeEngine（获取 KP 内容和前置知识作为出题上下文）
- 被 app.py 的练习答题 Tab、错题本 Tab、计划 Tab 调用
- 被 AssessmentEngine 委托批改（grade_answers）
- 使用 prompts/quiz_gen.md（出题提示词）和 prompts/grade.md（批改提示词）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from super_tutor.core.database import Database
from super_tutor.core.exceptions import LLMError, MaterialError
from super_tutor.core.llm_client import LLMClient
from super_tutor.engine.knowledge_engine import KnowledgeEngine, _parse_json_list
from super_tutor.models.enums import DifficultyLevel, QuestionType
from super_tutor.models.quiz import Question, QuizAttempt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 默认 prompt 路径
# ---------------------------------------------------------------------------
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_DEFAULT_QUIZ_GEN_PROMPT = _PROMPTS_DIR / "quiz_gen.md"    # 出题系统提示词
_DEFAULT_GRADE_PROMPT = _PROMPTS_DIR / "grade.md"           # 批改系统提示词

# ---------------------------------------------------------------------------
# 程序批改覆盖的题型 — 这些题型不需要调用 LLM
# ---------------------------------------------------------------------------
_PROGRAMMATIC_TYPES: set[str] = {"multiple_choice", "true_false"}


class QuizEngine:
    """测验引擎 — 出题、批改和错题收录。

    封装了 LLM 出题 → 程序/LLM 混合批改 → 错题本写入的完整流程。

    Usage::

        engine = QuizEngine(db, llm_client, knowledge_engine)
        questions = await engine.generate_questions(["kp-001"], count=5)
        attempts = await engine.grade_answers(questions, student_answers)
        for attempt in attempts:
            if not attempt.is_correct:
                await engine.add_to_wrong_book(attempt)
    """

    def __init__(
        self,
        db: Database,
        llm_client: LLMClient,
        knowledge_engine: KnowledgeEngine,
        quiz_gen_prompt_path: str | None = None,
        grade_prompt_path: str | None = None,
    ) -> None:
        """初始化测验引擎。

        Args:
            db: 已初始化的 Database 实例。
            llm_client: LLMClient 实例（用于出题和批改 API 调用）。
            knowledge_engine: KnowledgeEngine 实例（用于获取 KP 内容和前置知识）。
            quiz_gen_prompt_path: 可选的自定义出题提示词路径。
            grade_prompt_path: 可选的自定义批改提示词路径。
        """
        self._db = db
        self._llm = llm_client
        self._knowledge = knowledge_engine
        self._quiz_gen_prompt_path = (
            quiz_gen_prompt_path or str(_DEFAULT_QUIZ_GEN_PROMPT)
        )
        self._grade_prompt_path = (
            grade_prompt_path or str(_DEFAULT_GRADE_PROMPT)
        )

    # ==================================================================
    # generate_questions() — LLM 出题
    # ==================================================================

    async def generate_questions(
        self,
        kp_ids: list[str],
        count: int = 5,
        difficulty: str | None = None,
        types: list[str] | None = None,
    ) -> list[Question]:
        """根据知识点生成测验题目。

        完整流程（5 步）：
        1. 收集知识点数据 — 从 DB 获取 KP + 前置知识摘要（作为出题上下文）
        2. 构建 prompt 上下文 — 将 KP 信息格式化为 LLM 输入
        3. 加载系统提示词 → 调用 LLM（temperature=0.7, max_tokens=8192）
        4. 解析 JSON → 创建 Question 对象
        5. 逐题持久化到 questions 表

        Args:
            kp_ids: 要出题的知识点 ID 列表。
            count: 要生成的题目总数。
            difficulty: 可选的统一难度（None=由 AI 自动按比例分配）。
            types: 可选的题型过滤（None=全部题型）。

        Returns:
            Question 对象列表。

        Raises:
            ValueError: kp_ids 为空或 count < 1。
            MaterialError: LLM 调用失败或返回无效 JSON。
        """
        if not kp_ids:
            raise ValueError("kp_ids must not be empty")
        if count < 1:
            raise ValueError("count must be >= 1")

        # -- 第 1 步：收集知识点数据 -----------------------------------------
        kp_infos: list[dict[str, Any]] = []
        for kp_id in kp_ids:
            kp_row = await self._db.get_knowledge_point(kp_id)
            if kp_row is None:
                logger.warning("Knowledge point not found: %s", kp_id)
                continue

            # 获取前置知识点的摘要（注入到出题上下文中，帮助 LLM 理解 KP 背景）
            prereq_ids: list[str] = _parse_json_list(
                kp_row.get("prerequisite_ids", "[]")
            )
            prereq_summaries: list[str] = []
            for pid in prereq_ids:
                pr = await self._db.get_knowledge_point(pid)
                if pr:
                    prereq_summaries.append(
                        f"  [{pr.get('title', pid[:8])}] {pr.get('summary', '')}"
                    )

            kp_infos.append(
                {
                    "kp_id": kp_id,
                    "title": kp_row.get("title", ""),
                    "content": kp_row.get("content", ""),
                    "summary": kp_row.get("summary", ""),
                    "difficulty": kp_row.get("difficulty", "medium"),
                    "keywords": _parse_json_list(kp_row.get("keywords", "[]")),
                    "prerequisites": prereq_summaries,
                }
            )

        if not kp_infos:
            raise ValueError("None of the given kp_ids exist in the database")

        # -- 第 2 步：构建 prompt 上下文 -------------------------------------
        kp_context_lines: list[str] = []
        for info in kp_infos:
            lines = [
                f"## 知识点: {info['title']}",
                f"- kp_id: {info['kp_id']}",
                f"- difficulty: {info['difficulty']}",
                f"- keywords: {', '.join(info['keywords'])}" if info["keywords"] else "",
                f"- summary: {info['summary']}",
            ]
            if info["prerequisites"]:
                lines.append("- 前置知识点:")
                lines.extend(info["prerequisites"])
            lines.append(f"\n{info['content']}\n")
            kp_context_lines.append("\n".join(l for l in lines if l))

        kp_context = "\n---\n".join(kp_context_lines)

        # 均匀分配题目数量到各个 KP
        per_kp = _distribute_counts([i["kp_id"] for i in kp_infos], count)

        # 构建出题约束
        constraints: list[str] = [f"请生成 {count} 道题目。"]
        constraints.append(
            f"知识点分布: {', '.join(f'{kid}:{n}道' for kid, n in per_kp.items())}"
        )
        if difficulty:
            constraints.append(f"所有题目难度统一为: {difficulty}")
        if types:
            constraints.append(f"只生成以下题型: {', '.join(types)}")

        user_prompt = (
            f"## 知识点列表\n\n{kp_context}\n\n"
            f"## 出题要求\n\n" + "\n".join(f"- {c}" for c in constraints)
        )

        # -- 第 3 步：加载系统提示词并调用 LLM --------------------------------
        try:
            system_prompt = Path(self._quiz_gen_prompt_path).read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            raise MaterialError(
                f"无法加载出题提示词: {self._quiz_gen_prompt_path} ({exc})"
            ) from exc

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(
            "Generating %d questions for %d KPs (difficulty=%s, types=%s)",
            count, len(kp_infos), difficulty or "auto", types or "auto",
        )

        try:
            raw = await self._llm.chat(
                messages=messages,
                temperature=0.7,    # 中等温度保证题目多样性
                max_tokens=8192,    # 大 token 预算应对多道题
                timeout=180,        # 3 分钟超时
            )
        except LLMError as exc:
            raise MaterialError(f"LLM 出题失败: {exc}") from exc

        # -- 第 4 步：解析 JSON 响应 ------------------------------------------
        raw = _strip_markdown_fence(raw)  # 去除 ```json ... ``` 围栏

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("LLM 出题返回的 JSON 无法解析: %s", raw[:500])
            raise MaterialError(f"题目生成结果不是有效 JSON: {exc}") from exc

        raw_questions = data.get("questions", [])
        if not raw_questions:
            raise MaterialError("LLM 未生成任何题目。")

        # -- 第 5 步：创建 Question 对象并持久化 ------------------------------
        created: list[Question] = []
        now = datetime.now(timezone.utc).isoformat()

        # fallback kp_id：当 LLM 没返回 kp_id 时，使用第一个请求的 KP
        _fallback_kp_id = kp_ids[0] if kp_ids else ""

        for item in raw_questions:
            qid = str(uuid4())
            q = Question(
                question_id=qid,
                type=QuestionType(item.get("type", "multiple_choice")),
                difficulty=DifficultyLevel(
                    item.get("difficulty", "medium")
                ),
                subject=item.get("subject", ""),
                topic=item.get("topic", ""),
                stem=item.get("stem", ""),
                options=item.get("options", []),
                correct_answer=item.get("correct_answer", ""),
                explanation=item.get("explanation", ""),
                hints=item.get("hints", []),
                kp_id=item.get("kp_id", "").strip() or _fallback_kp_id,
                estimated_seconds=item.get("estimated_seconds", 120),
                points=item.get("points", 1.0),
                tags=item.get("tags", []),
                created_at=now,
            )

            # 逐题写入 questions 表
            await self._db.insert_question(
                {
                    "question_id": q.question_id,
                    "type": q.type.value,
                    "difficulty": q.difficulty.value,
                    "subject": q.subject,
                    "topic": q.topic,
                    "stem": q.stem,
                    "options": q.options,
                    "correct_answer": q.correct_answer,
                    "explanation": q.explanation,
                    "kp_id": q.kp_id,
                    "kp_context": json.dumps(
                        item.get("kp_context", {}), ensure_ascii=False
                    ),
                    "estimated_seconds": q.estimated_seconds,
                    "points": q.points,
                    "tags": q.tags,
                    "metadata": {},
                    "created_at": now,
                }
            )
            created.append(q)

        logger.info("Generated %d questions for %d KPs", len(created), len(kp_infos))
        return created

    # ==================================================================
    # grade_answers() — 混合批改（核心分流逻辑）
    # ==================================================================

    async def grade_answers(
        self,
        questions: list[Question],
        student_answers: list[dict[str, Any]],
        student_id: str = "",
    ) -> list[QuizAttempt]:
        """批改一批学生答案。

        分流策略（节约 LLM 成本的关键设计）：
        - 选择题 + 判断题 → _grade_programmatic（程序直接比对，零 LLM 成本）
        - 填空/简答/论述/编程题 → _grade_via_llm（调用 LLM 语义批改）

        Args:
            questions: 被作答的 Question 对象列表。
            student_answers: 学生答案列表，每项包含 question_id 和 student_answer。
            student_id: 学生标识。

        Returns:
            QuizAttempt 对象列表（每题一条记录）。
        """
        # -- 第 1 步：构建查找表 --------------------------------------------
        q_map: dict[str, Question] = {q.question_id: q for q in questions}
        answer_map: dict[str, dict] = {
            a["question_id"]: a for a in student_answers
        }

        # -- 第 2 步：分流 — 程序批改 vs LLM 批改 ---------------------------
        programmatic_items: list[tuple[Question, dict]] = []
        llm_items: list[tuple[Question, dict]] = []

        for a in student_answers:
            qid = a["question_id"]
            q = q_map.get(qid)
            if q is None:
                logger.warning("Answer references unknown question: %s", qid)
                continue
            if q.type.value in _PROGRAMMATIC_TYPES:
                programmatic_items.append((q, a))
            else:
                llm_items.append((q, a))

        # -- 第 3 步：程序批改（选择题+判断题）-------------------------------
        now = datetime.now(timezone.utc).isoformat()
        attempts: list[QuizAttempt] = []

        for q, ans in programmatic_items:
            is_correct, score, max_score = _grade_programmatic(
                q, str(ans.get("student_answer", ""))
            )
            attempt = await _persist_attempt(
                self._db, q, ans, student_id, is_correct, score, max_score, now
            )
            attempts.append(attempt)

        # -- 第 4 步：LLM 批改（填空/简答/论述/编程题）-----------------------
        if llm_items:
            llm_attempts = await _grade_via_llm(
                self._llm,
                self._grade_prompt_path,
                llm_items,
                student_id,
                now,
            )
            # 持久化每个 LLM 批改的结果
            for i, (q, ans) in enumerate(llm_items):
                result = (
                    llm_attempts[i]
                    if i < len(llm_attempts)
                    else {"is_correct": False, "score": 0.0, "max_score": 1.0}
                )
                attempt = await _persist_attempt(
                    self._db,
                    q,
                    ans,
                    student_id,
                    result.get("is_correct", False),
                    result.get("score", 0.0),
                    result.get("max_score", q.points),
                    now,
                    result.get("misconceptions"),
                    result.get("analysis", ""),
                )
                attempts.append(attempt)

        logger.info(
            "Graded %d answers: %d programmatic + %d LLM",
            len(attempts),
            len(programmatic_items),
            len(llm_items),
        )
        return attempts

    # ==================================================================
    # add_to_wrong_book() — 错题自动收录
    # ==================================================================

    async def add_to_wrong_book(
        self,
        attempt: QuizAttempt,
        question: Question | None = None,
    ) -> dict[str, Any]:
        """将错误作答记录到错题本。

        规则：
        - 只收录 is_correct=False 的作答
        - 如果同一学生+同一题目已有错题记录 → 递增 attempt_count
        - 如果首次答错 → 创建新记录

        Args:
            attempt: 已批改的 QuizAttempt。
            question: 对应的 Question（用于获取正确答案）。

        Returns:
            dict: 插入/更新后的错题记录。
        """
        if attempt.is_correct is not False:
            logger.debug(
                "Skipping wrong-book for correct attempt %s", attempt.attempt_id
            )
            return {}

        student_id = getattr(attempt, "student_id", "") or ""

        # 获取正确答案的字符串表示
        correct_answer: str = ""
        if question is not None:
            correct_answer = _serialize_answer(question.correct_answer)

        now = datetime.now(timezone.utc).isoformat()
        wrong_id = str(uuid4())

        # 检查是否已有此学生+此题的错题记录
        existing = await self._db.get_wrong_question_by_student_and_question(
            student_id, attempt.question_id
        )

        if existing is not None:
            # 已有记录 → 递增 attempt_count + 更新最新错误答案
            new_count = existing.get("attempt_count", 1) + 1
            updates: dict[str, Any] = {
                "wrong_answer": _serialize_answer(attempt.student_answer or ""),
                "attempt_count": new_count,
                "updated_at": now,
            }
            # 如果之前缺少 kp_id，补充
            new_kp_id = getattr(attempt, "kp_id", "") or ""
            if new_kp_id and new_kp_id != existing.get("kp_id", ""):
                updates["kp_id"] = new_kp_id
            # 如果正确答案有变化，更新
            if correct_answer and correct_answer != existing.get("correct_answer", ""):
                updates["correct_answer"] = correct_answer
            await self._db.update_wrong_question(
                existing["wrong_id"],
                updates,
            )
            logger.debug(
                "Updated wrong-book entry %s (attempt #%d)",
                existing["wrong_id"],
                new_count,
            )
            existing["attempt_count"] = new_count
            existing["updated_at"] = now
            return existing

        # 无已有记录 → 创建新错题条目
        record: dict[str, Any] = {
            "wrong_id": wrong_id,
            "student_id": student_id,
            "question_id": attempt.question_id,
            "kp_id": getattr(attempt, "kp_id", "") or "",
            "wrong_answer": _serialize_answer(attempt.student_answer or ""),
            "correct_answer": correct_answer,
            "attempt_count": 1,
            "resolution_status": "unresolved",   # 初始状态：未解决
            "note": "",
            "created_at": now,
            "updated_at": now,
        }
        await self._db.insert_wrong_question(record)
        logger.info("Created wrong-book entry %s for question %s", wrong_id, attempt.question_id)
        return record


# ==================================================================
# 内部辅助函数 — 批改
# ==================================================================


def _grade_programmatic(
    question: Question, student_answer: str
) -> tuple[bool, float, float]:
    """程序批改选择题和判断题（零 LLM 成本）。

    选择题：
    - 标准化大小写后直接比对 student_answer 和 correct_answer
    - 正确=1.0分，错误=0.0分

    判断题：
    - 支持多种 true/false 表示法（中文："对"/"错"/"正确"/"错误"）
    - 正确=1.0分，错误=0.0分

    Returns:
        tuple: (is_correct, score, max_score)
    """
    if question.type == QuestionType.MULTIPLE_CHOICE:
        student = student_answer.strip().upper()
        correct = str(question.correct_answer).strip().upper()
        is_correct = student == correct
        return is_correct, 1.0 if is_correct else 0.0, 1.0

    if question.type == QuestionType.TRUE_FALSE:
        def _to_bool(val: str) -> bool | None:
            """将各种真/假表示法统一为布尔值。"""
            v = val.strip().lower()
            if v in ("true", "1", "yes", "对", "正确"):
                return True
            if v in ("false", "0", "no", "错", "错误"):
                return False
            return None

        student_bool = _to_bool(student_answer)
        correct_raw = question.correct_answer
        if isinstance(correct_raw, bool):
            correct_bool = correct_raw
        else:
            correct_bool = _to_bool(str(correct_raw))

        if student_bool is None or correct_bool is None:
            is_correct = False
        else:
            is_correct = student_bool == correct_bool
        return is_correct, 1.0 if is_correct else 0.0, 1.0

    # 备用路径 — 不应到达这里
    return False, 0.0, question.points


async def _grade_via_llm(
    llm_client: LLMClient,
    grade_prompt_path: str,
    items: list[tuple[Question, dict]],
    student_id: str,
    now: str,
) -> list[dict[str, Any]]:
    """调用 LLM 批改非选择题（填空/简答/论述/编程题）。

    将所有题目+学生答案打包发送给 LLM（批量调用，节约 API 开销），
    LLM 按评分标准逐题判定并返回 misconceptions（迷思概念诊断）。

    Returns:
        list[dict]: 批改结果列表（与 items 顺序一致），
                    每项包含 is_correct、score、max_score、
                    analysis、misconceptions、remediation_note。
    """
    try:
        system_prompt = Path(grade_prompt_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise MaterialError(f"无法加载批改提示词: {grade_prompt_path} ({exc})") from exc

    # 构建批改上下文（把所有题目+答案格式化为 LLM 输入）
    lines: list[str] = []
    for idx, (q, ans) in enumerate(items):
        lines.append(f"## 题目 {idx + 1}")
        lines.append(f"- question_id: {q.question_id}")
        lines.append(f"- type: {q.type.value}")
        lines.append(f"- stem: {q.stem}")
        if q.options:
            lines.append(f"- options: {json.dumps(q.options, ensure_ascii=False)}")
        correct_repr = q.correct_answer
        if isinstance(correct_repr, (dict, list)):
            correct_repr = json.dumps(correct_repr, ensure_ascii=False)
        lines.append(f"- correct_answer (参考答案): {correct_repr}")
        lines.append(f"- max_score (满分): {q.points}")
        lines.append(f"- 学生作答: {ans.get('student_answer', '')}")
        lines.append("")

    user_prompt = "\n".join(lines)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    logger.info("Grading %d items via LLM...", len(items))

    try:
        raw = await llm_client.chat(
            messages=messages,
            temperature=0.1,     # 低温保证批改一致性
            max_tokens=4096,
            timeout=120,
        )
    except LLMError as exc:
        raise MaterialError(f"LLM 批改失败: {exc}") from exc

    raw = _strip_markdown_fence(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("LLM 批改返回的 JSON 无法解析: %s", raw[:500])
        raise MaterialError(f"批改结果不是有效 JSON: {exc}") from exc

    return data.get("results", [])


def _serialize_answer(answer: Any) -> str:
    """将正确答案序列化为 JSON 字符串，用于错题本存储。"""
    if isinstance(answer, (dict, list)):
        return json.dumps(answer, ensure_ascii=False)
    return str(answer)


async def _persist_attempt(
    db: Database,
    question: Question,
    answer: dict[str, Any],
    student_id: str,
    is_correct: bool,
    score: float,
    max_score: float,
    now: str,
    misconceptions: list[dict] | None = None,
    analysis: str = "",
) -> QuizAttempt:
    """将批改结果持久化为 QuizAttempt 记录并写入数据库。

    Returns:
        QuizAttempt: 包含完整字段的作答记录模型。
    """
    attempt_id = str(uuid4())

    kp_id = question.kp_id

    record: dict[str, Any] = {
        "attempt_id": attempt_id,
        "student_id": student_id,
        "question_id": question.question_id,
        "kp_id": kp_id,
        "student_answer": answer.get("student_answer"),
        "is_correct": 1 if is_correct else 0,
        "score": score,
        "time_spent_seconds": answer.get("time_spent_seconds", 0),
        "hints_used": answer.get("hints_used", 0),
        "attempt_number": answer.get("attempt_number", 1),
        "confidence": answer.get("confidence"),
        "misconception_ids": json.dumps(
            [m.get("label", "") for m in (misconceptions or [])],
            ensure_ascii=False,
        ),
        "note": analysis or "",
        "started_at": now,
        "submitted_at": now,
        "metadata": json.dumps(
            {
                "max_score": max_score,
                "misconceptions": misconceptions or [],
            },
            ensure_ascii=False,
        ),
    }

    await db.insert_attempt(record)

    return QuizAttempt(
        attempt_id=attempt_id,
        student_id=student_id,
        question_id=question.question_id,
        kp_id=kp_id,
        student_answer=answer.get("student_answer"),
        is_correct=is_correct,
        time_spent_seconds=answer.get("time_spent_seconds", 0),
        started_at=now,
        submitted_at=now,
    )


# ==================================================================
# 通用工具函数
# ==================================================================


def _strip_markdown_fence(raw: str) -> str:
    """去除 LLM 响应中的 Markdown 代码围栏（```json ... ```）。

    Args:
        raw: LLM 原始响应文本。

    Returns:
        str: 去除围栏后的纯 JSON 文本。
    """
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]       # 去掉开始的 ```json
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]      # 去掉结束的 ```
        raw = "\n".join(lines)
    return raw


def _distribute_counts(kp_ids: list[str], count: int) -> dict[str, int]:
    """将 count 道题目均匀分配到 kp_ids 列表中的各个 KP。

    分配策略：
    - 每个 KP 至少分配 base = count // n 道题
    - 余数 remainder = count % n 按顺序分配给前 remainder 个 KP

    例:
        kp_ids = ["A", "B", "C"], count = 5
        → base = 1, remainder = 2
        → {"A": 2, "B": 2, "C": 1}

    Args:
        kp_ids: 知识点 ID 列表。
        count: 总题目数。

    Returns:
        dict[str, int]: kp_id → 题目数量 的映射。
    """
    n = len(kp_ids)
    if n == 0:
        return {}
    base = count // n
    remainder = count % n
    result: dict[str, int] = {}
    for i, kp_id in enumerate(kp_ids):
        result[kp_id] = base + (1 if i < remainder else 0)
    return result
