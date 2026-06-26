# 超级私教 v3.0 — 实施计划

**文档编号：** STA-PLAN-2026-001
**版本：** v1.0
**日期：** 2026-06-24
**预计工期：** 8 个工作日

---

## 1. 目标

将现有 v0.3.0 代码重构为 v3.0：

- 前端 React → **Streamlit**
- 去掉 Orchestrator 状态机（~2,200 行）
- 去掉三 AI 角色系统
- 数据库 14 表 → **6 表**，知识点为核心实体
- 新增：课程类型选择、前后知识点联动、错题本苏格拉底追问

**一句话：** 一个 `streamlit run` 就能启动，页面按钮驱动完整学习闭环。

---

## 2. 分阶段计划

### P0 基础设施搭建（第 1-2 天）

> **目标：** `streamlit run app.py` 能看到导航骨架，数据库就绪。

#### 2.1 更新依赖

**文件：** `requirements.txt`

```diff
- slowapi>=0.1.9
- sqlite-vec>=0.1.0
- httpx>=0.27.0
+ streamlit>=1.35
```

保留：`fastapi`、`uvicorn`、`openai`、`aiosqlite`、`pymupdf`、`pydantic`、`pytest`、`pytest-asyncio`

#### 2.2 精简配置

**文件：** `super_tutor/config.py`

去掉以下配置项：`token_budget`、`model_heavy`、`model_medium`、`model_light`、`prompt_versions`。保留核心 6 项：

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

#### 2.3 精简枚举

**文件：** `super_tutor/models/enums.py`

| 处置 | 枚举 |
|:---:|------|
| 删除 | `AIRole`、`PipelinePhase`/`WorkflowState`、`QuizStatus`、`MasteryState`、`MisconceptionCategory` |
| 保留 | `DifficultyLevel`、`QuestionType`（7 种题型完整保留） |
| 新增 | `CourseType`（COMPUTER_SCIENCE / MATH / PHYSICS / CHEMISTRY / ENGLISH / CUSTOM） |

#### 2.4 重写数据库

**文件：** `super_tutor/core/database.py`

14 表 → 6 表。去掉 sqlite-vec 向量逻辑、embedding 相关代码。

| 表名 | 说明 |
|------|------|
| `materials` | 学习材料（+`course_type`，-`subject`/`description`） |
| `knowledge_points` | 知识点（替代 `knowledge_chunks`，+`prerequisite_ids`/`successor_ids`/`mastery_level`） |
| `questions` | 题库（+`kp_id`/`kp_context`，-`session_id`/`chunk_ids`/`knowledge_node_ids`） |
| `quiz_attempts` | 作答记录（+`kp_id`） |
| `wrong_questions` | 错题本（新表） |
| `study_plans` | 学习计划（+`kp_sequence`，合并 `review_items`） |

删除表：`sessions`、`mastery_records`、`review_items`、`socratic_hints`、`projects`、`artifacts`、`task_log`、`token_usage`、`git_commits`

#### 2.5 精简 LLM 客户端

**文件：** `super_tutor/core/llm_client.py`

去掉 `token_tracker` 参数和 `TokenTracker.consume()` / `TokenTracker.log()` 调用。保持接口：

```python
class LLMClient:
    def __init__(self, config: TutorConfig): ...
    async def chat(self, messages, temperature=0.7, max_tokens=4096, timeout=120) -> str: ...
```

#### 2.6 精简异常

**文件：** `super_tutor/core/exceptions.py`

删除 `SessionError`、`SessionNotFoundError`、`PhaseConflictError`、`MaxRetriesExceededError`。保留：`ConfigError`、`LLMError` 及子类、`DatabaseError`、`MaterialError` 及子类。

#### 2.7 创建 Streamlit 入口骨架

**文件：** `app.py`（新建）

```python
import streamlit as st

st.set_page_config(page_title="超级私教", page_icon="🎓", layout="wide")

with st.sidebar:
    st.title("🎓 超级私教")
    course_type = st.selectbox("课程类型", ["计算机科学", "数学", "物理", "化学", "英语", "自定义"])
    st.divider()
    page = st.radio("导航", ["📚 上传资料", "📝 诊断评估", "📋 学习计划", "✏️ 练习答题", "📕 错题本"])

# 页面占位，逐个实现
if page == "📚 上传资料":
    st.header("📚 上传学习资料")
    st.info("即将实现...")
elif page == "📝 诊断评估":
    st.header("📝 诊断评估")
    st.info("即将实现...")
# ...
```

**里程碑：** `streamlit run app.py` → 浏览器打开 `localhost:8501`，侧边栏可切换 5 个页面。

---

### P1 核心学习闭环（第 3-5 天）

> **目标：** 端到端可用 — 上传 PDF → 自动出题 → 答题判题 → 错题入库。

#### 2.8 新增 KnowledgeEngine

**文件：** `super_tutor/engine/knowledge_engine.py`（新建）

```
class KnowledgeEngine
├── parse(content, course_type, material_id) → list[KnowledgePoint]
│   ├── 调 LLM 拆分知识点（title/summary/keywords/difficulty）
│   ├── 识别 prerequisite/successor 关系
│   ├── 批量写入 knowledge_points 表
│   └── 双向更新 prerequisite_ids/successor_ids
├── get_by_material(material_id) → list[KnowledgePoint]
├── get_prerequisites(kp_id) → list[KnowledgePoint]
├── get_successors(kp_id) → list[KnowledgePoint]
└── update_mastery(kp_id, score) → None
```

**Prompt 文件：** `super_tutor/prompts/parse_knowledge.md`（新建）

#### 2.9 实现上传页

**文件：** `app.py`（上传页部分）

- `st.file_uploader("上传 PDF", type=["pdf"])` — PDF 模式
- `st.text_area("或粘贴文本")` — 文本模式
- 点击"开始解析" → `st.spinner("AI 正在提取知识点…")` → 调用 `KnowledgeEngine.parse()`
- 结果展示：`st.dataframe()` 表格（标题/难度/前驱/后继）
- "确认，开始诊断评估 →" 按钮（先放占位，P2 接通）

#### 2.10 修改 knowledge 模型

**文件：** `super_tutor/models/knowledge.py`

现有 `KnowledgeChunk` 保留不动，新增 `KnowledgePoint`：

```python
class KnowledgePoint(BaseModel):
    kp_id: str
    material_id: str
    title: str
    summary: str = ""
    content: str
    keywords: list[str] = []
    difficulty: DifficultyLevel = DifficultyLevel.MEDIUM
    course_type: str = ""
    chapter_index: int = 0
    prerequisite_ids: list[str] = []   # 前驱 KP ID
    successor_ids: list[str] = []      # 后继 KP ID
    mastery_level: float = 0.0
    assessment_count: int = 0
    created_at: str
    updated_at: str
```

`KnowledgeNode`/`KnowledgeEdge`/`KnowledgeGraph` 保留（拓扑排序可复用 `KnowledgeGraph.topological_order()`）。

#### 2.11 新增 QuizEngine

**文件：** `super_tutor/engine/quiz_engine.py`（新建）

```
class QuizEngine
├── generate_questions(kp_ids, count, difficulty, types) → list[Question]
│   └── 逐个 KP 出题，注入前驱知识点摘要
├── grade_answers(questions, student_answers) → list[QuizAttempt]
│   └── 选择题/判断题 → 程序比对；填空/简答/论述 → LLM 判；匹配 → 逐对比对+LLM复核
└── add_to_wrong_book(attempt) → WrongQuestion
    └── 错题写入 wrong_questions 表，更新 wrong_count
```

**Prompt 文件：** `super_tutor/prompts/quiz_gen.md`、`super_tutor/prompts/grade.md`（新建）

#### 2.12 修改 quiz 模型

**文件：** `super_tutor/models/quiz.py`

`Question` 增加 `kp_id`（直接关联知识点）、`kp_context`（出题时注入的上下文 JSON）。删除 `session_id`、`chunk_ids`、`knowledge_node_ids`。

新增 `WrongQuestion`：

```python
class WrongQuestion(BaseModel):
    wq_id: str
    student_id: str = "default"
    question_id: str
    kp_id: str
    attempt_id: str
    wrong_count: int = 1
    is_reviewed: bool = False
    last_wrong_at: str
    created_at: str
```

`QuizAttempt` 增加 `kp_id`，去掉 `session_id`/`score`/`hints_used`/`attempt_number`/`confidence`/`misconception_ids`/`note`。

#### 2.13 实现答题页

**文件：** `app.py`（练习答题页部分）

- 知识点选择器（`st.multiselect` 选 KP）
- 题数/题型/难度选项
- "生成题目" → spinner → 题目列表渲染

**6 种题型前端渲染：**

| 题型 | Streamlit 组件 |
|------|---------------|
| 选择题 | `st.radio(f"Q{i}. {stem}", options, format_func=...)` |
| 判断题 | `st.radio(f"Q{i}. {stem}", ["对", "错"], horizontal=True)` |
| 填空题 | `st.text_input(f"Q{i}. {stem}")` |
| 简答题 | `st.text_area(f"Q{i}. {stem}", height=100)` |
| 论述题 | `st.text_area(f"Q{i}. {stem}", height=200)` |
| 编程题 | `st.text_area(f"Q{i}. {stem}", height=150)` |

- "提交" → 调 `QuizEngine.grade_answers()` → 显示对错/解析
- 错题自动入库

#### 2.14 实现错题本页

**文件：** `app.py`（错题本页部分）

- 筛选：`st.selectbox("知识点", [...])` + `st.selectbox("时间", ["全部", "最近7天", "最近30天"])`
- 按知识点 `st.expander(f"📌 {kp_title} ({n} 道错题)")` 分组
- 每道错题显示：题干、用户答案 ❌、正确答案 ✅、解析、犯错次数
- `st.button("🔄 重新作答")` — 回到答题页同题重做
- `st.button("🗨 苏格拉底追问")` — 占位（P3 接通）

#### 2.15 精简路由

**保留并修改：**

| 文件 | 动作 |
|------|------|
| `super_tutor/routes/materials.py` | 去 Orchestrator 依赖 |
| `super_tutor/routes/quizzes.py` | 重写：直接调 `QuizEngine` |
| `super_tutor/routes/dashboard.py` | 简化：从 `knowledge_points` / `wrong_questions` 读 |
| `super_tutor/routes/schemas.py` | 精简 DTO |

**删除：**
- `super_tutor/routes/dependencies.py`（OrchestratorRegistry 等不再需要）
- `super_tutor/routes/tokens.py`（Token 统计不再需要）

**里程碑：** 端到端：上传 PDF → 提取知识点 → 出 6 种题型 → 答题 → 判题 → 错题入库。

---

### P2 诊断评估 + 学习计划（第 6-7 天）

> **目标：** 评估报告 + 个性化学习路径可用。

#### 2.16 新增 AssessmentEngine

**文件：** `super_tutor/engine/assessment_engine.py`（新建）

```
class AssessmentEngine
├── generate(kp_ids, question_count=15) → list[Question]
│   └── 每个 KP 至少 1 题，从前驱到后继递进
├── grade(questions, answers) → AssessmentReport
│   ├── 逐题判题
│   ├── 计算每个 KP 的 mastery_level 初值
│   └── 调用 apply_prerequisite_rules()
└── apply_prerequisite_rules(report) → None
    ├── 规则 1: 前驱未掌握(≤0.5) → 后继置信度 ×0.7
    ├── 规则 2: 后继对 but 前驱错 → 标记 NeedReview
    └── 规则 3: 连续 ≥3 后继错 → 前驱标记 NeedRelearn
```

**Prompt 文件：** `super_tutor/prompts/assessment.md`（新建）

#### 2.17 实现诊断评估页

**文件：** `app.py`（诊断评估页部分）

- "开始诊断" → 调 `AssessmentEngine.generate()` → 全 KP 覆盖测验
- 逐题渲染（同答题页布局）
- "提交评估" → 调 `AssessmentEngine.grade()` → 评估报告

**评估报告展示：**
- 📊 总体正确率 + 正确数/总题数
- ⚠️ 薄弱知识点列表（红色标签）
- ⭐ 强项列表（绿色标签）
- 📋 建议学习顺序（拓扑排序后的 KP 列表）
- "生成学习计划 →" 按钮

#### 2.18 新增 PlanEngine

**文件：** `super_tutor/engine/plan_engine.py`（新建）

```
class PlanEngine
├── generate(kp_ids, mastery_map) → StudyPlan
│   ├── 1. Kahn 拓扑排序（可复用 KnowledgeGraph.topological_order）
│   ├── 2. 优先级排序: (1 - mastery) × (1 + successor_count / total)
│   └── 3. 输出 kp_sequence → 写入 study_plans
└── topological_sort(kps) → list[str]
```

#### 2.19 修改 plan 模型

**文件：** `super_tutor/models/plan.py`

`StudyPlan` 增加 `kp_sequence: list[str]`（拓扑排序后的 KP ID 序列）。去掉 `description`/`subject`/`goal`/`start_date`/`end_date`/`metadata`。

#### 2.20 实现学习计划页

**文件：** `app.py`（学习计划页部分）

- 展示拓扑排序后的知识点学习路径
- 每个知识点显示：序号、标题、掌握度进度条、难度标签
- 掌握度 < 0.5 红色高亮（优先学习）
- "开始学习此知识点 →" 按钮 → 跳转答题页针对该 KP 出题

**里程碑：** 诊断报告 + 个性化学习路径可用。

---

### P3 苏格拉底追问 + 清理（第 8 天）

> **目标：** 全部功能就绪，旧代码清理完毕。

#### 2.21 新增 SocraticEngine

**文件：** `super_tutor/engine/socratic_engine.py`（新建）

```
class SocraticEngine
├── start_dialogue(kp_id, wrong_question_id) → SocraticTurn
│   └── 生成 L1 笼统引导问题
└── continue_dialogue(history, user_response) → SocraticTurn
    ├── 判断理解程度 → 升级(L1→L2→L3) / 降级 / 结束
    └── 用户说"显示答案" → 直接给出完整解析
```

苏格拉底状态（仅存在 `st.session_state`，不存 DB）：

```
L1_GUIDING → L2_HINTING → L3_NEAR_ANSWER → RESOLVED
     ↓            ↓              ↓
     └────────────┴──────────────┴──→ SHOW_ANSWER
```

**Prompt 文件：** `super_tutor/prompts/socratic.md`（新建）

#### 2.22 错题本接入苏格拉底追问

**文件：** `app.py`（错题本页补充）

- 每个错题组的 `st.expander` 内新增"🗨 苏格拉底追问"区域
- 点击后展开对话 UI：
  - 系统消息（L1/L2/L3）+ `st.chat_message("assistant")`
  - 用户输入 `st.chat_input("你的回答…")`
  - 逐轮递进
  - `st.button("我知道了 ✅")` / `st.button("显示答案")` 退出

#### 2.23 重写 Prompt 模板

**文件：** `super_tutor/prompts/`（全部替换）

| 旧文件（删除） | 新文件 | 用途 |
|--------------|--------|------|
| `tutor.md` | `parse_knowledge.md` | 知识点解析 |
| （无） | `assessment.md` | 诊断评估出题 |
| `assistant.md` | `quiz_gen.md` | 练习出题 |
| （无） | `grade.md` | 判题 |
| `evaluator.md` | `socratic.md` | 苏格拉底追问 |

每个新 Prompt 格式：`# System` + 模板变量 `{variable}`。

#### 2.24 删除旧前端

```bash
rm -rf frontend/
```

包含：`package.json`、`vite.config.ts`、`tailwind.config.js`、`tsconfig.json`、`postcss.config.js`、`index.html`、`src/`（13 个 .tsx/.ts 文件）、`dist/`、`node_modules/`

#### 2.25 删除状态机

```bash
rm super_tutor/core/orchestrator.py
rm super_tutor/core/orchestrator_phases.py
rm super_tutor/core/orchestrator_prompts.py
rm super_tutor/core/orchestrator_utils.py
rm super_tutor/core/role_manager.py
rm super_tutor/core/token_tracker.py
rm super_tutor/core/limiter.py
rm super_tutor/core/cli_backend.py
```

#### 2.26 删除旧路由和 Prompt

```bash
rm super_tutor/routes/dependencies.py
rm super_tutor/routes/tokens.py
```

#### 2.27 更新 main.py

**文件：** `super_tutor/main.py`

- `lifespan` 中去掉：`TutorConfig` 复杂加载、`RoleManager`、`TokenTracker`、`OrchestratorRegistry`、`limiter`
- 保留：`Database` 初始化、`LLMClient` 初始化、CORS、异常处理器、健康检查
- `app.state` 只暴露 `db` 和 `llm_client`

#### 2.28 更新测试

| 文件 | 动作 |
|------|------|
| `tests/conftest.py` | 去 `FakeLLMClient`、`Orchestrator` fixture |
| `tests/test_materials.py` | 适配简化路由 |
| `tests/test_quizzes.py` | 适配 QuizEngine |
| `tests/test_dashboard.py` | 适配简化查询 |
| `tests/test_tokens.py` | 删除 |
| `tests/test_knowledge_engine.py` | **新增** |
| `tests/test_quiz_engine.py` | **新增** |

---

## 3. 阶段总览

```
Day 1-2   P0  ████████████  基础设施搭建 (7 项)
          ├── 依赖、配置、枚举、数据库、LLM、异常、app.py 骨架
          └── ✅ streamlit run app.py 可启动
          
Day 3-5   P1  ████████████  核心闭环 (8 项)
          ├── KnowledgeEngine、上传页、知识模型
          ├── QuizEngine、quiz模型、答题页、错题本页
          └── ✅ 上传→解析→出题→判题→错题 全链路

Day 6-7   P2  ████████████  评估+计划 (5 项)
          ├── AssessmentEngine、诊断页
          ├── PlanEngine、plan模型、计划页
          └── ✅ 评估报告 + 学习路径

Day 8     P3  ████████████  追问+清理 (8 项)
          ├── SocraticEngine、追问UI
          ├── 删除 frontend/ + orchestrator + 旧路由 + 旧Prompt
          └── ✅ 全部功能 + 测试通过
```

| 阶段 | 项数 | 工期 | 累计 |
|:---:|:---:|:---:|:---:|
| P0 | 7 | 2 天 | 项目可启动 |
| P1 | 8 | 3 天 | 核心闭环可用 |
| P2 | 5 | 2 天 | 评估+计划可用 |
| P3 | 8 | 1 天 | 全部就绪 |
| **合计** | **28** | **8 天** | |

---

## 4. 文件变更汇总

| 类别 | 数量 | 文件 |
|:---:|:---:|------|
| 新建 | 11 | `app.py`、`engine/` (6 文件)、`prompts/` (5 文件) |
| 修改 | 12 | `config.py`、`database.py`、`llm_client.py`、`exceptions.py`、`main.py`、`enums.py`、`knowledge.py`、`quiz.py`、`plan.py`、`materials.py`、`quizzes.py`、`dashboard.py` |
| 删除 | 22+ | `frontend/` (整目录)、`orchestrator*.py` (4 文件)、`role_manager.py`、`token_tracker.py`、`limiter.py`、`cli_backend.py`、`dependencies.py`、`tokens.py`、`tutor.md`、`assistant.md`、`evaluator.md`、`test_tokens.py` |
