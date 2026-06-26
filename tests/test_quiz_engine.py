"""Tests for QuizEngine internals — helpers, edge cases, and grading logic."""

from __future__ import annotations

import json

import pytest

from super_tutor.engine.quiz_engine import (
    _distribute_counts,
    _grade_programmatic,
    _serialize_answer,
    _strip_markdown_fence,
)
from super_tutor.models.enums import DifficultyLevel, QuestionType
from super_tutor.models.quiz import Question


# ======================================================================
# _distribute_counts
# ======================================================================


class TestDistributeCounts:
    """Tests for _distribute_counts helper."""

    def test_even_distribution(self):
        """Should distribute evenly when count is divisible by kp count."""
        result = _distribute_counts(["a", "b"], 4)
        assert result == {"a": 2, "b": 2}

    def test_with_remainder(self):
        """Should assign remainder items to first KPs."""
        result = _distribute_counts(["a", "b", "c"], 5)
        assert result == {"a": 2, "b": 2, "c": 1}

    def test_single_kp(self):
        """Single KP should get all items."""
        result = _distribute_counts(["only"], 7)
        assert result == {"only": 7}

    def test_empty_list(self):
        """Empty input should return empty dict."""
        result = _distribute_counts([], 5)
        assert result == {}

    def test_count_less_than_kps(self):
        """Count less than KP count should assign 0 or 1 per KP."""
        result = _distribute_counts(["a", "b", "c"], 2)
        assert result["a"] == 1
        assert result["b"] == 1
        assert result["c"] == 0
        assert sum(result.values()) == 2


# ======================================================================
# _grade_programmatic
# ======================================================================


class TestGradeProgrammatic:
    """Tests for programmatic (non-LLM) grading."""

    # -- Multiple choice -------------------------------------------------
    def test_mc_correct_exact(self):
        q = Question(
            question_id="q1", type=QuestionType.MULTIPLE_CHOICE,
            stem="?", correct_answer="B", difficulty=DifficultyLevel.MEDIUM,
        )
        is_correct, score, max_score = _grade_programmatic(q, "B")
        assert is_correct is True
        assert score == 1.0
        assert max_score == 1.0

    def test_mc_correct_lowercase(self):
        q = Question(
            question_id="q2", type=QuestionType.MULTIPLE_CHOICE,
            stem="?", correct_answer="B", difficulty=DifficultyLevel.MEDIUM,
        )
        is_correct, _, _ = _grade_programmatic(q, "b")
        assert is_correct is True

    def test_mc_wrong(self):
        q = Question(
            question_id="q3", type=QuestionType.MULTIPLE_CHOICE,
            stem="?", correct_answer="B", difficulty=DifficultyLevel.MEDIUM,
        )
        is_correct, score, _ = _grade_programmatic(q, "A")
        assert is_correct is False
        assert score == 0.0

    def test_mc_whitespace(self):
        q = Question(
            question_id="q4", type=QuestionType.MULTIPLE_CHOICE,
            stem="?", correct_answer="B", difficulty=DifficultyLevel.MEDIUM,
        )
        is_correct, _, _ = _grade_programmatic(q, "  B  ")
        assert is_correct is True

    # -- True/False ------------------------------------------------------
    def test_tf_true_string(self):
        q = Question(
            question_id="q5", type=QuestionType.TRUE_FALSE,
            stem="?", correct_answer=True, difficulty=DifficultyLevel.EASY,
        )
        is_correct, _, _ = _grade_programmatic(q, "true")
        assert is_correct is True

    def test_tf_false_string(self):
        q = Question(
            question_id="q6", type=QuestionType.TRUE_FALSE,
            stem="?", correct_answer=False, difficulty=DifficultyLevel.EASY,
        )
        is_correct, _, _ = _grade_programmatic(q, "false")
        assert is_correct is True

    def test_tf_chinese_true(self):
        q = Question(
            question_id="q7", type=QuestionType.TRUE_FALSE,
            stem="?", correct_answer=True, difficulty=DifficultyLevel.EASY,
        )
        is_correct, _, _ = _grade_programmatic(q, "对")
        assert is_correct is True

    def test_tf_chinese_false(self):
        q = Question(
            question_id="q8", type=QuestionType.TRUE_FALSE,
            stem="?", correct_answer=False, difficulty=DifficultyLevel.EASY,
        )
        is_correct, _, _ = _grade_programmatic(q, "错")
        assert is_correct is True

    def test_tf_bool_correct_answer(self):
        q = Question(
            question_id="q9", type=QuestionType.TRUE_FALSE,
            stem="?", correct_answer=False, difficulty=DifficultyLevel.EASY,
        )
        # correct_answer is bool False, student says "false"
        is_correct, _, _ = _grade_programmatic(q, "false")
        assert is_correct is True

    def test_tf_numeric(self):
        q = Question(
            question_id="q10", type=QuestionType.TRUE_FALSE,
            stem="?", correct_answer=True, difficulty=DifficultyLevel.EASY,
        )
        is_correct, _, _ = _grade_programmatic(q, "1")
        assert is_correct is True

    def test_tf_yes_no(self):
        q = Question(
            question_id="q11", type=QuestionType.TRUE_FALSE,
            stem="?", correct_answer=True, difficulty=DifficultyLevel.EASY,
        )
        is_correct_yes, _, _ = _grade_programmatic(q, "yes")
        assert is_correct_yes is True

        q2 = Question(
            question_id="q12", type=QuestionType.TRUE_FALSE,
            stem="?", correct_answer=False, difficulty=DifficultyLevel.EASY,
        )
        is_correct_no, _, _ = _grade_programmatic(q2, "no")
        assert is_correct_no is True

    def test_tf_invalid_answer(self):
        q = Question(
            question_id="q13", type=QuestionType.TRUE_FALSE,
            stem="?", correct_answer=True, difficulty=DifficultyLevel.EASY,
        )
        is_correct, _, _ = _grade_programmatic(q, "gibberish")
        assert is_correct is False

    def test_tf_string_correct_answer(self):
        q = Question(
            question_id="q14", type=QuestionType.TRUE_FALSE,
            stem="?", correct_answer="true", difficulty=DifficultyLevel.EASY,
        )
        is_correct, _, _ = _grade_programmatic(q, "true")
        assert is_correct is True


# ======================================================================
# _strip_markdown_fence
# ======================================================================


class TestStripMarkdownFence:
    """Tests for _strip_markdown_fence helper (quiz engine variant)."""

    def test_strips_fence(self):
        result = _strip_markdown_fence('```\n{"key": "val"}\n```')
        assert result == '{"key": "val"}'

    def test_strips_fence_with_lang(self):
        result = _strip_markdown_fence('```json\n{"key": "val"}\n```')
        assert result == '{"key": "val"}'

    def test_no_fence_unchanged(self):
        result = _strip_markdown_fence('{"key": "val"}')
        assert result == '{"key": "val"}'

    def test_leading_trailing_whitespace(self):
        result = _strip_markdown_fence('  \n{"key": "val"}\n  ')
        assert result == '{"key": "val"}'


# ======================================================================
# _serialize_answer
# ======================================================================


class TestSerializeAnswer:
    """Tests for _serialize_answer helper."""

    def test_string_answer(self):
        assert _serialize_answer("B") == "B"

    def test_dict_answer(self):
        result = _serialize_answer({"key": "val"})
        assert json.loads(result) == {"key": "val"}

    def test_list_answer(self):
        result = _serialize_answer(["a", "b"])
        assert json.loads(result) == ["a", "b"]

    def test_int_answer(self):
        assert _serialize_answer(42) == "42"

    def test_bool_answer(self):
        assert _serialize_answer(True) == "True"
