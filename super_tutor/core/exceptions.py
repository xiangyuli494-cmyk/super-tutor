"""Super Tutor Agent — 自定义异常体系。

定义项目级异常树，让调用方能捕获细粒度错误类型，
避免依赖内置异常做控制流。
"""

from super_tutor.models.enums import AgentRole

# ---------------------------------------------------------------------------
# 有效角色标识符（单一数据源：从 AgentRole 枚举派生）
#
# 设计原则：任何模块需要校验角色时都引用这个常量，不手写角色名列表。
# 过渡期通过 | 运算保留 Forge 旧角色名，orchestrator 重构后删除。
# ---------------------------------------------------------------------------
VALID_ROLES: frozenset[str] = (
    frozenset(role.value for role in AgentRole)
    | {"claude-a", "codex", "claude-b"}  # TODO: orchestrator 重构后移除
)


class ForgeError(Exception):
    """Base exception for all Forge Engine errors.

    All custom exceptions raised within the Forge Engine should inherit
    from this class, enabling callers to catch ``ForgeError`` as a
    blanket handler for engine-specific failures.
    """


class LLMClientError(ForgeError):
    """Errors originating from the LLM client layer.

    Raised when an LLM API call fails after exhausting retries, returns
    empty content, or encounters a transport-level issue that cannot be
    recovered from.
    """


class ConfigurationError(ForgeError):
    """Configuration-related errors.

    Raised for invalid settings, unrecognised tier/role identifiers,
    missing required files, malformed configuration values, or
    path-security violations.
    """
