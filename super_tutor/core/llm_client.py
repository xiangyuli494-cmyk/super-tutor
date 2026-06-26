"""LLM client wrapper with retry and timeout."""

import asyncio
import logging
import os

from openai import AsyncOpenAI

from super_tutor.core.exceptions import LLMError

logger = logging.getLogger(__name__)

_RETRY_BASE_DELAY = 1.0  # seconds -> 1, 2, 4

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_API_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_MAX_RETRIES = 3


class LLMClient:
    """Async wrapper around the OpenAI SDK targeting a DeepSeek-compatible endpoint.

    Configuration is read from environment variables (with sensible defaults):
    - ``TUTOR_API_KEY``
    - ``TUTOR_API_BASE_URL`` (default: https://api.deepseek.com)
    - ``TUTOR_MODEL`` (default: deepseek-chat)
    - ``TUTOR_MAX_RETRIES`` (default: 3)

    Provides:
    - Automatic retry with exponential back-off.
    - Per-call timeout control.
    """

    def __init__(self) -> None:
        api_key = os.getenv("TUTOR_API_KEY", "")
        api_base_url = os.getenv("TUTOR_API_BASE_URL", _DEFAULT_API_BASE_URL)
        self._model = os.getenv("TUTOR_MODEL", _DEFAULT_MODEL)
        try:
            self._max_retries = int(os.getenv("TUTOR_MAX_RETRIES", str(_DEFAULT_MAX_RETRIES)))
        except ValueError:
            self._max_retries = _DEFAULT_MAX_RETRIES

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base_url,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 120,
    ) -> str:
        """Send a chat-completion request and return the response text.

        Args:
            messages: List of message dicts with ``"role"`` and
                ``"content"`` keys.
            temperature: Sampling temperature (0.0–2.0).
            max_tokens: Maximum tokens in the response.
            timeout: Per-request timeout in seconds.

        Returns:
            The text content of the first choice.

        Raises:
            LLMError: If all retry attempts are exhausted or the
                API returns empty content.
        """
        max_retries = self._max_retries
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):  # 1 initial + N retries
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=self._model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ),
                    timeout=timeout,
                )
                content = response.choices[0].message.content
                if content is None:
                    raise LLMError("LLM returned empty content (content is None)")
                return content
            except asyncio.TimeoutError:
                last_exc = LLMError(
                    f"LLM call timed out after {timeout}s"
                )
                logger.warning(
                    "LLM timeout (attempt %d/%d)",
                    attempt + 1,
                    max_retries + 1,
                )
            except LLMError:
                # Hard failures from our own layer (e.g. empty content)
                # must propagate immediately — they will not be fixed by
                # retrying.
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )

            if attempt < max_retries:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.debug("Retrying in %.1fs ...", delay)
                await asyncio.sleep(delay)

        raise LLMError(
            f"LLM call failed after {max_retries + 1} attempts"
        ) from last_exc
