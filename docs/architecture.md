# 超级私教 (Super Tutor) — 技术架构文档

**文档编号：** STA-ARCH-2026-003
**版本：** v3.0
**状态：** 已实现
**密级：** 内部

---

## 文档说明

本文档描述 v3.0 重构的目标架构。核心变化：

| 维度 | v2.0（当前代码） | v3.0（目标） |
|------|-----------------|-------------|
| 前端 | React + Vite + Tailwind + Zustand | **Streamlit** |
| 编排引擎 | Orchestrator 状态机 (~2,200 行) | **去掉**，页面按钮驱动 |
| AI 角色 | Tutor / Assistant / Evaluator (3 角色) | **去掉**，每次调用直接构建 Prompt |
| 数据库表 | 14 张 | **精简为 6 张**（知识点为核心） |
| 启动方式 | 两个终端（uvicorn + vite） | **一个命令**（`streamlit run`） |

**配套文档：**
- 产品需求 → [requirements.md](requirements.md) (v5.0)

---

## 第 1 章 · 现有文件处置清单

以当前项目根目录 `super-tutor-agent/` 为准，逐文件说明。

### 1.1 删除的文件

```
frontend/                          # 整个目录移除（React SPA）
├── index.html
├── package.json
├── package-lock.json
├── postcss.config.js
├── tailwind.config.js
├── tsconfig.json
├── vite.config.ts
├── dist/
├── node_modules/
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── index.css
    ├── api/client.ts
    ├── api/types.ts
    ├── store/quizStore.ts
    ├── store/studentStore.ts
    ├── pages/Dashboard.tsx
    ├── pages/MaterialsPage.tsx
    ├── pages/QuizPage.tsx
    ├── pages/ResultsPage.tsx
    ├── pages/PlanPage.tsx
    └── components/{Layout,Navbar,FileUpload,QuizCard,ResultCard,MasteryChart}.tsx

super_tutor/core/orchestrator.py          # 状态机主类 (~900 行)
super_tutor/core/orchestrator_phases.py   # 四阶段 Mixin (~760 行)
super_tutor/core/orchestrator_prompts.py  # Prompt 构建 (~280 行)
super_tutor/core/orchestrator_utils.py    # JSON 解析+水合 (~260 行)
super_tutor/core/role_manager.py          # 角色管理器
super_tutor/core/token_tracker.py         # Token 追踪器
super_tutor/core/limiter.py               # 限流器 (Streamlit 不需要)
super_tutor/core/cli_backend.py           # Claude CLI 回退（不再需要）

super_tutor/routes/dependencies.py        # 依赖注入（OrchestratorRegistry 等）
super_tutor/routes/quizzes.py             # 测验路由（依赖 Orchestrator）
super_tutor/routes/tokens.py              # Token 统计路由

super_tutor/prompts/tutor.md              # 角色 Prompt（不再需要角色系统）
super_tutor/prompts/assistant.md          # 角色 Prompt
super_tutor/prompts/evaluator.md          # 角色 Prompt

tests/test_tokens.py                      # Token 测试（不再需要）
```

### 1.2 保留并修改的文件

| 文件 | 修改内容 |
|------|---------|
| `requirements.txt` | 去掉 `slowapi`、`sqlite-vec`；新增 `streamlit` |
| `super_tutor/main.py` | 去掉 Orchestrator/limiter/role 相关导入；简化 lifespan |
| `super_tutor/config.py` | 去掉 `model_heavy/medium/light`、`token_budget`、`prompt_versions` |
| `super_tutor/core/database.py` | 14 表 → 5 表；去掉 vector/embedding 逻辑 |
| `super_tutor/core/llm_client.py` | 去掉 `token_tracker` 参数；简化接口 |
| `super_tutor/core/exceptions.py` | 去掉 `SessionError` 及子类；新增 `NoKnowledgePoints` |
| `super_tutor/models/enums.py` | 去掉 `AIRole`、`PipelinePhase`、`WorkflowState`、`MasteryState`、`MisconceptionCategory` |
| `super_tutor/models/knowledge.py` | 保留 `KnowledgeChunk`，新增 `KnowledgePoint`（含前后依赖字段）；KnowledgeNode/Edge/Graph 可保留 |
| `super_tutor/models/quiz.py` | 保留 `Question`/`QuizAttempt`；去掉 `QuizSession`/`SocraticHint`；新增 `WrongQuestion` |
| `super_tutor/models/mastery.py` | 内容合并到 `knowledge.py` 的 `KnowledgePoint.mastery_level` 字段 |
| `super_tutor/routes/materials.py` | 去掉 Orchestrator 依赖；简化上传逻辑 |
| `super_tutor/routes/dashboard.py` | 去掉 Orchestrator 依赖；精简查询 |
| `super_tutor/routes/schemas.py` | 去掉 Session/Orchestrator 相关 DTO；新增错题本相关 DTO |
| `tests/conftest.py` | 去掉 Orchestrator/FakeLLM 相关 fixture |
| `tests/test_materials.py` | 适配简化后的路由 |
| `tests/test_quizzes.py` | 适配简化后的出题/判题流程 |
| `tests/test_dashboard.py` | 适配简化后的查询 |

### 1.3 新增的文件

```
app.py                              # Streamlit 主入口（单文件应用）
super_tutor/engine/                 # 业务逻辑层（替代 orchestrator）
├── __init__.py
├── knowledge_engine.py             # 知识点解析 + 前后关联
├── assessment_engine.py            # 诊断评估
├── quiz_engine.py                  # 出题 + 判题
├── plan_engine.py                  # 学习计划（拓扑排序）
└── socratic_engine.py              # 苏格拉底追问
super_tutor/prompts/                # Prompt 模板（重写，按功能而非角色）
├── parse_knowledge.md              # 知识点解析
├── assessment.md                   # 诊断评估
├── quiz_gen.md                     # 出题
├── grade.md                        # 判题
└── socratic.md                     # 苏格拉底追问
```

---

## 第 2 章 · 目标项目结构

```
super-tutor-agent/
├── app.py                           # Streamlit 主入口
├── requirements.txt                 # Python 依赖（精简后）
├── pytest.ini
├── README.md
│
├── super_tutor/                     # 后端逻辑库
│   ├── __init__.py                  # 保留，更新 __version__
│   ├── config.py                    # 保留，精简
│   ├── main.py                      # 保留 FastAPI（可选，供未来 API 扩展）
│   │
│   ├── core/                        # 基础设施
│   │   ├── __init__.py
│   │   ├── database.py              # 改写：5 表，无向量
│   │   ├── llm_client.py            # 保留，去 token_tracker 参数
│   │   └── exceptions.py            # 保留，精简异常类
│   │
│   ├── engine/                      # 新增：业务引擎层
│   │   ├── __init__.py
│   │   ├── knowledge_engine.py
│   │   ├── assessment_engine.py
│   │   ├── quiz_engine.py
│   │   ├── plan_engine.py
│   │   └── socratic_engine.py
│   │
│   ├── models/                      # Pydantic 模型（保留，修改）
│   │   ├── __init__.py
│   │   ├── enums.py                 # 精简枚举
│   │   ├── knowledge.py             # 修改：+KnowledgePoint
│   │   ├── quiz.py                  # 修改：+WrongQuestion, -QuizSession
│   │   └── plan.py                  # 保留，简化
│   │
│   ├── routes/                      # FastAPI 路由（保留，简化）
│   │   ├── __init__.py
│   │   ├── schemas.py               # 精简 DTO
│   │   ├── materials.py             # 简化
│   │   ├── dashboard.py             # 简化
│   │   └── quizzes.py               # 重写：去 Orchestrator 依赖
│   │
│   └── prompts/                     # Prompt 模板
│       ├── parse_knowledge.md       # 新增
│       ├── assessment.md            # 新增
│       ├── quiz_gen.md              # 新增
│       ├── grade.md                 # 新增
│       └── socratic.md              # 新增
│
├── tests/                           # 测试
│   ├── __init__.py
│   ├── conftest.py                  # 精简 fixtures
│   ├── test_knowledge_engine.py     # 新增
│   ├── test_quiz_engine.py          # 新增
│   ├── test_materials.py            # 修改
│   └── test_dashboard.py            # 修改
│
└── docs/
    ├── requirements.md              # v5.0
    ├── architecture.md              # v3.0（本文档）
    └── PRD.md                       # 历史引用
```

---

## 第 3 章 · 数据库设计（从 14 表 → 6 表）

**文件：** `super_tutor/core/database.py`（重写）

### 3.1 现有表的处理

| 现有表 | 处置 | 原因 |
|--------|------|------|
| `materials` | **保留**，保留 `material_id`/`title`/`content`/`course_type`/`status`，去 `subject`/`description` | 记录上传来源 |
| `knowledge_chunks` | **改为 `knowledge_points`** | 知识点即核心实体，增加前后依赖字段 |
| `questions` | **保留**，增加 `kp_id`、`kp_context`，去 `session_id`/`knowledge_node_ids` | 题库 |
| `quiz_attempts` | **保留**，增加 `kp_id` | 作答记录 |
| `sessions` | **删除** | 无状态机，不需要会话 |
| `mastery_records` | **删除**（字段合并到 `knowledge_points`） | 掌握度是知识点的属性 |
| `study_plans` | **保留**，简化 | 学习计划 |
| `review_items` | **删除**（合并到 `study_plans.kp_sequence`） | 计划直接关联 KP |
| `socratic_hints` | **删除**（LLM 实时生成） | 不持久化 |
| `projects`/`artifacts`/`task_log`/`token_usage`/`git_commits` | **删除** | Codex CLI 模板遗留，与教学无关 |

### 3.2 目标 6 表

#### `materials` — 学习材料

```sql
CREATE TABLE materials (
    material_id TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    course_type TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'draft',  -- draft / processing / ready / error
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

> 相比现有：去掉 `subject`、`description`。新增 `course_type`。

#### `knowledge_points` — 知识点（核心表）

```sql
CREATE TABLE knowledge_points (
    kp_id             TEXT PRIMARY KEY,
    material_id       TEXT NOT NULL,
    title             TEXT NOT NULL,
    summary           TEXT NOT NULL DEFAULT '',
    content           TEXT NOT NULL,
    keywords          TEXT NOT NULL DEFAULT '[]',        -- JSON
    difficulty        TEXT NOT NULL DEFAULT 'medium',
    course_type       TEXT NOT NULL DEFAULT '',
    chapter_index     INTEGER NOT NULL DEFAULT 0,
    prerequisite_ids  TEXT NOT NULL DEFAULT '[]',        -- JSON [kp_id, ...]
    successor_ids     TEXT NOT NULL DEFAULT '[]',        -- JSON [kp_id, ...]
    mastery_level     REAL NOT NULL DEFAULT 0.0,
    assessment_count  INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE INDEX idx_kp_course ON knowledge_points(course_type);
CREATE INDEX idx_kp_material ON knowledge_points(material_id);
```

> 相比现有的 `knowledge_chunks`：新增 `prerequisite_ids`、`successor_ids`、`mastery_level`、`course_type`；去掉 `embedding`、`page_start`/`page_end`、`metadata`。

#### `questions` — 题库

```sql
CREATE TABLE questions (
    question_id    TEXT PRIMARY KEY,
    kp_id          TEXT NOT NULL,
    type           TEXT NOT NULL,              -- multiple_choice / true_false / fill_in_blank
    difficulty     TEXT NOT NULL DEFAULT 'medium',
    stem           TEXT NOT NULL,
    options        TEXT NOT NULL DEFAULT '[]', -- JSON
    correct_answer TEXT NOT NULL,
    explanation    TEXT NOT NULL DEFAULT '',
    kp_context     TEXT NOT NULL DEFAULT '[]', -- JSON [前驱KP摘要...]
    created_at     TEXT NOT NULL
);

CREATE INDEX idx_q_kp ON questions(kp_id);
```

> 相比现有：新增 `kp_id`（直接关联知识点）；新增 `kp_context`（记录注入的上下文）；去掉 `session_id`/`knowledge_node_ids`/`chunk_ids`/`subject`/`topic`/`tags`/`metadata`/`estimated_seconds`/`points`。

#### `quiz_attempts` — 作答记录

```sql
CREATE TABLE quiz_attempts (
    attempt_id         TEXT PRIMARY KEY,
    student_id         TEXT NOT NULL DEFAULT 'default',
    question_id        TEXT NOT NULL,
    kp_id              TEXT NOT NULL,
    student_answer     TEXT,
    is_correct         INTEGER,
    time_spent_seconds INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL
);

CREATE INDEX idx_qa_student ON quiz_attempts(student_id);
CREATE INDEX idx_qa_kp ON quiz_attempts(kp_id);
```

> 相比现有：新增 `kp_id`（冗余，方便按知识点查询）；去掉 `session_id`/`score`/`hints_used`/`attempt_number`/`confidence`/`misconception_ids`/`note`。

#### `wrong_questions` — 错题本（新表）

```sql
CREATE TABLE wrong_questions (
    wq_id         TEXT PRIMARY KEY,
    student_id    TEXT NOT NULL DEFAULT 'default',
    question_id   TEXT NOT NULL,
    kp_id         TEXT NOT NULL,
    attempt_id    TEXT NOT NULL,
    wrong_count   INTEGER NOT NULL DEFAULT 1,
    is_reviewed   INTEGER NOT NULL DEFAULT 0,
    last_wrong_at TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE INDEX idx_wq_student ON wrong_questions(student_id);
CREATE INDEX idx_wq_kp ON wrong_questions(kp_id);
```

#### `study_plans` — 学习计划（保留简化）

```sql
CREATE TABLE study_plans (
    plan_id     TEXT PRIMARY KEY,
    student_id  TEXT NOT NULL DEFAULT 'default',
    title       TEXT NOT NULL DEFAULT '',
    kp_sequence TEXT NOT NULL DEFAULT '[]',  -- JSON [kp_id, ...] 拓扑排序后的序列
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

> 相比现有：新增 `kp_sequence`（替代 `review_items` 表）；去掉 `description`/`subject`/`goal`/`start_date`/`end_date`/`metadata`。

---

## 第 4 章 · 枚举精简

**文件：** `super_tutor/models/enums.py`

```python
# === 保留 ===
class DifficultyLevel(str, Enum):
    BEGINNER = "beginner"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"

class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_IN_BLANK = "fill_in_blank"
    SHORT_ANSWER = "short_answer"
    ESSAY = "essay"
    CODING = "coding"

# === 删除 ===
# AIRole, PipelinePhase/WorkflowState, QuizStatus, MasteryState,
# MisconceptionCategory — 全部删除

# === 新增 ===
class CourseType(str, Enum):
    COMPUTER_SCIENCE = "computer_science"
    MATH = "math"
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    ENGLISH = "english"
    CUSTOM = "custom"

class PlanStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
```

---

## 第 5 章 · 配置精简

**文件：** `super_tutor/config.py`（修改）

| 配置键 | 保留？ | 说明 |
|--------|:---:|------|
| `api_key` | ✅ | DeepSeek API Key |
| `api_base_url` | ✅ | API 地址 |
| `db_path` | ✅ | SQLite 路径 |
| `max_retries` | ✅ | 重试次数 |
| `request_timeout` | ✅ | 超时 |
| `token_budget` | ❌ | 不再追踪 Token 预算 |
| `model_heavy` | ❌ | 不再分档，统一用 `model` |
| `model_medium` | ❌ | 同上 |
| `model_light` | ❌ | 同上 |

简化后：

```python
@dataclass
class TutorConfig:
    api_key: str = ""
    api_base_url: str = "https://api.deepseek.com"
    db_path: str = "~/.super-tutor/super_tutor.db"
    model: str = "deepseek-chat"
    max_retries: int = 3
    request_timeout: int = 120
```

---

## 第 6 章 · LLM 客户端精简

**文件：** `super_tutor/core/llm_client.py`（修改）

保留核心接口，去掉 `token_tracker` 参数：

```python
class LLMClient:
    def __init__(self, config: TutorConfig):
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.api_base_url,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 120,
    ) -> str:
        ...
```

重试策略保留（3 次指数退避）。

---

## 第 7 章 · 业务引擎层（新增，替代 Orchestrator）

**目录：** `super_tutor/engine/`

每个 Engine 是一组无状态的异步函数，直接操作 `Database` 和 `LLMClient`。没有状态机，没有角色切换。

### 7.1 KnowledgeEngine — 知识点解析与前后关联

```python
class KnowledgeEngine:
    def __init__(self, db: Database, llm: LLMClient): ...

    async def parse(
        self, content: str, course_type: str, material_id: str
    ) -> list[KnowledgePoint]:
        """1. 调 LLM 拆分知识点 (title/summary/keywords/difficulty)
           2. 识别 prerequisite/successor 关系 (按 title 匹配 → 转 kp_id)
           3. 批量写入 knowledge_points 表
           4. 双向更新 prerequisite_ids / successor_ids
        """

    async def get_by_material(self, material_id: str) -> list[KnowledgePoint]: ...
    async def get_by_course(self, course_type: str) -> list[KnowledgePoint]: ...
    async def get_prerequisites(self, kp_id: str) -> list[KnowledgePoint]: ...
    async def get_successors(self, kp_id: str) -> list[KnowledgePoint]: ...
    async def update_mastery(self, kp_id: str, score: float) -> None: ...
```

### 7.2 AssessmentEngine — 诊断评估

```python
class AssessmentEngine:
    def __init__(self, db: Database, llm: LLMClient): ...

    async def generate(
        self, kp_ids: list[str], question_count: int = 15
    ) -> list[Question]:
        """每个 KP 至少 1 题，从前驱到后继递进"""

    async def grade(
        self, questions: list[Question], answers: dict[str, str]
    ) -> AssessmentReport:
        """判题 + 更新 mastery_level + 应用前后联动规则"""

    def apply_prerequisite_rules(self, report: AssessmentReport) -> None:
        """规则 1: 前驱未掌握 → 后继置信度降低
           规则 2: 后继对但前驱错 → 标记 NeedReview
           规则 3: 连续 3 后继错 → 前驱标记 NeedRelearn
        """
```

### 7.3 QuizEngine — 出题与判题

```python
class QuizEngine:
    def __init__(self, db: Database, llm: LLMClient): ...

    async def generate_questions(
        self, kp_ids: list[str], count: int = 10,
        difficulty: str = "medium", types: list[str] = None,
    ) -> list[Question]:
        """出题时注入前驱知识点上下文 → 提高题目质量"""

    async def grade_answers(
        self, questions: list[Question], answers: dict[str, str]
    ) -> list[QuizAttempt]:
        """判题 + 自动收录错题到 wrong_questions"""

    async def add_to_wrong_book(self, attempt: QuizAttempt) -> WrongQuestion: ...
```

### 7.4 PlanEngine — 学习计划

```python
class PlanEngine:
    def __init__(self, db: Database): ...

    async def generate(
        self, kp_ids: list[str], mastery_map: dict[str, float]
    ) -> StudyPlan:
        """1. Kahn 拓扑排序 (前驱永远在前后继永远在后)
           2. 优先级 = (1 - 掌握度) × (1 + 后继数/总数)
           3. 输出 kp_sequence → 写入 study_plans
        """

    def topological_sort(self, kps: list[KnowledgePoint]) -> list[str]: ...
```

### 7.5 SocraticEngine — 苏格拉底追问

```python
class SocraticEngine:
    def __init__(self, db: Database, llm: LLMClient): ...

    async def start_dialogue(
        self, kp_id: str, wrong_question_id: str
    ) -> SocraticTurn:
        """初始提问 (L1 层级 — 笼统引导)"""

    async def continue_dialogue(
        self, history: list[SocraticTurn], user_response: str
    ) -> SocraticTurn:
        """根据回复决定升级(L1→L2→L3)/降级/结束/显示答案"""
```

苏格拉底对话状态（仅 4 状态，存在 `st.session_state`，不存 DB）：

```
L1_GUIDING → L2_HINTING → L3_NEAR_ANSWER → RESOLVED
     ↓            ↓              ↓
     └────────────┴──────────────┴──→ SHOW_ANSWER
```

---

## 第 8 章 · Streamlit 前端设计

### 8.1 入口：app.py

```python
import streamlit as st
from super_tutor.config import TutorConfig
from super_tutor.core.database import Database
from super_tutor.core.llm_client import LLMClient
from super_tutor.engine.knowledge_engine import KnowledgeEngine
from super_tutor.engine.assessment_engine import AssessmentEngine
from super_tutor.engine.quiz_engine import QuizEngine
from super_tutor.engine.plan_engine import PlanEngine
from super_tutor.engine.socratic_engine import SocraticEngine

st.set_page_config(page_title="超级私教", page_icon="🎓", layout="wide")

# ── 初始化（缓存，只执行一次） ──
@st.cache_resource
def init_services():
    config = TutorConfig.from_env()
    db = Database(config.db_path)
    llm = LLMClient(config)
    return {
        "db": db, "llm": llm,
        "knowledge": KnowledgeEngine(db, llm),
        "assessment": AssessmentEngine(db, llm),
        "quiz": QuizEngine(db, llm),
        "plan": PlanEngine(db),
        "socratic": SocraticEngine(db, llm),
    }

services = init_services()

# ── Sidebar ──
with st.sidebar:
    st.title("🎓 超级私教")
    course_type = st.selectbox(
        "课程类型",
        ["计算机科学", "数学", "物理", "化学", "英语", "自定义"]
    )
    st.divider()
    page = st.radio(
        "导航",
        ["📚 上传资料", "📝 诊断评估", "📋 学习计划",
         "✏️ 练习答题", "📕 错题本"],
    )

# ── 页面路由 ──
if page == "📚 上传资料":
    render_upload_page(services, course_type)
elif page == "📝 诊断评估":
    render_assessment_page(services)
elif page == "📋 学习计划":
    render_plan_page(services)
elif page == "✏️ 练习答题":
    render_practice_page(services)
elif page == "📕 错题本":
    render_wrong_book_page(services)
```

### 8.2 session_state 设计

```python
# 跨页面共享状态
if "material_id" not in st.session_state:
    st.session_state.material_id = None
if "knowledge_points" not in st.session_state:
    st.session_state.knowledge_points = []
if "assessment_done" not in st.session_state:
    st.session_state.assessment_done = False
if "assessment_report" not in st.session_state:
    st.session_state.assessment_report = None
if "current_plan" not in st.session_state:
    st.session_state.current_plan = None
if "practice_questions" not in st.session_state:
    st.session_state.practice_questions = []
if "practice_answers" not in st.session_state:
    st.session_state.practice_answers = {}
if "socratic_history" not in st.session_state:
    st.session_state.socratic_history = []
```

### 8.3 页面布局示意

#### 📚 上传资料页

```
┌────────────────────────────────────────────────────────┐
│  📚 上传学习资料                                        │
│                                                        │
│  ┌── PDF 上传 ──────────┐  ┌── 粘贴文本 ─────────────┐ │
│  │  [拖拽或选择文件]      │  │  [textarea]              │ │
│  │  (≤ 50MB, 文字型PDF)  │  │                          │ │
│  └───────────────────────┘  └──────────────────────────┘ │
│                                                        │
│  [🚀 开始解析]  ← 点击后 spinner "AI 正在提取知识点…"    │
│                                                        │
│  ── 解析结果 ──                                        │
│  ✅ 提取到 15 个知识点                                  │
│  ┌────┬──────────┬──────┬──────────┬──────────┐       │
│  │ #  │ 知识点    │ 难度  │ 前驱      │ 后继      │       │
│  │ 1  │ F=ma     │ easy │ -        │ 动量定理   │       │
│  │ 2  │ 动量定理  │ med  │ F=ma     │ 动量守恒   │       │
│  └────┴──────────┴──────┴──────────┴──────────┘       │
│                                                        │
│  [✅ 确认，开始诊断评估 →]                               │
└────────────────────────────────────────────────────────┘
```

#### 📝 诊断评估页

```
┌────────────────────────────────────────────────────────┐
│  📝 诊断评估                                            │
│                                                        │
│  📊 共 15 题 · 覆盖 15 个知识点 · 预计 20 分钟           │
│                                                        │
│  Q1. [选择题] 一个质量为 2kg 的物体受 10N 力...            │
│  ○ A  ○ B  ○ C  ○ D                                   │
│  ─────────────────────────────────────                 │
│  Q2. [判断题] F=ma 只适用于匀速运动                       │
│  ○ 对  ○ 错                                            │
│                                                        │
│  [📤 提交评估]                                          │
│                                                        │
│  ── 评估结果 ──                                        │
│  📊 正确率: 9/15 (60%)                                  │
│  ⚠️ 薄弱: 牛顿第二定律 (0%), 动量守恒 (33%)               │
│  ⭐ 强项: 动能定理 (100%)                                │
│  [📋 生成学习计划 →]                                     │
└────────────────────────────────────────────────────────┘
```

#### 📕 错题本页（含苏格拉底追问）

```
┌────────────────────────────────────────────────────────┐
│  📕 错题本                                              │
│                                                        │
│  筛选: [全部知识点 ▼] [最近 7 天 ▼]                      │
│                                                        │
│  ┌─ 知识点: 牛顿第二定律 (3 道错题) ─────────────────┐  │
│  │  Q1. [选择] 质量为 2kg 物体受 10N 力...              │  │
│  │  你的答案: B (20 m/s²)    ❌                        │  │
│  │  正确答案: A (5 m/s²)                               │  │
│  │  解析: a = F/m = 10/2 = 5 m/s²                     │  │
│  │  错误 2 次   [🔄 重新作答]  [🗨 苏格拉底追问]        │  │
│  │                                                    │  │
│  │  ── 🗨 苏格拉底对话 ──                              │  │
│  │  🎓: 你回忆一下，牛顿第二定律的公式是什么？            │  │
│  │  🙋 学生: [F=ma                    ] [发送]         │  │
│  │  🎓: 对。已知 F=10N, m=2kg，求 a 应怎么做？          │  │
│  │  🙋 学生: [a=10/2=5                ] [发送]         │  │
│  │  🎓: 很好！现在你能理解正确答案了吗？                  │  │
│  │  [我知道了 ✅]  [直接显示答案]                        │  │
│  └────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

### 8.4 UI 约定

- **Loading：** 所有 LLM 调用使用 `with st.spinner("AI 正在处理…")` 包裹
- **数据表格：** 使用 `st.dataframe()` 展示知识点、错题列表
- **答题交互：** 选择题用 `st.radio()`，判断题用 `st.radio(["对", "错"])`，填空题用 `st.text_input()`
- **状态切换：** `st.session_state` + `st.rerun()` 实现页面间跳转
- **错误处理：** `st.error()` 展示异常信息，关键操作提供 `st.button("重试")`

---

## 第 9 章 · Prompt 模板（5 个，替代旧 3 个角色 Prompt）

### 9.1 parse_knowledge.md

```markdown
# System
你是 {course_type} 教学专家。请将以下教材内容按知识点拆分。

要求:
1. 每个知识点是一个不可再分的概念/公式/定理
2. 为每个知识点输出: title, summary(≤200字), keywords(数组), difficulty
3. 识别知识点间的依赖关系: 每个知识点的 prerequisites 和 successors
   - 用 title 描述依赖关系，后续系统会自动转为 ID
4. 输出严格 JSON: {"knowledge_points": [{...}]}

课程类型: {course_type}
拆分粒度: {granularity_hint}  （根据课程类型自动填充）
```

### 9.2 assessment.md

```markdown
# System
你是 {course_type} 出题专家。请生成诊断评估测验。

知识点列表 (按依赖关系排序):
{kp_list_json}

要求:
- 每个知识点至少 1 题
- 从前驱知识点开始，逐步到后继知识点
- 题型: 选择题 60% + 判断题 20% + 填空题 20%
- 难度匹配各知识点的 difficulty
- 输出: {{"questions": [...]}}
```

### 9.3 quiz_gen.md

```markdown
# System
请基于以下知识点生成练习题。

目标知识点: {kp_title} (难度: {difficulty})
知识点内容: {kp_summary}

前驱知识背景 (已学过的知识):
{prerequisite_context}

要求:
- 考察对「{kp_title}」的理解深度
- 干扰项可引用前驱知识的常见迷思概念
- 题型: {question_type}
- 输出: {{"questions": [...]}}
```

### 9.4 grade.md

```markdown
# System
请批改以下作答。

题目: {stem}
题型: {type}
正确答案: {correct_answer}
学生答案: {student_answer}

规则:
- 选择题/判断题: 直接比对，100% 准确
- 填空题: 语义匹配 + 关键词比对，宽松判定
- 输出: {{"is_correct": bool, "explanation": "详细解析"}}
```

### 9.5 socratic.md

```markdown
# System
你是苏格拉底式导师。用户答错了关于「{kp_title}」的题。

目标知识点: {kp_title}
知识点摘要: {kp_summary}
题目: {stem}
用户错误答案: {student_answer}
正确答案: {correct_answer}

当前引导层级: {level}

规则:
- L1 (笼统引导): 提出概念性问题，让用户回忆相关知识
- L2 (方向提示): 给出方向性提示，缩小思考范围
- L3 (接近答案): 几乎说出答案但留最后一步
- 用户回答正确 → 升级；不正确 → 同级换角度；说"显示答案" → 直接给出
```

---

## 第 10 章 · FastAPI 路由精简

**文件：** `super_tutor/routes/`（修改）

### 10.1 保留的路由端点

| 方法 | 路径 | 文件 | 变化 |
|------|------|------|------|
| POST | `/api/v1/materials/upload` | materials.py | 去 Orchestrator 依赖 |
| POST | `/api/v1/materials/upload/file` | materials.py | 同上 |
| GET | `/api/v1/materials/{id}/status` | materials.py | 同上 |
| POST | `/api/v1/questions/generate` | quizzes.py | **重写**：直接调 QuizEngine |
| POST | `/api/v1/questions/grade` | quizzes.py | **重写**：直接调 QuizEngine |
| GET | `/api/v1/students/{id}/dashboard` | dashboard.py | 简化查询 |
| GET | `/api/v1/students/{id}/mastery` | dashboard.py | 简化查询，从 knowledge_points 读 |
| GET | `/api/v1/students/{id}/wrong-questions` | dashboard.py | 查询 wrong_questions 表 |
| POST | `/api/v1/students/{id}/socratic/start` | dashboard.py | **新增**：调 SocraticEngine |
| POST | `/api/v1/students/{id}/socratic/continue` | dashboard.py | **新增** |

### 10.2 删除的路由端点

| 原端点 | 原因 |
|--------|------|
| POST `/api/v1/sessions` | 无会话概念 |
| GET `/api/v1/sessions/{id}/questions` | 无会话概念 |
| POST `/api/v1/sessions/{id}/answers` | 无会话概念 |
| GET `/api/v1/sessions/{id}/results` | 无会话概念 |
| POST `/api/v1/sessions/{id}/plan` | 无会话概念 |
| POST `/api/v1/sessions/{id}/restore` | 无 Orchestrator |
| POST `/api/v1/sessions/{id}/resume` | 无 Orchestrator |
| POST `/api/v1/sessions/{id}/retry` | 无 Orchestrator |
| GET `/api/v1/tokens/stats` | 不再追踪 Token |
| ~~POST `/api/v1/students/{id}/plan/today`~~ | 简化为直接查 study_plans |
| ~~POST `/api/v1/students/{id}/plan/items/{id}/toggle`~~ | 不再需要 |

---

## 第 11 章 · 启动方式

### 11.1 旧方式（v2.0）

```bash
# 终端 1: 后端
cd super-tutor-agent
python -m super_tutor.main --reload

# 终端 2: 前端
cd super-tutor-agent/frontend
npm run dev
```

### 11.2 新方式（v3.0）

```bash
# 单命令启动
cd super-tutor-agent
streamlit run app.py
# → http://localhost:8501
```

### 11.3 requirements.txt 变化

```diff
- fastapi>=0.115.0
- uvicorn[standard]>=0.30.0
+ streamlit>=1.35
  openai>=1.0.0
  aiosqlite>=0.20.0
- sqlite-vec>=0.1.0
  pymupdf>=1.24.0
  pydantic>=2.0.0
- slowapi>=0.1.9
  pytest>=8.0.0
  pytest-asyncio>=0.24.0
- httpx>=0.27.0
```

> FastAPI + Uvicorn 保留但不作为主要启动方式，仅需 API 扩展时使用。

---

## 第 12 章 · 代码量估算

| 模块 | 行数 | vs 旧架构 |
|------|------|----------|
| `app.py` (Streamlit) | ~500 | 替代 frontend/ (~1,800) |
| `super_tutor/engine/` (5 文件) | ~1,000 | 替代 orchestrator (~2,200) |
| `super_tutor/core/` (3 文件) | ~350 | 精简自 ~650 |
| `super_tutor/models/` (4 文件) | ~400 | 精简自 ~1,200 |
| `super_tutor/routes/` (3 文件) | ~300 | 精简自 ~1,000 |
| `super_tutor/prompts/` (5 文件) | ~200 | 大致持平 |
| `super_tutor/config.py` | ~50 | 精简自 ~100 |
| `super_tutor/main.py` | ~80 | 精简自 ~220 |
| `tests/` | ~400 | 大致持平 |
| **总计** | **~3,280** | **vs ~10,000，精简约 67%** |

---

## 附录 A · 旧架构残留检查清单

实现时逐项确认：

- [ ] `super_tutor/core/` 下 6 个文件已删除
- [ ] `super_tutor/routes/` 下 2 个文件已删除（dependencies.py, tokens.py）
- [ ] `super_tutor/prompts/` 下 3 个文件已替换为 5 个新文件
- [ ] `super_tutor/models/` 中 `enums.py` 已精简
- [ ] `super_tutor/models/` 中 `mastery.py` 内容已合并到 `knowledge.py`
- [ ] `frontend/` 目录已删除
- [ ] `requirements.txt` 已更新
- [ ] `super_tutor/main.py` 中无 Orchestrator/RoleManager/TokenTracker/limiter 引用
- [ ] `tests/conftest.py` 中无 Orchestrator/FakeLLMClient fixture
- [ ] 所有 `from super_tutor.core.orchestrator import ...` 引用已清除
- [ ] 所有 `from super_tutor.core.role_manager import ...` 引用已清除
- [ ] 所有 `from super_tutor.core.token_tracker import ...` 引用已清除
