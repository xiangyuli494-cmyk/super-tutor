"""Super Tutor — 自定义异常体系。

定义项目级异常树，让调用方能捕获细粒度错误类型，
避免依赖内置异常做控制流。
"""

from super_tutor.models.enums import AIRole

# ---------------------------------------------------------------------------
# 有效角色标识符（单一数据源：从 AIRole 枚举派生）
#
# 设计原则：任何模块需要校验角色时都引用这个常量，不手写角色名列表。
# ---------------------------------------------------------------------------
VALID_ROLES: frozenset[str] = frozenset(role.value for role in AIRole)


class TutorError(Exception):
    """Super Tutor 所有自定义异常的基类。

    项目内所有自定义异常都应继承自本类，
    使调用方能通过 ``except TutorError`` 捕获所有项目级错误。
    """


class LLMClientError(TutorError):
    """LLM 客户端层错误。

    在 API 调用重试耗尽、返回空内容或传输层故障时抛出。
    """


class ConfigurationError(TutorError):
    """配置相关错误。

    在设置无效、角色/算力档位无法识别、必要文件缺失、
    配置值格式错误或路径安全违规时抛出。
    """
