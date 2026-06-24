import { useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuizStore } from "../store/quizStore";
import QuizCard from "../components/QuizCard";

export default function QuizPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const {
    questions,
    answers,
    state,
    loading,
    error,
    fetchQuestions,
    setAnswer,
    submitAnswers,
    fetchResults,
  } = useQuizStore();

  useEffect(() => {
    if (sessionId && questions.length === 0) {
      fetchQuestions(sessionId);
    }
  }, [sessionId]);

  // All answers submitted → go to results
  const allAnswered = questions.every((q) => answers[q.question_id] != null && answers[q.question_id] !== "");

  async function handleSubmit() {
    if (!sessionId) return;
    await submitAnswers();
    // After submitting, fetch results and navigate
    await fetchResults(sessionId);
    navigate(`/quiz/${sessionId}/results`);
  }

  // Loading state
  if (loading && questions.length === 0) {
    return (
      <div className="text-center py-12">
        <div className="animate-pulse text-gray-400">正在生成题目...</div>
        <p className="text-xs text-gray-400 mt-2">AI 正在根据材料为你定制测验</p>
      </div>
    );
  }

  if (error) {
    return <p className="text-danger text-sm">{error}</p>;
  }

  if (!questions.length) {
    return <p className="text-gray-400">暂无题目。请先上传材料并创建测验。</p>;
  }

  return (
    <div>
      <h1 className="text-xl font-bold mb-4">测验答题</h1>
      <p className="text-xs text-gray-400 mb-4">
        {questions.length} 题 · 已回答 {Object.keys(answers).length} 题
      </p>

      {questions.map((q) => (
        <QuizCard
          key={q.question_id}
          question={q}
          selected={answers[q.question_id] ?? null}
          disabled={loading}
          onSelect={setAnswer}
        />
      ))}

      <div className="flex justify-end mt-4">
        <button
          className="bg-primary-600 text-white px-6 py-2 rounded text-sm hover:bg-primary-700 disabled:opacity-50"
          disabled={!allAnswered || loading}
          onClick={handleSubmit}
        >
          {loading ? "提交中..." : "提交答案"}
        </button>
      </div>
    </div>
  );
}
