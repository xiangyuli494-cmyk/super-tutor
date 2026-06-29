"""Super Tutor — 业务引擎层。

【功能说明】
提供 5 个高层次的业务逻辑组件（均为无状态 Engine 类），
组成从知识点提取到教学反馈的完整闭环：

1. KnowledgeEngine    — 知识点解析（LLM 驱动）、关系管理和掌握度追踪
2. QuizEngine          — 题目生成（LLM 驱动）+ 程序/LLM 混合批改 + 错题自动收录
3. AssessmentEngine    — 诊断性评估 + 3 条前置规则校准（纯 Python 逻辑）
4. PlanEngine          — 拓扑排序（Kahn 算法）+ 优先级公式 + 排期生成
5. SocraticEngine      — 苏格拉底式追问（L1→L2→L3 状态机 + 2 个安全阀）

【引擎间依赖关系】
KnowledgeEngine（入口引擎，被以下引擎依赖）
    ├── QuizEngine ──────────────→ 调用 KnowledgeEngine 获取 KP 上下文
    ├── AssessmentEngine ────────→ 委托 QuizEngine 批改 + 调用 KnowledgeEngine 查询
    ├── PlanEngine ──────────────→ 独立（只依赖 Database，不依赖 LLM）
    └── SocraticEngine ─────────→ 独立（只依赖 Database + LLMClient）

【耦合关系】
- 全部 5 个引擎依赖 Database（数据 CRUD）
- 除 PlanEngine 外的 4 个引擎依赖 LLMClient（API 调用）
- 被 app.py 的各个 Tab 页面编排和调用
- 输出模型（KnowledgePoint、Question、AssessmentReport、StudyPlan、SocraticTurn）
  供 app.py 渲染 UI
"""

from super_tutor.engine.assessment_engine import AssessmentEngine
from super_tutor.engine.knowledge_engine import KnowledgeEngine
from super_tutor.engine.plan_engine import PlanEngine
from super_tutor.engine.quiz_engine import QuizEngine
from super_tutor.engine.socratic_engine import SocraticEngine

__all__ = [
    "AssessmentEngine",
    "KnowledgeEngine",
    "PlanEngine",
    "QuizEngine",
    "SocraticEngine",
]
