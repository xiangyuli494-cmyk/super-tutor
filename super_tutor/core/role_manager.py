"""Role system-prompt loader and context builder."""

import logging
from pathlib import Path

from super_tutor.core.exceptions import ConfigurationError, VALID_ROLES

logger = logging.getLogger(__name__)

# Constitution summary character limit to avoid blowing the context window.
_CONSTITUTION_MAX_CHARS = 6000


class RoleManager:
    """Loads role system-prompt templates and builds execution context.

    Templates are cached in memory after the first read to avoid repeated
    file-system access.

    Usage::

        mgr = RoleManager(prompts_dir="forge-engine/prompts")
        system_prompt = mgr.build_context(
            role="codex",
            project_path="/home/user/projects/demo",
            extra_context={"current_module": "m2-llm-client", "token_budget": "12000"},
        )
    """

    def __init__(self, prompts_dir: str) -> None:
        """Initialise the manager.

        Args:
            prompts_dir: Path to the directory containing role ``.md``
                template files.  Expected layout::

                    {prompts_dir}/claude-a.md
                    {prompts_dir}/codex.md
                    {prompts_dir}/claude-b.md
        """
        self._prompts_dir = Path(prompts_dir)
        self._cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_system_prompt(self, role: str) -> str:
        """Load the system-prompt template for *role*.

        Reads ``{prompts_dir}/{role}.md``.  Results are cached so
        subsequent calls for the same role do not touch disk.

        Args:
            role: One of ``"claude-a"``, ``"codex"``, ``"claude-b"``.

        Returns:
            The raw markdown template content.

        Raises:
            ConfigurationError: If *role* is not a recognised role name
                or if the template file does not exist.
        """
        if role not in VALID_ROLES:
            raise ConfigurationError(
                f"Unknown role '{role}'. Expected one of: {sorted(VALID_ROLES)}"
            )

        if role in self._cache:
            return self._cache[role]

        template_path = self._prompts_dir / f"{role}.md"
        if not template_path.is_file():
            raise ConfigurationError(f"Role template not found: {template_path}")

        content = template_path.read_text(encoding="utf-8")
        self._cache[role] = content
        logger.info("Loaded system prompt for role=%s from %s", role, template_path)
        return content

    def build_context(
        self,
        role: str,
        project_path: str,
        extra_context: dict[str, str] | None = None,
    ) -> str:
        """Build a complete system prompt by merging the role template with
        project-level context.

        The returned string is composed of three sections:

        1. The role's system-prompt template (see ``load_system_prompt``).
        2. A snapshot of the project constitution
           (``{project_path}/constitution/constitution.md``), if present.
        3. Key-value pairs from *extra_context* injected as a
           "运行时上下文" block.

        Args:
            role: Target role identifier.
            project_path: Root path of the active Forge project directory.
            extra_context: Optional key-value pairs describing the current
                execution environment (e.g. ``{"current_module": "m2-llm-client",
                "token_budget_remaining": "15000"}``).

        Returns:
            The fully assembled system prompt string ready to be passed as
            the ``system`` message to an LLM.
        """
        parts: list[str] = []

        # 1. Core role template
        template = self.load_system_prompt(role)
        parts.append(template)

        # 2. Project constitution snapshot
        constitution = self._read_constitution(project_path)
        if constitution:
            parts.append("\n## 项目宪法摘要\n")
            parts.append(constitution)

        # 3. Runtime context
        if extra_context:
            parts.append("\n## 运行时上下文\n")
            for key, value in extra_context.items():
                parts.append(f"- **{key}**: {value}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_constitution(project_path: str) -> str | None:
        """Read the project constitution and return its content.

        Returns ``None`` if the constitution file is missing or unreadable.
        Content is truncated to ``_CONSTITUTION_MAX_CHARS`` to avoid
        consuming excessive context window space.
        """
        constitution_path = Path(project_path) / "constitution" / "constitution.md"
        if not constitution_path.is_file():
            logger.debug("No constitution found at %s", constitution_path)
            return None

        try:
            text = constitution_path.read_text(encoding="utf-8")
            if len(text) > _CONSTITUTION_MAX_CHARS:
                text = text[:_CONSTITUTION_MAX_CHARS] + "\n\n... (宪法内容已截断)"
            return text
        except OSError as exc:
            logger.warning("Failed to read constitution at %s: %s", constitution_path, exc)
            return None
