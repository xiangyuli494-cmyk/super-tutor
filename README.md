# 超级私教 (Super Tutor Agent)

**基于 Multi-Agent 协作的认知孪生驱动深度学习辅助系统**

> 不是「问答机器人」——是持续追踪你每个知识点掌握度的**认知孪生私教**。

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Status](https://img.shields.io/badge/Status-MVP%20开发中-orange)]()

---

## 目录

- [项目概述](#项目概述)
- [与竞品的核心差异](#与竞品的核心差异)
- [系统架构](#系统架构)
- [三个 AI Agent](#三个-ai-agent)
- [Agent 工作流](#agent-工作流)
- [功能矩阵 (MVP)](#功能矩阵-mvp)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [API 概览](#api-概览)
- [技术栈](#技术栈)
- [文档](#文档)

---

## 项目概述

超级私教是一个**基于 Multi-Agent 协作的认知孪生驱动深度学习辅助系统**。用户上传 PDF 教材后，三个 AI Agent（Tutor / Assistant / Evaluator）协作完成「资料解析 → 自适应出题 → 智能排期」的完整学习闭环。

### 目标用户

- **大学生**：专业课教材 PDF 多，备考压力大，需要系统化复习工具
- **考研 / 考公人群**：长期备考（3-12 个月），SM-2 排期天然适配
- **自学编程 / 技术人群**：大量技术文档需要结构化理解和测验

---

## 与竞品的核心差异

| 维度 | 扣子 / ChatGPT | 超级私教（本系统） |
|------|---------------|-------------------|
| 交互模式 | 单轮 / 多轮对话 | 持续性学习闭环 |
| 知识管理 | 每次对话独立 | PDF 上传后持久化向量索引 |
| 题目生成 | 一次性批量输出 | 基于掌握度薄弱点的**自适应出题** |
| 学习追踪 | 无 | 每个知识点的**认知孪生**（EMA 掌握度 + SM-2 排期） |
| 错误诊断 | 判对错 + 给答案 | **迷思概念分类** + 苏格拉底式引导提示 |
| 架构 | 单一模型 | 三 Agent 状态机协作 |

---

## 系统架构

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
│  │              Orchestrator (状态机)                    │    │
│  │   IDLE → PARSING → QUIZ_GEN → EVALUATING → PLANNING   │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │  Tutor Agent│  │Assistant Agent│  │ Evaluator Agent  │    │
│  │  (Parser +  │  │  (QuizMaster) │  │  (Auto-grading + │    │
│  │   Planner)  │  │               │  │   Diagnosis)     │    │
│  └──────┬──────┘  └──────┬───────┘  └───────┬──────────┘    │
│         │                │                   │                │
│  ┌──────▼────────────────▼───────────────────▼──────────┐    │
│  │                  LLM Client (DeepSeek API)            │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │      SQLite + sqlite-vec (结构化 + 向量检索)          │    │
│  └──────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────┘
```

---

## 三个 AI Agent

| Agent | 角色 | 职责 | System Prompt |
|-------|------|------|---------------|
| **Tutor** | 主导师 | PDF 解析 → 知识切片；综合评估 → SM-2 排期学习计划 | `prompts/tutor.md` |
| **Assistant** | 助教 | 基于知识库生成测验题目（Bloom 难度分层） | `prompts/assistant.md` |
| **Evaluator** | 评估者 | 批改作答 → 迷思概念诊断 → 苏格拉底式引导提示 | `prompts/evaluator.md` |

---

## Agent 工作流

```
IDLE ──start()──▶ PARSING ──proceed()──▶ QUIZ_GEN
                                            │
                                    submit_answers()  ← 学生作答（断点）
                                            │
                                            ▼
                        DONE ◀── PLANNING ◀── EVALUATING
                          ▲         ▲            ▲
                          └─proceed()┘─proceed()──┘
```

状态机由 `Orchestrator` 驱动，通过 `super_tutor/models/enums.py` 中的 `WorkflowState` 枚举管理 8 个活跃状态 + 3 个旧版兼容状态。

---

## 功能矩阵 (MVP)

| 优先级 | 功能 | 描述 | 工期 | 验收标准 |
|--------|------|------|------|---------|
| **P0** | F1 资料上传与解析 | 单 PDF → PyMuPDF 提取 → 切片 → 向量化 | Day 2 | PDF ≤50MB 成功率 ≥95% |
| **P0** | F2 自动出题 | 基于知识库生成 10 道选择题 | Day 3 | 题目与 chunk 关联覆盖率 ≥80% |
| **P0** | F3 在线作答与批改 | 选择题即时判定 + 简答题 LLM 批改 | Day 4 | 批改准确率 ≥90% |
| **P0** | F4 迷思概念诊断 | 错题自动打标签（7 种类别） | Day 4 | 标签至少命中 1 个 |
| **P0** | F5 SM-2 排期计划 | 基于作答历史生成间隔重复复习计划 | Day 5 | 每个知识点有下次复习日期 |
| **P1** | F6 仪表盘 | 掌握度概览 + 今日待复习清单 | Day 6 | 数据刷新 ≤2s |
| **P1** | F7 错题本 | 错题按时间倒序浏览 + 诊断和解析 | Day 6 | 加载 ≤1s |
| **P2** | F8 苏格拉底式追问 | 错题展示 3 层渐进式提示 | Day 7 | 3 层提示可触发 |

### 明确不做的功能 (Out of Scope)

- 多课程 / 多科目管理体系
- 用户账号系统与权限管理
- 知识图谱可视化（D3.js / Canvas 渲染）
- PDF 图片与表格结构化解析
- 语音 / 图片输入
- FSRS 全参数优化算法（当前采用简化 SM-2）
- 实时协作与分享功能
- WebSocket 推送通知

---

## 快速开始

### 前置要求

- Python 3.11+
- Node.js 18+
- DeepSeek API Key

### 后端

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 API 服务
python -m super_tutor.main
# API 文档自动生成于 http://localhost:8000/docs
```

### 前端

```bash
cd frontend
npm install
npm run dev
# 开发服务器启动于 http://localhost:5173
```

### 配置文件

在 `~/.super-tutor/settings.json` 中配置 API Key：

```json
{
    "deepseek_api_key": "sk-your-key-here",
    "deepseek_base_url": "https://api.deepseek.com",
    "token_budget_default": 1000000
}
```

也可通过环境变量覆盖：`TUTOR_API_KEY`、`TUTOR_API_BASE_URL`、`TUTOR_TOKEN_BUDGET`。

---

## 项目结构

```
super-tutor-agent/
├── super_tutor/                # Python 后端
│   ├── __init__.py             # 包描述
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # TutorConfig 配置管理
│   ├── models/                 # 数据模型层 (19 个 Pydantic 模型)
│   │   ├── enums.py            #   5 个枚举 (AgentRole, WorkflowState, ...)
│   │   ├── knowledge.py        #   5 个模型 (KnowledgeChunk, KnowledgeGraph, ...)
│   │   ├── quiz.py             #   6 个模型 (Question, QuizSession, SocraticHint, ...)
│   │   └── mastery.py          #   4 个模型 (MasteryRecord, StudyPlan, ...)
│   ├── core/                   # 核心引擎
│   │   ├── orchestrator.py     #   状态机编排器
│   │   ├── database.py         #   SQLite + sqlite-vec 持久层
│   │   ├── llm_client.py       #   DeepSeek API 客户端
│   │   ├── role_manager.py     #   Agent System Prompt 管理
│   │   ├── token_tracker.py    #   Token 统计与预算
│   │   └── exceptions.py       #   异常体系 (TutorError 基类)
│   ├── prompts/                # Agent System Prompt 模板
│   │   ├── tutor.md            #   Tutor Agent
│   │   ├── assistant.md        #   Assistant Agent
│   │   └── evaluator.md        #   Evaluator Agent
│   └── routes/                 # API 路由
├── frontend/                   # React 前端 (SPA)
├── docs/                       # 文档
│   └── PRD.md                  # 产品需求规格说明书 (v2.0)
├── requirements.txt
└── README.md
```

---

## API 概览

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/v1/materials/upload` | 上传 PDF 材料 |
| `GET` | `/api/v1/materials/{id}/status` | 查询材料解析状态 |
| `POST` | `/api/v1/sessions` | 创建测验会话 |
| `GET` | `/api/v1/sessions/{id}/questions` | 获取测验题目 |
| `POST` | `/api/v1/sessions/{id}/answers` | 提交作答 |
| `GET` | `/api/v1/sessions/{id}/results` | 获取批改结果 |
| `POST` | `/api/v1/sessions/{id}/plan` | 生成复习计划 |
| `GET` | `/api/v1/students/{id}/dashboard` | 获取仪表盘数据 |
| `GET` | `/api/v1/students/{id}/mastery` | 获取掌握度明细 |
| `GET` | `/api/v1/students/{id}/wrong-questions` | 获取错题本 |
| `GET` | `/api/v1/students/{id}/plan/today` | 获取今日复习清单 |
| `GET` | `/api/v1/tokens/stats` | 获取 Token 用量统计 |
| `GET` | `/health` | 健康检查 |

标准响应格式：

```json
{
    "code": 0,
    "message": "success",
    "data": { ... }
}
```

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **后端框架** | FastAPI ≥ 0.115 | 异步支持、自动 OpenAPI 文档 |
| **ASGI** | Uvicorn ≥ 0.30 | FastAPI 官方推荐 |
| **LLM** | DeepSeek API (OpenAI SDK 兼容) | 三档算力 (heavy/medium/light) |
| **数据库** | SQLite + aiosqlite + sqlite-vec | 零运维嵌入式向量检索 |
| **PDF 解析** | PyMuPDF ≥ 1.24 | 文本提取精度最高 |
| **数据校验** | Pydantic ≥ 2.0 | FastAPI 原生集成 |
| **前端** | React 18 + TypeScript + Tailwind CSS 3 | 生态最丰富 |
| **状态管理** | Zustand 4 | 轻量无 boilerplate |
| **算法** | SM-2 / EMA 掌握度估计 | 间隔重复 + 认知孪生建模 |
| **测试** | pytest + pytest-asyncio ≥ 8.0 | Python 标准测试框架 |

---

## 文档

- **[PRD.md](docs/PRD.md)** — 完整产品需求规格说明书 (v2.0, 687 行)，包含 9 章 + 风险登记册 + 测试策略 + 错误码体系
- **Agent Prompt 模板** — `super_tutor/prompts/` 目录下三个 Agent 的系统提示词

---

## License

MIT © 2026 xiangyuli494-cmyk
