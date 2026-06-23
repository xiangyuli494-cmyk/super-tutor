# super-tutor-agent

基于 Multi-Agent 协作的专属"超级私教"——认知孪生驱动的深度学习辅助系统。

## 项目定位

扣子能做"知识库问答 + 简单出题"，我们做的是**认知建模**：

- **迷思概念诊断** — 不只判对错，分析你"为什么错"
- **认知孪生** — FSRS 算法为每个知识点建立数学化的掌握度模型
- **苏格拉底式教学** — 不是直接给答案，是引导你自己发现答案

## 三个 AI Agent

| Agent | 职责 |
|-------|------|
| 资料解析 Agent (Parser) | PDF 切片 + 向量索引 + 知识依赖图构建 |
| 出题与测验 Agent (QuizMaster) | 迷思概念诊断 + 苏格拉底式追问 |
| 规划 Agent (Planner) | FSRS 排期 + 认知孪生建模 + 元认知报告 |

## 技术栈

- 后端：Python FastAPI + SQLite + sqlite-vec
- 前端：React + TypeScript + Tailwind CSS
- AI：DeepSeek API（兼容 OpenAI SDK）
- 算法：SM-2 / FSRS 间隔重复

## 快速开始

```bash
# 后端
pip install -r requirements.txt
python -m super_tutor.main

# 前端
cd frontend
npm install
npm run dev
```

## 项目结构

```
super-tutor-agent/
├── super_tutor/          # Python 后端
│   ├── main.py
│   ├── config.py
│   ├── models/           # 数据模型
│   ├── core/             # 核心引擎
│   ├── routes/           # API 路由
│   └── prompts/          # Agent System Prompt
├── frontend/             # React 前端
├── docs/                 # 需求文档 + 计划表
└── requirements.txt
```
