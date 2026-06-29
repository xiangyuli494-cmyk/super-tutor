"""苏格拉底式引导引擎 — 基于错题的启发式追问教学。

【功能说明】
基于错题和知识点内容，通过层层递进的引导性问题帮助学生自主发现正确答案，
而非直接告知。模仿苏格拉底教学法"产婆术"。

状态机（5 级层级，LLM 驱动 + Python 安全阀）：

    start_dialogue → L1_GUIDING (笼统引导)
                         ↓
                    学生回答
                         ↓
                    LLM 判断 → L2_HINTING (具体提示)
                                   ↓
                              学生回答
                                   ↓
                              LLM 判断 → L3_NEAR_ANSWER (接近答案)
                                             ↓
                                         RESOLVED (已解决) ← 学生展示理解
                                         SHOW_ANSWER (显示答案) ← 学生请求/超限

两个 Python 安全阀（在 LLM 调用前拦截）：
1. 关键词检测（_is_show_answer_request）:
   15 个中英文触发词 → 直接进入 SHOW_ANSWER 路径
2. 最大轮数限制（_MAX_DIALOGUE_TURNS = 6）:
   超过 6 轮 → 强制执行 _force_show_answer（LLM 输出 SHOW_ANSWER）

对话状态仅保存在 st.session_state，不持久化到数据库。

【耦合关系】
- 依赖 Database（获取 KP 和错题数据）、LLMClient（LLM 引导生成）
- 被 app.py 的错题本 Tab 中苏格拉底追问功能调用
- 使用 models/socratic.py 的 SocraticTurn 模型和工具函数
- 使用 prompts/socratic.md（苏格拉底教学系统提示词）
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from super_tutor.core.database import Database
from super_tutor.core.exceptions import LLMError, MaterialError
from super_tutor.core.llm_client import LLMClient
from super_tutor.models.socratic import (
    SocraticTurn,
    build_history_entry,
    format_history_for_prompt,
    L1_GUIDING,
    SHOW_ANSWER,
    RESOLVED,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 默认 prompt 路径 — 苏格拉底教学系统提示词
# ---------------------------------------------------------------------------
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_DEFAULT_SOCRATIC_PROMPT = _PROMPTS_DIR / "socratic.md"

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
_MAX_DIALOGUE_TURNS = 6  # 超过此轮数自动升级到 SHOW_ANSWER（安全阀2）


class SocraticEngine:
    """苏格拉底式引导追问引擎。

    核心设计理念：教师不直接告知答案，而是通过问题链引导学生
    自主推理和发现正确答案。这种教学法的关键在于：
    1. 从学生的当前认知水平出发（L1）
    2. 逐步缩小问题范围（L1 → L2 → L3）
    3. 在学生顿悟时及时确认（RESOLVED）
    4. 在必要时给予完整解析（SHOW_ANSWER）

    Usage::

        engine = SocraticEngine(db, llm_client)
        turn = await engine.start_dialogue("kp-001", "wrong-001")
        # 展示 turn.teacher_message 给学生...
        history = [build_history_entry(turn, "学生的回答")]
        next_turn = await engine.continue_dialogue(history, "学生的回答")
    """

    def __init__(
        self,
        db: Database,
        llm_client: LLMClient,
        prompt_path: Optional[str] = None,
    ) -> None:
        """初始化苏格拉底引擎。

        Args:
            db: 已初始化的 Database 实例。
            llm_client: LLMClient 实例。
            prompt_path: 可选的自定义提示词路径（默认 prompts/socratic.md）。
        """
        self._db = db
        self._llm = llm_client
        self._prompt_path = prompt_path or str(_DEFAULT_SOCRATIC_PROMPT)

    # ==================================================================
    # start_dialogue() — 开始新对话（入口）
    # ==================================================================

    async def start_dialogue(
        self,
        kp_id: str,
        wrong_question_id: str,
    ) -> SocraticTurn:
        """开始一轮新的苏格拉底对话。

        流程：
        1. 从 DB 获取 KP 内容和错题记录（含原始题目信息）
        2. 构建对话启动 prompt（含 KP 内容、错题信息、正确答案）
        3. 调用 LLM，要求从 L1_GUIDING 层级开始引导

        Args:
            kp_id: 知识点 ID。
            wrong_question_id: 错题记录 ID（wrong_questions 表）。

        Returns:
            SocraticTurn: level=L1_GUIDING 的首轮引导消息。

        Raises:
            MaterialError: KP 或错题记录不存在，或 LLM 返回无效响应。
        """
        # -- 第 1 步：获取上下文数据 ------------------------------------------
        kp_data, wrong_data = await self._fetch_context(kp_id, wrong_question_id)

        # -- 第 2 步：构建启动 prompt -----------------------------------------
        user_prompt = self._build_start_prompt(kp_data, wrong_data)

        # -- 第 3 步：调用 LLM ------------------------------------------------
        raw_json = await self._call_llm(user_prompt)

        # -- 第 4 步：解析并返回 ----------------------------------------------
        turn = self._parse_turn(raw_json, kp_id, wrong_question_id)

        logger.info(
            "Socratic dialogue started: kp=%s wrong=%s turn=%s level=%s",
            kp_id,
            wrong_question_id,
            turn.turn_id,
            turn.level,
        )
        return turn

    # ==================================================================
    # continue_dialogue() — 继续对话（核心状态机）
    # ==================================================================

    async def continue_dialogue(
        self,
        history: list[dict[str, Any]],
        user_response: str,
    ) -> SocraticTurn:
        """继续苏格拉底对话。

        这是状态机的核心方法，根据学生回答和历史对话决定下一层级。
        决策顺序（优先级从高到低）：

        1. 关键词检测 → 学生说"显示答案"等 → SHOW_ANSWER（Python 安全阀1）
        2. 轮数检测 → 超过 6 轮 → 强制 SHOW_ANSWER（Python 安全阀2）
        3. LLM 决策 → 将历史+学生回答发给 LLM，由 LLM 判断下一层级

        Args:
            history: 对话历史列表（build_history_entry() 返回的格式）。
            user_response: 学生本次的回答文本。

        Returns:
            SocraticTurn: 下一轮教师引导消息。

        Raises:
            ValueError: history 为空。
            MaterialError: 上下文获取失败或 LLM 返回无效响应。
        """
        if not history:
            raise ValueError("history 不能为空")

        # -- 安全阀1：检测学生是否明确要求显示答案 -------------------------
        if self._is_show_answer_request(user_response):
            return self._build_show_answer_turn(history)

        # -- 安全阀2：检测是否超过最大轮数 ---------------------------------
        if len(history) >= _MAX_DIALOGUE_TURNS:
            logger.info(
                "Max dialogue turns (%d) reached — escalating to SHOW_ANSWER",
                _MAX_DIALOGUE_TURNS,
            )
            return await self._force_show_answer(history, user_response)

        # -- 正常流程：从 history 中提取上下文 ---------------------------------
        kp_id = history[0].get("kp_id", "")
        wrong_question_id = history[0].get("wrong_question_id", "")

        if not kp_id or not wrong_question_id:
            raise ValueError("history[0] 缺少 kp_id 或 wrong_question_id")

        # -- 获取上下文数据 ---------------------------------------------------
        kp_data, wrong_data = await self._fetch_context(kp_id, wrong_question_id)

        # -- 构建继续对话 prompt（含完整历史）----------------------------------
        user_prompt = self._build_continue_prompt(
            kp_data, wrong_data, history, user_response
        )

        # -- 调用 LLM（由 LLM 判断下一层级）----------------------------------
        raw_json = await self._call_llm(user_prompt)

        # -- 解析并返回 -------------------------------------------------------
        turn = self._parse_turn(raw_json, kp_id, wrong_question_id)

        logger.info(
            "Socratic dialogue continued: turn=%s level=%s resolved=%s",
            turn.turn_id,
            turn.level,
            turn.resolved,
        )
        return turn

    # ==================================================================
    # 内部方法：上下文获取
    # ==================================================================

    async def _fetch_context(
        self, kp_id: str, wrong_question_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """从数据库获取 KP 和错题数据，并丰富题目信息。

        获取的数据用于构建 LLM prompt：
        - KP: 标题、难度、内容
        - 错题: 学生错误答案、正确答案
        - 原始题目: 题干、解析、题目类型

        Returns:
            tuple: (kp_data, wrong_data)。wrong_data 被丰富后增加了
                   _question_stem、_question_explanation、_question_type 字段。
        """
        # 获取知识点
        kp_data = await self._db.get_knowledge_point(kp_id)
        if kp_data is None:
            raise MaterialError(f"知识点不存在: {kp_id}")

        # 获取错题记录
        wrong_data = await self._db.get_wrong_question(wrong_question_id)
        if wrong_data is None:
            raise MaterialError(f"错题记录不存在: {wrong_question_id}")

        # 丰富错题数据：从 questions 表获取原始题目信息
        question_id = wrong_data.get("question_id", "")
        if question_id:
            q_row = await self._db.get_question(question_id)
            if q_row:
                wrong_data["_question_stem"] = q_row.get("stem", "")
                wrong_data["_question_explanation"] = q_row.get("explanation", "")
                wrong_data["_question_type"] = q_row.get("type", "")

        return kp_data, wrong_data

    # ==================================================================
    # 内部方法：prompt 构建
    # ==================================================================

    @staticmethod
    def _build_start_prompt(
        kp_data: dict[str, Any],
        wrong_data: dict[str, Any],
    ) -> str:
        """构建 start_dialogue 的 LLM 用户 prompt。

        包含：知识点信息、错题信息（题干+学生答案+正确答案+解析）
        末尾指示 LLM 从 L1_GUIDING 开始。
        """
        lines = [
            "## 知识点",
            f"- 标题: {kp_data.get('title', '')}",
            f"- 难度: {kp_data.get('difficulty', 'medium')}",
            f"- 内容: {kp_data.get('content', '')}",
            "",
            "## 错题",
            f"- 题干: {wrong_data.get('_question_stem', wrong_data.get('note', ''))}",
            f"- 学生答案: {wrong_data.get('wrong_answer', '')}",
            f"- 正确答案: {wrong_data.get('correct_answer', '')}",
        ]

        explanation = wrong_data.get(
            "_question_explanation", ""
        ) or wrong_data.get("note", "")
        if explanation:
            lines.append(f"- 解析: {explanation}")

        lines.append("")
        lines.append("请从 L1_GUIDING 层级开始引导。")
        return "\n".join(lines)

    @staticmethod
    def _build_continue_prompt(
        kp_data: dict[str, Any],
        wrong_data: dict[str, Any],
        history: list[dict[str, Any]],
        user_response: str,
    ) -> str:
        """构建 continue_dialogue 的 LLM 用户 prompt。

        在启动 prompt 基础上增加：
        - 对话历史（格式化后的教师-学生多轮对话）
        - 学生本轮回应
        - 指示 LLM 判断下一层级
        """
        lines = [
            "## 知识点",
            f"- 标题: {kp_data.get('title', '')}",
            f"- 难度: {kp_data.get('difficulty', 'medium')}",
            f"- 内容: {kp_data.get('content', '')}",
            "",
            "## 错题",
            f"- 题干: {wrong_data.get('_question_stem', wrong_data.get('note', ''))}",
            f"- 学生答案: {wrong_data.get('wrong_answer', '')}",
            f"- 正确答案: {wrong_data.get('correct_answer', '')}",
        ]

        explanation = wrong_data.get(
            "_question_explanation", ""
        ) or wrong_data.get("note", "")
        if explanation:
            lines.append(f"- 解析: {explanation}")

        lines.append("")
        lines.append("## 对话历史")
        lines.append(format_history_for_prompt(history))
        lines.append("")
        lines.append("## 学生本轮回应")
        lines.append(user_response)
        lines.append("")
        lines.append("请根据学生的回应判断下一层级并生成引导内容。")
        return "\n".join(lines)

    # ==================================================================
    # 内部方法：LLM 调用
    # ==================================================================

    async def _call_llm(
        self, user_prompt: str
    ) -> str:
        """调用 LLM 进行苏格拉底式引导生成。

        加载系统提示词（prompts/socratic.md）→ 发送用户 prompt →
        返回原始 LLM 响应（JSON 字符串）。

        Args:
            user_prompt: 格式化的用户 prompt。

        Returns:
            str: LLM 原始响应（JSON 格式，待解析）。
        """
        try:
            system_prompt = Path(self._prompt_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise MaterialError(
                f"无法加载苏格拉底提示词: {self._prompt_path} ({exc})"
            ) from exc

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            raw = await self._llm.chat(
                messages=messages,
                temperature=0.7,     # 中等温度保持引导自然度
                max_tokens=2048,     # 教师消息通常不长
                timeout=120,
            )
        except LLMError as exc:
            raise MaterialError(f"LLM 苏格拉底追问失败: {exc}") from exc

        return _strip_markdown_fence(raw)

    # ==================================================================
    # 内部方法：解析和辅助
    # ==================================================================

    def _parse_turn(
        self,
        raw_json: str,
        kp_id: str,
        wrong_question_id: str,
    ) -> SocraticTurn:
        """解析 LLM 返回的 JSON → SocraticTurn 模型。

        必填字段：level、teacher_message
        可选字段：expected_concepts、reasoning、resolved、resolution_note

        Raises:
            MaterialError: JSON 无效或缺少 teacher_message。
        """
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.error("Socratic LLM 返回无效 JSON: %s", raw_json[:500])
            raise MaterialError(
                f"苏格拉底追问结果不是有效 JSON: {exc}"
            ) from exc

        level = data.get("level", L1_GUIDING)
        teacher_message = data.get("teacher_message", "")

        if not teacher_message:
            raise MaterialError("LLM 未返回 teacher_message")

        return SocraticTurn(
            turn_id=str(uuid4()),
            kp_id=kp_id,
            wrong_question_id=wrong_question_id,
            level=level,
            teacher_message=teacher_message,
            expected_concepts=data.get("expected_concepts", []),
            reasoning=data.get("reasoning", ""),
            resolved=data.get("resolved", False)
                or level in (RESOLVED, SHOW_ANSWER),  # 终端层级自动 resolved=True
            resolution_note=data.get("resolution_note", ""),
        )

    @staticmethod
    def _is_show_answer_request(user_response: str) -> bool:
        """检测学生是否明确要求直接显示答案。（安全阀1 — Python 关键词匹配）

        触发词列表（15 个中英文关键词）：
        - 中文: "显示答案", "告诉我答案", "直接说答案", "公布答案",
                 "看答案", "给答案", "答案是什么", "正确答案是什么",
                 "我不会", "完全不会", "太难了", "想不出来"
        - 英文: "show answer", "tell me the answer", "give me the answer"

        Args:
            user_response: 学生的输入文本。

        Returns:
            bool: 匹配到任何触发词返回 True。
        """
        triggers = [
            "显示答案", "告诉我答案", "直接说答案", "公布答案",
            "看答案", "给答案", "答案是什么", "正确答案是什么",
            "我不会", "完全不会", "太难了", "想不出来",
            "show answer", "tell me the answer", "give me the answer",
        ]
        lowered = user_response.strip().lower()
        return any(t.lower() in lowered for t in triggers)

    def _build_show_answer_turn(
        self,
        history: list[dict[str, Any]],
    ) -> SocraticTurn:
        """构建 SHOW_ANSWER 轮次（安全阀1的快速路径）。

        不调用 LLM，直接返回一则"软确认"消息。
        学生必须再次输入"显示答案"才会真正进入 LLM 生成的完整解析。

        这种"二次确认"设计防止学生误触"显示答案"按钮后
        直接看到答案，给予最后一次思考机会。

        Args:
            history: 对话历史（用于提取上下文 ID）。

        Returns:
            SocraticTurn: level=SHOW_ANSWER 但 resolved=False 的软确认轮。
        """
        first = history[0]
        kp_id = first.get("kp_id", "")
        wrong_question_id = first.get("wrong_question_id", "")

        logger.info(
            "User requested answer explicitly — switching to SHOW_ANSWER"
        )
        return SocraticTurn(
            turn_id=str(uuid4()),
            kp_id=kp_id,
            wrong_question_id=wrong_question_id,
            level=SHOW_ANSWER,
            teacher_message=(
                '好的，让我来为你详细解析这道题。\n\n'
                '不过在此之前 — 你能先告诉我你目前对这个知识点的理解吗？'
                '这样我可以更有针对性地解释。\n\n'
                '（如果你希望直接看答案，请再次输入 **显示答案**。）'
            ),
            expected_concepts=[],
            reasoning="学生请求显示答案，先进行一轮软确认",
            resolved=False,  # 注意：不是终端状态，学生还可以继续
            resolution_note="",
        )

    async def _force_show_answer(
        self,
        history: list[dict[str, Any]],
        user_response: str,
    ) -> SocraticTurn:
        """达到最大轮数后强制显示答案。（安全阀2 — 轮数限制）

        调用 LLM 时附加"已达到最大对话轮数"的指示，
        LLM 将以 SHOW_ANSWER 层级给出完整解析。

        Args:
            history: 对话历史。
            user_response: 学生本轮输入。

        Returns:
            SocraticTurn: level=SHOW_ANSWER 的完整解析。
        """
        first = history[0]
        kp_id = first.get("kp_id", "")
        wrong_question_id = first.get("wrong_question_id", "")
        kp_data, wrong_data = await self._fetch_context(kp_id, wrong_question_id)

        user_prompt = (
            self._build_continue_prompt(kp_data, wrong_data, history, user_response)
            + "\n\n**注意：已达到最大对话轮数，请直接以 SHOW_ANSWER 层级给出完整解析。**"
        )

        raw_json = await self._call_llm(user_prompt)
        return self._parse_turn(raw_json, kp_id, wrong_question_id)


# ===================================================================
# 模块级工具函数
# ===================================================================


def _strip_markdown_fence(raw: str) -> str:
    """去除 LLM 响应中的 Markdown 代码围栏（```json ... ```）。"""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]       # 去掉开始的 ```json
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]      # 去掉结束的 ```
        raw = "\n".join(lines)
    return raw
