"""LLM 客户端模块 — 封装 DeepSeek API 的异步调用。

【功能说明】
基于 OpenAI 兼容 SDK（AsyncOpenAI）封装 DeepSeek API 调用。
提供以下核心能力：
1. 自动重试：指数退避（1s → 2s → 4s），默认最多 3 次重试
2. 超时控制：每次请求独立超时，默认 120 秒
3. 环境变量配置：通过 TUTOR_* 系列环境变量配置

【环境变量】
- TUTOR_API_KEY — API 密钥（必填）
- TUTOR_API_BASE_URL — API 地址，默认 https://api.deepseek.com
- TUTOR_MODEL — 模型名称，默认 deepseek-chat
- TUTOR_MAX_RETRIES — 最大重试次数，默认 3

【耦合关系】
- 依赖 super_tutor.core.exceptions.LLMError（异常类型）
- 被 app.py 的 _init_services() 创建实例
- 被所有 5 个 Engine 依赖：KnowledgeEngine、QuizEngine、AssessmentEngine、
  PlanEngine（间接）、SocraticEngine
- 对外暴露唯一接口：chat(messages, temperature, max_tokens, timeout) → str
"""

import asyncio
import logging
import os

from openai import AsyncOpenAI

from super_tutor.core.exceptions import LLMError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 重试常量
# ---------------------------------------------------------------------------
_RETRY_BASE_DELAY = 1.0  # 基础重试延迟（秒）→ 第1次重试等1s，第2次等2s，第3次等4s

# ---------------------------------------------------------------------------
# 默认值
# ---------------------------------------------------------------------------
_DEFAULT_API_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_MAX_RETRIES = 3


class LLMClient:
    """DeepSeek API 异步客户端封装。

    使用 OpenAI 兼容的 SDK 调用 DeepSeek API。
    自动处理重试、超时和错误转换。

    Usage::

        client = LLMClient()
        response = await client.chat(
            messages=[{"role": "user", "content": "你好"}],
            temperature=0.7,
            max_tokens=4096,
        )
    """

    def __init__(self) -> None:
        """初始化 LLM 客户端，从环境变量读取配置。

        Raises:
            不抛出异常 — 即使 API key 为空也会创建客户端，
            实际调用时由 LLMError 处理。
        """
        # -- 读取环境变量配置 --
        api_key = os.getenv("TUTOR_API_KEY", "")
        api_base_url = os.getenv("TUTOR_API_BASE_URL", _DEFAULT_API_BASE_URL)
        self._model = os.getenv("TUTOR_MODEL", _DEFAULT_MODEL)
        try:
            self._max_retries = int(
                os.getenv("TUTOR_MAX_RETRIES", str(_DEFAULT_MAX_RETRIES))
            )
        except ValueError:
            self._max_retries = _DEFAULT_MAX_RETRIES

        # -- 创建 AsyncOpenAI 客户端 --
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base_url,
        )

    # ------------------------------------------------------------------
    # 公开 API — chat()
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 120,
    ) -> str:
        """发送聊天补全请求，返回 LLM 响应文本。

        自动重试机制：
        - 第 0 次（首次尝试）
        - 第 1 次重试（等 1s）
        - 第 2 次重试（等 2s）
        - 第 3 次重试（等 4s）
        总计最多 4 次尝试（1 初始 + 3 重试）。

        Args:
            messages: 消息列表，每项含 "role" 和 "content"。
            temperature: 采样温度（0.0–2.0），越低越确定性，越高越随机。
            max_tokens: 响应最大 token 数。
            timeout: 单次请求超时（秒）。

        Returns:
            LLM 返回的文本内容（response.choices[0].message.content）。

        Raises:
            LLMError: 所有重试耗尽或 LLM 返回空内容时抛出。
        """
        max_retries = self._max_retries
        last_exc: Exception | None = None

        # 循环：1 次初始调用 + N 次重试
        for attempt in range(max_retries + 1):
            try:
                # -- 带超时的 API 调用 --
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
                    # 空内容 — 直接抛出，不重试（重试也无法修复）
                    raise LLMError("LLM returned empty content (content is None)")
                return content

            except asyncio.TimeoutError:
                # 超时 — 记录并准备重试
                last_exc = LLMError(
                    f"LLM call timed out after {timeout}s"
                )
                logger.warning(
                    "LLM timeout (attempt %d/%d)",
                    attempt + 1,
                    max_retries + 1,
                )

            except LLMError:
                # 我们自己的硬错误（如空内容）— 不重试，直接传播
                raise

            except Exception as exc:
                # 其他异常（网络错误等）— 记录并准备重试
                last_exc = exc
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )

            # -- 指数退避延迟（仅在还有重试次数时） --
            if attempt < max_retries:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)  # 1s, 2s, 4s
                logger.debug("Retrying in %.1fs ...", delay)
                await asyncio.sleep(delay)

        # -- 所有重试耗尽 --
        raise LLMError(
            f"LLM call failed after {max_retries + 1} attempts"
        ) from last_exc
