"""Orchestrator — 各阶段 Prompt 构建函数。

从 ``orchestrator.py`` 中提取的模块级函数，为 PARSING / QUIZ_GEN /
EVALUATING / PLANNING 四个阶段构建发送给 LLM 的用户提示词。
"""

from __future__ import annotations

from typing import Any

from super_tutor.core.orchestrator_utils import _safe_truncate_json


# ======================================================================
# PARSING 阶段
# ======================================================================


def _build_parsing_prompt(material_id: str, content: str = "") -> str:
    """构建 PDF 解析阶段的用户提示词。

    Args:
        material_id: 材料唯一标识。
        content: 材料的全文内容（由 PyMuPDF 提取或文本上传）。"""
    # 截断过长的文本以适配 LLM 上下文窗口
    # 中文约 1.5 字符/token，50K 字符 ≈ 33K tokens，留足输出空间
    _MAX_CONTENT_CHARS = 50_000
    if len(content) > _MAX_CONTENT_CHARS:
        content = content[:_MAX_CONTENT_CHARS]
        truncation_note = (
            f"\n\n（注：原文共超过 {_MAX_CONTENT_CHARS} 字符，"
            f"已截断至前 {_MAX_CONTENT_CHARS} 字符。请分析已有内容。）"
        )
    else:
        truncation_note = ""

    return (
        "你是一位教学资料分析专家。请分析以下学习材料，将其拆分为独立的知识片段。\n\n"
        f"材料 ID: {material_id}\n"
        f"材料长度: {len(content)} 字符{truncation_note}\n\n"
        "────────────────────────────────────────\n"
        "## 学习材料内容\n\n"
        f"{content}\n\n"
        "────────────────────────────────────────\n\n"
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


# ======================================================================
# QUIZ_GEN 阶段
# ======================================================================


def _build_quiz_gen_prompt(
    chunks: list[dict[str, Any]],
    mastery_summary: str = "",
) -> str:
    """构建题目生成阶段的用户提示词。

    Args:
        chunks: 知识片段列表。
        mastery_summary: 可选的学生掌握度摘要，注入后将启用自适应出题模式。
    """
    # 限制 chunks 数量以避免 prompt 过长
    chunks_preview = chunks[:15] if len(chunks) > 15 else chunks
    chunks_json = _safe_truncate_json(chunks_preview, max_items=15)

    # -- 自适应出题指令 ---------------------------------------------------
    adaptive_section = ""
    if mastery_summary:
        adaptive_section = (
            "\n\n## 学生掌握度数据（自适应出题）\n"
            f"{mastery_summary}\n\n"
            "### 自适应出题规则\n"
            "1. **弱知识点优先**：掌握度 < 40% 或状态为 new/learning 的节点，"
            "每节点至少出 2-3 道题，合计占总题量 ≥ 50%\n"
            "2. **中等知识点适量**：掌握度 40-70% 或状态为 reviewing 的节点，"
            "每节点 1-2 道题，合计占总题量 30-40%\n"
            "3. **强知识点复习**：掌握度 > 70% 或状态为 mastered 的节点，"
            "每节点 0-1 道题（以复习/变式题为主），合计占总题量 ≤ 20%\n"
            "4. **迷思概念优先**：有 misconception 记录的知识点，"
            "优先出针对性的改错/辨析题\n"
            "5. 若某些知识点无掌握度数据（首次学习），视同弱知识点处理\n"
        )

    return (
        "你是一位资深教学出题专家。请根据以下知识片段生成一套测验题。\n\n"
        f"## 知识片段（共 {len(chunks)} 个）\n"
        f"```json\n{chunks_json}\n```"
        f"{adaptive_section}\n\n"
        "## 出题要求\n"
        "1. 题型以选择题（multiple_choice）为主，可含少量简答题（short_answer）\n"
        "2. 难度分布：记忆 30% / 理解 40% / 应用 20% / 分析 10%\n"
        "3. 每道题包含：\n"
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


# ======================================================================
# EVALUATING 阶段
# ======================================================================


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


# ======================================================================
# PLANNING 阶段
# ======================================================================


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
