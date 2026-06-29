"""Super Tutor — 多角色智能教学系统后端引擎。

【功能说明】
本包是整个系统的后端核心，包含配置管理、数据库持久化、LLM 客户端、
5 个业务引擎（知识点解析、出题批改、诊断评估、学习计划、苏格拉底追问）
和 8 个 Pydantic 数据模型。

【子包结构】
- config.py               — 全局配置（从文件+环境变量加载）
- core/                   — 基础设施层（数据库、LLM 客户端、异常）
- engine/                 — 业务引擎层（5 个无状态引擎）
- models/                 — 数据模型层（Pydantic + 枚举）
- prompts/                — LLM 提示词模板（5 个 Markdown 文件）

【耦合关系】
- 被 app.py（Streamlit 前端）导入和编排
- core/ 不依赖 engine/ 和 models/（底层基础设施）
- engine/ 依赖 core/ 和 models/（业务逻辑层）
- models/ 仅依赖自身的 enums.py 和 pydantic（纯数据结构）
- 对外零依赖（不依赖其他项目包）
"""
