"""CLI backend for Super Tutor.

Routes chat requests through the ``claude`` CLI binary instead of the
DeepSeek API, passing file paths directly to avoid token overhead.

.. note::

    The CLI backend is activated by setting ``cli_mode=True`` on
    :class:`LLMClient`.  When disabled (the default), all chat requests
    flow through the API client instead.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from super_tutor.core.exceptions import ConfigurationError, LLMClientError

if TYPE_CHECKING:
    from super_tutor.config import TutorConfig

logger = logging.getLogger(__name__)

# CLI binary name — may be extended to support "codex" in the future.
_CLI_BINARY = "claude"


class CLIBackend:
    """Invoke the Claude Code CLI for file-context chat requests.

    The backend reads referenced files from disk (with an optional
    project-root sandbox) and passes them to the ``claude`` binary via
    subprocess.  System prompts are forwarded through
    ``--append-system-prompt``.
    """

    def __init__(
        self,
        config: "TutorConfig",
        project_root: str | None = None,
    ) -> None:
        """Initialise the CLI backend.

        Args:
            config: TutorConfig instance (retained for future extension
                such as per-tier model overrides or CLI flags).
            project_root: Root directory used for file-sandbox checks.
                When ``None``, file reading is disabled (same constraint
                as :class:`LLMClient`).

        Raises:
            ConfigurationError: If the ``claude`` binary is not found on
                ``PATH``.
        """
        self._config = config
        self._project_root = Path(project_root).resolve() if project_root else None

        # Fail-fast: ensure the CLI binary is available.
        self._binary_path = shutil.which(_CLI_BINARY)
        if self._binary_path is None:
            raise ConfigurationError(
                f"CLI mode is enabled but '{_CLI_BINARY}' was not found on PATH. "
                f"Install the Claude Code CLI or set cli_mode=False to use the API."
            )
        logger.info("CLI backend ready — using %s at %s", _CLI_BINARY, self._binary_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat_with_file_context(
        self,
        *,
        role: str,
        user_message: str,
        files: list[str],
        tier: str,
        system_prompt: str | None = None,
    ) -> str:
        """Send a message with referenced files to the CLI.

        Args:
            role: Logical role name (informational; not used by the CLI).
            user_message: The user's question or instruction.
            files: List of file paths to include as context.
            tier: Computation tier (informational; CLI runs at full capacity).
            system_prompt: Optional system prompt passed via
                ``--append-system-prompt``.

        Returns:
            The stdout text from the CLI.

        Raises:
            LLMClientError: If the CLI exits with a non-zero code or
                produces empty output.
            ConfigurationError: If *project_root* is not configured but
                file reading is attempted.
        """
        # Build the full prompt: system prompt (if any) + file contents + user message.
        parts: list[str] = []

        if system_prompt:
            parts.append(system_prompt)

        if files:
            parts.append("\n---\n## 参考文件内容\n")
            for path in files:
                try:
                    content = await asyncio.to_thread(self._read_file, path)
                    parts.append(f"### {path}\n```\n{content}\n```\n")
                except (OSError, ConfigurationError) as exc:
                    logger.warning("Cannot read context file %s: %s", path, exc)
                    parts.append(f"### {path}\n[读取失败: {exc}]\n")

        parts.append(user_message)
        merged_prompt = "\n".join(parts)

        logger.debug(
            "Invoking %s CLI (role=%s, tier=%s, files=%d, prompt_len=%d)",
            _CLI_BINARY, role, tier, len(files), len(merged_prompt),
        )

        # Build the CLI command.
        # ``--print`` returns the response to stdout instead of entering
        # interactive mode.
        # ``--append-system-prompt`` is used when a system_prompt is supplied;
        # when there isn't one we skip it.
        cmd: list[str] = [self._binary_path, "--print"]
        if system_prompt:
            cmd.extend(["--append-system-prompt", system_prompt])
        cmd.append(merged_prompt)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        except FileNotFoundError:
            raise LLMClientError(
                f"CLI binary '{_CLI_BINARY}' disappeared from PATH during execution."
            )
        except OSError as exc:
            raise LLMClientError(
                f"Failed to spawn {_CLI_BINARY} process: {exc}"
            ) from exc

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        if stderr_text:
            logger.warning("%s stderr: %s", _CLI_BINARY, stderr_text[:500])

        if process.returncode != 0:
            detail = stderr_text or stdout_text or "(no output)"
            raise LLMClientError(
                f"{_CLI_BINARY} exited with code {process.returncode}: {detail[:500]}"
            )

        if not stdout_text:
            raise LLMClientError(f"{_CLI_BINARY} returned empty output")

        logger.debug(
            "%s returned %d chars (returncode=%d)",
            _CLI_BINARY, len(stdout_text), process.returncode,
        )
        return stdout_text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_file(self, path: str) -> str:
        """Read a text file with project-root sandbox enforcement.

        Mirrors :meth:`LLMClient._read_file` — only files residing within
        ``self._project_root`` are readable.

        Raises:
            ConfigurationError: If *project_root* is not configured or
                the resolved path lies outside it.
            FileNotFoundError: If the file does not exist.
        """
        if self._project_root is None:
            raise ConfigurationError(
                "Cannot read file: project_root is not configured on CLIBackend. "
                "Pass project_root to the constructor to enable sandboxed file access."
            )

        resolved = Path(path).resolve()
        try:
            resolved.relative_to(self._project_root)
        except ValueError:
            raise ConfigurationError(
                f"File path '{path}' resolves to '{resolved}', which is outside "
                f"the project root '{self._project_root}'."
            )

        with open(resolved, "r", encoding="utf-8") as fh:
            return fh.read()
