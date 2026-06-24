"""Orchestrator 通用工具函数 — JSON 解析、模型水合、token 估算、知识图谱构建。

从 ``orchestrator.py`` 中提取的模块级辅助函数，无状态、无依赖。
"""

from __future__ import annotations

import json as _json
import logging
import re as _re
from typing import Any, Optional
from uuid import uuid4

from super_tutor.models.knowledge import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
)

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


# ======================================================================
# 知识图谱构建（F? — PARSING 阶段后从 chunks 自动构建）
# ======================================================================


def _build_knowledge_graph(
    chunks_raw: list[dict[str, Any]],
) -> KnowledgeGraph:
    """从知识片段构建知识图谱。

    每个 chunk 映射为一个 KnowledgeNode，相同 topic 的节点之间
    创建双向关联边，相邻 chunk 之间创建顺序边（prerequisite 关系）。

    Args:
        chunks_raw: PARSING 阶段产出的原始 chunk dict 列表。

    Returns:
        包含节点和边的 KnowledgeGraph 实例。
    """
    nodes: list[KnowledgeNode] = []
    edges: list[KnowledgeEdge] = []

    # 按 topic 分组
    topic_groups: dict[str, list[int]] = {}
    for i, c in enumerate(chunks_raw):
        chunk_id = c.get("chunk_id", str(uuid4()))
        node = KnowledgeNode(
            node_id=chunk_id,
            label=c.get("topic", f"Chunk {i}"),
            description=c.get("summary", c.get("content", ""))[:256],
            node_type="concept",
            subject=c.get("topic", ""),
            difficulty=c.get("difficulty", "medium"),
            importance=3,
            estimated_minutes=5,
            keywords=c.get("keywords", []),
            chunk_ids=[chunk_id],
        )
        nodes.append(node)

        topic = c.get("topic", "").strip()
        if topic:
            topic_groups.setdefault(topic, []).append(i)

    # 同 topic 的节点间创建双向关联边
    for indices in topic_groups.values():
        if len(indices) < 2:
            continue
        for a_idx in range(len(indices)):
            for b_idx in range(a_idx + 1, len(indices)):
                edges.append(KnowledgeEdge(
                    edge_id=str(uuid4()),
                    source_id=nodes[indices[a_idx]].node_id,
                    target_id=nodes[indices[b_idx]].node_id,
                    relation="related_to",
                    weight=0.5,
                    label="same_topic",
                ))
                edges.append(KnowledgeEdge(
                    edge_id=str(uuid4()),
                    source_id=nodes[indices[b_idx]].node_id,
                    target_id=nodes[indices[a_idx]].node_id,
                    relation="related_to",
                    weight=0.5,
                    label="same_topic",
                ))

    # 相邻 chunk 之间创建顺序边（prerequisite 关系）
    for i in range(len(nodes) - 1):
        edges.append(KnowledgeEdge(
            edge_id=str(uuid4()),
            source_id=nodes[i].node_id,
            target_id=nodes[i + 1].node_id,
            relation="prerequisite",
            weight=0.8,
            label="sequence",
        ))

    return KnowledgeGraph(nodes=nodes, edges=edges)
