"""学习计划生成引擎 — 根据诊断评估结果生成个性化学习计划。

【功能说明】
将诊断评估结果（知识点掌握度映射）转化为结构化的学习计划。
核心流程（5 步）：

1. 从 DB 获取知识点 → 拓扑排序（Kahn 算法，按前置依赖排列）
2. 计算每个 KP 的优先级分数：
   公式: (1 - mastery) × (1 + successor_count / total_kps)
   — 掌握度越低越优先，后继越多越优先（因为阻塞了更多 KP）
3. 根据掌握度分配活动类型：
   - mastery < 0.3 → learn_new (新学)
   - 0.3 ≤ mastery < 0.5 → review (复习)
   - 0.5 ≤ mastery < 0.8 → practice (练习)
   - mastery ≥ 0.8 → quiz (测验)
4. 按难度和掌握度差距估算学习时长（10–120 分钟）
5. 构建 StudyPlan 模型 → 持久化到 study_plans 表

排期策略：每天一个知识点，从 start_date 开始按拓扑序排列。

【耦合关系】
- 依赖 Database（CRUD 操作 + KP 查询）
- 被 app.py 的 _do_generate_plan() 调用
- 输入来自 AssessmentEngine 的 AssessmentReport
- 输出 StudyPlan 模型供 app.py 的 _render_plan_tab() 展示
- 使用 knowledge_engine._parse_json_list() 解析 successor_ids
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from super_tutor.core.database import Database
from super_tutor.engine.knowledge_engine import _parse_json_list
from super_tutor.models.mastery import ReviewItem
from super_tutor.models.plan import StudyPlan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 活动类型 → 掌握度区间映射（4 级分类）
# ---------------------------------------------------------------------------

_ACTIVITY_LEARN_NEW = "learn_new"       # mastery < 0.3（完全未掌握，需要新学）
_ACTIVITY_REVIEW = "review"              # 0.3 ≤ mastery < 0.5（部分掌握，需复习）
_ACTIVITY_PRACTICE = "practice"          # 0.5 ≤ mastery < 0.8（基本掌握，需练习）
_ACTIVITY_QUIZ = "quiz"                  # mastery ≥ 0.8（已掌握，用测验巩固）

# ---------------------------------------------------------------------------
# 默认学习时长（分钟）— 按难度等级
# ---------------------------------------------------------------------------

_DIFFICULTY_MINUTES: dict[str, int] = {
    "beginner": 15,   # 入门内容约 15 分钟
    "easy": 20,       # 简单内容约 20 分钟
    "medium": 30,     # 中等内容约 30 分钟
    "hard": 45,       # 困难内容约 45 分钟
    "expert": 60,     # 专家级内容约 60 分钟
}


class PlanEngine:
    """学习计划生成引擎。

    根据知识点掌握度映射，生成拓扑排序后的个性化学习计划。
    每个知识点按掌握度分配活动类型和预估学习时长。

    Usage::

        engine = PlanEngine(db)
        plan = await engine.generate(kp_ids, mastery_map, student_id="s1")
    """

    def __init__(self, db: Database) -> None:
        """初始化学习计划引擎。

        Args:
            db: 已初始化的 Database 实例。
        """
        self._db = db

    # ==================================================================
    # generate() — 学习计划生成主流程（5 步）
    # ==================================================================

    async def generate(
        self,
        kp_ids: list[str],
        mastery_map: dict[str, float],
        student_id: str = "",
        plan_title: str = "",
        plan_goal: str = "",
        start_date: str = "",
    ) -> StudyPlan:
        """生成个性化学习计划。

        完整流程：
        1. 从 DB 获取知识点 → 过滤不存在的 KP
        2. 拓扑排序（Kahn 算法，按前置依赖排列）
        3. 计算优先级 → 分配活动类型 → 估算学习时长
        4. 构建 StudyPlan 模型（包含 ReviewItem 排期列表）
        5. 持久化到 study_plans 表

        Args:
            kp_ids: 要包含在计划中的知识点 ID 列表。
            mastery_map: kp_id → 掌握度（0.0–1.0）的映射。
            student_id: 学生标识。
            plan_title: 可选的自定义计划标题。
            plan_goal: 可选的学习目标描述。
            start_date: 开始日期（ISO 8601 date 格式），默认今天。

        Returns:
            StudyPlan: 包含完整排期的学习计划模型。

        Raises:
            ValueError: kp_ids 为空或所有 KP 都不存在时抛出。
        """
        if not kp_ids:
            raise ValueError("kp_ids 不能为空")

        # -- 第 1 步：从 DB 获取知识点，过滤不存在的 KP --------------------
        kps: list[dict] = []
        for kid in kp_ids:
            row = await self._db.get_knowledge_point(kid)
            if row is None:
                logger.warning("KP %s 不存在，跳过", kid)
                continue
            kps.append(row)

        if not kps:
            raise ValueError("所有指定的 kp_ids 均不存在于数据库中")

        # -- 第 2 步：拓扑排序（Kahn 算法）-----------------------------------
        ordered_ids = self.topological_sort(kps)
        total_kps = len(ordered_ids)

        # 构建 kp_id → 行数据 的快速查找表
        kp_by_id: dict[str, dict] = {kp["kp_id"]: kp for kp in kps}

        # -- 第 3 步：计算每个 KP 的优先级、活动类型和时长 -----------------
        if not start_date:
            start_date = datetime.now(timezone.utc).date().isoformat()

        kp_sequence: list[dict] = []      # DB 格式的序列化数据
        schedule: list[ReviewItem] = []   # 模型格式的排期列表

        for idx, kid in enumerate(ordered_ids):
            kp = kp_by_id.get(kid, {})
            mastery = mastery_map.get(kid, 0.0)
            successor_ids = _parse_json_list(
                kp.get("successor_ids", "[]")
            )
            successor_count = len(successor_ids)
            difficulty = kp.get("difficulty", "medium")

            # 优先级公式：掌握度越低 + 后继越多 = 越优先
            # (1 - mastery) 的范围是 [0, 1]，successor_factor 的范围是 [1, 2]
            # 最终优先级范围: [0, 2]，数值越大越紧急
            priority_score = self._compute_priority(
                mastery=mastery,
                successor_count=successor_count,
                total_kps=total_kps,
            )

            # 根据掌握度确定活动类型
            activity_type = self._activity_for_mastery(mastery)

            # 根据难度和掌握度差距估算学习时长
            estimated_minutes = self._estimate_minutes(
                difficulty=difficulty,
                mastery_gap=1.0 - mastery,
            )

            # 排期日期：每天一个知识点，从 start_date 起依次排列
            scheduled_date = (
                datetime.fromisoformat(start_date).date() + timedelta(days=idx)
            ).isoformat()

            # -- kp_sequence 条目（存入 DB 的 JSON 格式）--
            entry = {
                "kp_id": kid,
                "title": kp.get("title", kid),
                "order": idx,
                "priority_score": round(priority_score, 4),
                "mastery": round(mastery, 4),
                "activity_type": activity_type,
                "estimated_minutes": estimated_minutes,
                "scheduled_date": scheduled_date,
                "completed": False,
                "completed_at": None,
                "notes": "",
            }
            kp_sequence.append(entry)

            # -- ReviewItem（Python 模型格式）--
            schedule.append(
                ReviewItem(
                    item_id=str(uuid4()),
                    knowledge_node_id=kid,
                    scheduled_date=scheduled_date,
                    activity_type=activity_type,
                    estimated_minutes=estimated_minutes,
                    completed=False,
                    notes=f"掌握度={mastery:.2f} 优先级={priority_score:.2f}",
                )
            )

        # -- 第 4 步：构建 StudyPlan 模型 -----------------------------------
        now = datetime.now(timezone.utc).isoformat()
        plan = StudyPlan(
            plan_id=str(uuid4()),
            student_id=student_id,
            title=plan_title or "个性化学习计划",
            status="active",
            kp_sequence=ordered_ids.copy(),
            schedule=schedule,
            created_at=now,
            updated_at=now,
        )

        # -- 第 5 步：持久化到 DB -------------------------------------------
        await self._db.create_study_plan({
            "plan_id": plan.plan_id,
            "student_id": plan.student_id,
            "title": plan.title,
            "description": f"基于 {total_kps} 个知识点的诊断评估自动生成",
            "goal": plan_goal or "掌握所有知识点，达到 ≥0.8 掌握度",
            "start_date": start_date,
            "end_date": None,
            "status": plan.status,
            "kp_sequence": kp_sequence,
            "metadata": {
                "source": "plan_engine",
                "kp_count": total_kps,
                "generated_at": now,
            },
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
        })

        logger.info(
            "学习计划已生成: plan_id=%s kps=%d items=%d",
            plan.plan_id,
            total_kps,
            len(schedule),
        )

        return plan

    # ==================================================================
    # topological_sort() — Kahn 算法拓扑排序
    # ==================================================================

    @staticmethod
    def topological_sort(kps: list[dict]) -> list[str]:
        """按前置依赖关系对知识点进行拓扑排序。

        使用 Kahn 算法（BFS 基实现）：
        1. 计算每个节点的入度（有几条 prerequisite 边指向它）
        2. 入度为零的节点入队（无依赖，可先学）
        3. 出队 → 输出 → 将其后继的入度减一 → 入度为零者入队
        4. 剩余节点（环或孤立引用）追加到末尾

        Args:
            kps: 知识点字典列表，每个包含 kp_id 和
                 prerequisite_ids（JSON 字符串或列表）。

        Returns:
            list[str]: 拓扑排序后的 kp_id 列表。
        """
        if not kps:
            return []

        kp_ids = {kp["kp_id"] for kp in kps}

        # 构建邻接表和入度表
        # adj[前置] → [后继列表]（方向：前置 → 后继）
        adj: dict[str, list[str]] = {k: [] for k in kp_ids}
        in_degree: dict[str, int] = {k: 0 for k in kp_ids}

        for kp in kps:
            kid = kp["kp_id"]
            prereqs = _parse_json_list(kp.get("prerequisite_ids", "[]"))
            for pid in prereqs:
                if pid in kp_ids and pid != kid:
                    adj.setdefault(pid, []).append(kid)
                    in_degree[kid] = in_degree.get(kid, 0) + 1

        # Kahn 算法：入度为零者入队
        queue: deque[str] = deque(
            k for k in kp_ids if in_degree.get(k, 0) == 0
        )
        result: list[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 追加剩余节点（环或孤立引用）
        for k in kp_ids:
            if k not in result:
                result.append(k)

        return result

    # ==================================================================
    # 辅助计算方法
    # ==================================================================

    @staticmethod
    def _compute_priority(
        mastery: float,
        successor_count: int,
        total_kps: int,
    ) -> float:
        """计算单个知识点的优先级分数。

        公式: (1 - mastery) × (1 + successor_count / total_kps)

        两层含义：
        - (1 - mastery): 掌握度越低 → 越紧急（范围为 [0, 1]）
        - (1 + successor_count/total_kps): 后继越多 → 越重要
          （阻塞了更多 KP，范围为 [1, 2]）

        Args:
            mastery: 当前掌握度（0.0–1.0）。
            successor_count: 直接后继知识点数量。
            total_kps: 计划中的总知识点数量。

        Returns:
            float: 优先级分数（0.0–2.0，越大越优先）。
        """
        mastery_gap = 1.0 - mastery
        successor_factor = 1.0 + (successor_count / total_kps if total_kps > 0 else 0.0)
        return round(mastery_gap * successor_factor, 4)

    @staticmethod
    def _activity_for_mastery(mastery: float) -> str:
        """根据掌握度确定推荐的活动类型。

        4 个区间：
        - < 0.3: learn_new（需要从零学习）
        - 0.3–0.5: review（基本了解但需要系统复习）
        - 0.5–0.8: practice（基本掌握，通过练习巩固）
        - ≥ 0.8: quiz（已掌握，用测验验证）

        Args:
            mastery: 当前掌握度（0.0–1.0）。

        Returns:
            str: 活动类型常量（learn_new / review / practice / quiz）。
        """
        if mastery < 0.3:
            return _ACTIVITY_LEARN_NEW
        elif mastery < 0.5:
            return _ACTIVITY_REVIEW
        elif mastery < 0.8:
            return _ACTIVITY_PRACTICE
        else:
            return _ACTIVITY_QUIZ

    @staticmethod
    def _estimate_minutes(difficulty: str, mastery_gap: float) -> int:
        """根据难度和掌握度差距估算学习时长。

        公式: duration = base_difficulty × (0.5 + mastery_gap)
        - mastery_gap=1.0（完全不会）→ 1.5× 基准时长
        - mastery_gap=0.0（已掌握）→ 0.5× 基准时长
        - 最终裁剪到 [10, 120] 分钟

        Args:
            difficulty: 难度等级（beginner/easy/medium/hard/expert）。
            mastery_gap: 1.0 - mastery（还需掌握多少）。

        Returns:
            int: 预估学习时长（分钟），范围 10–120。
        """
        base = _DIFFICULTY_MINUTES.get(difficulty, 30)
        # 缩放因子：0.5（已掌握）到 1.5（完全不会）
        scaled = int(base * (0.5 + mastery_gap))
        return max(10, min(120, scaled))
