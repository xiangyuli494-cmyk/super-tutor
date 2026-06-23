"""Super Tutor Agent — 掌握度与学习计划模型。

定义认知孪生追踪、学生画像和基于 SM-2 算法的智能排期。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ============================================================================
# SM-2 算法常量
# ============================================================================

_SM2_DEFAULT_EF = 2.5       # 初始难易度因子
_SM2_MIN_EF = 1.3           # 难易度下限
_SM2_FIRST_INTERVAL = 1     # 首次通过后间隔（天）
_SM2_SECOND_INTERVAL = 6    # 第二次通过后间隔（天）
_SM2_QUALITY_PASS = 3        # 通过阈值（0-5 评分中 >= 3 算通过）


# ============================================================================
# MasteryRecord — 单知识点认知孪生
# ============================================================================


class MasteryRecord(BaseModel):
    """学生对单个知识节点的掌握度追踪记录（认知孪生）。

    内嵌 SM-2 间隔重复算法状态，每次作答后调用 ``apply_sm2(quality)``
    更新排期参数。quality 为学生自评或系统评估的 0-5 分：
    - 5: 完美 — 无需思考即答对
    - 4: 正确 — 稍有犹豫但答对
    - 3: 正确 — 但比较困难
    - 2: 错误 — 但看到答案后觉得很简单
    - 1: 错误 — 看到答案后仍然不理解
    - 0: 完全不会
    """

    record_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="记录唯一标识",
    )
    student_id: str = Field(
        ...,
        description="学生 ID",
    )
    knowledge_node_id: str = Field(
        ...,
        description="对应的 KnowledgeNode ID",
    )
    mastery_level: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="当前预估掌握度（0-1），综合正确率与 SM-2 状态得出",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="系统对该掌握度估计的置信度（数据越多越接近 1.0）",
    )
    total_attempts: int = Field(
        default=0,
        ge=0,
        description="总作答次数",
    )
    correct_attempts: int = Field(
        default=0,
        ge=0,
        description="正确作答次数",
    )
    last_attempt_at: Optional[str] = Field(
        default=None,
        description="最近一次作答时间（ISO 8601）",
    )
    last_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="最近一次得分",
    )
    streak: int = Field(
        default=0,
        ge=0,
        description="连续正确次数",
    )
    time_spent_total_seconds: int = Field(
        default=0,
        ge=0,
        description="该知识点累计学习时间（秒）",
    )
    hints_used_total: int = Field(
        default=0,
        ge=0,
        description="累计使用提示次数",
    )
    misconception_ids: list[str] = Field(
        default_factory=list,
        description="反复出现的 MisconceptionTag ID 列表",
    )
    state: str = Field(
        default="new",
        description="学习状态：new / learning / reviewing / mastered / stagnated",
    )

    # -- SM-2 排期参数 -------------------------------------------------------

    sm2_repetitions: int = Field(
        default=0,
        ge=0,
        description="SM-2: 成功记忆的连续次数 (n)",
    )
    sm2_ease_factor: float = Field(
        default=_SM2_DEFAULT_EF,
        ge=_SM2_MIN_EF,
        description="SM-2: 难易度因子 (EF)，初始 2.5，下限 1.3",
    )
    sm2_interval_days: int = Field(
        default=0,
        ge=0,
        description="SM-2: 当前复习间隔（天）",
    )
    sm2_next_review: Optional[str] = Field(
        default=None,
        description="SM-2: 下一次复习日期（ISO 8601 date）",
    )
    sm2_last_quality: Optional[int] = Field(
        default=None,
        ge=0,
        le=5,
        description="SM-2: 最近一次作答质量评分（0-5）",
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601）",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="最后更新时间（ISO 8601）",
    )

    # -- 计算属性 ------------------------------------------------------------

    @property
    def accuracy(self) -> float:
        """正确率（0-1），无作答记录时返回 0.0。"""
        if self.total_attempts == 0:
            return 0.0
        return self.correct_attempts / self.total_attempts

    @property
    def is_due(self) -> bool:
        """SM-2 排期：是否到了应复习的时间。"""
        if self.sm2_next_review is None:
            return self.state in ("new", "learning")
        today = datetime.now(timezone.utc).date().isoformat()
        return self.sm2_next_review <= today

    @property
    def days_until_review(self) -> Optional[int]:
        """距下次复习还有多少天（负数=已逾期）。"""
        if self.sm2_next_review is None:
            return None
        today = datetime.now(timezone.utc).date()
        review_date = datetime.fromisoformat(self.sm2_next_review).date()
        return (review_date - today).days

    # -- SM-2 算法 -----------------------------------------------------------

    def apply_sm2(self, quality: int) -> None:
        """根据作答质量评分更新 SM-2 状态与排期。

        调用时机：学生完成一次针对该知识点的作答后。

        Args:
            quality: 0-5 作答质量评分（详见类文档）。

        Raises:
            ValueError: 若 quality 不在 0-5 范围内。
        """
        if not 0 <= quality <= 5:
            raise ValueError(f"quality 必须在 0-5 之间，收到 {quality}")

        self.sm2_last_quality = quality
        self.total_attempts += 1
        passed = quality >= _SM2_QUALITY_PASS

        # ① 更新难易度因子 (EF) — 必须在计算间隔之前
        ef_delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
        self.sm2_ease_factor = max(
            _SM2_MIN_EF, self.sm2_ease_factor + ef_delta
        )

        # ② 根据新 EF 计算复习间隔
        if passed:
            self.correct_attempts += 1
            self.streak += 1

            if self.sm2_repetitions == 0:
                self.sm2_interval_days = _SM2_FIRST_INTERVAL
            elif self.sm2_repetitions == 1:
                self.sm2_interval_days = _SM2_SECOND_INTERVAL
            else:
                self.sm2_interval_days = round(
                    self.sm2_interval_days * self.sm2_ease_factor
                )

            self.sm2_repetitions += 1
        else:
            self.streak = 0
            self.sm2_repetitions = 0
            self.sm2_interval_days = _SM2_FIRST_INTERVAL

        # ③ 计算下次复习日期
        review_date = datetime.now(timezone.utc).date()
        from datetime import timedelta

        review_date += timedelta(days=self.sm2_interval_days)
        self.sm2_next_review = review_date.isoformat()

        # 更新掌握度与学习状态
        self._update_mastery()
        self._update_state()

    # -- 内部状态更新 --------------------------------------------------------

    def _update_mastery(self) -> None:
        """综合正确率、SM-2 状态和置信度估算掌握度。"""
        # 基础分来自正确率
        acc_weight = self.accuracy

        # SM-2 贡献：高 repetitions + 高 EF → 更牢固
        sm2_weight = min(1.0, self.sm2_repetitions / 10) * min(1.0, self.sm2_ease_factor / 2.5)

        # 置信度权重：数据少时保守估计
        confidence_weight = min(1.0, self.total_attempts / 5)

        raw = 0.4 * acc_weight + 0.4 * sm2_weight + 0.2 * confidence_weight
        self.mastery_level = round(min(1.0, max(0.0, raw)), 4)
        self.confidence = round(min(1.0, self.total_attempts / 7), 4)

    def _update_state(self) -> None:
        """根据 mastering 程度更新学习状态标签。"""
        if self.total_attempts == 0:
            self.state = "new"
        elif self.mastery_level >= 0.9 and self.sm2_repetitions >= 3:
            self.state = "mastered"
        elif self.streak == 0 and self.total_attempts >= 3:
            self.state = "stagnated"
        elif self.sm2_repetitions >= 1:
            self.state = "reviewing"
        else:
            self.state = "learning"


# ============================================================================
# StudentProfile — 学生画像
# ============================================================================


class StudentProfile(BaseModel):
    """学生综合学习画像，聚合所有 MasteryRecord 以形成全局视图。

    由 AI 引擎定期更新或根据作答事件增量刷新。
    """

    student_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="学生唯一标识",
    )
    display_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="显示名称（昵称 / 真实姓名）",
    )
    avatar_url: Optional[str] = Field(
        default=None,
        description="头像 URL",
    )
    grade_level: str = Field(
        default="",
        description="年级，如'高一'、'大学二年级'",
    )
    subjects: list[str] = Field(
        default_factory=list,
        description="学习科目列表",
    )
    learning_style: str = Field(
        default="visual",
        description="学习风格偏好：visual / auditory / reading / kinesthetic",
    )
    daily_study_minutes: int = Field(
        default=30,
        ge=0,
        description="每日目标学习时长（分钟）",
    )
    current_streak_days: int = Field(
        default=0,
        ge=0,
        description="当前连续学习天数",
    )
    total_study_days: int = Field(
        default=0,
        ge=0,
        description="累计学习天数",
    )
    total_questions_attempted: int = Field(
        default=0,
        ge=0,
        description="累计作答题目数",
    )
    overall_accuracy: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="总体正确率",
    )
    mastery_record_ids: list[str] = Field(
        default_factory=list,
        description="所有 MasteryRecord ID 列表",
    )
    weak_topics: list[str] = Field(
        default_factory=list,
        description="薄弱知识点标签（需重点加强）",
    )
    strong_topics: list[str] = Field(
        default_factory=list,
        description="优势知识点标签",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601）",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="最后更新时间（ISO 8601）",
    )

    @property
    def recorded_nodes_count(self) -> int:
        """已追踪的知识点数量。"""
        return len(self.mastery_record_ids)


# ============================================================================
# ReviewItem — 排期中的单个复习项
# ============================================================================


class ReviewItem(BaseModel):
    """学习计划中的单个复习/学习条目。

    由 SM-2 算法根据 MasteryRecord 自动生成，也可手动添加。
    """

    item_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="条目唯一标识",
    )
    knowledge_node_id: str = Field(
        ...,
        description="对应的 KnowledgeNode ID",
    )
    mastery_record_id: Optional[str] = Field(
        default=None,
        description="关联的 MasteryRecord ID（如有）",
    )
    scheduled_date: str = Field(
        ...,
        description="计划日期（ISO 8601 date）",
    )
    activity_type: str = Field(
        default="review",
        description="活动类型：review / learn_new / practice / quiz / rest",
    )
    estimated_minutes: int = Field(
        default=15,
        ge=0,
        description="预计耗时（分钟）",
    )
    completed: bool = Field(
        default=False,
        description="是否已完成",
    )
    completed_at: Optional[str] = Field(
        default=None,
        description="完成时间（ISO 8601）",
    )
    notes: str = Field(
        default="",
        description="备注",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据",
    )


# ============================================================================
# StudyPlan — 学习计划
# ============================================================================


class StudyPlan(BaseModel):
    """基于 SM-2 算法生成的学习计划，将待复习知识点按优先级排入日程。

    计划中的每个 ReviewItem 对应一个知识点在某一天的学习/复习任务。
    学生完成条目后更新对应 MasteryRecord，SM-2 自动计算下次排期。
    """

    plan_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="计划唯一标识",
    )
    student_id: str = Field(
        ...,
        description="学生 ID",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="计划标题，如'高二物理力学复习计划'",
    )
    description: str = Field(
        default="",
        description="计划说明",
    )
    subject: str = Field(
        default="",
        description="所属学科",
    )
    goal: str = Field(
        default="",
        description="学习目标描述",
    )
    start_date: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat(),
        description="计划开始日期（ISO 8601 date）",
    )
    end_date: Optional[str] = Field(
        default=None,
        description="计划结束日期（ISO 8601 date），None 表示无截止日",
    )
    status: str = Field(
        default="draft",
        description="计划状态：draft / active / completed / paused / archived",
    )
    schedule: list[ReviewItem] = Field(
        default_factory=list,
        description="排期条目列表（按日期升序）",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601）",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="最后更新时间（ISO 8601）",
    )

    # -- 查询方法 -----------------------------------------------------------

    def get_items_for_date(self, date_str: str) -> list[ReviewItem]:
        """返回指定日期的所有排期条目。"""
        return [it for it in self.schedule if it.scheduled_date == date_str]

    def get_pending_items(self) -> list[ReviewItem]:
        """返回所有未完成的条目（含逾期），按日期升序。"""
        return sorted(
            [it for it in self.schedule if not it.completed],
            key=lambda it: it.scheduled_date,
        )

    def get_overdue_items(self) -> list[ReviewItem]:
        """返回所有逾期未完成的条目。"""
        today = datetime.now(timezone.utc).date().isoformat()
        return [
            it
            for it in self.schedule
            if not it.completed and it.scheduled_date < today
        ]

    def get_upcoming_items(self, days: int = 7) -> list[ReviewItem]:
        """返回未来 N 天内的排期条目。"""
        from datetime import timedelta

        today = datetime.now(timezone.utc).date()
        cutoff = today + timedelta(days=days)
        return [
            it
            for it in self.schedule
            if today.isoformat() <= it.scheduled_date <= cutoff.isoformat()
        ]

    # -- 统计 ---------------------------------------------------------------

    @property
    def item_count(self) -> int:
        """排期条目总数。"""
        return len(self.schedule)

    @property
    def completed_count(self) -> int:
        """已完成条目数。"""
        return sum(1 for it in self.schedule if it.completed)

    @property
    def progress(self) -> float:
        """完成进度（0-1），空计划返回 0.0。"""
        if not self.schedule:
            return 0.0
        return round(self.completed_count / len(self.schedule), 4)
