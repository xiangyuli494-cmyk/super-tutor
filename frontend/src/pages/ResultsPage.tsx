import { useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuizStore } from "../store/quizStore";
import ResultCard from "../components/ResultCard";

export default function ResultsPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const { results, misconceptions, loading, error, fetchResults, generatePlan } =
    useQuizStore();

  useEffect(() => {
    if (sessionId && results.length === 0) {
      fetchResults(sessionId);
    }
  }, [sessionId]);

  const correctCount = results.filter((r) => r.is_correct).length;
  const accuracy =
    results.length > 0 ? Math.round((correctCount / results.length) * 100) : 0;

  async function handleGeneratePlan() {
    if (!sessionId) return;
    await generatePlan(sessionId);
    navigate("/plan");
  }

  if (loading && results.length === 0) {
    return <p className="text-gray-400">正在加载结果...</p>;
  }

  if (error) {
    return <p className="text-danger text-sm">{error}</p>;
  }

  return (
    <div>
      <h1 className="text-xl font-bold mb-2">测验结果</h1>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow p-4 text-center">
          <p className="text-2xl font-bold text-primary-700">{results.length}</p>
          <p className="text-xs text-gray-400">总题数</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4 text-center">
          <p className="text-2xl font-bold text-success">{correctCount}</p>
          <p className="text-xs text-gray-400">正确</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4 text-center">
          <p className="text-2xl font-bold">{accuracy}%</p>
          <p className="text-xs text-gray-400">正确率</p>
        </div>
      </div>

      {/* Results */}
      <h2 className="font-semibold mb-3">逐题批改</h2>
      {results.map((attempt, i) => (
        <ResultCard key={attempt.attempt_id} attempt={attempt} index={i} />
      ))}

      {/* Misconceptions */}
      {misconceptions.length > 0 && (
        <div className="bg-white rounded-lg shadow p-5 mt-4">
          <h2 className="font-semibold mb-3">迷思概念诊断</h2>
          {misconceptions.map((m) => (
            <div
              key={m.tag_id}
              className="flex items-start gap-3 py-2 border-b last:border-0"
            >
              <span
                className={`text-xs px-2 py-0.5 rounded mt-0.5 ${
                  m.severity === "high"
                    ? "bg-red-100 text-red-700"
                    : m.severity === "medium"
                    ? "bg-yellow-100 text-yellow-700"
                    : "bg-blue-100 text-blue-700"
                }`}
              >
                {m.severity}
              </span>
              <div>
                <p className="text-sm font-medium">{m.label}</p>
                <p className="text-xs text-gray-500">{m.description}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-3 mt-6">
        <button
          className="bg-primary-600 text-white px-5 py-2 rounded text-sm hover:bg-primary-700"
          onClick={handleGeneratePlan}
          disabled={loading}
        >
          {loading ? "生成中..." : "生成复习计划"}
        </button>
        <button
          className="border border-gray-300 text-gray-600 px-5 py-2 rounded text-sm hover:bg-gray-50"
          onClick={() => navigate("/")}
        >
          返回首页
        </button>
      </div>
    </div>
  );
}
