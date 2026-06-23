# 超级私教 (Super Tutor Agent) — 产品需求规格说明书

**文档编号：** STA-PRD-2026-001
**版本：** v2.0
**状态：** MVP 开发中
**密级：** 内部（课程答辩用）

---

## 文档控制

| 角色 | 姓名 / 标识 | 日期 |
|------|------------|------|
| **作者** | xiangyuli494-cmyk | 2026-06-23 |
| **审核** | —（学生项目，导师审核） | — |
| **批准** | — | — |

### 变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|---------|------|
| v1.0 | 2026-06-22 | 初稿，9 章完整 PRD | xiangyuli494-cmyk |
| v2.0 | 2026-06-23 | 重构为企业标准格式；与代码实际模型对齐；增加风险登记册与测试策略 | xiangyuli494-cmyk |

### 术语对照

| 缩写 | 全称 | 说明 |
|------|------|------|
| RAG | Retrieval-Augmented Generation | 检索增强生成 |
| SM-2 | SuperMemo-2 | 间隔重复调度算法 |
| EMA | Exponential Moving Average | 指数移动平均（掌握度平滑） |
| KNN | K-Nearest Neighbors | K 近邻向量检索 |
| EF | Ease Factor | SM-2 难易度因子 |

---

## 第 1 章 · 项目概述

### 1.1 产品愿景

超级私教是一个**基于 Multi-Agent 协作的认知孪生驱动深度学习辅助系统**。用户上传 PDF 教材后，三个 AI Agent（Parser / QuizMaster / Planner）协作完成「资料解析 → 自适应出题 → 智能排期」的完整学习闭环。

### 1.2 一句话定位

> 不是「问答机器人」——是持续追踪你每个知识点掌握度的**认知孪生私教**。

### 1.3 与竞品的核心差异

| 维度 | 扣子 / ChatGPT | 超级私教（本系统） |
|------|---------------|-------------------|
| 交互模式 | 单轮 / 多轮对话 | 持续性学习闭环 |
| 知识管理 | 每次对话独立 | PDF 上传后持久化向量索引 |
| 题目生成 | 一次性批量输出 | 基于掌握度薄弱点的**自适应出题** |
| 学习追踪 | 无 | 每个知识点的**认知孪生**（EMA 掌握度 + SM-2 排期） |
| 错误诊断 | 判对错 + 给答案 | **迷思概念分类** + 苏格拉底式引导提示 |
| 架构 | 单一模型 | 三 Agent 状态机协作 |

### 1.4 目标用户

- **大学生**：专业课教材 PDF 多，备考压力大，需要系统化复习工具
- **考研 / 考公人群**：长期备考（3-12 个月），SM-2 排期天然适配
- **自学编程 / 技术人群**：大量技术文档需要结构化理解和测验

### 1.5 MVP 范围定义

| 优先级 | 功能 | 描述 | 工期 |
|--------|------|------|------|
| **P0** | F1 资料上传与解析 | 单 PDF 上传 → PyMuPDF 提取 → 切片 → 向量化 | Day 2 |
| **P0** | F2 自动出题 | 基于知识库生成 10 道选择题，Bloom 难度分层 | Day 3 |
| **P0** | F3 在线作答与批改 | 选择题即时判定 + 简答题 LLM 批改 | Day 4 |
| **P0** | F4 迷思概念诊断 | 错题自动打标签（概念混淆 / 计算错误 / 粗心等） | Day 4 |
| **P0** | F5 SM-2 排期计划 | 基于作答历史生成间隔重复复习计划 | Day 5 |
| **P1** | F6 仪表盘 | 掌握度概览 + 今日待复习清单 | Day 6 |
| **P1** | F7 错题本 | 按时间倒序浏览错题 + 查看诊断和解析 | Day 6 |
| **P2** | F8 苏格拉底式追问 | 错题展示渐进式提示（3 层），引导自主发现 | Day 7（如时间允许）|

### 1.6 明确不做的功能（Out of Scope）

本阶段以下功能**明确不纳入**：
- 多课程 / 多科目管理体系
- 用户账号系统与权限管理
- 知识图谱可视化（D3.js / Canvas 渲染）
- PDF 图片与表格结构化解析
- 语音 / 图片输入
- FSRS 全参数优化算法（当前采用简化 SM-2）
- 实时协作与分享功能
- WebSocket 推送通知

---

## 第 2 章 · 系统架构

### 2.1 技术选型

| 层级 | 技术 | 版本要求 | 选型理由 |
|------|------|---------|---------|
| **后端框架** | FastAPI | ≥ 0.115 | 异步支持好、自动 OpenAPI 文档、生态成熟 |
| **ASGI 服务器** | Uvicorn | ≥ 0.30 | FastAPI 官方推荐 |
| **LLM 接入** | OpenAI SDK (兼容模式) | ≥ 1.0 | 兼容 DeepSeek API，社区成熟 |
| **关系数据库** | SQLite + aiosqlite | ≥ 0.20 | 零配置嵌入式，个人用户场景无需 PostgreSQL |
| **向量检索** | sqlite-vec | ≥ 0.1 | SQLite 原生向量扩展，零运维 |
| **PDF 解析** | PyMuPDF | ≥ 1.24 | 文本提取精度最高，支持页码索引 |
| **数据校验** | Pydantic | ≥ 2.0 | FastAPI 原生集成 |
| **前端框架** | React + TypeScript | 18.x | 生态最丰富 |
| **样式方案** | Tailwind CSS | 3.x | 快速 UI 开发 |
| **状态管理** | Zustand | 4.x | 轻量、无 boilerplate |
| **测试** | pytest + pytest-asyncio | ≥ 8.0 | Python 标准测试框架 |

### 2.2 系统架构图

```
┌──────────────────────────────────────────────────────────────┐
│                   React 前端 (SPA)                           │
│  仪表盘  │  资料上传  │  答题页  │  复习计划  │  错题本      │
└─────────────────────────┬────────────────────────────────────┘
                          │ HTTP REST (JSON)
┌─────────────────────────▼────────────────────────────────────┐
│               FastAPI 后端引擎                                │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │            Orchestrator 状态机引擎                     │    │
│  │   IDLE → PARSING → QUIZ_GEN → EVALUATING → PLANNING  │    │
│  │                       ↕ PAUSED / ERROR                │    │
│  └───────┬───────────────┬────────────────┬─────────────┘    │
│          │               │                │                   │
│  ┌───────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐           │
│  │  Tutor Agent │ │ Assistant   │ │ Evaluator   │           │
│  │  (解析+规划)  │ │ Agent (出题) │ │ Agent (批改) │           │
│  └───────┬──────┘ └──────┬──────┘ └──────┬──────┘           │
│          │               │               │                   │
│  ┌───────▼───────────────▼───────────────▼──────┐           │
│  │  Core Layer: LLMClient / Database / RoleMgr  │           │
│  └──────────────────┬───────────────────────────┘           │
│                     │                                        │
│  ┌──────────────────▼──────────────────────────┐            │
│  │  SQLite + sqlite-vec (向量检索 + CRUD)      │            │
│  └─────────────────────────────────────────────┘            │
└──────────────────────────────────────────────────────────────┘
```

### 2.3 部署拓扑

本项目为**单机单用户**架构，不依赖外部服务：

```
User Browser (localhost:5173)
       │
       ▼
FastAPI Server (127.0.0.1:8765)
       │
       ├── SQLite DB (local .db file)
       ├── DeepSeek API (external, via HTTPS)
       └── Uploaded PDFs (local filesystem)
```

---

## 第 3 章 · 功能需求（用户故事 + 验收标准）

### F1 资料上传与解析

**用户故事：**
> 作为一名学生，我希望上传课程 PDF 教材，系统能自动提取内容并生成可供检索的知识片段，以便后续出题和复习。

**验收标准：**

| ID | 标准 | 量化指标 |
|----|------|---------|
| AC1.1 | PDF 文本提取完整率 | ≥ 95%（排除页眉页脚） |
| AC1.2 | 切片语义完整率 | ≥ 90%（在句子/段落边界断开） |
| AC1.3 | 标题层级识别准确率 | ≥ 85%（人工标注 20 页抽样对比） |
| AC1.4 | 向量检索命中率 (Top-5) | ≥ 80%（10 个预设问题测试） |
| AC1.5 | 50 页 PDF 解析耗时 | ≤ 30 秒 |

**异常处理：**

| 场景 | 错误码 | 行为 |
|------|--------|------|
| 无文本层 PDF（扫描件） | `4001` | 返回明确提示「PDF 无可提取文本，请上传文字型 PDF」 |
| PDF 超过 50MB 或 200 页 | `4004` | 拒绝处理，提示分割后上传 |
| 单个 chunk 嵌入生成失败 | — | 跳过该 chunk，标记 `embedding: null`，不影响其他 chunk |

---

### F2 自动出题

**用户故事：**
> 作为一名学生，我希望系统根据我上传的教材自动生成测验题，题目难度有层次递进，且每题有详细解析。

**验收标准：**

| ID | 标准 | 量化指标 |
|----|------|---------|
| AC2.1 | 题干可理解率 | ≥ 95% |
| AC2.2 | 正确答案准确性 | ≥ 90%（人工验证） |
| AC2.3 | 干扰项合理性 | ≥ 75%（错误选项不能明显荒谬） |
| AC2.4 | 知识点覆盖度 | 每个知识 chunk 至少 1 题 |
| AC2.5 | 难度分布 | 记忆:理解:应用:分析 ≈ 3:4:2:1 |
| AC2.6 | JSON 解析成功率 | ≥ 95%（经 4 层防御解析后） |
| AC2.7 | 10 道题生成耗时 | ≤ 20 秒 |

**异常处理：**

| 场景 | 错误码 | 行为 |
|------|--------|------|
| LLM 返回空内容 | `4002` | 重试 1 次（换 `temperature=0.3`），仍空则返回错误 |
| LLM JSON 格式异常 | `4003` | 4 层防御解析兜底，全失败则通知前端「出题异常，请重试」 |
| 知识库为空 | `4005` | 「请先上传学习材料后再出题」 |

**4 层防御 JSON 解析流程：**

```
第 1 层：json.loads(完整响应)
第 2 层：正则提取 ```json ... ``` 围栏代码块
第 3 层：正则提取第一个 JSON 对象 / 数组
第 4 层：返回 []（兜底，不抛异常）
```

---

### F3 在线作答与即时批改

**用户故事：**
> 作为一名学生，我希望在线答题并立即看到对错和详细解析，以便即时纠正理解偏差。

**验收标准：**

| ID | 标准 | 量化指标 |
|----|------|---------|
| AC3.1 | 选择题批改准确率 | 100%（程序化比对，无错误空间） |
| AC3.2 | 简答题关键点匹配率 | ≥ 85%（预设 5 个关键点判定） |
| AC3.3 | 提交后批改响应时间 | ≤ 3 秒（10 题批量批改） |

---

### F4 迷思概念诊断

**用户故事：**
> 作为一名学生，我希望系统不仅仅判对错，还能分析我错在哪里——是概念混淆、计算错误还是粗心——这样我才能针对性地弥补。

**验收标准：**

| ID | 标准 | 量化指标 |
|----|------|---------|
| AC4.1 | 每道错题自动生成诊断标签 | ≥ 1 个 MisconceptionTag |
| AC4.2 | 标签合理性 | ≥ 70%（人工抽检） |
| AC4.3 | 补救建议覆盖 | 每个标签含 `remediation_hint` |

**迷思概念分类体系：**

| 类别 | 标识 | 示例 |
|------|------|------|
| 概念混淆 | `conceptual` | 动量与动能混淆；矩阵特征值与行列式混淆 |
| 计算错误 | `calculation` | 符号错误；数值代入错误 |
| 应用不当 | `application` | 公式选错；条件判断遗漏 |
| 逻辑错误 | `logic` | 推理链条断裂；因果关系颠倒 |
| 粗心 | `careless` | 漏看条件；抄错数字 |
| 符号书写 | `notation` | 单位遗漏；LaTeX 语法错误 |
| 不完整 | `incomplete` | 只写结论无过程；漏答子问题 |

---

### F5 SM-2 排期计划

**用户故事：**
> 作为一名学生，我希望系统根据我的作答表现自动生成每日复习计划，薄弱点多排、已掌握的少排，像真人私教一样帮我分配精力。

**验收标准：**

| ID | 标准 | 量化指标 |
|----|------|---------|
| AC5.1 | 排期依据 | 基于 SM-2 算法计算间隔（EF + repetitions + interval） |
| AC5.2 | 优先级公式 | `(1 - mastery) × log(1 + overdue_days)` |
| AC5.3 | 每日复习量上限 | ≤ 2 小时 / 日 |
| AC5.4 | 混合推荐 | 探索（薄弱点）: 利用（已掌握回顾）≈ 3:1 |

**SM-2 算法规格：**

| 参数 | 初始值 | 范围 | 说明 |
|------|--------|------|------|
| EF (Ease Factor) | 2.5 | [1.3, +∞) | 难易度因子，越高表示越容易记住 |
| 首次通过间隔 | 1 天 | — | 连续正确 1 次后隔 1 天复习 |
| 二次通过间隔 | 6 天 | — | 连续正确 2 次后隔 6 天复习 |
| 后续间隔公式 | `interval × EF` | — | 第 3 次及以后按 EF 倍增 |
| 失败时重置 | interval=1, repetitions=0 | — | 答错回到初始间隔 |
| 通过阈值 | quality ≥ 3 | [0, 5] | 评分 ≥ 3 算通过 |
| 掌握度更新 (EMA) | `α=0.3, decay=0.4` | — | 正确 MA+=α(1-MA)，错误 MA*=decay |

---

### F6 仪表盘

**用户故事：**
> 作为一名学生，我希望打开首页就能看到我的学习概览——掌握了多少、今天要复习什么、最近学得怎么样。

**MVP 范围：**

- 3 个数字卡片：已掌握知识点数 / 学习中 / 待复习
- 最近 5 次作答记录列表（含得分和诊断摘要）
- 今日待复习清单（按优先级排序）

---

### F7 错题本

**用户故事：**
> 作为一名学生，我希望回顾我所有做错的题目，点开能看正确答案、解析和当时犯的错误诊断。

**MVP 范围：**

- 按时间倒序列出所有错题
- 点击展开查看正确答案、详细解析、迷思概念标签
- 支持按知识点 / 错误类别过滤

---

### F8 苏格拉底式引导（P2，时间允许时实现）

**用户故事：**
> 作为一名学生，当我答错时，我不希望系统直接告诉我正确答案——我希望它给我一条提示，引导我自己想出来。

**验收标准：**

| ID | 标准 | 量化指标 |
|----|------|---------|
| AC8.1 | 提示分层 | 3 层（笼统 → 方向 → 接近答案） |
| AC8.2 | 触发控制 | 连续答错 N 次后触发对应层级的提示 |
| AC8.3 | 自适应跳过 | 掌握度 ≥ 0.7 的学生自动跳过提示 |

---

## 第 4 章 · 非功能需求

### 4.1 性能

| 指标 | 目标 | 测量方法 |
|------|------|---------|
| PDF 解析（50 页） | ≤ 30 s | 计时器 |
| 单次出题（10 题） | ≤ 20 s | 计时器 |
| 批量批改（10 题） | ≤ 3 s | 计时器 |
| 向量语义检索 | ≤ 2 s | 计时器 |
| 前端首屏加载 | ≤ 3 s | Lighthouse |
| API 响应（非 LLM） | ≤ 200 ms | p95 |

### 4.2 可用性

- 所有 LLM 调用有 **loading 状态** 和 **超时提示**（60s）
- 错误消息对用户友好——不展示堆栈信息，展示可操作的指导语
- 关键操作（上传、出题、提交）提供 **撤销 / 重试** 按钮

### 4.3 安全性

- API Key 通过环境变量 `TUTOR_API_KEY` 注入，不硬编码
- LLM 调用通过后端代理，前端不直接持有 API Key
- 无用户认证体系（本地单用户场景，MVP 边界内）

### 4.4 可维护性

- 核心模块（chunker, quiz_engine, scheduler）单元测试覆盖率 ≥ 70%
- 所有公共 API 有完整 docstring（Google Style）
- 提交遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范

### 4.5 兼容性

| 组件 | 最低版本 |
|------|---------|
| Python | ≥ 3.11 |
| Node.js | ≥ 18 |
| 浏览器 | Chrome / Firefox / Edge 最新两个大版本 |

---

## 第 5 章 · 数据模型规范

### 5.1 实体关系图

```
Material (1) ────< (N) KnowledgeChunk ────< (N) KnowledgeNode
                                                 │
                                          (N) ───┼─── (N)
                                                 │
                                          KnowledgeEdge
                                                 │
Question (N) >──── (N) KnowledgeNode             │
   │                                              │
   │ (1)                                         │
   ▼                                             │
QuizSession (1) ──< (N) QuizAttempt ────> MisconceptionTag
                          │
                          │ (1)
                          ▼
                   MasteryRecord ──> KnowledgeNode (1)
                          │
                          │ (N)
                          ▼
                      StudyPlan (1) ──< (N) ReviewItem
                          │
                          ▼
                   StudentProfile (1)
```

### 5.2 核心模型摘要

> 完整定义见 `super_tutor/models/` 下的 Pydantic 模型文件。以下为关键字段摘要。

#### Material（学习材料）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `material_id` | UUID | 是 | 主键 |
| `title` | str(256) | 是 | 材料标题 |
| `subject` | str | 否 | 学科 |
| `source_type` | enum | 是 | pdf_upload / url / manual |
| `total_pages` | int | 否 | 总页数 |
| `chunk_ids` | list[UUID] | 否 | 关联的 KnowledgeChunk ID |

#### KnowledgeChunk（知识片段）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `chunk_id` | UUID | 是 | 主键 |
| `material_id` | FK | 是 | 外键 → Material |
| `content` | str | 是 | 原文 |
| `summary` | str(256) | 是 | 摘要（用于向量化索引） |
| `page_start/end` | int | 否 | 页码范围（0-based） |
| `topic` | str | 否 | 主题标签 |
| `difficulty` | enum | 否 | beginner/easy/medium/hard/expert |
| `keywords` | list[str] | 否 | 检索关键词 |
| `knowledge_node_ids` | list[UUID] | 否 | 关联的知识节点 |

#### Question（题目）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `question_id` | UUID | 是 | 主键 |
| `type` | enum | 是 | 7 种题型 |
| `difficulty` | enum | 是 | 难度等级 |
| `stem` | str | 是 | 题干（Markdown） |
| `options` | list[dict] | 否 | 选项（选择题/匹配题） |
| `correct_answer` | any | 是 | 正确答案（格式依题型而定） |
| `explanation` | str | 是 | 详细解析 |
| `hints` | list[str] | 否 | 渐进式提示 |
| `knowledge_node_ids` | list[UUID] | 否 | 考查的知识节点 |
| `estimated_seconds` | int | 否 | 预计耗时（默认 120s） |
| `points` | float | 否 | 分值（默认 1.0） |

#### QuizAttempt（作答记录）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `attempt_id` | UUID | 是 | 主键 |
| `session_id` | FK | 是 | 外键 → QuizSession |
| `question_id` | FK | 是 | 外键 → Question |
| `student_answer` | any | 是 | 学生提交的答案 |
| `is_correct` | bool | 否 | 批改结果 |
| `score` | float | 否 | 得分 |
| `time_spent_seconds` | int | 否 | 耗时 |
| `hints_used` | int | 否 | 查看提示次数 |
| `confidence` | float | 否 | 学生自评置信度（0-1） |
| `misconception_ids` | list[UUID] | 否 | 诊断出的错误概念 |

#### MisconceptionTag（迷思概念标签）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `tag_id` | UUID | 是 | 主键 |
| `label` | str(128) | 是 | 标签名 |
| `category` | enum | 是 | 7 种错误类别 |
| `severity` | enum | 否 | minor / moderate / critical |
| `knowledge_node_ids` | list[UUID] | 否 | 关联的知识节点 |
| `remediation_hint` | str | 是 | 补救建议 |

#### MasteryRecord（掌握度记录 / 认知孪生）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `record_id` | UUID | 是 | 主键 |
| `student_id` | str | 是 | 学生标识 |
| `knowledge_node_id` | FK | 是 | 外键 → KnowledgeNode |
| `mastery_level` | float(0-1) | 是 | EMA 平滑后的掌握度 |
| `confidence` | float(0-1) | 否 | 估计置信度 |
| `total_attempts` | int | 否 | 总作答次数 |
| `correct_attempts` | int | 否 | 正确次数 |
| `streak` | int | 否 | 连续正确次数 |
| `sm2_repetitions` | int | 否 | SM-2 成功记忆次数 |
| `sm2_ease_factor` | float | 否 | SM-2 EF（默认 2.5，下限 1.3） |
| `sm2_interval_days` | int | 否 | 当前复习间隔 |
| `sm2_next_review` | date | 否 | 下次复习日期 |
| `state` | enum | 否 | new / learning / reviewing / mastered / stagnated |

#### SocraticHint（苏格拉底提示）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `hint_id` | UUID | 是 | 主键 |
| `question_id` | FK | 是 | 外键 → Question |
| `level` | int(1-3) | 是 | 1=笼统 / 2=方向 / 3=接近答案 |
| `content` | str | 是 | 提示正文 |
| `trigger_after_failures` | int | 否 | 累计答错 N 次后触发（0=立即可见） |
| `difficulty_adapt` | bool | 否 | 是否根据掌握度自适应跳过 |
| `was_helpful` | bool | 否 | 效果追踪 |

---

## 第 6 章 · API 接口规范

### 6.1 标准响应格式

所有接口统一使用以下 JSON 响应格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": { }
}
```

### 6.2 错误码定义

| 错误码 | HTTP 状态 | 含义 | 可重试 |
|--------|----------|------|:---:|
| `0` | 200 | 成功 | — |
| `1001` | 400 | 请求参数校验失败 | 否 |
| `2001` | 502 | LLM API 调用失败（超时 / 网络异常） | 是 |
| `2002` | 503 | LLM API 返回空内容 | 是 |
| `2003` | 422 | LLM JSON 输出解析失败 | 是 |
| `4001` | 400 | PDF 无可提取文本（扫描件） | 否 |
| `4002` | 502 | AI 服务暂时不可用 | 是 |
| `4003` | 422 | AI 输出格式异常 | 是 |
| `4004` | 400 | PDF 过大（> 50MB 或 > 200 页） | 否 |
| `4005` | 400 | 知识库为空，请先上传材料 | 否 |
| `5001` | 500 | 数据库异常 | 否 |
| `5002` | 500 | 内部未知错误 | 否 |

### 6.3 API 端点清单

#### 资料管理

| 方法 | 路径 | 说明 | MVP |
|:-----|------|------|:---:|
| `POST` | `/api/v1/materials/upload` | 上传 PDF，触发解析流水线 | ✅ |
| `GET` | `/api/v1/materials/{id}` | 获取材料详情 + 切片列表 | ✅ |
| `GET` | `/api/v1/materials/{id}/chunks` | 分页获取知识片段 | ✅ |
| `GET` | `/api/v1/materials/{id}/search?q=` | 语义搜索知识片段 | ✅ |

#### 出题与答题

| 方法 | 路径 | 说明 | MVP |
|:-----|------|------|:---:|
| `POST` | `/api/v1/quizzes/generate` | 基于知识库生成测验 | ✅ |
| `GET` | `/api/v1/quizzes/{id}` | 获取测验详情（题目列表） | ✅ |
| `POST` | `/api/v1/quizzes/{id}/submit` | 提交作答，触发批改+诊断 | ✅ |
| `GET` | `/api/v1/quizzes/{id}/attempts` | 获取作答记录 | ✅ |

#### 学习规划

| 方法 | 路径 | 说明 | MVP |
|:-----|------|------|:---:|
| `GET` | `/api/v1/plans/current` | 获取当前学习计划 | ✅ |
| `POST` | `/api/v1/plans/generate` | 生成 SM-2 排期计划 | ✅ |
| `PATCH` | `/api/v1/plans/{id}/items/{item_id}` | 标记复习条目完成 | ✅ |

#### 仪表盘

| 方法 | 路径 | 说明 | MVP |
|:-----|------|------|:---:|
| `GET` | `/api/v1/dashboard/overview` | 全局学习概览数据 | ✅ |
| `GET` | `/api/v1/dashboard/errors` | 错题本数据 | ✅ |
| `GET` | `/api/v1/health` | 健康检查 | ✅ |

---

## 第 7 章 · Agent 工作流规格

### 7.1 状态定义

| 状态 | 含义 | 负责 Agent | 超时 |
|------|------|-----------|:---:|
| `IDLE` | 空闲，等待用户触发 | — | — |
| `PARSING` | 解析 PDF → 切片 → 向量化 | Tutor | 120s |
| `QUIZ_GEN` | 基于知识库检索 + LLM 生成题目 | Assistant | 60s |
| `EVALUATING` | 批改作答 + 迷思概念诊断 | Evaluator | 30s |
| `PLANNING` | 综合数据生成 SM-2 排期计划 | Tutor | 60s |
| `DONE` | 本轮学习闭环完成 | — | — |
| `PAUSED` | 用户手动暂停 | — | — |
| `ERROR` | 异常中断 | — | — |

### 7.2 状态流转图

```
IDLE ──start()──▶ PARSING ──proceed()──▶ QUIZ_GEN ──proceed()──▶ EVALUATING
                      │                                                  │
                      │                                                  ▼
                      │                                       proceed() PLANNING
                      │                                                  │
                      │                                                  ▼
                      │                                        proceed() DONE
                      │
任意非终态 ──pause()──▶ PAUSED ──resume()──▶ 上一状态
任意非终态 ──异常────▶ ERROR  ──retry_step()──▶ 失败状态 (最多 3 次)
```

### 7.3 Agent 角色与 Prompt 映射

| Agent | RoleManager Key | Prompt 文件 | LLM 档位 | 职责 |
|-------|----------------|-------------|---------|------|
| Tutor（主导师） | `tutor` | `prompts/tutor.md` | heavy（解析）/ medium（规划） | PDF 解析 + 排期计划 |
| Assistant（助教） | `assistant` | `prompts/assistant.md` | heavy | 检索知识库 + 出题 |
| Evaluator（评估者） | `evaluator` | `prompts/evaluator.md` | medium | 批改 + 迷思概念诊断 |

---

## 第 8 章 · 风险登记册

| 风险 ID | 风险描述 | 概率 | 影响 | 缓解措施 |
|---------|---------|:---:|:---:|---------|
| R1 | DeepSeek API 服务不稳定 | 中 | 高 | 指数退避重试 3 次 + 友好错误提示；LLMClient 已内置重试 |
| R2 | LLM JSON 输出格式不合法 | 中 | 中 | 4 层防御 JSON 解析；95% 成功率即可接受；剩余 5% 提示用户重试 |
| R3 | PDF 文本提取质量低（扫描件/图片） | 中 | 低 | 明确错误码 4001 + 提示上传文字型 PDF |
| R4 | SQLite 向量扩展加载失败 | 低 | 低 | 自动降级为 LIKE 搜索 + 相关度打分 |
| R5 | 前端开发时间不足 | 高 | 中 | 后端优先策略：API + 数据模型先完工，前端做最简可演示版 |
| R6 | 答辩演示时 API 不可用 | 低 | 高 | 准备录屏备份；提供离线 demo 模式 |
| R7 | 单次 LLM 调用超时 | 低 | 中 | 60s 超时 + 重试；分段处理大 PDF |

---

## 第 9 章 · 测试策略

### 9.1 测试金字塔

```
           ┌─────┐
           │ E2E │  2 个场景：上传→做题→排期 全链路
           ├─────┤
           │集成 │  5 个：LLM调用、数据库CRUD、向量检索、PDF解析、状态机
           ├─────┤
           │单元 │  12+ 个：chunker、JSON解析、SM-2算法、模型校验、异常处理
           └─────┘
```

### 9.2 关键测试用例

| 模块 | 测试用例 | 优先级 |
|------|---------|:---:|
| chunker | 正常 Markdown PDF → 正确识别标题并切片 | P0 |
| chunker | 无标题 PDF → 降级为 ParagraphChunker | P0 |
| JSON 解析 | 4 层防御各层能正确解析对应格式 | P0 |
| JSON 解析 | 垃圾文本 → 返回空列表不抛异常 | P0 |
| SM-2 | 连续正确 3 次 → 间隔按预期增长 | P0 |
| SM-2 | 答错 1 次 → interval 重置为 1 天 | P0 |
| 模型校验 | KnowledgeChunk 构造后 page_end 自动补齐 | P1 |
| 模型校验 | 非法 page 范围 → ValueError | P1 |
| 状态机 | IDLE → start → PARSING → proceed → ... → DONE | P0 |
| 状态机 | 任意状态 → pause → resume → 恢复正确 | P1 |
| 状态机 | ERROR → retry_step 超过 3 次 → 保持 ERROR | P1 |

---

## 附录 A · 参考资源

| 资源 | URL |
|------|-----|
| SuperMemo SM-2 Algorithm | https://www.supermemo.com/en/blog/application-of-a-computer-to-improve-the-results-obtained-in-working-with-the-supermemo-method |
| sqlite-vec | https://github.com/asg017/sqlite-vec |
| Bloom's Taxonomy | https://bloomstaxonomy.net/ |
| FSRS (Anki 新一代排期) | https://github.com/open-spaced-repetition/fsrs4anki |
| PyMuPDF | https://pymupdf.readthedocs.io/ |
| FastAPI | https://fastapi.tiangolo.com/ |
| Pydantic v2 | https://docs.pydantic.dev/latest/ |

---

## 附录 B · 词汇表

| 术语 | 英文 | 定义 |
|------|------|------|
| 检索增强生成 | RAG | 先从知识库检索相关内容，再提交给 LLM 生成回答的技术范式 |
| 嵌入向量 | Embedding | 将文本映射到高维向量空间的数值表示，语义相似的文本在向量空间中距离近 |
| K 近邻 | KNN | 在向量空间中搜索距离最近的 K 个邻居的算法 |
| 间隔重复 | Spaced Repetition | 根据遗忘曲线在最佳时机安排复习的学习方法 |
| 难易度因子 | Ease Factor (EF) | SM-2 算法核心参数，反映知识点的记忆难度 |
| 指数移动平均 | EMA | 一种加权平均方法，越新的数据权重越大，用于平滑掌握度 |
| 认知孪生 | Cognitive Twin | 为每个知识点建立数学化的学生掌握度模型 |
| 迷思概念 | Misconception | 学生头脑中与科学概念不一致的认知结构（错误理解） |
| 苏格拉底式教学 | Socratic Method | 通过提问引导学生自主发现答案，而非直接告知的教育方法 |
| 布鲁姆分类法 | Bloom's Taxonomy | 将认知目标分为记忆/理解/应用/分析/评价/创造六个层次的教育分类框架 |
