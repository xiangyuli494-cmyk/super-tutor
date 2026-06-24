# 超级私教 (Super Tutor)

<br>

> **扔给它一本 PDF 教材。它读、它出题、它批改、它诊断你错在哪、它帮你排复习计划。**
>
> 三个 AI 角色协作，像一个真正的私教一样盯住你每个知识点的掌握程度。

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Status](https://img.shields.io/badge/Status-MVP%20开发中-orange)]()
[![Tests](https://img.shields.io/badge/Tests-18/18%20passed-brightgreen)]()

---

## 它做了什么

你扔给它一本《大学物理》PDF，它自动完成 4 件事：

```
📄 上传 PDF           🤖 AI 出题              ✍️ 你答题               📊 它排计划
┌──────────┐         ┌──────────┐         ┌──────────┐         ┌──────────┐
│ 教材 PDF  │ ───→   │ 自动生成  │  ───→  │ 在线作答  │  ───→  │ 间隔重复 │
│ 智能解析  │        │ 自适应测验 │        │ 即时批改  │        │ 复习排期 │
│ 向量索引  │        │ 难度分层  │        │ 错因诊断  │        │ 今日清单 │
└──────────┘         └──────────┘         └──────────┘         └──────────┘
```

> 不是「问答机器人」。是持续追踪你每个知识点掌握度的**认知孪生私教**。

### 面向谁

| 用户 | 痛点 | 超级私教怎么帮 |
|------|------|---------------|
| 🎓 大学生 | 专业课 PDF 堆积如山，不知道从哪复习起 | 上传即解析，薄弱点优先出题 |
| 📝 考研 / 考公 | 备考周期长（3-12 个月），学了忘忘了学 | SM-2 间隔重复，该复习时自动提醒 |
| 💻 自学编程 | 技术文档看完记不住，不知道自己到底会没会 | 自动出题检验，诊断 ≠ 判对错 |

---

## 快速开始

### 前置要求

- Python 3.11+
- Node.js 18+
- DeepSeek API Key

### 后端

```bash
pip install -r requirements.txt
python -m super_tutor.main
# API 文档自动生成于 http://localhost:8765/docs
```

### 前端

```bash
cd frontend
npm install
npm run dev
# 开发服务器启动于 http://localhost:5173
```

### 配置

在 `~/.super-tutor/settings.json` 中配置 API Key：

```json
{
    "deepseek_api_key": "sk-your-key-here",
    "deepseek_base_url": "https://api.deepseek.com",
    "token_budget_default": 1000000
}
```

也可通过环境变量：`TUTOR_API_KEY`、`TUTOR_API_BASE_URL`、`TUTOR_TOKEN_BUDGET`。

---

## 测试

```bash
python -m pytest tests/ -v
# 18 passed
```

---

## 文档

| 文档 | 说明 |
|------|------|
| [**requirements.md**](docs/requirements.md) | 产品需求规格说明书：项目概述、功能需求（用户故事 + 验收标准）、非功能需求、风险登记册、词汇表 |
| [**architecture.md**](docs/architecture.md) | 技术架构文档：系统架构图、项目结构、数据模型（7 个核心实体）、API 接口规范（13 个端点）、流水线工作流、SM-2 算法规格、4 层 JSON 防御解析、测试策略 |

---

## License

MIT © 2026 xiangyuli494-cmyk
