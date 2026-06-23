"""DeepSeek API client wrapper with retry, timeout, and three-tier model mapping."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from super_tutor.config import ForgeConfig
from super_tutor.core.exceptions import ConfigurationError, LLMClientError, VALID_ROLES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier -> (model, max_tokens, temperature) mapping
#
# All tiers default to "deepseek-chat" and are differentiated by max_tokens
# and temperature rather than different model names.  Users may override
# the model per tier via ForgeConfig attributes (model_heavy / model_medium /
# model_light).
# ---------------------------------------------------------------------------
_TIER_PARAMS: dict[str, dict[str, Any]] = {
    "heavy": {
        "model": "deepseek-chat",
        "max_tokens": 8192,
        "temperature": 0.3,
    },
    "medium": {
        "model": "deepseek-chat",
        "max_tokens": 4096,
        "temperature": 0.5,
    },
    "light": {
        "model": "deepseek-chat",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
}

_RETRY_MAX = 4  # 1 initial attempt + 3 retries (1s, 2s, 4s back-off)
_RETRY_BASE_DELAY = 1.0  # seconds -> 1, 2, 4


class LLMClient:
    """Async wrapper around the OpenAI SDK targeting a DeepSeek-compatible endpoint.

    Provides:
    - Three computation tiers (heavy / medium / light) differentiated by
      *max_tokens* and *temperature*.
    - Automatic retry with exponential back-off (3 retries, 4 total attempts).
    - Per-call timeout control.
    - Optional project-root sandbox for file-context security.
    """

    def __init__(
        self,
        config: ForgeConfig,
        project_root: str | None = None,
        cli_mode: bool = False,
    ) -> None:
        """Initialize the client from project configuration.

        Args:
            config: ForgeConfig instance providing ``api_key`` and
                ``api_base_url``.  Optional per-tier model overrides may
                be supplied as ``model_heavy``, ``model_medium``,
                ``model_light``.
            project_root: Root directory of the active Forge project.
                When set, ``_read_file`` will only allow reading files
                inside this subtree, enforcing a path sandbox.  If
                ``None``, file-context methods will raise
                ``ConfigurationError``.
            cli_mode: When ``True``, use Claude Code / Codex CLI binaries
                instead of the DeepSeek API.  Requires ``claude`` and
                ``codex`` to be on PATH.  The API client is still created
                for embedding generation (sqlite-vec).
        """
        self._config = config
        self._project_root = Path(project_root).resolve() if project_root else None
        # Auto-detect from config if not explicitly passed.
        self._cli_mode = cli_mode or getattr(config, "cli_mode", False)

        # CLI backend (lazily initialised on first use).
        self._cli_backend = None

        # API client — always created for embedding generation,
        # but only used for chat when cli_mode is False.
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.api_base_url,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        role: str,
        messages: list[dict[str, str]],
        tier: str = "medium",
        timeout: int = 120,
    ) -> str:
        """Send a chat-completion request and return the response text.

        Args:
            role: Logical role name (``"claude-a"``, ``"codex"``,
                ``"claude-b"``).  Validated against the canonical role
                set; used for logging and, when *messages* already
                contain a system prompt, as a routing label.
            messages: List of message dicts with ``"role"`` and
                ``"content"`` keys.
            tier: Computation tier: ``"heavy"``, ``"medium"``, or
                ``"light"``.
            timeout: Per-request timeout in seconds.

        Returns:
            The text content of the first choice.

        Raises:
            ConfigurationError: If *role* is not a recognised role or
                *tier* is not one of the recognised tiers.
            LLMClientError: If all retry attempts are exhausted or the
                API returns empty content.
        """
        if role not in VALID_ROLES:
            raise ConfigurationError(
                f"Unknown role '{role}'. Expected one of: {sorted(VALID_ROLES)}"
            )
        tier_params = self._resolve_tier(tier)
        last_exc: Exception | None = None

        for attempt in range(_RETRY_MAX):
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=tier_params["model"],
                        messages=messages,
                        max_tokens=tier_params["max_tokens"],
                        temperature=tier_params["temperature"],
                    ),
                    timeout=timeout,
                )
                content = response.choices[0].message.content
                if content is None:
                    raise LLMClientError("LLM returned empty content (content is None)")
                return content
            except asyncio.TimeoutError:
                last_exc = LLMClientError(
                    f"LLM call timed out after {timeout}s"
                )
                logger.warning(
                    "LLM timeout (attempt %d/%d, tier=%s, role=%s)",
                    attempt + 1,
                    _RETRY_MAX,
                    tier,
                    role,
                )
            except LLMClientError:
                # Hard failures from our own layer (e.g. empty content)
                # must propagate immediately — they will not be fixed by
                # retrying.
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LLM call failed (attempt %d/%d, tier=%s, role=%s): %s",
                    attempt + 1,
                    _RETRY_MAX,
                    tier,
                    role,
                    exc,
                )

            if attempt < _RETRY_MAX - 1:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.debug("Retrying in %.1fs ...", delay)
                await asyncio.sleep(delay)

        raise LLMClientError(
            f"LLM call failed after {_RETRY_MAX} attempts "
            f"(role={role}, tier={tier})"
        ) from last_exc

    async def chat_with_file_context(
        self,
        role: str,
        user_message: str,
        files: list[str],
        tier: str = "medium",
        system_prompt: str | None = None,
    ) -> str:
        """Send a message with the contents of referenced files appended as context.

        In **API mode** (default), each file's content is read and injected as
        a fenced code block into the prompt.

        In **CLI mode** (``cli_mode=True``), File paths are passed directly to
        the CLI binary — both Claude Code and Codex can read files from disk
        natively, saving token overhead.

        Args:
            role: Logical role name (validated by ``chat()``).
            user_message: The user's question or instruction.
            files: List of file paths to include as context.
            tier: Computation tier (ignored in CLI mode).
            system_prompt: Optional system prompt.  In API mode it is placed
                as a ``system`` message.  In CLI mode it is passed via
                ``--append-system-prompt`` (Claude) or inlined (Codex).

        Returns:
            The text content of the LLM / CLI response.

        Raises:
            ConfigurationError: If *project_root* is not configured.
            LLMClientError: Propagated from ``chat()`` or the CLI.
        """
        # --- CLI mode: route to Claude Code / Codex CLI ---
        if self._cli_mode:
            if self._cli_backend is None:
                from super_tutor.core.cli_backend import CLIBackend

                self._cli_backend = CLIBackend(
                    config=self._config,
                    project_root=str(self._project_root) if self._project_root else None,
                )

            return await self._cli_backend.chat_with_file_context(
                role=role,
                user_message=user_message,
                files=files,
                tier=tier,
                system_prompt=system_prompt,
            )

        # --- API mode: embed file contents in prompt ---
        parts: list[str] = [user_message]

        if files:
            parts.append("\n---\n## 参考文件内容\n")
            for path in files:
                try:
                    content = await asyncio.to_thread(self._read_file, path)
                    parts.append(f"### {path}\n```\n{content}\n```\n")
                except OSError as exc:
                    logger.warning("Cannot read context file %s: %s", path, exc)
                    parts.append(f"### {path}\n[读取失败: {exc}]\n")

        merged = "\n".join(parts)
        messages: list[dict[str, str]] = []

        # Inject system prompt as the first message when provided.
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": merged})
        return await self.chat(role=role, messages=messages, tier=tier)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_tier(self, tier: str) -> dict[str, Any]:
        """Return the ``(model, max_tokens, temperature)`` dict for *tier*.

        User-configured model overrides on ``ForgeConfig`` (attributes
        ``model_heavy``, ``model_medium``, ``model_light``) take
        precedence over the built-in defaults.

        Raises:
            ConfigurationError: If *tier* is not one of the recognised tiers.
        """
        if tier not in _TIER_PARAMS:
            raise ConfigurationError(
                f"Unknown tier '{tier}'. Expected one of: {sorted(_TIER_PARAMS)}"
            )
        params = dict(_TIER_PARAMS[tier])

        # Allow ForgeConfig to override the model per tier.
        override_attr = f"model_{tier}"
        if hasattr(self._config, override_attr):
            override_value = getattr(self._config, override_attr)
            if override_value is not None:
                params["model"] = override_value

        return params

    def _read_file(self, path: str) -> str:
        """Read a text file, returning its full content.

        Only files residing within ``self._project_root`` are readable;
        any path outside that subtree (or relative paths that resolve
        outside it) will raise ``ConfigurationError``.

        Args:
            path: Absolute or relative path to a text file.

        Returns:
            The full file content as a string.

        Raises:
            ConfigurationError: If ``project_root`` is not configured on
                this client, or if the resolved *path* lies outside
                ``project_root``.
            FileNotFoundError: If the file does not exist.
        """
        if self._project_root is None:
            raise ConfigurationError(
                "Cannot read file: project_root is not configured on LLMClient. "
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
