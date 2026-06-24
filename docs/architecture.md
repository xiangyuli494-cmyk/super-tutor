# 超级私教 (Super Tutor) — 技术架构文档

**文档编号：** STA-ARCH-2026-002
**版本：** v2.0
**状态：** 与代码同步（v0.3.0）
**密级：** 内部

---

## 文档说明

本文档是 Super Tutor 系统的**唯一技术真相源**。当代码与本文档冲突时，以代码为准并更新本文档。

**与 v1.x 的区别：** v2.0 从概要级重写为**逐文件逐函数**级别，涵盖所有模块的完整接口、数据流、错误路径和前端渲染决策。

**配套文档：**
- 产品需求 → [requirements.md](requirements.md)
- 历史引用 → [PRD.md](PRD.md)（不再维护）

---

## 第 1 章 · 系统总览

### 1.1 一句话架构

> React SPA（5 页）→ HTTP REST → FastAPI（4 路由组）→ Orchestrator 状态机 → 3 个 AI 角色 → DeepSeek API。数据存 SQLite（14 表），向量检索用 sqlite-vec。

### 1.2 技术栈（精确版本）

| 层 | 技术 | 版本 | 文件/配置 |
|---|------|------|----------|
| **后端框架** | FastAPI | ≥0.115 | `super_tutor/main.py` |
| **ASGI** | Uvicorn | ≥0.30 | CLI: `uvicorn.run()` |
| **LLM SDK** | OpenAI (兼容) | ≥1.0 | `super_tutor/core/llm_client.py` |
| **数据库** | SQLite + aiosqlite | ≥0.20 | `super_tutor/core/database.py` |
| **向量扩展** | sqlite-vec | ≥0.1 | 同上文件，`vec0` 虚拟表 |
| **PDF 解析** | PyMuPDF | ≥1.24 | `routes/materials.py` |
| **校验** | Pydantic | ≥2.0 | `super_tutor/models/` |
| **限流** | slowapi | — | `main.py` 中挂载 |
| **前端框架** | React | 18.x | `frontend/package.json` |
| **构建** | Vite | 5.x | `frontend/vite.config.ts` |
| **样式** | Tailwind CSS | 3.x | `frontend/tailwind.config.js` |
| **状态** | Zustand | 4.x | `frontend/src/store/` |
| **路由** | react-router-dom | 6.x | `frontend/src/App.tsx` |
| **测试** | pytest + pytest-asyncio | ≥8.0 | `tests/` |

### 1.3 部署拓扑

```
用户的浏览器  (http://localhost:5173)
       │  Vite dev server 代理 /api/* → 127.0.0.1:8765
       │
       ▼
┌─────────────────────────────────────────────────┐
│  FastAPI  (127.0.0.1:8765)                      │
│  ┌───────────────────────────────────────────┐  │
│  │  lifespan: init_app_state()               │  │
│  │  ├─ TutorConfig     (settings.json + env) │  │
│  │  ├─ Database        (SQLite .db 文件)      │  │
│  │  ├─ LLMClient       (DeepSeek API)        │  │
│  │  ├─ RoleManager     (prompts/*.md)        │  │
│  │  ├─ TokenTracker    (预算: 1,000,000)      │  │
│  │  └─ OrchestratorRegistry (内存 dict)       │  │
│  └───────────────────────────────────────────┘  │
│                      │                          │
│  4 个 APIRouter:                                │
│  ├─ /api/v1/materials/*   (资料上传)            │
│  ├─ /api/v1/sessions/*    (测验会话)            │
│  ├─ /api/v1/students/*    (仪表盘)              │
│  └─ /api/v1/tokens/*      (用量统计)            │
└──────────────────┬──────────────────────────────┘
                   │ HTTPS
                   ▼
          ┌─────────────────┐
          │  DeepSeek API   │
          │  (外部服务)      │
          └─────────────────┘
```

### 1.4 三 AI 角色协作模型

```
                      ┌──────────────┐
                      │  Orchestrator │
                      │  状态机引擎   │
                      └───┬────┬──┬──┘
            ┌─────────────┘    │  └──────────────┐
            ▼                  ▼                  ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  Tutor (导师) │  │Assistant(助教)│  │Evaluator(评估)│
    │  解析+规划    │  │    出题       │  │  批改+诊断    │
    └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
           │                 │                  │
    ┌──────▼─────────────────▼──────────────────▼──────┐
    │              共享基础设施                          │
    │  Database │ LLMClient │ RoleManager │ TokenTracker │
    └──────────────────────────────────────────────────┘
```

| 角色 | RoleManager Key | Prompt 文件 | LLM 档位 | 负责阶段 |
|------|----------------|-------------|---------|---------|
| Tutor | `tutor` | `prompts/tutor.md` | heavy | PARSING |
| Assistant | `assistant` | `prompts/assistant.md` | heavy | QUIZ_GEN |
| Evaluator | `evaluator` | `prompts/evaluator.md` | medium | EVALUATING |
| Tutor | `tutor` | `prompts/tutor.md` | medium | PLANNING |

---

## 第 2 章 · 项目文件清单（完整）

### 2.1 后端 Python（`super_tutor/`）

```
super_tutor/
├── __init__.py                     # __version__ = "0.3.0"
├── main.py                         # FastAPI 应用工厂 + lifespan + 启动 CLI
├── config.py                       # TutorConfig: 单例配置管理器
│
├── core/                           # 核心引擎（~3,500 行）
│   ├── exceptions.py               # TutorError 基类 + 子类异常体系
│   ├── database.py                 # Database: SQLite + sqlite-vec (14 表)
│   ├── llm_client.py               # LLMClient: DeepSeek API + CLI 回退
│   ├── role_manager.py             # RoleManager: 角色 Prompt 加载与管理
│   ├── token_tracker.py            # TokenTracker: 预算管控 + 用量统计
│   ├── orchestrator.py             # Orchestrator: 状态机主类 (~900 行)
│   ├── orchestrator_phases.py      # _PhaseHandlers: 四阶段 Mixin (~760 行)
│   ├── orchestrator_prompts.py     # 各阶段 LLM Prompt 构建函数 (~280 行)
│   ├── orchestrator_utils.py       # JSON 解析/模型水合/图谱构建 (~260 行)
│   └── cli_backend.py              # Claude CLI 回退后端
│
├── models/                         # Pydantic 数据模型（9 文件）
│   ├── enums.py                    # 7 个枚举类型
│   ├── knowledge.py                # KnowledgeChunk, KnowledgeNode, KnowledgeEdge, KnowledgeGraph
│   ├── material.py                 # Material
│   ├── quiz.py                     # Question, QuizSession, QuizAttempt, MisconceptionTag, SocraticHint
│   ├── plan.py                     # StudyPlan, ReviewItem
│   ├── student.py                  # StudentProfile
│   ├── mastery.py                  # MasteryRecord
│   └── (other model files)
│
├── routes/                         # FastAPI 路由层（6 文件）
│   ├── dependencies.py             # 依赖注入: use_db, use_llm_client, etc.
│   ├── schemas.py                  # HTTP DTO: 请求/响应 Pydantic 模型
│   ├── materials.py                # /api/v1/materials/*
│   ├── quizzes.py                  # /api/v1/sessions/*
│   ├── dashboard.py                # /api/v1/students/*
│   └── tokens.py                   # /api/v1/tokens/*
│
└── prompts/                        # AI 角色系统提示词（Markdown）
    ├── tutor.md                    # Tutor: PDF 解析专家
    ├── assistant.md                # Assistant: 出题专家（含 6 题型示例）
    └── evaluator.md                # Evaluator: 批改诊断专家
```

### 2.2 前端 TypeScript（`frontend/src/`）

```
frontend/
├── index.html                      # SPA 入口: <div id="root">
├── vite.config.ts                  # Vite 配置: 代理 /api → 127.0.0.1:8765
├── tailwind.config.js              # Tailwind CSS 配置
├── tsconfig.json                   # TypeScript 配置
│
└── src/
    ├── main.tsx                    # ReactDOM.createRoot + BrowserRouter
    ├── App.tsx                     # 路由定义: 5 个 Route
    ├── index.css                   # Tailwind 指令
    │
    ├── api/
    │   ├── types.ts                # TypeScript 接口 (APIResponse, 所有 DTO)
    │   └── client.ts               # API 客户端: request<T>() + ApiError
    │
    ├── store/
    │   ├── quizStore.ts            # 测验状态: phase/quizStatus/questions/answers/results
    │   └── studentStore.ts         # 学生状态: dashboard/mastery/todayPlan
    │
    ├── pages/
    │   ├── Dashboard.tsx           # / — 学习仪表盘
    │   ├── MaterialsPage.tsx       # /materials — 上传材料
    │   ├── QuizPage.tsx            # /quiz/:sessionId — 答题（阶段驱动渲染）
    │   ├── ResultsPage.tsx         # /quiz/:sessionId/results — 批改结果
    │   └── PlanPage.tsx            # /plan — 今日复习计划
    │
    └── components/
        ├── Layout.tsx              # 应用外壳: Navbar + main + footer
        ├── Navbar.tsx              # 顶部导航: 仪表盘/材料/今日计划
        ├── FileUpload.tsx          # 双模式上传: 文本 + PDF
        ├── QuizCard.tsx            # 题目卡片: 选择题/简答题渲染
        ├── ResultCard.tsx          # 批改结果卡片: 对/错 + 解析
        └── MasteryChart.tsx        # 掌握度柱状图
```

### 2.3 测试（`tests/`）

```
tests/
├── conftest.py                     # Fixtures: FakeLLMClient, TestDatabase, etc.
├── test_materials.py               # 资料上传测试
├── test_quizzes.py                 # 测验会话测试
├── test_dashboard.py               # 仪表盘测试
└── test_tokens.py                  # Token 统计测试
```

---

## 第 3 章 · 入口与启动流程

### 3.1 后端启动 (`super_tutor/main.py`)

**文件：** [super_tutor/main.py](../super_tutor/main.py)

API 应用通过 `create_app()` 工厂函数创建：

```python
app = FastAPI(
    title="Super Tutor",
    description="多角色智能教学系统...",
    version="0.3.0",
    lifespan=lifespan,       # 启动/关闭钩子
    docs_url="/docs",        # Swagger UI
    redoc_url="/redoc",      # ReDoc
)
```

**Lifespan 启动顺序（`init_app_state()`）：**

```
1. TutorConfig.from_default_path()
   ├─ 读取 ~/.super-tutor/settings.json
   └─ 环境变量覆盖 (TUTOR_API_KEY, TUTOR_API_BASE_URL, TUTOR_TOKEN_BUDGET)

2. Database(db_path)
   └─ await db.initialize()  → 创建 14 张表 + sqlite-vec 扩展

3. LLMClient(config, token_tracker)
   └─ OpenAI 兼容客户端 → DeepSeek API

4. RoleManager(prompts_dir)
   └─ 加载 prompts/{tutor,assistant,evaluator}.md

5. TokenTracker(budget=1_000_000)

6. OrchestratorRegistry()  → 空 dict[str, Orchestrator]
```

以上 6 个对象全部注入 `app.state`，通过 `routes/dependencies.py` 的依赖注入函数供路由使用。

**Shutdown：** `await Database.close()` — 关闭 SQLite 连接。

**命令行启动：**

```bash
python -m super_tutor.main --host 127.0.0.1 --port 8765
# 可选: --reload (开发模式热重载)
# 等价于: uvicorn super_tutor.main:app --host 127.0.0.1 --port 8765
```

### 3.2 前端启动 (`frontend/`)

**Vite 配置：** [frontend/vite.config.ts](../frontend/vite.config.ts)

```typescript
server: {
  port: 5173,
  proxy: {
    "/api": {
      target: "http://127.0.0.1:8765",
      changeOrigin: true,
    },
  },
}
```

**启动命令：**

```bash
cd frontend
npm install        # 首次
npm run dev        # → http://localhost:5173
npm run build      # 生产构建 → dist/
```

**入口文件链：**

```
index.html
  └─ <script type="module" src="/src/main.tsx">
       └─ ReactDOM.createRoot → <BrowserRouter> → <App />
            └─ <Layout> → <Routes> (5 个路由)
```

---

## 第 4 章 · 中间件与横切关注点

**文件：** [super_tutor/main.py](../super_tutor/main.py)

### 4.1 CORS

```python
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)
```

仅允许 localhost/127.0.0.1 来源，匹配任意端口。

### 4.2 速率限制（slowapi）

| 端点 | 限制 |
|------|------|
| `POST /api/v1/materials/upload` | 10 次/分钟 |
| `POST /api/v1/materials/upload/file` | 5 次/分钟 |
| 其他端点 | 默认限制（由 `limiter` 配置） |

限流超限时返回 `RateLimitExceeded` 异常。

### 4.3 全局异常处理器

| 异常类型 | HTTP 状态 | 说明 |
|---------|----------|------|
| `TutorError` | 400 | 业务逻辑错误（自定义异常基类） |
| `ValueError` | 422 | 参数校验失败 |
| `Exception` | 500 | 未分类的内部错误（会记录 traceback） |

### 4.4 健康检查

```
GET /api/v1/health
→ {"status": "ok", "version": "0.3.0", "prompt_versions": {...}}
```

不依赖任何外部服务，始终返回 200。

---

## 第 5 章 · 配置系统

**文件：** [super_tutor/config.py](../super_tutor/config.py)

### 5.1 配置来源与优先级

```
环境变量 (TUTOR_*)  >  settings.json  >  代码默认值
```

### 5.2 配置项清单

| 配置键 | 环境变量 | 默认值 | 说明 |
|--------|---------|--------|------|
| `api_key` | `TUTOR_API_KEY` | `""` | DeepSeek API Key（空值时 LLM 调用返回 503） |
| `api_base_url` | `TUTOR_API_BASE_URL` | `https://api.deepseek.com` | LLM API 地址 |
| `token_budget` | `TUTOR_TOKEN_BUDGET` | `1_000_000` | Token 预算上限 |
| `db_path` | `TUTOR_DB_PATH` | `~/.super-tutor/super_tutor.db` | SQLite 数据库路径 |
| `model_heavy` | — | `deepseek-chat` | 重度 LLM 调用模型 |
| `model_medium` | — | `deepseek-chat` | 中度 LLM 调用模型 |
| `model_light` | — | `deepseek-chat` | 轻度 LLM 调用模型 |
| `max_retries` | — | `3` | LLM 调用最大重试次数 |
| `request_timeout` | — | `120` | 单次 LLM 请求超时（秒） |

### 5.3 配置文件位置

```
~/.super-tutor/
├── settings.json        # 手动编辑
└── super_tutor.db       # SQLite 数据库（自动创建）
```

配置文件 JSON 格式示例：

```json
{
  "api_key": "sk-xxx",
  "api_base_url": "https://api.deepseek.com",
  "token_budget": 1000000,
  "model_heavy": "deepseek-chat",
  "model_medium": "deepseek-chat"
}
```

---

## 第 6 章 · 数据库架构

**文件：** [super_tutor/core/database.py](../super_tutor/core/database.py)

### 6.1 概览

- **引擎：** SQLite 3（通过 aiosqlite 异步访问）
- **向量扩展：** sqlite-vec — `vec_artifacts` 虚拟表用于语义相似度搜索（条件启用）
- **表数量：** 14 张（5 张继承自 Codex CLI 模板，9 张 Super Tutor 专用）
- **连接管理：** 单连接（`aiosqlite.connect()`），所有写操作串行化
- **嵌入维度：** 1536（默认，`Database.embedding_dim`）

### 6.2 表分类

| 分类 | 表名 | 用途 |
|------|------|------|
| 继承（Codex CLI 模板） | `projects` | 项目管理 |
| 继承 | `artifacts` | 产物存储（含 embedding 向量） |
| 继承 | `task_log` | 任务执行日志 |
| 继承 | `token_usage` | Token 用量日志 |
| 继承 | `git_commits` | Git 提交记录 |
| Super Tutor 专用 | `materials` | 学习材料 |
| Super Tutor 专用 | `knowledge_chunks` | 知识片段（含 embedding） |
| Super Tutor 专用 | `questions` | 题库 |
| Super Tutor 专用 | `quiz_attempts` | 作答记录 |
| Super Tutor 专用 | `mastery_records` | 掌握度（认知孪生） |
| Super Tutor 专用 | `study_plans` | 学习计划 |
| Super Tutor 专用 | `review_items` | 复习条目 |
| Super Tutor 专用 | `sessions` | Orchestrator 会话（合并了测验会话） |
| Super Tutor 专用 | `socratic_hints` | 苏格拉底提示 |

> **注意：** 以下内容仅列出 Super Tutor 专用表。继承表与教学业务无直接关联，不在此展开。

### 6.3 Super Tutor 专用表（9 张）

#### 表: `materials` — 学习材料

```sql
CREATE TABLE IF NOT EXISTS materials (
    material_id  TEXT PRIMARY KEY,
    title        TEXT    NOT NULL,
    content      TEXT    NOT NULL DEFAULT '',
    subject      TEXT    NOT NULL DEFAULT '',
    description  TEXT    NOT NULL DEFAULT '',
    status       TEXT    NOT NULL DEFAULT 'draft',
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);
```

| 列 | 类型 | 说明 |
|----|------|------|
| `material_id` | TEXT PK | UUID |
| `title` | TEXT | 材料标题 |
| `content` | TEXT | 材料全文（默认空字符串） |
| `subject` | TEXT | 学科 |
| `description` | TEXT | 简介 |
| `status` | TEXT | draft / processing / ready / error |
| `created_at` | TEXT | ISO 8601 |
| `updated_at` | TEXT | ISO 8601 |

> **注意：** 此表结构与 architecture.md v1.x 的文档不同。实际表中**没有** `source_type`、`total_pages`、`file_path`、`file_hash`、`metadata` 列。PDF 元数据由路由层管理，不在此表中。

#### 表: `knowledge_chunks` — 知识片段

```sql
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id     TEXT PRIMARY KEY,
    material_id  TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    summary      TEXT    NOT NULL DEFAULT '',
    topic        TEXT    NOT NULL DEFAULT '',
    difficulty   TEXT    NOT NULL DEFAULT 'medium',
    keywords     TEXT    NOT NULL DEFAULT '[]',
    page_start   INTEGER,
    page_end     INTEGER,
    embedding    BLOB,
    metadata     TEXT    NOT NULL DEFAULT '{}',
    created_at   TEXT    NOT NULL
);
```

| 列 | 类型 | 说明 |
|----|------|------|
| `chunk_id` | TEXT PK | UUID |
| `material_id` | TEXT | 关联材料（无 FK 约束） |
| `content` | TEXT | 原文片段 |
| `summary` | TEXT | 摘要（用于向量化检索） |
| `topic` | TEXT | 主题标签 |
| `difficulty` | TEXT | beginner/easy/medium/hard/expert |
| `keywords` | TEXT | JSON 数组字符串 |
| `page_start` | INTEGER | 起始页码 |
| `page_end` | INTEGER | 结束页码 |
| `embedding` | BLOB | 向量嵌入（二进制） |
| `metadata` | TEXT | JSON 扩展 |
| `created_at` | TEXT | ISO 8601 |

索引：`material_id`、`topic`、`difficulty`

#### 表: `questions` — 题库

```sql
CREATE TABLE IF NOT EXISTS questions (
    question_id        TEXT PRIMARY KEY,
    session_id         TEXT,
    type               TEXT    NOT NULL,
    difficulty         TEXT    NOT NULL DEFAULT 'medium',
    subject            TEXT    NOT NULL DEFAULT '',
    topic              TEXT    NOT NULL DEFAULT '',
    stem               TEXT    NOT NULL,
    options            TEXT    NOT NULL DEFAULT '[]',
    correct_answer     TEXT    NOT NULL,
    explanation        TEXT    NOT NULL DEFAULT '',
    chunk_ids          TEXT    NOT NULL DEFAULT '[]',
    knowledge_node_ids TEXT    NOT NULL DEFAULT '[]',
    estimated_seconds  INTEGER NOT NULL DEFAULT 120,
    points             REAL    NOT NULL DEFAULT 1.0,
    tags               TEXT    NOT NULL DEFAULT '[]',
    metadata           TEXT    NOT NULL DEFAULT '{}',
    created_at         TEXT    NOT NULL
);
```

| 列 | 类型 | 说明 |
|----|------|------|
| `question_id` | TEXT PK | UUID |
| `session_id` | TEXT | 所属会话（无 FK 约束） |
| `type` | TEXT | 7 种题型之一 |
| `difficulty` | TEXT | 难度等级 |
| `subject` | TEXT | 学科 |
| `topic` | TEXT | 主题标签 |
| `stem` | TEXT | 题干（Markdown） |
| `options` | TEXT | JSON 数组字符串 |
| `correct_answer` | TEXT | JSON 字符串（格式因题型而异） |
| `explanation` | TEXT | 详细解析 |
| `chunk_ids` | TEXT | JSON 数组 |
| `knowledge_node_ids` | TEXT | JSON 数组 |
| `estimated_seconds` | INTEGER | 预计耗时（默认 120） |
| `points` | REAL | 分值（默认 1.0） |
| `tags` | TEXT | JSON 数组 |
| `metadata` | TEXT | JSON 扩展 |
| `created_at` | TEXT | ISO 8601 |

索引：`session_id`、`topic`、`difficulty`、`type`

> **设计要点：** `correct_answer` 不直接返回给前端。路由层在 `GET /questions` 中剔除该字段和 `explanation` 字段，生成 `QuestionResponse`。

#### 表: `quiz_attempts` — 作答记录

```sql
CREATE TABLE IF NOT EXISTS quiz_attempts (
    attempt_id        TEXT PRIMARY KEY,
    session_id        TEXT    NOT NULL,
    student_id        TEXT    NOT NULL DEFAULT '',
    question_id       TEXT    NOT NULL,
    student_answer    TEXT,
    is_correct        INTEGER,
    score             REAL,
    time_spent_seconds INTEGER NOT NULL DEFAULT 0,
    hints_used        INTEGER NOT NULL DEFAULT 0,
    attempt_number    INTEGER NOT NULL DEFAULT 1,
    confidence        REAL,
    misconception_ids TEXT    NOT NULL DEFAULT '[]',
    note              TEXT    NOT NULL DEFAULT '',
    started_at        TEXT    NOT NULL,
    submitted_at      TEXT,
    metadata          TEXT    NOT NULL DEFAULT '{}'
);
```

| 列 | 类型 | 说明 |
|----|------|------|
| `attempt_id` | TEXT PK | UUID |
| `session_id` | TEXT | 所属会话 |
| `student_id` | TEXT | 学生标识（默认空字符串） |
| `question_id` | TEXT | 题目 ID |
| `student_answer` | TEXT | 学生提交的答案（JSON 字符串） |
| `is_correct` | INTEGER | NULL=未批改 / 0=错 / 1=对 |
| `score` | REAL | 得分（NULL=未批改） |
| `time_spent_seconds` | INTEGER | 耗时（默认 0） |
| `hints_used` | INTEGER | 查看提示次数（默认 0） |
| `attempt_number` | INTEGER | 第几次尝试（默认 1） |
| `confidence` | REAL | 自评置信度 0-1（NULL=未自评） |
| `misconception_ids` | TEXT | JSON 数组（诊断出的错误概念 ID） |
| `note` | TEXT | 学生笔记 |
| `started_at` | TEXT | 开始时间（ISO 8601） |
| `submitted_at` | TEXT | 提交时间 |

索引：`session_id`、`student_id`、`question_id`、`is_correct`

#### 表: `mastery_records` — 掌握度记录（认知孪生）

```sql
CREATE TABLE IF NOT EXISTS mastery_records (
    record_id              TEXT PRIMARY KEY,
    student_id             TEXT    NOT NULL,
    knowledge_node_id      TEXT    NOT NULL,
    mastery_level          REAL    NOT NULL DEFAULT 0.0,
    confidence             REAL    NOT NULL DEFAULT 0.5,
    total_attempts         INTEGER NOT NULL DEFAULT 0,
    correct_attempts       INTEGER NOT NULL DEFAULT 0,
    last_attempt_at        TEXT,
    last_score             REAL,
    streak                 INTEGER NOT NULL DEFAULT 0,
    time_spent_total_seconds INTEGER NOT NULL DEFAULT 0,
    hints_used_total       INTEGER NOT NULL DEFAULT 0,
    misconception_ids      TEXT    NOT NULL DEFAULT '[]',
    state                  TEXT    NOT NULL DEFAULT 'new',
    sm2_repetitions        INTEGER NOT NULL DEFAULT 0,
    sm2_ease_factor        REAL    NOT NULL DEFAULT 2.5,
    sm2_interval_days      INTEGER NOT NULL DEFAULT 0,
    sm2_next_review        TEXT,
    sm2_last_quality       INTEGER,
    metadata               TEXT    NOT NULL DEFAULT '{}',
    created_at             TEXT    NOT NULL,
    updated_at             TEXT    NOT NULL
);
```

| 列 | 类型 | 说明 |
|----|------|------|
| `record_id` | TEXT PK | UUID |
| `student_id` | TEXT | 学生标识 |
| `knowledge_node_id` | TEXT | 知识点 ID（无 FK 约束，节点在内存中构建） |
| `mastery_level` | REAL | EMA 平滑后的掌握度 0-1（默认 0.0） |
| `confidence` | REAL | 置信度（默认 0.5） |
| `total_attempts` | INTEGER | 总作答次数 |
| `correct_attempts` | INTEGER | 正确次数 |
| `last_attempt_at` | TEXT | 最近作答时间 |
| `last_score` | REAL | 最近得分 |
| `streak` | INTEGER | 连续正确次数 |
| `time_spent_total_seconds` | INTEGER | 累计耗时 |
| `hints_used_total` | INTEGER | 累计提示使用次数 |
| `misconception_ids` | TEXT | JSON 数组 |
| `state` | TEXT | new / learning / reviewing / mastered / stagnated |
| `sm2_repetitions` | INTEGER | SM-2 成功记忆次数（默认 0） |
| `sm2_ease_factor` | REAL | EF（默认 2.5，下限 1.3） |
| `sm2_interval_days` | INTEGER | 当前复习间隔（默认 0） |
| `sm2_next_review` | TEXT | 下次复习日期 |
| `sm2_last_quality` | INTEGER | 最近作答质量评分 0-5 |
| `metadata` | TEXT | JSON 扩展 |

索引：`student_id`、`knowledge_node_id`

#### 表: `study_plans` — 学习计划

```sql
CREATE TABLE IF NOT EXISTS study_plans (
    plan_id      TEXT PRIMARY KEY,
    student_id   TEXT    NOT NULL,
    title        TEXT    NOT NULL DEFAULT '',
    description  TEXT    NOT NULL DEFAULT '',
    subject      TEXT    NOT NULL DEFAULT '',
    goal         TEXT    NOT NULL DEFAULT '',
    start_date   TEXT    NOT NULL,
    end_date     TEXT,
    status       TEXT    NOT NULL DEFAULT 'active',
    metadata     TEXT    NOT NULL DEFAULT '{}',
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);
```

| 列 | 类型 | 说明 |
|----|------|------|
| `plan_id` | TEXT PK | UUID |
| `student_id` | TEXT | 学生标识 |
| `title` | TEXT | 计划标题 |
| `description` | TEXT | 计划描述 |
| `subject` | TEXT | 学科 |
| `goal` | TEXT | 学习目标 |
| `start_date` | TEXT | 开始日期 |
| `end_date` | TEXT | 结束日期（NULL=无截止） |
| `status` | TEXT | active / completed / paused |

索引：`student_id`

#### 表: `review_items` — 复习条目

```sql
CREATE TABLE IF NOT EXISTS review_items (
    item_id            TEXT PRIMARY KEY,
    plan_id            TEXT    NOT NULL,
    student_id         TEXT    NOT NULL,
    knowledge_node_id  TEXT    NOT NULL,
    mastery_record_id  TEXT,
    scheduled_date     TEXT    NOT NULL,
    activity_type      TEXT    NOT NULL DEFAULT 'review',
    estimated_minutes  INTEGER NOT NULL DEFAULT 15,
    completed          INTEGER NOT NULL DEFAULT 0,
    completed_at       TEXT,
    notes              TEXT    NOT NULL DEFAULT '',
    metadata           TEXT    NOT NULL DEFAULT '{}',
    FOREIGN KEY (plan_id) REFERENCES study_plans(plan_id)
);
```

| 列 | 类型 | 说明 |
|----|------|------|
| `item_id` | TEXT PK | UUID |
| `plan_id` | TEXT FK | → study_plans |
| `student_id` | TEXT | 学生标识 |
| `knowledge_node_id` | TEXT | 知识点 ID |
| `mastery_record_id` | TEXT | 关联掌握度记录 |
| `scheduled_date` | TEXT | 计划复习日期 |
| `activity_type` | TEXT | review / practice / quiz |
| `estimated_minutes` | INTEGER | 预计耗时（默认 15） |
| `completed` | INTEGER | 0=未完成 / 1=已完成 |
| `completed_at` | TEXT | 完成时间 |
| `notes` | TEXT | 备注 |

索引：`plan_id`、`(student_id, scheduled_date)` 联合索引

#### 表: `sessions` — Orchestrator 会话

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL DEFAULT '',
    state             TEXT NOT NULL DEFAULT 'idle',
    previous_state    TEXT NOT NULL DEFAULT 'idle',
    in_progress       INTEGER NOT NULL DEFAULT 0,
    error_message     TEXT,
    step_retry_count  INTEGER NOT NULL DEFAULT 0,
    session_context   TEXT NOT NULL DEFAULT '{}',
    artifacts         TEXT NOT NULL DEFAULT '{}',
    role_statuses     TEXT NOT NULL DEFAULT '{}',
    role_tasks        TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
```

| 列 | 类型 | 说明 |
|----|------|------|
| `session_id` | TEXT PK | UUID |
| `user_id` | TEXT | 用户标识（默认空） |
| `state` | TEXT | 当前 PipelinePhase |
| `previous_state` | TEXT | 上一阶段 |
| `in_progress` | INTEGER | 是否有 LLM 调用进行中 |
| `error_message` | TEXT | 错误信息 |
| `step_retry_count` | INTEGER | 当前步骤重试次数 |
| `session_context` | TEXT | JSON：material_id, question_count, student_id 等 |
| `artifacts` | TEXT | JSON：各阶段 LLM 产出物（chunks, questions, attempts 等） |
| `role_statuses` | TEXT | JSON：各角色状态 |
| `role_tasks` | TEXT | JSON：任务记录 |
| `created_at` | TEXT | ISO 8601 |
| `updated_at` | TEXT | ISO 8601 |

> **设计要点：** 此表合并了 "测验会话" 和 "编排器会话" 的职责。测验元数据（title、quiz_status 等）存储在 `session_context` 和 `artifacts` JSON 字段中，而非独立列。

#### 表: `socratic_hints` — 苏格拉底提示

```sql
CREATE TABLE IF NOT EXISTS socratic_hints (
    hint_id                TEXT PRIMARY KEY,
    question_id            TEXT NOT NULL DEFAULT '',
    misconception_tag_id   TEXT NOT NULL DEFAULT '',
    level                  INTEGER NOT NULL DEFAULT 1,
    content                TEXT NOT NULL DEFAULT '',
    trigger_after_failures INTEGER NOT NULL DEFAULT 0,
    difficulty_adapt       INTEGER NOT NULL DEFAULT 0,
    times_shown            INTEGER NOT NULL DEFAULT 0,
    was_helpful            INTEGER,
    created_at             TEXT NOT NULL
);
```

| 列 | 类型 | 说明 |
|----|------|------|
| `hint_id` | TEXT PK | UUID |
| `question_id` | TEXT | 关联题目（无 FK 约束） |
| `misconception_tag_id` | TEXT | 关联迷思概念标签（无 FK 约束） |
| `level` | INTEGER | 1=笼统引导 / 2=方向提示 / 3=接近答案 |
| `content` | TEXT | 提示正文 |
| `trigger_after_failures` | INTEGER | 累计答错 N 次后触发（0=首次即可见） |
| `difficulty_adapt` | INTEGER | 是否根据掌握度自适应跳过（0/1） |
| `times_shown` | INTEGER | 已展示次数 |
| `was_helpful` | INTEGER | NULL=未评估 / 0=无帮助 / 1=有帮助 |
| `created_at` | TEXT | ISO 8601 |

索引：`question_id`、`misconception_tag_id`

### 6.4 重要说明

- **无独立 knowledge_nodes / knowledge_edges 表：** 知识图谱节点和边在 PARSING 阶段从 chunks 动态构建（`_build_knowledge_graph()`），存储于内存/artifacts，不单独建表。
- **无独立 misconception_tags 表：** 迷思概念作为 JSON 对象嵌入 `quiz_attempts.misconception_ids` 和 `artifacts` JSON 中，而非独立表。`socratic_hints.misconception_tag_id` 引用的是 artifacts 中的 ID。
- **questions 表含 correct_answer：** 路由层 `QuestionResponse` 负责剔除敏感字段，DB 不负责。
- **JSON 字段用 TEXT 存储：** SQLite 无原生 JSON 类型，所有列表/对象以 JSON 字符串存储（`'[]'` / `'{}'`）。

---

## 第 7 章 · 枚举定义全集

**文件：** [super_tutor/models/enums.py](../super_tutor/models/enums.py)

```python
class PipelinePhase(str, Enum):
    IDLE = "idle"              # 空闲
    PARSING = "parsing"        # PDF 解析 + 向量化
    QUIZ_GEN = "quiz_gen"      # 生成测验题目
    EVALUATING = "evaluating"  # 批改 + 迷思概念诊断
    PLANNING = "planning"      # 生成 SM-2 排期计划

class QuizStatus(str, Enum):
    DRAFT = "draft"            # 草稿
    READY = "ready"            # 题目已生成
    IN_PROGRESS = "in_progress"  # 学生答题中
    SUBMITTED = "submitted"    # 已提交
    GRADED = "graded"          # 已批改
    REVIEWED = "reviewed"      # 已复习

class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_IN_BLANK = "fill_in_blank"
    SHORT_ANSWER = "short_answer"
    ESSAY = "essay"
    CODING = "coding"          # 已定义但从未被 prompt 引用
    MATCHING = "matching"

class DifficultyLevel(str, Enum):
    BEGINNER = "beginner"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"

class AIRole(str, Enum):
    TUTOR = "tutor"
    ASSISTANT = "assistant"
    EVALUATOR = "evaluator"

class MasteryState(str, Enum):
    NEW = "new"
    LEARNING = "learning"
    REVIEWING = "reviewing"
    MASTERED = "mastered"
    STAGNATED = "stagnated"

class MisconceptionCategory(str, Enum):
    CONCEPTUAL = "conceptual"       # 概念混淆
    CALCULATION = "calculation"     # 计算错误
    CARELESS = "careless"           # 粗心
    APPLICATION = "application"     # 应用不当
    LOGIC = "logic"                 # 逻辑错误
    NOTATION = "notation"           # 符号书写
    INCOMPLETE = "incomplete"       # 不完整
```

---

## 第 8 章 · 路由层详解

### 8.1 依赖注入体系

**文件：** [super_tutor/routes/dependencies.py](../super_tutor/routes/dependencies.py)

所有路由通过 `Depends()` 获取共享资源：

```python
def use_db(request: Request) -> Database:
    return request.app.state.db

def use_llm_client(request: Request) -> LLMClient:
    return request.app.state.llm_client

def use_role_manager(request: Request) -> RoleManager:
    return request.app.state.role_manager

def use_token_tracker(request: Request) -> TokenTracker:
    return request.app.state.token_tracker

def use_orchestrator_registry(request: Request) -> OrchestratorRegistry:
    return request.app.state.registry
```

`OrchestratorRegistry` 是一个 `dict[str, Orchestrator]`，以 `session_id` 为键。

### 8.2 Materials 路由 (`/api/v1/materials`)

**文件：** [super_tutor/routes/materials.py](../super_tutor/routes/materials.py)

#### POST `/api/v1/materials/upload` — 上传文本材料

```
限流: 10 次/分钟
Content-Type: application/json

Request:
{
  "title": "大学物理·力学篇",       // str, 1-256 字符
  "content": "第一章 质点运动学...", // str, ≥1 字符
  "subject": "物理",               // str, 可选
  "description": "..."             // str, 可选, ≤512 字符
}

Response 200:
{
  "code": 0,
  "message": "success",
  "data": {
    "material_id": "uuid",
    "title": "大学物理·力学篇",
    "status": "draft",             // draft → processing → ready
    "chunk_count": 0,
    "subject": "物理",
    "created_at": "2026-06-24T00:00:00"
  }
}

错误:
  404 - 材料不存在
  400 - 参数校验失败 (TutorError)
  429 - 限流超限
```

#### POST `/api/v1/materials/upload/file` — 上传 PDF 文件

```
限流: 5 次/分钟
Content-Type: multipart/form-data

Form 字段:
  file:   PDF 文件 (≤50MB)
  title:  str
  subject: str (可选)

内部流程:
  1. 保存 PDF 到本地
  2. PyMuPDF 提取文本
  3. 存入 materials 表 (status=draft)
  4. 返回 MaterialStatusResponse

Response 同 upload 端点
```

#### GET `/api/v1/materials/{material_id}/status` — 查询材料状态

```
Response 200:
{
  "code": 0,
  "data": {
    "material_id": "uuid",
    "title": "...",
    "status": "ready",        // draft | processing | ready | error
    "chunk_count": 15,
    "subject": "物理",
    "created_at": "..."
  }
}
```

### 8.3 Quiz Sessions 路由 (`/api/v1/sessions`)

**文件：** [super_tutor/routes/quizzes.py](../super_tutor/routes/quizzes.py)

这是核心路由组，驱动整个测验生命周期。

#### POST `/api/v1/sessions` — 创建测验会话

```json
// Request:
{
  "material_id": "uuid",        // 必填
  "title": "新测验",            // 可选, ≤256 字符
  "question_count": 10,         // 可选, 1-50, 默认 10
  "difficulty": "medium",       // 可选, beginner/easy/medium/hard/expert
  "student_id": "student-1"     // 可选
}

// Response 200:
{
  "code": 0,
  "data": {
    "session_id": "uuid",
    "material_id": "uuid",
    "title": "新测验",
    "state": "idle",            // PipelinePhase
    "quiz_status": "draft",     // QuizStatus
    "question_count": 0         // 尚未生成题目
  }
}
```

**内部流程：**

1. 验证材料存在（`db.get_material()`），不存在 → 404
2. `build_orchestrator()` 创建 Orchestrator 实例
3. `orch.initialize(session_context={"material_id", "session_id", "student_id", "question_count", "difficulty"})`
4. 注册到 `registry[session_id]`
5. `orch.save()` — 持久化初始 IDLE 状态到 DB
6. 返回 SessionResponse

#### GET `/api/v1/sessions/{session_id}/questions` — 获取题目

这是最复杂的端点，有两种路径：

**路径 A：DB 缓存命中**

```
条件: orch.state == QUIZ_GEN 或 EVALUATING 或 PLANNING
      且 DB 中已有该 session 的 questions

行为:
  1. 从 DB 加载 questions
  2. 剔除 correct_answer 和 explanation 字段
  3. quiz_status → "in_progress"
  4. 立即返回题目列表（不调用 LLM）
```

**路径 B：触发流水线生成**

```
条件: orch.state == IDLE 或 PARSING
      或 DB 中无缓存

行为:
  1. orch.start()    → IDLE → PARSING (Tutor 解析 PDF)
  2. orch.proceed()  → PARSING → QUIZ_GEN (Assistant 出题)
  3. 从 orch._artifacts["questions"] 获取题目
  4. 剔除正确答案
  5. quiz_status → "in_progress"
  6. 返回题目列表

耗时: 30-120 秒（两次 LLM 调用）
```

**响应格式：**

```json
{
  "code": 0,
  "data": {
    "session_id": "uuid",
    "state": "quiz_gen",
    "quiz_status": "in_progress",
    "question_count": 10,
    "questions": [
      {
        "question_id": "uuid",
        "stem": "一个质量为 2kg 的物体受到 10N...",
        "type": "multiple_choice",
        "difficulty": "easy",
        "topic": "牛顿第二定律",
        "options": [
          {"key": "A", "text": "5 m/s²"},
          {"key": "B", "text": "20 m/s²"}
        ],
        "hints": ["回忆 F=ma 公式", "代入数值计算"],
        "points": 2.0,
        "estimated_seconds": 120
      }
    ]
  }
}
```

> **安全注意：** `correct_answer` 和 `explanation` 在此端点被**显式剔除**。前端无法获取答案。

#### POST `/api/v1/sessions/{session_id}/answers` — 提交作答

```json
// Request:
{
  "answers": [
    {
      "question_id": "uuid",
      "student_answer": "A",          // any
      "time_spent_seconds": 30,       // int, ≥0
      "hints_used": 0,                // int, ≥0
      "attempt_number": 1,            // int, ≥1
      "confidence": 0.8               // float, 0-1, 可选
    }
  ]
}

// Response 200:
{
  "code": 0,
  "data": {
    "session_id": "uuid",
    "accepted_count": 10,
    "state": "evaluating"             // 已触发批改
  }
}
```

**内部流程：**

1. 验证 `orch.state == QUIZ_GEN` 且 `quiz_status == in_progress`
2. `orch.submit_answers(req.answers)` — 保存作答到 DB
3. `orch.proceed()` — QUIZ_GEN → EVALUATING（Evaluator 批改）
4. 返回确认

> **设计要点：** 后端在 `proceed()` 之前先将 phase 写入 DB（`evaluating`），再执行 LLM。若 LLM 调用期间服务崩溃，重启后可从 DB 恢复并重试。

#### GET `/api/v1/sessions/{session_id}/results` — 获取批改结果

```json
// Response 200:
{
  "code": 0,
  "data": {
    "session_id": "uuid",
    "state": "evaluating",
    "attempts": [
      {
        "attempt_id": "uuid",
        "question_id": "uuid",
        "student_answer": "B",
        "is_correct": false,
        "score": 0.0,
        "explanation": "正确应为 A。F=ma → a=10/2=5 m/s²"
      }
    ],
    "misconceptions": [
      {
        "tag_id": "uuid",
        "label": "F=ma 公式混淆",
        "description": "将 F×m 当作加速度",
        "category": "conceptual",
        "severity": "moderate",
        "remediation_hint": "建议重新推导 F=ma 的变形"
      }
    ],
    "socratic_hints": [
      {
        "hint_id": "uuid",
        "question_id": "uuid",
        "misconception_tag_id": "uuid",
        "level": 1,
        "content": "想一想力和加速度的关系...",
        "trigger_after_failures": 0,
        "difficulty_adapt": false
      }
    ],
    "summary": {
      "total_questions": 10,
      "correct_count": 6,
      "accuracy": 0.6,
      "weakest_topic": "牛顿第二定律",
      "strongest_topic": "动能定理",
      "overall_assessment": "力学基础较好，牛顿第二定律的应用需要加强"
    }
  }
}
```

#### POST `/api/v1/sessions/{session_id}/plan` — 生成复习计划

```
触发: EVALUATING → PLANNING (Tutor 生成 SM-2 排期)

Response 200:
{
  "code": 0,
  "data": {
    "session_id": "uuid",
    "state": "planning",
    "plan_items": [
      {
        "item_id": "uuid",
        "knowledge_node_id": "uuid",
        "activity_type": "review",
        "scheduled_date": "2026-06-25",
        "estimated_minutes": 15,
        "notes": "..."
      }
    ],
    "summary": "未来 7 天安排 12 个复习条目..."
  }
}
```

#### 运维端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/sessions/{id}/restore` | 服务重启后从 DB 恢复到内存 |
| `POST` | `/api/v1/sessions/{id}/resume` | 恢复暂停的会话 |
| `POST` | `/api/v1/sessions/{id}/retry` | 重试失败的流水线步骤（最多 3 次） |

### 8.4 Dashboard 路由 (`/api/v1/students`)

**文件：** [super_tutor/routes/dashboard.py](../super_tutor/routes/dashboard.py)

#### GET `/api/v1/students/{student_id}/dashboard`

```json
// Response:
{
  "data": {
    "student_id": "student-1",
    "total_questions_attempted": 50,
    "correct_count": 35,
    "overall_accuracy": 0.70,
    "weak_topics": ["牛顿第二定律", "动量守恒"],
    "strong_topics": ["动能定理"],
    "recent_attempts": [{...}]    // 最近 10 条
  }
}
```

#### GET `/api/v1/students/{student_id}/mastery`

```json
// Response:
{
  "data": {
    "student_id": "student-1",
    "items": [
      {
        "knowledge_node_id": "uuid",
        "total_attempts": 8,
        "correct_attempts": 6,
        "accuracy": 0.75,
        "last_attempt_at": "2026-06-24T...",
        "mastery_level": 0.72,
        "state": "reviewing",
        "sm2_next_review": "2026-06-27",
        "sm2_interval_days": 3
      }
    ]
  }
}
```

#### GET `/api/v1/students/{student_id}/wrong-questions`

```
Query: ?limit=20&offset=0
分页返回错题列表，按提交时间倒序排列。
```

#### GET `/api/v1/students/{student_id}/plan/today`

```json
// Response:
{
  "data": {
    "date": "2026-06-24",
    "items": [
      {
        "item_id": "uuid",
        "knowledge_node_id": "uuid",
        "activity_type": "review",
        "scheduled_date": "2026-06-24",
        "estimated_minutes": 15,
        "completed": false,
        "notes": ""
      }
    ]
  }
}
```

#### POST `/api/v1/students/{student_id}/plan/items/{item_id}/toggle`

```json
// Request: {"completed": true}
// Response: {"item_id": "uuid", "completed": true}
```

### 8.5 Tokens 路由

**文件：** [super_tutor/routes/tokens.py](../super_tutor/routes/tokens.py)

```
GET /api/v1/tokens/stats?project_id=optional

Response:
{
  "data": {
    "total_prompt_tokens": 50000,
    "total_completion_tokens": 15000,
    "total_tokens": 65000,
    "call_count": 12,
    "by_role": {
      "tutor": {"prompt": 20000, "completion": 5000, "total": 25000},
      "assistant": {"prompt": 20000, "completion": 7000, "total": 27000},
      "evaluator": {"prompt": 10000, "completion": 3000, "total": 13000}
    },
    "budget": 1000000,
    "used": 65000,
    "remaining": 935000,
    "by_tier": {
      "heavy": {...},
      "medium": {...}
    }
  }
}
```

### 8.6 标准 API 响应封装

所有成功端点统一返回：

```json
{
  "code": 0,          // int，业务状态码，0=成功
  "message": "success",
  "data": { ... }     // 端点特定的载荷
}
```

错误响应：

```json
{
  "code": 2001,
  "message": "LLM API 调用失败",
  "detail": "Connection timeout after 120s"
}
```

---

## 第 9 章 · Orchestrator 状态机（核心引擎）

**文件：**
- [super_tutor/core/orchestrator.py](../super_tutor/core/orchestrator.py) — 主类 + 状态管理 (~900 行)
- [super_tutor/core/orchestrator_phases.py](../super_tutor/core/orchestrator_phases.py) — 四阶段 Mixin (~760 行)
- [super_tutor/core/orchestrator_prompts.py](../super_tutor/core/orchestrator_prompts.py) — Prompt 构建 (~280 行)
- [super_tutor/core/orchestrator_utils.py](../super_tutor/core/orchestrator_utils.py) — 工具函数 (~260 行)

### 9.1 类结构

```
Orchestrator(_PhaseHandlers)
├── 状态管理 (_phase, _paused, _error_message, _quiz_status)
├── 会话上下文 (_session_context)
├── 阶段产物 (_artifacts: dict)
├── 生命周期: initialize() → start() → proceed() → save() → get_status()
└── 四阶段处理器 (Mixin from _PhaseHandlers):
    ├── _parsing_phase()     # Tutor 解析 PDF
    ├── _quiz_gen_phase()    # Assistant 出题
    ├── _evaluating_phase()  # Evaluator 批改
    └── _planning_phase()    # Tutor 排期
```

### 9.2 核心状态字段

```python
class Orchestrator:
    _phase: PipelinePhase        # 当前阶段
    _previous_phase: PipelinePhase
    _paused: bool                # 是否暂停
    _error_message: str | None   # 错误信息
    _quiz_status: str            # QuizStatus
    _session_context: dict       # 传入的上下文
    _artifacts: dict             # 各阶段的 LLM 产出物
    _step_retry_count: int       # 当前步骤重试次数
    _in_progress: bool           # 是否有 LLM 调用进行中
    _step_stats: list            # 每步的耗时+Token 统计
```

### 9.3 阶段流转图（含暂停与错误恢复）

```
                    initialize()
                         │
                         ▼
    ┌───────────────── IDLE ──────────────────┐
    │                    │                     │
    │               start()                    │
    │                    │                     │
    │                    ▼                     │
    │    ┌────────── PARSING ─────────┐        │
    │    │  Tutor 解析 PDF            │        │
    │    │  产出: chunks, nodes, edges│        │
    │    └──────────┬─────────────────┘        │
    │               │ proceed()                │
    │               ▼                          │
    │    ┌────────── QUIZ_GEN ────────┐        │
    │    │  Assistant 出题             │        │
    │    │  产出: questions            │        │
    │    └──────────┬─────────────────┘        │
    │               │ submit_answers()         │
    │               │   + proceed()            │
    │               ▼                          │
    │    ┌──────── EVALUATING ────────┐        │
    │    │  Evaluator 批改+诊断        │        │
    │    │  产出: attempts,            │        │
    │    │  misconceptions,            │        │
    │    │  socratic_hints, summary    │        │
    │    └──────────┬─────────────────┘        │
    │               │ proceed()                │
    │               ▼                          │
    │    ┌──────── PLANNING ──────────┐        │
    │    │  Tutor 生成排期计划         │        │
    │    │  产出: plan_items, summary  │        │
    │    └────────────────────────────┘        │
    │                                          │
    └── 任意阶段 ── pause() ──► _paused=True ─┘
    └── 任意阶段 ── 异常 ──► retry_step() (≤3 次)
```

### 9.4 每个阶段的完整数据流

以 QUIZ_GEN 为例：

```
_quiz_gen_phase()
│
├─ 1. _start_phase(QUIZ_GEN, ASSISTANT, "基于知识库生成测验题目")
│     └─ 写 DB: phase=quiz_gen, role=assistant, status=running
│
├─ 2. chunks = self._artifacts["chunks"]   ← PARSING 产出
│
├─ 3. _build_quiz_gen_prompt(chunks, question_count, difficulty)
│     └─ 构建 user prompt（含 6 题型分布表 + JSON 示例）
│
├─ 4. _roles.build_context(role="assistant", ...)
│     └─ 构建 system prompt（加载 assistant.md + 注入上下文变量）
│
├─ 5. _invoke_role(role="assistant", user_message, system_prompt, tier="heavy")
│     ├─ TokenTracker.consume() → 检查预算
│     ├─ LLMClient.chat() → DeepSeek API (120s timeout, 3 retries)
│     └─ TokenTracker.log() → 记录用量
│
├─ 6. _safe_parse_json_list(response, "questions")
│     └─ 4 层 JSON 防御解析 → list[dict]
│
├─ 7. _hydrate_models(questions_raw, Question, defaults)
│     └─ Pydantic 校验 → list[Question]
│
├─ 8. 持久化到 questions 表（逐条 insert）
│
├─ 9. self._artifacts["questions"] = questions_raw
│    self._artifacts["question_models"] = questions
│    self._quiz_status = "ready"
│
└─ 10. _end_phase(QUIZ_GEN, role="assistant")
      └─ 写 DB: status=completed, 记录耗时
```

### 9.5 崩溃恢复机制

```
save() 时机:
  - initialize() 后立即保存 (phase=idle)
  - 每个 _start_phase() 开始时保存 (phase + role + status)
  - 每个 _end_phase() 结束时保存 (phase + artifacts)
  - submit_answers() 后保存

恢复流程 (POST /sessions/{id}/restore):
  1. 从 quiz_sessions 表读取 phase + artifacts
  2. 重建 Orchestrator 实例
  3. 注入 artifacts
  4. 如果 _in_progress=True（上次崩溃时有 LLM 调用进行中）
     → 重试当前阶段（幂等：DB 中已有数据则跳过 LLM）
```

### 9.6 错误处理与重试

```python
# orchestrator.py
MAX_RETRIES = 3

async def _handle_phase_error(self, exc: Exception) -> None:
    self._step_retry_count += 1
    if self._step_retry_count <= MAX_RETRIES:
        logger.warning("Phase %s failed, retry %d/%d",
                       self._phase, self._step_retry_count, MAX_RETRIES)
        # 重新执行当前阶段
        await self._retry_current_phase()
    else:
        self._error_message = str(exc)
        logger.error("Phase %s failed after %d retries: %s",
                     self._phase, MAX_RETRIES, exc)
```

---

## 第 10 章 · Prompt 工程（LLM 指令设计）

### 10.1 角色 Prompt 架构

每个角色的系统提示词存储在 `super_tutor/prompts/{role}.md`，通过 `RoleManager` 加载。

**文件：** [super_tutor/core/role_manager.py](../super_tutor/core/role_manager.py)

```python
class RoleManager:
    def __init__(self, prompts_dir: str):
        # 加载 prompts/*.md → {role: markdown_content}

    def build_context(self, role: str, project_path: str,
                      extra_context: dict[str, str]) -> str:
        # 1. 读取角色 prompt 模板
        # 2. 替换模板变量 {{variable}} → extra_context 中的值
        # 3. 返回完整的 system prompt
```

### 10.2 Assistant Prompt 详解（出题角色）

**文件：** [super_tutor/prompts/assistant.md](../super_tutor/prompts/assistant.md)

这是出题质量的核心控制点。关键约束：

| 约束 | 值 | 位置 |
|------|-----|------|
| 可用题型 | multiple_choice, true_false, fill_in_blank, short_answer, matching, essay | 第 13 行 |
| 难度分布 | 记忆30%/理解40%/应用20%/分析10% | 第 15 行 |
| 干扰项规范 | 每个错误选项对应一个具体迷思概念；禁止"以上都对/都错" | 第 18-22 行 |
| 输出格式 | `{"questions": [...]}`，纯 JSON，以 `{` 开始 `}` 结束 | 第 43-71 行 |
| 自查清单 | 6 项检查（干扰项/难度/解析/溯源/无垃圾选项/JSON 格式） | 第 110-118 行 |
| 题型示例 | 每种题型一个完整 JSON 示例 | 第 75-108 行 |

### 10.3 QUIZ_GEN User Prompt（出题引导）

**文件：** [super_tutor/core/orchestrator_prompts.py](../super_tutor/core/orchestrator_prompts.py) → `_build_quiz_gen_prompt()`

```python
def _build_quiz_gen_prompt(
    chunks: list[dict[str, Any]],
    question_count: int = 10,
    difficulty: str = "medium",
) -> str:
```

发给 LLM 的完整内容：

1. **知识片段预览** — chunks 的 JSON（超过 20 个时均匀采样）
2. **题目总数约束** — `{question_count} 道（必须精确，不多不少）`
3. **6 题型分布表** — 选择题 40%、判断 15%、填空 15%、简答 15%、匹配 10%、论述 5%
4. **难度锚定** — 根据用户选择的 difficulty 调整策略文案
5. **6 个完整 JSON 示例** — 每种题型一个 few-shot 示例
6. **结束强调** — 重复题目总数和题型覆盖要求

### 10.4 Tutor Prompt（解析 + 规划）

**文件：** [super_tutor/prompts/tutor.md](../super_tutor/prompts/tutor.md)

负责两阶段：
- **PARSING** — 将 PDF 内容切分为 KnowledgeChunk（content/summary/topic/difficulty/keywords）
- **PLANNING** — 基于 SM-2 算法生成间隔重复复习计划

### 10.5 Evaluator Prompt（批改）

**文件：** [super_tutor/prompts/evaluator.md](../super_tutor/prompts/evaluator.md)

负责 EVALUATING 阶段：
1. 逐题判定对错
2. 错题诊断迷思概念（7 种错误类别）
3. 生成苏格拉底式渐进提示（3 层级）
4. 输出评估汇总（total/correct/accuracy/weakest_topic/overall_assessment）

### 10.6 4 层 JSON 防御解析

**文件：** [super_tutor/core/orchestrator_utils.py](../super_tutor/core/orchestrator_utils.py) → `_safe_parse_json_list()`

LLM 输出的 JSON 可能包含 Markdown 围栏或格式噪音。解析器采用递进式防御：

```
层 1: json.loads(完整响应)           — 理想情况
层 2: 正则提取 ```json...``` 代码块  — LLM 加了 Markdown 围栏
层 3: 正则提取第一个 {...} 或 [...]  — LLM 在 JSON 前后加了说明文字
层 4: 返回 []                        — 彻底失败，不抛异常（上层需处理空列表）
```

> **注意：** 层 4 返回空列表**不抛异常**。这意味着 LLM 完全无法解析时，用户看到的是 "暂无题目"，而不是友好的错误提示。这是一个已知设计取舍。

---

## 第 11 章 · LLM 客户端

**文件：** [super_tutor/core/llm_client.py](../super_tutor/core/llm_client.py)

### 11.1 接口

```python
class LLMClient:
    def __init__(self, config: TutorConfig, token_tracker: TokenTracker):
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.api_base_url,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 120,
    ) -> str:
        """发送聊天请求，返回 LLM 响应文本。"""
```

### 11.2 重试策略

- 最大重试：3 次
- 退避策略：指数退避（1s → 2s → 4s）
- 可重试条件：网络错误、超时、5xx 状态码
- 不可重试：4xx（API Key 错误等）

### 11.3 Token 预算管控

每次调用前：

```python
# 1. 检查预算
if token_tracker.remaining <= 0:
    raise TutorError("Token budget exceeded")

# 2. 预估消耗（prompt tokens + max_tokens）
# 3. 调用 LLM
# 4. 记录实际消耗
token_tracker.log(role, phase, tier, prompt_tokens, completion_tokens)
```

### 11.4 API 不可用时的行为

如果 `config.api_key` 为空：
- 所有 LLM 调用返回 HTTP 503
- 错误消息："AI 服务未配置，请设置 TUTOR_API_KEY 环境变量"

---

## 第 12 章 · Token 追踪器

**文件：** [super_tutor/core/token_tracker.py](../super_tutor/core/token_tracker.py)

```python
class TokenTracker:
    def __init__(self, budget: int = 1_000_000):
        self._budget = budget
        self._used_prompt = 0
        self._used_completion = 0
        self._call_count = 0
        self._by_role: dict[str, dict] = {}    # {role: {prompt, completion, total}}
        self._by_tier: dict[str, dict] = {}    # {tier: {prompt, completion, total}}

    @property
    def budget(self) -> int: ...
    @property
    def used(self) -> int: ...          # prompt + completion
    @property
    def remaining(self) -> int: ...

    def log(self, role: str, phase: str, tier: str,
             prompt_tokens: int, completion_tokens: int) -> None: ...

    def stats(self) -> dict: ...        # 返回完整统计
```

---

## 第 13 章 · 前端架构

### 13.1 路由表

**文件：** [frontend/src/App.tsx](../frontend/src/App.tsx)

| 路径 | 页面组件 | 数据依赖 | 入口方式 |
|------|---------|---------|---------|
| `/` | `Dashboard` | `studentStore.fetchDashboard()` | 导航栏 |
| `/materials` | `MaterialsPage` | `quizStore.createSession()` | 导航栏 |
| `/quiz/:sessionId` | `QuizPage` | `quizStore.fetchQuestions()` | 代码跳转 |
| `/quiz/:sessionId/results` | `ResultsPage` | `quizStore.fetchResults()` | 代码跳转 |
| `/plan` | `PlanPage` | `studentStore.fetchTodayPlan()` | 导航栏 |

### 13.2 组件树

```
<BrowserRouter>
  <App>
    <Layout>
      ├── <Navbar>           ← 仪表盘 | 材料 | 今日计划
      ├── <main>
      │   └── <Routes>
      │       ├── <Dashboard>
      │       │   └── <MasteryChart>
      │       ├── <MaterialsPage>
      │       │   └── <FileUpload>    ← 文本模式 + PDF 模式
      │       ├── <QuizPage>
      │       │   └── <QuizCard> × N  ← 单选按钮 或 文本框
      │       ├── <ResultsPage>
      │       │   └── <ResultCard> × N
      │       └── <PlanPage>
      └── <footer>            ← "Super Tutor v0.3.0"
```

### 13.3 状态管理（Zustand Store）

#### quizStore（测验状态机镜像）

**文件：** [frontend/src/store/quizStore.ts](../frontend/src/store/quizStore.ts)

```typescript
interface QuizState {
  // ── 会话（直接对应后端 Orchestrator 字段）──
  sessionId: string | null;
  materialId: string | null;
  phase: PipelinePhase;        // 后端 _phase 的直译
  quizStatus: string;          // 后端 _quiz_status 的直译
  title: string;
  studentId: string;

  // ── 阶段产物 ──
  questions: QuestionResponse[];
  answers: Record<string, unknown>;
  results: AttemptResult[];
  misconceptions: MisconceptionTag[];
  socraticHints: SocraticHint[];
  summary: ResultSummary | null;
  planItems: PlanItem[];
  planSummary: string;

  // ── UI 状态 ──
  loading: boolean;
  error: string | null;

  // ── Actions ──
  createSession(...): Promise<string | null>;
  fetchQuestions(sessionId): Promise<void>;
  setAnswer(questionId, answer): void;
  submitAnswers(): Promise<void>;
  fetchResults(sessionId): Promise<void>;
  generatePlan(sessionId): Promise<void>;
  reset(): void;
  clearError(): void;
}
```

**关键设计：** 每个 action 调用 API 后，从响应的 `state` 字段提取 `phase`，从 `quiz_status` 字段提取 `quizStatus`，立即同步到 store。前端 UI 根据这两个字段决定渲染什么。

```typescript
// 辅助函数
function extractPhase(data): PipelinePhase {
  const state = data.state;
  return validPhases.has(state) ? state : "idle";
}

function extractQuizStatus(data): string {
  return data.quiz_status || "draft";
}
```

#### studentStore（学生仪表盘）

**文件：** [frontend/src/store/studentStore.ts](../frontend/src/store/studentStore.ts)

```typescript
interface StudentState {
  studentId: string;
  dashboard: DashboardResponse | null;
  mastery: MasteryItem[];
  todayPlan: PlanTodayResponse | null;
  wrongQuestions: WrongQuestionItem[];
  loading: boolean;
  error: string | null;

  fetchDashboard(studentId): Promise<void>;
  fetchMastery(studentId): Promise<void>;
  fetchTodayPlan(studentId): Promise<void>;
  fetchWrongQuestions(studentId, limit?, offset?): Promise<void>;
  togglePlanItem(studentId, itemId, completed): Promise<void>;
}
```

### 13.4 API 客户端

**文件：** [frontend/src/api/client.ts](../frontend/src/api/client.ts)

```typescript
const BASE = "/api/v1";

class ApiError extends Error {
  status: number;      // HTTP 状态码
  detail: string;      // 服务端 detail 字段
}

async function request<T>(url: string, options?): Promise<APIResponse<T>> {
  // timeout: 默认 120,000ms（适配 LLM 长时间调用）
  // 超时 → AbortController → ApiError(408)
  // HTTP 错误 → 解析 resp.json().detail → ApiError(status, detail)
  // 网络错误 → 透传
}
```

**前端错误处理策略：**

| HTTP 状态 | 前端行为 |
|-----------|---------|
| 409 | 显示 `detail` 或 "当前状态不允许此操作，请刷新页面后重试" |
| 408 | 显示 "请求超时，AI 仍在处理中，请稍后重试" |
| 其他 4xx/5xx | 显示 `detail` 或通用错误消息 |
| 网络错误 | 显示错误消息 + 重试按钮 |

### 13.5 前端类型定义（与后端对齐）

**文件：** [frontend/src/api/types.ts](../frontend/src/api/types.ts)

关键类型及后端对应：

| 前端 interface | 后端 Schema | 说明 |
|---------------|------------|------|
| `APIResponse<T>` | `schemas.APIResponse` | `{code, message, data}` |
| `SessionResponse` | `schemas.SessionResponse` | 含 `state` + `quiz_status` |
| `QuestionsData` | GET questions 响应 | 含 `state` + `questions[]` |
| `QuestionResponse` | `schemas.QuestionResponse` | 不含 `correct_answer` |
| `ResultResponse` | `schemas.ResultResponse` | attempts + misconceptions + summary |
| `SubmitAnswersRequest` | `schemas.SubmitAnswersRequest` | answers 数组 |

### 13.6 阶段驱动渲染（QuizPage）

**文件：** [frontend/src/pages/QuizPage.tsx](../frontend/src/pages/QuizPage.tsx)

QuizPage 是整个前端最复杂的页面，根据 `phase` 有 5 种渲染状态：

```typescript
const PHASE_LOADING: Record<PipelinePhase, {icon, message, sub}> = {
  idle:       {icon: "⏳", message: "正在连接…",       sub: "正在创建测验会话"},
  parsing:    {icon: "📖", message: "AI 正在解析学习材料…", sub: "提取知识点、构建知识图谱，复杂材料可能需要 30 秒以上"},
  quiz_gen:   {icon: "✏️", message: "AI 正在生成测验题目…", sub: "根据知识库定制个性化题目"},
  evaluating: {icon: "🔍", message: "AI 正在批改作答…",   sub: "逐题判定对错、诊断迷思概念"},
  planning:   {icon: "📋", message: "处理中…",         sub: ""},
};
```

**渲染决策树：**

```
QuizPage 渲染
├─ (idle|parsing) + loading → 大图标 + 阶段文案 + 旋转 spinner
├─ evaluating + !results → 批改动画
├─ error → 错误卡片 + 重试按钮 + 返回材料页按钮
├─ !questions + !loading → "暂无题目" + 刷新按钮
└─ 正常 → 题目列表 + 提交按钮
```

**3 个 useEffect 驱动自动流转：**

1. **useEffect #1** — 首次 mount 触发 `fetchQuestions(sessionId)`（IDLE → PARSING → QUIZ_GEN）
2. **useEffect #2** — `phase==evaluating && quizStatus==submitted` → 自动 `fetchResults(sessionId)`
3. **useEffect #3** — `results.length>0 && phase==evaluating` → 自动导航到 `/quiz/:id/results`

### 13.7 阶段门控渲染（ResultsPage）

**文件：** [frontend/src/pages/ResultsPage.tsx](../frontend/src/pages/ResultsPage.tsx)

ResultsPage 根据 `phase` 做门控：

| phase | 渲染 |
|-------|------|
| `idle` / `parsing` | "请先等待题目生成" + 返回答题按钮 |
| `quiz_gen` | "请先完成答题并提交答案" + 返回答题按钮 |
| `evaluating` | 加载中 | 正常结果页 |
| `planning` | 正常结果页 + "已完成" 标签 |

**Summary 卡片渲染：**

```tsx
// 如果 summary 对象存在（后端 F8 产出）→ 渐变色卡片
<summary-card>
  总题数 | 正确数 | 正确率
  ⚠ 最弱知识点: {summary.weakest_topic}
  ⭐ 最强知识点: {summary.strongest_topic}
  {summary.overall_assessment}
</summary-card>

// 如果 summary 为 null → 简单统计卡片（fallback）
<simple-stats> 总题数 | 正确 | 正确率 </simple-stats>
```

### 13.8 前端题型渲染（QuizCard）

**文件：** [frontend/src/components/QuizCard.tsx](../frontend/src/components/QuizCard.tsx)

当前是**二元判断**：

```typescript
const isMultipleChoice = question.type === "multiple_choice";

// type == "multiple_choice" → 单选按钮
// type == 其他任何值      → 文本框 + "简答题" 标签
```

| 后端题型 | 当前渲染 | 状态 |
|---------|---------|:---:|
| `multiple_choice` | 单选按钮 + 选项 | ✅ 正确 |
| `true_false` | 文本框 + "简答题" | ❌ 应为 ✓/✗ 按钮 |
| `fill_in_blank` | 文本框 + "简答题" | ❌ 应挖空显示 |
| `short_answer` | 文本框 + "简答题" | ⚠️ 可用 |
| `matching` | 文本框 + "简答题" | ❌ 应为配对 UI |
| `essay` | 文本框 + "简答题" | ⚠️ 可用 |

> **注意：** `hints` 字段虽然在 `QuestionResponse` 中返回，但 QuizCard **完全没有使用**。答题时的渐进提示功能尚未实现。

### 13.9 材料上传流程（MaterialsPage + FileUpload）

**文件：**
- [frontend/src/pages/MaterialsPage.tsx](../frontend/src/pages/MaterialsPage.tsx)
- [frontend/src/components/FileUpload.tsx](../frontend/src/components/FileUpload.tsx)

```
MaterialsPage
├─ Student ID 输入框 (默认 "student-1")
│
└─ FileUpload (onUploaded → handleStartQuiz)
   ├─ 模式 A: 文本上传
   │   ├─ title input + subject input + content textarea
   │   └─ "上传文本材料" → api.uploadMaterial() → materialId
   │
   └─ 模式 B: PDF 上传
       ├─ file input (accept=".pdf", max 50MB)
       └─ onFileSelect → api.uploadPdfFile() → materialId

handleStartQuiz(materialId):
  1. quizStore.createSession(materialId, {studentId})
  2. navigate(`/quiz/${sid}`)
```

### 13.10 今日计划页（PlanPage）

**文件：** [frontend/src/pages/PlanPage.tsx](../frontend/src/pages/PlanPage.tsx)

```
PlanPage
├─ useEffect: studentStore.fetchTodayPlan(studentId)
│
├─ 加载中 → spinner
├─ 无计划 → 引导文案
├─ 有计划 → 条目列表:
│   └─ 每条:
│       ├─ checkbox (完成/未完成)
│       ├─ activity_type 标签
│       ├─ estimated_minutes
│       └─ 点击 → api.togglePlanItem()
```

### 13.11 仪表盘（Dashboard）

**文件：** [frontend/src/pages/Dashboard.tsx](../frontend/src/pages/Dashboard.tsx)

```
Dashboard
├─ useEffect:
│   ├─ studentStore.fetchDashboard(studentId)
│   └─ studentStore.fetchMastery(studentId)
│
├─ 统计卡片行:
│   ├─ 累计作答数
│   ├─ 正确率
│   └─ 薄弱知识点数
│
├─ 强弱知识点标签:
│   ├─ 薄弱 (red) × N
│   └─ 优势 (green) × N
│
├─ MasteryChart:
│   └─ 每个知识点: 名称 + 准确率柱 + 状态标签 + SM-2 间隔
│
└─ 快捷按钮:
    ├─ "开始新测验" → navigate("/materials")
    └─ "查看今日计划" → navigate("/plan")
```

---

## 第 14 章 · SM-2 间隔重复算法

**实现位置：** [super_tutor/core/orchestrator_phases.py](../super_tutor/core/orchestrator_phases.py) → `_persist_mastery_records()`

### 14.1 算法参数

| 参数 | 符号 | 初始值 | 范围 | 说明 |
|------|------|--------|------|------|
| Ease Factor | EF | 2.5 | [1.3, +∞) | 难易度因子，越高越容易记住 |
| Repetitions | n | 0 | [0, +∞) | 连续正确次数 |
| Interval | I | 1 天 | [1, +∞) | 当前复习间隔 |
| Quality | q | — | [0, 5] | 作答评分（≥3 通过） |
| EMA α | α | 0.3 | (0, 1) | 掌握度平滑系数 |
| Decay | d | 0.4 | (0, 1) | 错误衰减因子 |

### 14.2 核心更新逻辑

```python
def _update_sm2(record: MasteryRecord, quality: int) -> MasteryRecord:
    if quality >= 3:  # 通过
        if record.sm2_repetitions == 0:
            record.sm2_interval_days = 1
        elif record.sm2_repetitions == 1:
            record.sm2_interval_days = 6
        else:
            record.sm2_interval_days = int(
                record.sm2_interval_days * record.sm2_ease_factor
            )
        record.sm2_repetitions += 1
        # EMA 更新
        record.mastery_level += 0.3 * (1 - record.mastery_level)
    else:  # 失败
        record.sm2_repetitions = 0
        record.sm2_interval_days = 1
        record.sm2_ease_factor = max(1.3, record.sm2_ease_factor - 0.2)
        # 衰减
        record.mastery_level *= 0.4

    # 更新 EF
    record.sm2_ease_factor += 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    record.sm2_ease_factor = max(1.3, record.sm2_ease_factor)

    # 下次复习日期
    record.sm2_next_review = today + timedelta(days=record.sm2_interval_days)
    return record
```

### 14.3 掌握度状态判定

| mastery_level | state |
|---------------|-------|
| 0.0 - 0.2 | `new` |
| 0.2 - 0.5 | `learning` |
| 0.5 - 0.8 | `reviewing` |
| 0.8 - 1.0 | `mastered` |
| 任意值 + streak=0 + last_attempt > 30d | `stagnated` |

### 14.4 复习计划生成逻辑

```
PLANNING 阶段 (Tutor):
  输入: attempts + misconceptions + mastery_records
  规则:
    1. mastery < 0.5 的知识点 → 必须复习
    2. 优先级 = (1 - mastery) × log(1 + overdue_days)
       （越不掌握 + 越逾期 → 越优先）
    3. 每日复习量 ≤ 2 小时
    4. 探索(薄弱点) : 利用(已掌握) ≈ 3:1
  输出: plan_items[] (scheduled_date, activity_type, estimated_minutes)
```

---

## 第 15 章 · 异常体系

**文件：** [super_tutor/core/exceptions.py](../super_tutor/core/exceptions.py)

```
TutorError (BaseException)
├── ConfigError           # 配置错误（缺少 API Key 等）
├── LLMError              # LLM 调用失败
│   ├── LLMTimeoutError   # 超时
│   ├── LLMEmptyResponse  # 返回空内容
│   └── LLMParseError     # JSON 解析失败
├── DatabaseError         # 数据库异常
├── MaterialError         # 材料处理错误
│   ├── PDFExtractionError  # PDF 提取失败（扫描件）
│   ├── PDFTooLargeError    # PDF 过大
│   └── EmptyContentError   # 知识库为空
└── SessionError          # 会话错误
    ├── SessionNotFoundError   # 会话不存在
    ├── PhaseConflictError     # 阶段冲突（在错误阶段调用操作）
    └── MaxRetriesExceededError # 超过最大重试次数
```

---

## 第 16 章 · 测试策略

### 16.1 当前状态

```
tests/
├── conftest.py          # 共享 fixtures
│   ├── FakeLLMClient    # 返回预置 JSON（含 2 道样题）
│   ├── TestDatabase     # 内存 SQLite
│   └── ...
├── test_materials.py    # 资料上传
├── test_quizzes.py      # 测验会话（创建/答题/批改/排期）
├── test_dashboard.py    # 仪表盘
└── test_tokens.py       # Token 统计

当前通过: 18 个用例
```

### 16.2 关键测试场景

| 场景 | 文件 | 覆盖内容 |
|------|------|---------|
| 上传文本材料 → 返回 material_id | test_materials.py | Material API |
| 上传 PDF → 文本提取 → 入库 | test_materials.py | PDF 处理链 |
| 创建会话 → 获取题目 → 提交 → 批改 → 排期 | test_quizzes.py | 完整 5 阶段流水线 |
| 404 会话不存在 | test_quizzes.py | 错误路径 |
| 仪表盘数据聚合 | test_dashboard.py | 聚合查询 |
| Token 超预算 | test_tokens.py | 预算管控 |

### 16.3 FakeLLMClient 设计

```python
class FakeLLMClient:
    """避免实际调用 DeepSeek API，返回预置的合法 JSON"""
    async def chat(self, messages, **kwargs) -> str:
        # 根据 system prompt 中的角色返回不同预置响应
        if "出题" in str(messages):
            return CANNED_QUESTIONS_JSON  # 2 道样题
        elif "批改" in str(messages):
            return CANNED_EVALUATION_JSON
        ...
```

### 16.4 测试缺口（已知但未覆盖）

- 流水线暂停/恢复 (pause/resume)
- 崩溃恢复 (restore from DB)
- 4 层 JSON 解析的每一层（目前依赖 FakeLLM 绕过）
- 前端组件测试（0 个前端测试）
- 409 阶段冲突场景
- 并发创建多个会话

---

## 第 17 章 · 开发与调试

### 17.1 启动开发环境

```bash
# 终端 1: 后端 (http://127.0.0.1:8765)
cd super-tutor-agent
pip install -r requirements.txt
python -m super_tutor.main --reload

# 终端 2: 前端 (http://localhost:5173)
cd super-tutor-agent/frontend
npm install
npm run dev
```

### 17.2 环境变量

```bash
# .env 或直接 export
export TUTOR_API_KEY="sk-xxxx"           # 必填
export TUTOR_API_BASE_URL="https://api.deepseek.com"  # 可选
export TUTOR_TOKEN_BUDGET="1000000"      # 可选
export TUTOR_DB_PATH="~/.super-tutor/super_tutor.db"  # 可选
```

### 17.3 API 文档

启动后端后访问：
- Swagger UI: http://127.0.0.1:8765/docs
- ReDoc: http://127.0.0.1:8765/redoc

### 17.4 构建生产版本

```bash
# 前端
cd frontend && npm run build   # → dist/

# 后端
pip install -e .               # 安装为可编辑包
python -m super_tutor.main --host 0.0.0.0 --port 8765
```

---

## 第 18 章 · 已知问题与设计取舍

### 18.1 已知问题

| # | 严重度 | 位置 | 描述 |
|---|--------|------|------|
| 1 | 🟡 中 | `orchestrator_utils.py:86` | JSON 解析失败静默返回 `[]`，用户看到"暂无题目"但不知原因 |
| 2 | 🟡 中 | `orchestrator_prompts.py:70` | chunks 超过 20 个时均匀采样，后段知识点可能不被出题 |
| 3 | 🟡 中 | `QuizCard.tsx:11` | 6 种题型只区分了 `multiple_choice` vs 其他，true_false/fill_blank/matching 都退化成了文本框 |
| 4 | 🟡 中 | `QuizCard.tsx` | `hints` 字段未渲染，答题时无渐进提示 |
| 5 | 🟢 低 | `enums.py` | `QuestionType.CODING` 枚举存在但从未被任何 prompt 引用 |
| 6 | 🟢 低 | 前端 | 无错题本页面（API 已就绪，缺少前端路由和页面） |
| 7 | 🟢 低 | 前端 | 无会话历史页面 |

### 18.2 有意设计取舍

| 取舍 | 原因 |
|------|------|
| 前端只有 5 个页面 | MVP 范围：完整学习闭环可演示即可 |
| 错题本 API 有了但没前端页面 | PRD 中 F7 为 P1，当前时间投入在核心流程 |
| JSON 解析静默失败 | LLM 输出不可控，静默降级比崩掉体验好 |
| 无 WebSocket | 单用户场景，轮询开销可接受 |
| QuestionResponse 不含 `explanation` | 安全需求：防止前端暴露答案 |
| SQLite 而非 PostgreSQL | MVP 零运维，单用户场景 SQLite 足够 |
| 无用户认证 | 本地单用户场景 |

---

## 附录 A · 完整代码量统计

| 模块 | 文件数 | 代码行数（约） | 说明 |
|------|--------|-------------|------|
| `super_tutor/core/` | 10 | ~3,500 | 核心引擎 |
| `super_tutor/models/` | 9 | ~1,200 | Pydantic 模型 |
| `super_tutor/routes/` | 6 | ~1,000 | FastAPI 路由 |
| `super_tutor/prompts/` | 3 | ~400 | AI 角色 Prompt |
| `super_tutor/` (顶层) | 3 | ~300 | 入口+配置 |
| `frontend/src/` | 13 | ~1,800 | React SPA |
| `tests/` | 5 | ~600 | pytest |
| `docs/` | 3 | ~1,200 | 文档 |
| **总计** | **49** | **~10,000** | |

## 附录 B · 术语速查

| 术语 | 缩写 | 定义 |
|------|------|------|
| Pipeline Phase | — | 流水线阶段：idle → parsing → quiz_gen → evaluating → planning |
| Quiz Status | — | 测验生命周期：draft → ready → in_progress → submitted → graded → reviewed |
| Orchestrator | — | 流水线编排器，管理 5 阶段状态转换和 3 AI 角色调度 |
| Role Manager | — | 加载和管理 AI 角色系统提示词（prompts/*.md） |
| SM-2 | SuperMemo-2 | 间隔重复排期算法 |
| EMA | Exponential Moving Average | 掌握度指数移动平均（α=0.3） |
| EF | Ease Factor | SM-2 难易度因子（默认 2.5） |
| Socratic Hint | — | 苏格拉底式渐进引导提示（L1/L2/L3） |
| Misconception | — | 迷思概念：学生的系统性错误认知 |
| Cognitive Twin | — | 认知孪生：每个知识点的数学化掌握度模型 |
| Bloom's Taxonomy | — | 认知目标分类：记忆/理解/应用/分析/评价/创造 |
| vec0 | — | sqlite-vec 虚拟表类型，用于语义向量检索 |
| chunk | — | 知识片段：PDF 解析后按知识点边界切分的文本块 |

## 附录 C · 参考资源

| 资源 | URL |
|------|-----|
| FastAPI 文档 | https://fastapi.tiangolo.com/ |
| Pydantic v2 文档 | https://docs.pydantic.dev/latest/ |
| SuperMemo SM-2 Algorithm | https://www.supermemo.com/en/blog/application-of-a-computer-to-improve-the-results-obtained-in-working-with-the-supermemo-method |
| sqlite-vec | https://github.com/asg017/sqlite-vec |
| Bloom's Taxonomy | https://bloomstaxonomy.net/ |
| FSRS (Anki 新一代) | https://github.com/open-spaced-repetition/fsrs4anki |
| PyMuPDF | https://pymupdf.readthedocs.io/ |
| React Router v6 | https://reactrouter.com/ |
| Zustand | https://docs.pmnd.rs/zustand |
| Tailwind CSS | https://tailwindcss.com/docs |
| Vite | https://vitejs.dev/ |
