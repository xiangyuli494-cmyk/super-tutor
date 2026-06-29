"""知识点引擎 — 知识点解析、关系管理和掌握度追踪。

【功能说明】
将 LLM 调用、知识点 CRUD 和前置/后继关系维护封装为高层次的
业务逻辑组件，是 Super Tutor 的入口引擎。

核心能力：
1. parse(): LLM 提取知识点 → 写入 DB → 建立双向依赖关系
2. get_by_material(): 按教材查询所有知识点
3. get_prerequisites(): 查询某知识点的所有前置知识点
4. get_successors(): 查询某知识点的所有后继知识点
5. update_mastery(): 更新知识点的掌握度

双向关系建立逻辑（parse 的第 5 步）：
- LLM 返回每个 KP 的 prerequisite_indices（基于临时 index 的引用）
- 将 index 映射为实际 kp_id（UUID）
- 对每个 KP：更新其 prerequisite_ids
- 同时对每个前置 KP：追加 successor_ids（保证双向同步）

【耦合关系】
- 依赖 Database（数据持久化）、LLMClient（API 调用）
- 被 app.py 的 _do_parse() 调用，作为知识点解析的入口
- 被 QuizEngine 和 AssessmentEngine 依赖（提供 KP 查询能力）
- 依赖 prompts/parse_knowledge.md（LLM 系统提示词）
- 使用 models/knowledge.py 的 KnowledgePoint 模型
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from super_tutor.core.database import Database
from super_tutor.core.exceptions import LLMError, MaterialError
from super_tutor.core.llm_client import LLMClient
from super_tutor.models.knowledge import KnowledgePoint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 默认 prompt 路径 — 知识点解析提示词
# ---------------------------------------------------------------------------
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_DEFAULT_PARSE_PROMPT = _PROMPTS_DIR / "parse_knowledge.md"


class KnowledgeEngine:
    """知识点引擎 — 解析、查询和掌握度管理。

    封装了 LLM 解析 → 数据库 CRUD → 前置/后继关系双向同步的完整流程。
    是整个系统的入口引擎，负责将原始教材转化为结构化的知识点 DAG。

    Usage::

        engine = KnowledgeEngine(db, llm_client)
        kps = await engine.parse(content, "physics", "material-001")
        prereqs = await engine.get_prerequisites("kp-003")
    """

    def __init__(
        self,
        db: Database,
        llm_client: LLMClient,
        parse_prompt_path: str | None = None,
    ) -> None:
        """初始化知识点引擎。

        Args:
            db: 已初始化的 Database 实例。
            llm_client: LLMClient 实例（用于 LLM 调用）。
            parse_prompt_path: 可选的自定义解析提示词路径。
                默认使用 prompts/parse_knowledge.md。
        """
        self._db = db
        self._llm = llm_client
        self._prompt_path = parse_prompt_path or str(_DEFAULT_PARSE_PROMPT)

    # ==================================================================
    # parse() — LLM 驱动的知识点提取（系统的核心入口流程）
    # ==================================================================

    async def parse(
        self,
        content: str,
        course_type: str,
        material_id: str,
    ) -> list[KnowledgePoint]:
        """将教材原文解析为结构化知识点列表。

        完整流程（5 步）：
        1. 加载系统提示词（prompts/parse_knowledge.md）
        2. 构建消息 → 调用 LLM（temperature=0.3，max_tokens=8192，timeout=180s）
        3. 解析 LLM 返回的 JSON（去除 Markdown 代码围栏）
        4. 遍历 JSON 数组 → 创建 KnowledgePoint → 逐条插入 DB
        5. 解析前置关系 → 双向更新 prerequisite_ids 和 successor_ids

        Args:
            content: 教材原文文本。
            course_type: 课程类型（如 "physics"、"mathematics"）。
            material_id: 所属材料 ID（materials 表的外键）。

        Returns:
            KnowledgePoint 列表（按依赖顺序：无前置的在前）。

        Raises:
            MaterialError: LLM 调用失败、JSON 解析失败或返回空结果时抛出。
        """
        # -- 第 1 步：加载系统提示词 ------------------------------------------
        try:
            system_prompt = Path(self._prompt_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise MaterialError(
                f"无法加载知识点解析提示词: {self._prompt_path} ({exc})"
            ) from exc

        # -- 第 2 步：构建消息并调用 LLM -------------------------------------
        user_prompt = (
            f"## 教材内容\n\n课程类型: {course_type}\n\n"
            f"{content}\n\n"
            f"请按 JSON 格式输出所有知识点的解析结果。"
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info("开始解析教材 %s (course_type=%s, 内容长度=%d)...",
                     material_id, course_type, len(content))

        try:
            raw = await self._llm.chat(
                messages=messages,
                temperature=0.3,   # 较低温度保证提取结果稳定
                max_tokens=8192,   # 大 token 预算应对长教材
                timeout=180,       # 3 分钟超时
            )
        except LLMError as exc:
            raise MaterialError(
                f"LLM 调用失败 (material_id={material_id}): {exc}"
            ) from exc

        # -- 第 3 步：解析 LLM 返回的 JSON -----------------------------------
        raw = raw.strip()
        # 去除可能的 Markdown 代码围栏（```json ... ```）
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("LLM 返回的 JSON 无法解析: %s", raw[:500])
            raise MaterialError(
                f"知识点解析结果不是有效 JSON: {exc}"
            ) from exc

        raw_kps = data.get("knowledge_points", [])
        if not raw_kps:
            raise MaterialError("LLM 未返回任何知识点，请检查教材内容是否为空或格式是否正确。")

        # -- 第 4 步：逐条创建 KnowledgePoint 并插入 DB ----------------------
        # index_to_kp_id 映射：LLM 返回的临时 index → 实际 UUID
        index_to_kp_id: dict[int, str] = {}
        created: list[KnowledgePoint] = []
        now = datetime.now(timezone.utc).isoformat()

        for item in raw_kps:
            kp_id = str(uuid4())
            idx = item.get("index", len(created))
            index_to_kp_id[idx] = kp_id

            kp = KnowledgePoint(
                kp_id=kp_id,
                material_id=material_id,
                title=item.get("title", ""),
                summary=item.get("summary", ""),
                content=item.get("content", ""),
                keywords=item.get("keywords", []),
                difficulty=item.get("difficulty", "medium"),
                course_type=course_type,
                chapter_index=item.get("chapter_index", idx),
                prerequisite_ids=[],   # 第 5 步填充
                successor_ids=[],      # 第 5 步填充
                assessment_count=0,
                created_at=now,
                updated_at=now,
            )

            await self._db.insert_knowledge_point(kp.model_dump())
            created.append(kp)

        logger.info("已插入 %d 个知识点 (material_id=%s)", len(created), material_id)

        # -- 第 5 步：解析并双向写入前置/后继关系 ---------------------------
        # 这是整个系统最关键的步骤，确保知识点 DAG 的双向一致性
        for item in raw_kps:
            idx = item.get("index", 0)
            kp_id = index_to_kp_id.get(idx)
            if kp_id is None:
                continue

            # 将 LLM 返回的 prerequisite_indices（临时 index）转为实际 kp_id
            prereq_indices: list[int] = item.get("prerequisite_indices", [])
            prerequisite_ids: list[str] = []
            for pi in prereq_indices:
                prereq_kp_id = index_to_kp_id.get(pi)
                if prereq_kp_id and prereq_kp_id != kp_id:
                    prerequisite_ids.append(prereq_kp_id)

            # 更新当前 KP 的 prerequisite_ids
            if prerequisite_ids:
                await self._db.update_knowledge_point(
                    kp_id, {"prerequisite_ids": prerequisite_ids}
                )

            # 为每个前置 KP 追加 successor_ids（建立双向关系）
            for prereq_kp_id in prerequisite_ids:
                prereq = await self._db.get_knowledge_point(prereq_kp_id)
                if prereq is None:
                    continue
                successors: list[str] = _parse_json_list(
                    prereq.get("successor_ids", "[]")
                )
                if kp_id not in successors:
                    successors.append(kp_id)
                    await self._db.update_knowledge_point(
                        prereq_kp_id, {"successor_ids": successors}
                    )

            # 同步更新内存中的 KnowledgePoint 模型（prerequisite_ids + successor_ids）
            for kp in created:
                if kp.kp_id == kp_id:
                    kp.prerequisite_ids = prerequisite_ids
                if kp.kp_id in prerequisite_ids:
                    if kp_id not in kp.successor_ids:
                        kp.successor_ids.append(kp_id)

        logger.info(
            "已解析 %d 个知识点，建立 %d 条前置关系 (material_id=%s)",
            len(created),
            sum(len(kp.prerequisite_ids) for kp in created),
            material_id,
        )

        return created

    # ==================================================================
    # 查询方法 — 知识点的读取操作
    # ==================================================================

    async def get_by_material(self, material_id: str) -> list[KnowledgePoint]:
        """查询某教材的所有知识点（按章节序号排序）。

        Args:
            material_id: 教材 ID。

        Returns:
            KnowledgePoint 列表。
        """
        rows = await self._db.list_knowledge_points_by_material(material_id)
        return [_row_to_knowledge_point(r) for r in rows]

    async def get_prerequisites(self, kp_id: str) -> list[KnowledgePoint]:
        """查询某知识点的直接前置知识点（即必须先学会这些 KP 才能学此 KP）。

        Args:
            kp_id: 知识点 ID。

        Returns:
            KnowledgePoint 列表（前置知识点）。
        """
        kp = await self._db.get_knowledge_point(kp_id)
        if kp is None:
            return []
        prereq_ids: list[str] = _parse_json_list(
            kp.get("prerequisite_ids", "[]")
        )
        result: list[KnowledgePoint] = []
        for pid in prereq_ids:
            row = await self._db.get_knowledge_point(pid)
            if row:
                result.append(_row_to_knowledge_point(row))
        return result

    async def get_successors(self, kp_id: str) -> list[KnowledgePoint]:
        """查询某知识点的直接后继知识点（即依赖此 KP 才能学习的 KP）。

        Args:
            kp_id: 知识点 ID。

        Returns:
            KnowledgePoint 列表（后继知识点）。
        """
        kp = await self._db.get_knowledge_point(kp_id)
        if kp is None:
            return []
        successor_ids: list[str] = _parse_json_list(
            kp.get("successor_ids", "[]")
        )
        result: list[KnowledgePoint] = []
        for sid in successor_ids:
            row = await self._db.get_knowledge_point(sid)
            if row:
                result.append(_row_to_knowledge_point(row))
        return result

    # ==================================================================
    # 掌握度管理
    # ==================================================================

    async def update_mastery(self, kp_id: str, score: float) -> None:
        """更新知识点的掌握度。

        Args:
            kp_id: 知识点 ID。
            score: 新的掌握度（0.0–1.0），超出范围自动裁剪。
        """
        clamped = max(0.0, min(1.0, score))
        await self._db.upsert_knowledge_point_mastery(kp_id, clamped)
        logger.debug("Updated mastery for %s → %.2f", kp_id, clamped)


# ==================================================================
# 模块级工具函数
# ==================================================================


def _parse_json_list(raw: str | list) -> list[str]:
    """将 JSON 字符串或列表统一解析为字符串列表。

    数据库中 JSON 字段（如 prerequisite_ids、successor_ids、keywords）
    存储为 JSON 字符串，需要用此函数解析。已为列表类型则直接返回。

    Args:
        raw: JSON 字符串（如 '["a","b"]'）或列表。

    Returns:
        list[str]: 解析后的字符串列表。解析失败返回空列表。
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
    return []


def _row_to_knowledge_point(row: dict) -> KnowledgePoint:
    """将数据库行字典转换为 KnowledgePoint 模型。

    自动解析 JSON 字符串字段（keywords、prerequisite_ids、successor_ids）。

    Args:
        row: 数据库查询返回的字段字典。

    Returns:
        KnowledgePoint: 填充了所有字段的模型实例。
    """
    return KnowledgePoint(
        kp_id=row.get("kp_id", ""),
        material_id=row.get("material_id", ""),
        title=row.get("title", ""),
        summary=row.get("summary", ""),
        content=row.get("content", ""),
        keywords=_parse_json_list(row.get("keywords", "[]")),
        difficulty=row.get("difficulty", "medium"),
        course_type=row.get("course_type", ""),
        chapter_index=row.get("chapter_index", 0),
        prerequisite_ids=_parse_json_list(row.get("prerequisite_ids", "[]")),
        successor_ids=_parse_json_list(row.get("successor_ids", "[]")),
        mastery_level=row.get("mastery_level", 0.0),
        assessment_count=row.get("assessment_count", 0),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )
