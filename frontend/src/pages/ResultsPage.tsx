import { useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuizStore } from "../store/quizStore";
import ResultCard from "../components/ResultCard";

export default function ResultsPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const {
    results,
    misconceptions,
    socraticHints,
    summary,
    phase,
    quizStatus,
    loading,
    error,
    fetchResults,
    generatePlan,
    clearError,
  } = useQuizStore();

  const fetchedRef = useRef(false);

  // ── ① 如果 phase 允许，拉取结果 ──
  useEffect(() => {
    if (
      sessionId &&
      !fetchedRef.current &&
      (phase === "evaluating" || phase === "planning")
    ) {
      fetchedRef.current = true;
      fetchResults(sessionId);
    }
  }, [sessionId, phase, fetchResults]);

  // ── 计算 ──
  const correctCount = results.filter((r) => r.is_correct).length;
  const accuracy =
    results.length > 0 ? Math.round((correctCount / results.length) * 100) : 0;

  // ── 生成复习计划 ──
  async function handleGeneratePlan() {
    if (!sessionId) return;
    await generatePlan(sessionId);
    navigate("/plan");
  }

  function handleRetry() {
    if (!sessionId) return;
    clearError();
    fetchResults(sessionId);
  }

  // ── 渲染：phase 不允许查看结果 ──
  if (phase !== "evaluating" && phase !== "planning" && !loading && !error) {
    return (
      <div className="text-center py-16">
        <p className="text-4xl mb-4">📝</p>
        <p className="text-lg font-medium text-gray-700 mb-2">尚无批改结果</p>
        <p className="text-sm text-gray-400 mb-6">
          {phase === "quiz_gen"
            ? "请先完成答题并提交答案。"
            : phase === "idle" || phase === "parsing"
              ? "请先等待题目生成。"
              : `当前阶段: ${phase}，无法查看结果。`}
        </p>
        <button
          className="bg-primary-600 text-white px-5 py-2 rounded text-sm hover:bg-primary-700"
          onClick={() => navigate(`/quiz/${sessionId}`)}
        >
          返回答题
        </button>
      </div>
    );
  }

  // ── 渲染：加载中 ──
  if (loading && results.length === 0) {
    return (
      <div className="text-center py-16">
        <p className="text-4xl mb-4">🔍</p>
        <p className="text-gray-500">正在加载批改结果…</p>
        <div className="inline-block w-6 h-6 border-2 border-primary-300 border-t-primary-600 rounded-full animate-spin mt-4" />
      </div>
    );
  }

  // ── 渲染：错误 ──
  if (error) {
    return (
      <div className="text-center py-16">
        <p className="text-4xl mb-4">⚠️</p>
        <p className="text-lg font-medium text-red-600 mb-2">加载结果失败</p>
        <p className="text-sm text-gray-500 mb-6 max-w-md mx-auto whitespace-pre-wrap">
          {error}
        </p>
        <div className="flex gap-3 justify-center">
          <button
            className="bg-primary-600 text-white px-5 py-2 rounded text-sm hover:bg-primary-700"
            onClick={handleRetry}
          >
            重试
          </button>
          <button
            className="border border-gray-300 text-gray-600 px-5 py-2 rounded text-sm hover:bg-gray-50"
            onClick={() => navigate(`/quiz/${sessionId}`)}
          >
            返回答题
          </button>
        </div>
      </div>
    );
  }

  // ── 渲染：正常结果页 ──
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">测验结果</h1>
        <span className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded">
          {phase === "planning" ? "已完成" : "已批改"}
        </span>
      </div>

      {/* ── Summary 汇总卡片（F8: 后端 evaluator 输出的 summary 对象）── */}
      {summary && (
        <div className="bg-gradient-to-r from-primary-50 to-blue-50 rounded-lg shadow p-5 mb-6 border border-primary-100">
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div className="text-center">
              <p className="text-2xl font-bold text-primary-700">
                {summary.total_questions}
              </p>
              <p className="text-xs text-gray-400">总题数</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-green-600">
                {summary.correct_count}
              </p>
              <p className="text-xs text-gray-400">正确</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-primary-700">
                {Math.round(summary.accuracy * 100)}%
              </p>
              <p className="text-xs text-gray-400">正确率</p>
            </div>
          </div>
          {summary.weakest_topic && (
            <div className="flex items-center gap-2 text-sm mb-1">
              <span className="text-red-500 font-medium">⚠ 最弱知识点:</span>
              <span className="text-gray-700">{summary.weakest_topic}</span>
            </div>
          )}
          {summary.strongest_topic && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-green-500 font-medium">⭐ 最强知识点:</span>
              <span className="text-gray-700">{summary.strongest_topic}</span>
            </div>
          )}
          {summary.overall_assessment && (
            <p className="text-sm text-gray-500 mt-3 border-t border-primary-200 pt-3">
              {summary.overall_assessment}
            </p>
          )}
        </div>
      )}

      {/* 无 summary 时的简单统计 */}
      {!summary && results.length > 0 && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <p className="text-2xl font-bold text-primary-700">{results.length}</p>
            <p className="text-xs text-gray-400">总题数</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <p className="text-2xl font-bold text-green-600">{correctCount}</p>
            <p className="text-xs text-gray-400">正确</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <p className="text-2xl font-bold">{accuracy}%</p>
            <p className="text-xs text-gray-400">正确率</p>
          </div>
        </div>
      )}

      {/* ── 逐题批改 ── */}
      {results.length > 0 && (
        <>
          <h2 className="font-semibold mb-3">逐题批改</h2>
          {results.map((attempt, i) => (
            <ResultCard key={attempt.attempt_id || i} attempt={attempt} index={i} />
          ))}
        </>
      )}

      {/* ── 迷思概念 ── */}
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
                  m.severity === "high" || m.severity === "critical"
                    ? "bg-red-100 text-red-700"
                    : m.severity === "medium" || m.severity === "moderate"
                      ? "bg-yellow-100 text-yellow-700"
                      : "bg-blue-100 text-blue-700"
                }`}
              >
                {m.severity || m.category || "conceptual"}
              </span>
              <div>
                <p className="text-sm font-medium">{m.label}</p>
                <p className="text-xs text-gray-500">{m.description}</p>
                {m.remediation_hint && (
                  <p className="text-xs text-primary-700 mt-1">
                    💡 {m.remediation_hint}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── 苏格拉底提示 (F8) ── */}
      {socraticHints.length > 0 && (
        <div className="bg-amber-50 rounded-lg shadow p-5 mt-4 border border-amber-200">
          <h2 className="font-semibold mb-3 text-amber-800">
            🧭 苏格拉底式引导提示
          </h2>
          <p className="text-xs text-amber-600 mb-3">
            以下提示从笼统到具体逐层递进，请先尝试自己思考再展开查看
          </p>
          {misconceptions
            .filter((m) =>
              socraticHints.some((h) => h.misconception_tag_id === m.tag_id)
            )
            .map((m) => {
              const tagHints = socraticHints.filter(
                (h) => h.misconception_tag_id === m.tag_id
              );
              return (
                <details
                  key={m.tag_id}
                  className="mb-2 border border-amber-300 rounded bg-white"
                >
                  <summary className="px-4 py-2 text-sm font-medium cursor-pointer hover:bg-amber-50">
                    {m.label}
                    <span className="text-xs text-gray-400 ml-2">
                      ({tagHints.length} 层提示)
                    </span>
                  </summary>
                  <div className="px-4 pb-3 space-y-2">
                    {tagHints
                      .sort((a, b) => a.level - b.level)
                      .map((h) => (
                        <div
                          key={h.hint_id}
                          className="bg-amber-50 rounded p-3 text-sm"
                        >
                          <span className="text-xs font-bold text-amber-600 mr-2">
                            L{h.level}
                          </span>
                          <span className="text-gray-700">{h.content}</span>
                        </div>
                      ))}
                  </div>
                </details>
              );
            })}
        </div>
      )}

      {/* ── 操作按钮 ── */}
      <div className="flex gap-3 mt-6">
        <button
          className="bg-primary-600 text-white px-5 py-2 rounded text-sm hover:bg-primary-700 disabled:opacity-50"
          onClick={handleGeneratePlan}
          disabled={loading}
        >
          {loading ? "生成中…" : "生成复习计划"}
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
