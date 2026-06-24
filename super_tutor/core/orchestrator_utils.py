"""Orchestrator 通用工具函数 — JSON 解析、模型水合、token 估算。

从 ``orchestrator.py`` 中提取的模块级辅助函数，无状态、无依赖。
"""

from __future__ import annotations

import json as _json
import logging
import re as _re
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ======================================================================
# JSON 安全解析
# ======================================================================


def _safe_parse_json_list(
    response: str, key: str
) -> list[dict[str, Any]]:
    """从 LLM 响应中安全提取 JSON 列表。

    使用 4 层防御策略：
    1. 直接 ``json.loads`` 整个响应
    2. 正则提取 ```json ... ``` 围栏代码块
    3. 正则提取第一个 ``{...}`` 或 ``[...]``
    4. 返回空列表

    Args:
        response: LLM 原始响应文本。
        key: 期望的 JSON 对象键名（如 ``"chunks"``、``"questions"``）。

    Returns:
        解析出的字典列表，失败时返回空列表。
    """
    # 第 1 层：尝试直接解析整个响应
    try:
        data = _json.loads(response)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and key in data:
            items = data[key]
            return items if isinstance(items, list) else [items]
    except (_json.JSONDecodeError, TypeError):
        pass

    # 第 2 层：提取 ```json ... ``` 围栏代码块
    fence_match = _re.search(
        r"```(?:json)?\s*\n?([\s\S]*?)\n?```", response
    )
    if fence_match:
        try:
            data = _json.loads(fence_match.group(1).strip())
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and key in data:
                items = data[key]
                return items if isinstance(items, list) else [items]
        except (_json.JSONDecodeError, TypeError):
            pass

    # 第 3 层：查找第一个 JSON 对象或数组
    json_match = _re.search(r"(\[.*\]|\{.*\})", response, _re.DOTALL)
    if json_match:
        try:
            data = _json.loads(json_match.group(1))
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and key in data:
                items = data[key]
                return items if isinstance(items, list) else [items]
        except (_json.JSONDecodeError, TypeError):
            pass

    # 第 4 层：放弃，返回空列表
    logger.warning(
        "_safe_parse_json_list: 无法解析 LLM 响应为 JSON，"
        "key=%s，响应前 200 字符: %s",
        key,
        response[:200],
    )
    return []


# ======================================================================
# Pydantic 模型水合
# ======================================================================


def _hydrate_models(
    raw_items: list[dict[str, Any]],
    model_cls: type,
    *,
    defaults: Optional[dict[str, Any]] = None,
) -> list[Any]:
    """将 LLM 输出的原始字典列表反序列化为 Pydantic 模型实例。

    逐条尝试 ``model_cls(**defaults, **item)``，验证失败的条目
    记录警告后跳过，确保单个脏数据不影响整批产出物。

    Args:
        raw_items: LLM 输出的原始字典列表。
        model_cls: 目标 Pydantic 模型类（如 ``KnowledgeChunk``）。
        defaults: 注入到每条记录的默认字段值
                  （如 ``material_id``、``session_id`` 等运行时上下文）。

    Returns:
        成功反序列化的模型实例列表（可能短于输入）。
    """
    models: list[Any] = []
    merged_defaults = defaults or {}
    for i, item in enumerate(raw_items):
        try:
            merged = {**merged_defaults, **item}
            models.append(model_cls(**merged))
        except Exception as exc:
            logger.warning(
                "_hydrate_models: 第 %d 条 %s 反序列化失败: %s",
                i,
                model_cls.__name__,
                exc,
            )
    if models:
        logger.debug(
            "_hydrate_models: %d/%d 条成功反序列化为 %s。",
            len(models),
            len(raw_items),
            model_cls.__name__,
        )
    return models


# ======================================================================
# JSON 安全截断
# ======================================================================


def _safe_truncate_json(
    items: list[dict[str, Any]], max_items: int = 15
) -> str:
    """将列表截断并序列化为 JSON 字符串。

    超过 ``max_items`` 时自动截断并附加占位提示。

    Args:
        items: 待序列化的字典列表。
        max_items: 最大保留条数。

    Returns:
        JSON 字符串。
    """
    truncated = items[:max_items]
    result = _json.dumps(truncated, ensure_ascii=False, indent=2)
    if len(items) > max_items:
        result += f"\n// ... 共 {len(items)} 条，已截断显示前 {max_items} 条"
    return result


# ======================================================================
# Token 估算
# ======================================================================


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数（按词数 / 0.75）。"""
    return max(1, int(len(text.split()) / 0.75))
