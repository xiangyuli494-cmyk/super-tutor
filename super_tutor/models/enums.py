"""枚举定义模块 — 全项目共用的枚举类型。

【功能说明】
统一管理所有枚举定义，其他模块通过以下方式引用：
    from super_tutor.models.enums import DifficultyLevel, QuestionType

包含两个核心枚举：
1. DifficultyLevel — 难度等级（beginner/easy/medium/hard/expert）
2. QuestionType — 题目类型（选择题/判断题/填空题/简答题/论述题/编程题）

【耦合关系】
- 被所有 Engine 模块使用（knowledge_engine, quiz_engine, assessment_engine, plan_engine）
- 被所有 Model 模块使用（knowledge, quiz, assessment）
- 被 app.py 用于渲染 UI 选项和题目
"""

from enum import Enum


# ============================================================================
# DifficultyLevel — 难度等级
# ============================================================================


class DifficultyLevel(str, Enum):
    """题目 / 学习材料的难度等级。

    基于 Bloom 认知分类法分层：
    - beginner: 记忆层 — 概念了解、基础记忆
    - easy: 理解层 — 单一知识点、直接套用
    - medium: 应用层 — 多知识点组合、需要分析
    - hard: 分析/评价层 — 综合应用、深层推理
    - expert: 创造层 — 竞赛级 / 研究级
    """

    BEGINNER = "beginner"   # 入门
    EASY = "easy"           # 简单
    MEDIUM = "medium"       # 中等
    HARD = "hard"           # 困难
    EXPERT = "expert"       # 专家


# ============================================================================
# QuestionType — 题目类型
# ============================================================================


class QuestionType(str, Enum):
    """题目类型枚举，覆盖常见教学测评形式。

    不同类型的批改方式不同：
    - 程序批改（零 LLM 成本）：multiple_choice、true_false
    - LLM 批改（需 API 调用）：fill_in_blank、short_answer、essay、coding
    """

    MULTIPLE_CHOICE = "multiple_choice"  # 选择题（4个选项，程序批改）
    TRUE_FALSE = "true_false"            # 判断题（对/错，程序批改）
    FILL_IN_BLANK = "fill_in_blank"      # 填空题（LLM 语义批改）
    SHORT_ANSWER = "short_answer"        # 简答题（LLM 按采分点批改）
    ESSAY = "essay"                      # 论述题/作文（LLM 多维度评分）
    CODING = "coding"                    # 编程题（LLM 评估代码正确性）
