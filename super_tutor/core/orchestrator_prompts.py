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
    question_count: int = 10,
    difficulty: str = "medium",
) -> str:
    """构建题目生成阶段的用户提示词。

    Args:
        chunks: PARSING 阶段产出的知识片段列表。
        question_count: 期望生成的题目总数（默认 10）。
        difficulty: 整体难度偏好（beginner / easy / medium / hard / expert）。
    """
    total_chunks = len(chunks)
    # 限制 chunks 数量以避免 prompt 过长；
    # 超过上限时均匀采样，确保覆盖全部 topic
    _MAX_CHUNKS = 20
    if total_chunks > _MAX_CHUNKS:
        step = total_chunks / _MAX_CHUNKS
        sampled = [chunks[int(i * step)] for i in range(_MAX_CHUNKS)]
        chunks_preview = sampled
        truncation_note = (
            f"（共 {total_chunks} 个片段，已均匀采样 {_MAX_CHUNKS} 个；"
            f"出题时请覆盖所有 {total_chunks} 个片段的 topic）"
        )
    else:
        chunks_preview = chunks
        truncation_note = ""
    chunks_json = _safe_truncate_json(chunks_preview, max_items=_MAX_CHUNKS)

    # 难度锚定说明
    difficulty_anchor = {
        "beginner": "整体偏简单，以记忆和理解层次为主",
        "easy": "整体较简单，记忆+理解为主，少量应用",
        "medium": "中等难度，按 30/40/20/10 比例分布",
        "hard": "整体偏难，以应用和分析层次为主",
        "expert": "高难度，以分析+评价层次为主",
    }.get(difficulty, "中等难度，按 30/40/20/10 比例分布")

    return (
        "你是一位资深教学出题专家。请根据以下知识片段生成一套测验题。\n\n"
        f"## 知识片段（共 {total_chunks} 个）{truncation_note}\n"
        f"```json\n{chunks_json}\n```\n\n"
        "────────────────────────────────────────\n"
        "## 出题要求\n\n"
        f"**题目总数：{question_count} 道**（必须精确，不多不少）\n\n"
        "### 题型分布（6 种题型都要覆盖）\n"
        "| 题型 | type 值 | 占比 | 说明 |\n"
        "|------|---------|------|------|\n"
        "| 选择题 | multiple_choice | ~40% | 4 个选项，每个干扰项对应一个迷思概念 |\n"
        "| 判断题 | true_false | ~15% | 判断命题对错，陈述需有迷惑性 |\n"
        "| 填空题 | fill_in_blank | ~15% | 挖空关键术语/公式/数值 |\n"
        "| 简答题 | short_answer | ~15% | 一句话解释或计算 |\n"
        "| 匹配题 | matching | ~10% | 左右两列配对（概念<->定义/公式<->含义） |\n"
        "| 论述题 | essay | ~5% | 需要展开分析或评价的开放问题 |\n\n"
        f"### 难度分布\n"
        f"{difficulty_anchor}\n"
        "具体：记忆(Bloom-remember) 30% / 理解(Bloom-understand) 40% / "
        "应用(Bloom-apply) 20% / 分析(Bloom-analyze) 10%\n\n"
        "### 每道题必须包含\n"
        "- **stem**: 题干（Markdown，清晰无歧义）\n"
        "- **type**: 题型（上述 6 种之一）\n"
        "- **difficulty**: beginner / easy / medium / hard / expert\n"
        "- **correct_answer**: 正确答案（选择题填 key，判断题填 true/false，"
        "填空题填字符串或字符串数组，简答/论述填参考答案文本，"
        "匹配题填 pairs 数组）\n"
        "- **explanation**: 详细解析（为什么对、为什么错）\n"
        "- **options**: 选择题和匹配题为必填，判断题/填空/简答可为空数组\n"
        "- **knowledge_node_ids**: 考查的知识点 ID 列表\n\n"
        "### 各题型 options 格式\n"
        "- 选择题: [{'key': 'A', 'text': '...', 'misconception': '...'}]\n"
        "- 判断题: [{'key': 'true', 'text': 'Correct'}, {'key': 'false', 'text': 'Incorrect'}]\n"
        "- 匹配题: [{'left': 'Concept A', 'right': 'Definition A'}, ...]\n"
        "- 其他题型: []\n\n"
        "## 各题型输出示例\n\n"
        "### 选择题 (multiple_choice)\n"
        '```json\n{"stem": "A 2kg object experiences a net force of 10N. '
        'What is its acceleration?", '
        '"type": "multiple_choice", "difficulty": "easy", '
        '"options": [{"key": "A", "text": "5 m/s^2", "misconception": ""}, '
        '{"key": "B", "text": "20 m/s^2", "misconception": "confuses F*m with F/m"}], '
        '"correct_answer": "A", '
        '"explanation": "F=ma so a=F/m=10/2=5 m/s^2"}\n```\n\n'
        "### 判断题 (true_false)\n"
        '```json\n{"stem": "If net force is zero, the object must be at rest.", '
        '"type": "true_false", "difficulty": "easy", '
        '"options": [{"key": "true", "text": "True"}, '
        '{"key": "false", "text": "False"}], '
        '"correct_answer": "false", '
        '"explanation": "Zero net force means no acceleration - '
        'the object could be moving at constant velocity (Newton\'s First Law)."}\n```\n\n'
        "### 填空题 (fill_in_blank)\n"
        '```json\n{"stem": "Newton\'s Second Law is expressed as `F = ___` '
        'where F is the net force.", '
        '"type": "fill_in_blank", "difficulty": "beginner", '
        '"options": [], '
        '"correct_answer": "ma", '
        '"explanation": "F=ma is the core formula: m is mass, a is acceleration."}\n```\n\n'
        "### 简答题 (short_answer)\n"
        '```json\n{"stem": "State Newton\'s Third Law in one sentence.", '
        '"type": "short_answer", "difficulty": "easy", '
        '"options": [], '
        '"correct_answer": "For every action, there is an equal and opposite reaction.", '
        '"explanation": "Forces always come in pairs acting on different objects."}\n```\n\n'
        "### 匹配题 (matching)\n"
        '```json\n{"stem": "Match each physical quantity with its SI unit.", '
        '"type": "matching", "difficulty": "easy", '
        '"options": [{"left": "Force", "right": "Newton (N)"}, '
        '{"left": "Work", "right": "Joule (J)"}, '
        '{"left": "Power", "right": "Watt (W)"}], '
        '"correct_answer": {"pairs": [{"left": "Force", "right": "Newton (N)"}, '
        '{"left": "Work", "right": "Joule (J)"}, '
        '{"left": "Power", "right": "Watt (W)"}]}, '
        '"explanation": "The three fundamental mechanical quantities and their SI units."}\n```\n\n'
        "### 论述题 (essay)\n"
        '```json\n{"stem": "Compare Newtonian mechanics and Einstein\'s relativity '
        'in terms of their views on space and time. State their domains of applicability.", '
        '"type": "essay", "difficulty": "expert", '
        '"options": [], '
        '"correct_answer": "Newtonian mechanics assumes absolute space and time... '
        'valid for macroscopic objects at v<<c. '
        'Relativity treats space and time as relative... '
        'valid at all speeds, reducing to Newtonian at v<<c.", '
        '"explanation": "Key difference: absolute vs relative spacetime. '
        'Domain: low-speed macroscopic vs all speeds/strong gravity."}\n```\n\n'
        "## 输出格式\n"
        "**严格按以下 JSON Schema 输出。只输出 JSON，以 `{` 开头，以 `}` 结尾，不要任何额外文字。**\n\n"
        '```json\n{"questions": [...]}\n```\n\n'
        f"**再次强调：一共 {question_count} 道题，6 种题型都要有，"
        "难度按比例分布。**"
    )


# ======================================================================
# EVALUATING 阶段
# ======================================================================


def _build_evaluating_prompt(
    questions: list[dict[str, Any]],
    student_answers: list[dict[str, Any]],
) -> str:
    """构建批改诊断阶段的用户提示词。

    输出 schema 包含苏格拉底式渐进提示（F8）和评估汇总。
    """
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
        "3. 为每道错题提供苏格拉底式渐进提示（socratic_hints），分三个层级：\n"
        "   - **Level 1**: 笼统引导，让学生意识到问题方向\n"
        "   - **Level 2**: 指向具体方向或概念，缩小思考范围\n"
        "   - **Level 3**: 接近答案的具体线索，逼近但不等于答案\n"
        "4. 输出评估汇总（summary）\n\n"
        "请以 JSON 格式输出：\n"
        '```json\n{\n'
        '  "attempts": [{"question_id": "...", "is_correct": false, '
        '"score": 0.0, "misconception_ids": ["..."]}],\n'
        '  "misconceptions": [{"label": "...", "category": "conceptual", '
        '"description": "...", "remediation_hint": "...",\n'
        '    "socratic_hints": [\n'
        '      {"level": 1, "content": "笼统引导，让学生意识到问题方向"},\n'
        '      {"level": 2, "content": "指向具体方向或概念，缩小思考范围"},\n'
        '      {"level": 3, "content": "接近答案的具体线索，逼近但不等于答案"}\n'
        '    ]}],\n'
        '  "summary": {"total_questions": 0, "correct_count": 0, '
        '"accuracy": 0.0, "weakest_topic": "...", '
        '"overall_assessment": "..."}\n'
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
