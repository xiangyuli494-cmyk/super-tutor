"""苏格拉底式引导追问模型 — 对话轮次数据结构。

【功能说明】
定义 SocraticEngine 的单轮对话输出结构 SocraticTurn，
以及对话历史的构建和格式化工具函数。

状态机层级常量（5 级）：
- L1_GUIDING: 笼统引导 — 最宽泛的开放性问题
- L2_HINTING: 具体提示 — 方向性暗示
- L3_NEAR_ANSWER: 接近答案 — 几乎给出完整推理步骤
- RESOLVED: 已解决 — 学生展示出正确理解，对话结束
- SHOW_ANSWER: 显示答案 — 直接给出完整解析

【耦合关系】
- 被 SocraticEngine 创建和返回
- 被 app.py 的 _render_socratic_dialogue() 渲染对话 UI
- 不依赖数据库（对话状态仅保存在 st.session_state）
- 不依赖项目内其他模型模块
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 苏格拉底层级常量（对话状态机的 5 种状态）
# ---------------------------------------------------------------------------

L1_GUIDING = "L1_GUIDING"            # 笼统引导 — 最宽泛的开放性问题（对话入口）
L2_HINTING = "L2_HINTING"            # 具体提示 — 给出方向性暗示，缩小思考范围
L3_NEAR_ANSWER = "L3_NEAR_ANSWER"    # 接近答案 — 几乎给出完整推理步骤，只留最后一步
RESOLVED = "RESOLVED"                # 已解决 — 学生展示出正确理解，对话终止
SHOW_ANSWER = "SHOW_ANSWER"          # 显示答案 — 学生请求/需要直接看完整解析，对话终止

# 合法层级集合（用于验证）
VALID_LEVELS: set[str] = {
    L1_GUIDING,
    L2_HINTING,
    L3_NEAR_ANSWER,
    RESOLVED,
    SHOW_ANSWER,
}


# ============================================================================
# SocraticTurn — 单轮苏格拉底对话
# ============================================================================


class SocraticTurn(BaseModel):
    """苏格拉底式引导追问中的单轮教师回复。

    由 SocraticEngine.start_dialogue() 或
    SocraticEngine.continue_dialogue() 生成。
    不持久化到数据库，仅保存在 st.session_state 中。

    对话流程：
    1. start_dialogue() → L1_GUIDING 的 SocraticTurn
    2. 学生回答 → continue_dialogue() → 下一轮 SocraticTurn
    3. 重复步骤 2，直到 resolved=True（RESOLVED 或 SHOW_ANSWER）
    """

    turn_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="本轮唯一标识（UUID v4）",
    )
    kp_id: str = Field(
        ...,
        description="关联的知识点 ID",
    )
    wrong_question_id: str = Field(
        ...,
        description="关联的错题 ID（wrong_questions 表）",
    )
    level: str = Field(
        default=L1_GUIDING,
        description=f"当前引导层级：L1_GUIDING / L2_HINTING / L3_NEAR_ANSWER / RESOLVED / SHOW_ANSWER",
    )
    teacher_message: str = Field(
        ...,
        min_length=1,
        description="教师对学生的引导消息（支持 Markdown 格式），展示在对话 UI 中",
    )
    expected_concepts: list[str] = Field(
        default_factory=list,
        description="学生应在此轮中想到的关键概念列表（1–5 个，用于教师参考）",
    )
    reasoning: str = Field(
        default="",
        description="内部推理：选择此层级和内容的简短理由（不展示给学生）",
    )
    resolved: bool = Field(
        default=False,
        description="True 表示对话已结束（RESOLVED 或 SHOW_ANSWER 层级）",
    )
    resolution_note: str = Field(
        default="",
        description="当 resolved=True 时的解决方式说明（如'学生通过引导自主发现正确答案'）",
    )

    @property
    def is_terminal(self) -> bool:
        """本轮是否为对话的最后一轮（终端状态）。

        Returns:
            bool: resolved=True 或 level 为 RESOLVED/SHOW_ANSWER 时返回 True。
        """
        return self.resolved or self.level in (RESOLVED, SHOW_ANSWER)


# ============================================================================
# 辅助函数 — 对话历史构建和格式化
# ============================================================================


def build_history_entry(turn: SocraticTurn, user_response: str) -> dict[str, Any]:
    """将一轮对话转为历史条目，用于下次 continue_dialogue() 调用。

    对话历史存储在 st.session_state[_S_SOCRATIC_HISTORY] 中，
    不写入数据库。每次学生回答后，将本轮 turn 和学生回应打包
    追加到历史列表。

    Args:
        turn: 本轮教师回复（SocraticTurn 对象）
        user_response: 学生对本轮教师消息的回应文本

    Returns:
        dict: 包含 turn_id、kp_id、wrong_question_id、level、
              teacher_message、user_response 的字典
    """
    return {
        "turn_id": turn.turn_id,
        "kp_id": turn.kp_id,
        "wrong_question_id": turn.wrong_question_id,
        "level": turn.level,
        "teacher_message": turn.teacher_message,
        "user_response": user_response,
    }


def format_history_for_prompt(history: list[dict[str, Any]]) -> str:
    """将对话历史格式化为可嵌入 LLM prompt 的文本。

    用于 SocraticEngine._build_continue_prompt() 中，
    将历史对话转为 LLM 能理解的上下文。

    Args:
        history: build_history_entry() 返回的条目列表

    Returns:
        str: 格式化的对话历史文本，每轮包含层级标签、教师消息和学生回应。
    """
    if not history:
        return "（无历史对话）"

    lines: list[str] = []
    for i, entry in enumerate(history):
        level_label = _level_label(entry.get("level", ""))
        lines.append(f"## 第 {i + 1} 轮 ({level_label})")
        lines.append(f"**教师**: {entry.get('teacher_message', '')}")
        lines.append(f"**学生**: {entry.get('user_response', '')}")
        lines.append("")
    return "\n".join(lines)


def _level_label(level: str) -> str:
    """将层级常量转为人类可读的中文标签。

    Args:
        level: 层级常量（L1_GUIDING 等）

    Returns:
        str: 中文标签（如'笼统引导'）
    """
    labels: dict[str, str] = {
        L1_GUIDING: "笼统引导",
        L2_HINTING: "具体提示",
        L3_NEAR_ANSWER: "接近答案",
        RESOLVED: "已解决",
        SHOW_ANSWER: "显示答案",
    }
    return labels.get(level, level)
