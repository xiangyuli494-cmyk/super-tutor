import { useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuizStore, type PipelinePhase } from "../store/quizStore";
import QuizCard from "../components/QuizCard";

// ── Phase → 加载文案映射（直接对应后端 PipelinePhase） ──────────────

const PHASE_LOADING: Record<PipelinePhase, { icon: string; message: string; sub: string }> = {
  idle: {
    icon: "⏳",
    message: "正在连接…",
    sub: "正在创建测验会话",
  },
  parsing: {
    icon: "📖",
    message: "AI 正在解析学习材料…",
    sub: "提取知识点、构建知识图谱，复杂材料可能需要 30 秒以上",
  },
  quiz_gen: {
    icon: "✏️",
    message: "AI 正在生成测验题目…",
    sub: "根据知识库定制个性化题目",
  },
  evaluating: {
    icon: "🔍",
    message: "AI 正在批改作答…",
    sub: "逐题判定对错、诊断迷思概念",
  },
  planning: {
    icon: "📋",
    message: "处理中…",
    sub: "",
  },
};

export default function QuizPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const {
    questions,
    answers,
    phase,
    quizStatus,
    loading,
    error,
    fetchQuestions,
    setAnswer,
    submitAnswers,
    fetchResults,
    clearError,
  } = useQuizStore();

  // 用于防止重复 fetch
  const fetchedRef = useRef(false);

  // ── ① 首次进入：触发 fetchQuestions（IDLE → PARSING → QUIZ_GEN） ──
  useEffect(() => {
    if (sessionId && !fetchedRef.current) {
      fetchedRef.current = true;
      fetchQuestions(sessionId);
    }
  }, [sessionId, fetchQuestions]);

  // ── ② 提交后等 phase 变成 evaluating/planning → 自动拉结果 ──
  useEffect(() => {
    if (phase === "evaluating" && quizStatus === "submitted" && sessionId) {
      // LLM 批改完成后 phase 是 evaluating，quizStatus 是 graded
      // 后端 POST /answers 返回时已包含 grading 结果，可直接拉
      fetchResults(sessionId);
    }
  }, [phase, quizStatus, sessionId, fetchResults]);

  // ── ③ 结果到手后跳转 ──
  const results = useQuizStore((s) => s.results);
  useEffect(() => {
    if (results.length > 0 && phase === "evaluating" && sessionId) {
      navigate(`/quiz/${sessionId}/results`);
    }
  }, [results, phase, sessionId, navigate]);

  // ── 所有题都答了 ──
  const allAnswered =
    questions.length > 0 &&
    questions.every((q) => answers[q.question_id] != null && answers[q.question_id] !== "");

  // ── 提交 ──
  async function handleSubmit() {
    if (!sessionId) return;
    await submitAnswers();
    // submitAnswers 成功后 phase 变成 "evaluating"，
    // 上面的 useEffect ② 会自动拉结果然后跳转
  }

  // ── 错误时重试 ──
  function handleRetry() {
    if (!sessionId) return;
    clearError();
    // 超时或 409 → 重新 fetch（后端幂等，已有产物会直接返回）
    if (phase === "parsing" || phase === "idle") {
      fetchQuestions(sessionId);
    } else if (phase === "evaluating" && quizStatus === "submitted") {
      fetchResults(sessionId);
    }
  }

  // ── 渲染：等待阶段（idle / parsing / quiz_gen 加载中） ──
  if ((phase === "idle" || phase === "parsing") && loading) {
    const info = PHASE_LOADING[phase];
    return (
      <div className="text-center py-16">
        <p className="text-5xl mb-4">{info.icon}</p>
        <p className="text-lg font-medium text-gray-700 mb-1">{info.message}</p>
        <p className="text-sm text-gray-400 mb-6">{info.sub}</p>
        <div className="inline-block w-8 h-8 border-4 border-primary-300 border-t-primary-600 rounded-full animate-spin" />
        <p className="text-xs text-gray-400 mt-4">
          首次解析可能需要 30 秒以上，请耐心等待…
        </p>
      </div>
    );
  }

  // ── 渲染：批改中 ──
  if (phase === "evaluating" && !results.length) {
    const info = PHASE_LOADING.evaluating;
    return (
      <div className="text-center py-16">
        <p className="text-5xl mb-4">{info.icon}</p>
        <p className="text-lg font-medium text-gray-700 mb-1">{info.message}</p>
        <p className="text-sm text-gray-400 mb-6">{info.sub}</p>
        <div className="inline-block w-8 h-8 border-4 border-primary-300 border-t-primary-600 rounded-full animate-spin" />
      </div>
    );
  }

  // ── 渲染：错误 ──
  if (error) {
    return (
      <div className="text-center py-16">
        <p className="text-4xl mb-4">⚠️</p>
        <p className="text-lg font-medium text-red-600 mb-2">出错了</p>
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
            onClick={() => navigate("/materials")}
          >
            返回材料页
          </button>
        </div>
      </div>
    );
  }

  // ── 渲染：无题目 ──
  if (!questions.length && !loading) {
    return (
      <div className="text-center py-16">
        <p className="text-gray-400 mb-4">暂无题目</p>
        <button
          className="bg-primary-600 text-white px-5 py-2 rounded text-sm hover:bg-primary-700"
          onClick={() => sessionId && fetchQuestions(sessionId)}
        >
          重新获取题目
        </button>
      </div>
    );
  }

  // ── 渲染：正常答题界面 ──
  const answeredCount = Object.keys(answers).length;

  return (
    <div>
      {/* 顶栏：进度 + 阶段指示 */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold">测验答题</h1>
          <p className="text-xs text-gray-400">
            {questions.length} 题 · 已回答 {answeredCount} 题
            {phase === "quiz_gen" && quizStatus === "in_progress" && (
              <span className="text-green-600 ml-2">· 答题中</span>
            )}
          </p>
        </div>
        {/* 阶段小标签 */}
        <span className="text-xs bg-primary-100 text-primary-700 px-2 py-1 rounded">
          {phase === "quiz_gen" ? "答题阶段" : phase}
        </span>
      </div>

      {/* 题目列表 */}
      {questions.map((q) => (
        <QuizCard
          key={q.question_id}
          question={q}
          selected={answers[q.question_id] ?? null}
          disabled={loading}
          onSelect={setAnswer}
        />
      ))}

      {/* 提交按钮 */}
      <div className="flex justify-end mt-4">
        <button
          className="bg-primary-600 text-white px-6 py-2 rounded text-sm hover:bg-primary-700 disabled:opacity-50"
          disabled={!allAnswered || loading}
          onClick={handleSubmit}
        >
          {loading ? "提交中…" : "提交答案"}
        </button>
      </div>
    </div>
  );
}
