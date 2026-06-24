"""Super Tutor — 全项目共用枚举定义。

所有枚举统一在此模块定义，其他模块通过 ``from super_tutor.models.enums import ...`` 引用。
"""

from enum import Enum


# ============================================================================
# AIRole — AI 角色标识
# ============================================================================


class AIRole(str, Enum):
    """教学流水线中的 AI 角色。

    每个角色有独立的系统提示词、能力边界和分工，由 RoleManager 统一调度。
    """

    TUTOR = "tutor"          # 主导师 — 制定学习计划、讲解知识点、验收学习成果
    ASSISTANT = "assistant"  # 助教 — 出题、批改、答疑辅
    EVALUATOR = "evaluator"  # 评估者 — 独立评估学生掌握程度、生成学情报告


# ============================================================================
# DifficultyLevel — 难度等级
# ============================================================================


class DifficultyLevel(str, Enum):
    """题目 / 学习材料的难度等级。"""

    BEGINNER = "beginner"        # 入门 — 概念了解、基础记忆
    EASY = "easy"                # 简单 — 单一知识点、直接套用
    MEDIUM = "medium"            # 中等 — 多知识点组合、需要分析
    HARD = "hard"                # 困难 — 综合应用、深层推理
    EXPERT = "expert"            # 专家 — 竞赛级 / 研究级


# ============================================================================
# QuestionType — 题目类型
# ============================================================================


class QuestionType(str, Enum):
    """题目类型，覆盖常见教学测评形式。"""

    MULTIPLE_CHOICE = "multiple_choice"  # 选择题
    TRUE_FALSE = "true_false"            # 判断题
    FILL_IN_BLANK = "fill_in_blank"      # 填空题
    SHORT_ANSWER = "short_answer"        # 简答题
    ESSAY = "essay"                      # 论述题 / 作文
    CODING = "coding"                    # 编程题
    MATCHING = "matching"                # 匹配题 / 连线题


# ============================================================================
# QuizStatus — 测验 / 试卷生命周期状态
# ============================================================================


class QuizStatus(str, Enum):
    """测验从创建到归档的完整生命周期状态。"""

    DRAFT = "draft"            # 草稿 — 题目编辑中，不可发布
    READY = "ready"            # 就绪 — 题目已审核，等待发布
    PUBLISHED = "published"    # 已发布 — 学生可见、可作答
    IN_PROGRESS = "in_progress"  # 作答中 — 学生已开始答题
    SUBMITTED = "submitted"    # 已提交 — 等待批改
    GRADED = "graded"          # 已评分 — 客观题已出分
    REVIEWED = "reviewed"      # 已复习 — 主观题人工复核完毕，成绩最终
    ARCHIVED = "archived"      # 已归档 — 历史测验，只读


# ============================================================================
# WorkflowState — 工作流状态机状态
# ============================================================================


class PipelinePhase(str, Enum):
    """教学流水线的五个线性阶段。

    五个阶段按序推进：

    * **IDLE**        — 空闲，等待用户触发
    * **PARSING**     — 解析 PDF → 切片 → 向量化
    * **QUIZ_GEN**    — 基于知识库生成题目
    * **EVALUATING**  — 批改作答、诊断迷思概念
    * **PLANNING**    — 生成 SM-2 排期计划

    注：PAUSED 和 ERROR 不再是独立的枚举值，改为 Orchestrator
    上的 ``_paused: bool`` 和 ``_error_message: str | None`` 字段。
    DONE 由 ``phase == PLANNING and not paused and not error`` 隐式表示。
    """

    IDLE = "idle"
    PARSING = "parsing"
    QUIZ_GEN = "quiz_gen"
    EVALUATING = "evaluating"
    PLANNING = "planning"

# 向后兼容别名（旧代码中仍可能从枚举模块导入 WorkflowState）
WorkflowState = PipelinePhase  # type: ignore[assignment]
