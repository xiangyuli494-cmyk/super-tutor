"""Core 基础设施层 — 数据库、LLM 客户端和异常定义。

【功能说明】
提供整个系统的底层基础设施，包括：
1. database.py  — SQLite 异步数据库管理器（6 表 + 25+ CRUD 方法）
2. llm_client.py — DeepSeek API 异步客户端（OpenAI SDK 封装，指数退避重试）
3. exceptions.py — 3 层异常体系（TutorError → LLMError / MaterialError）

【耦合关系】
- 被 engine/ 层的所有 5 个引擎依赖（KnowledgeEngine、QuizEngine、
  AssessmentEngine、PlanEngine、SocraticEngine）
- 被 app.py 的 _init_services() 直接创建 Database 和 LLMClient 实例
- 不依赖 engine/ 和 models/（底层基础设施，向下不依赖业务层）
- database.py 仅依赖 aiosqlite（外部库）
- llm_client.py 依赖 openai（外部库）+ core/exceptions.py（内部异常）
"""
