"""Forge Engine custom exception hierarchy.

Defines a project-level exception tree so callers can catch fine-grained
error types instead of relying on built-in exceptions.
"""

# ---------------------------------------------------------------------------
# Shared constant — valid role identifiers used by both LLMClient and
# RoleManager for input validation.
# ---------------------------------------------------------------------------
VALID_ROLES: frozenset[str] = frozenset({"claude-a", "codex", "claude-b"})


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
