import { create } from "zustand";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import type {
  QuestionResponse,
  AttemptResult,
  MisconceptionTag,
  PlanItem,
  SocraticHint,
  ResultSummary,
} from "../api/types";

// ── 类型 ──────────────────────────────────────────────────────────────

/** 后端 PipelinePhase 直接映射 */
export type PipelinePhase =
  | "idle"
  | "parsing"
  | "quiz_gen"
  | "evaluating"
  | "planning";

interface QuizState {
  // ── 会话（直接对应后端 Orchestrator 字段） ──
  sessionId: string | null;
  materialId: string | null;
  phase: PipelinePhase;        // 后端 _phase
  quizStatus: string;           // 后端 _quiz_status
  title: string;
  studentId: string;

  // ── 阶段产物（后端 _artifacts） ──
  questions: QuestionResponse[];
  answers: Record<string, unknown>;
  results: AttemptResult[];
  misconceptions: MisconceptionTag[];
  socraticHints: SocraticHint[];
  summary: ResultSummary | null;
  planItems: PlanItem[];
  planSummary: string;

  // ── UI 状态 ──
  loading: boolean;
  error: string | null;

  // ── Actions ──
  createSession: (materialId: string, opts?: {
    title?: string;
    questionCount?: number;
    difficulty?: string;
    studentId?: string;
  }) => Promise<string | null>;
  fetchQuestions: (sessionId: string) => Promise<void>;
  setAnswer: (questionId: string, answer: unknown) => void;
  submitAnswers: () => Promise<void>;
  fetchResults: (sessionId: string) => Promise<void>;
  generatePlan: (sessionId: string) => Promise<void>;
  reset: () => void;
  clearError: () => void;
}

// ── 辅助：从 ApiError 提取友好消息 ──────────────────────────────────

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    // 409 → 说明当前阶段不允许此操作
    if (e.status === 409) {
      return e.detail || "当前状态不允许此操作，请刷新页面后重试。";
    }
    // 408 → 超时
    if (e.status === 408) {
      return e.detail || "请求超时，AI 仍在处理中，请稍后重试。";
    }
    return e.detail || e.message;
  }
  return (e as Error).message || "未知错误";
}

// ── 辅助：从 API 响应提取 phase ─────────────────────────────────────

function extractPhase(data: Record<string, unknown> | undefined): PipelinePhase {
  if (!data) return "idle";
  const state = (data as Record<string, string>).state;
  const valid = new Set(["idle", "parsing", "quiz_gen", "evaluating", "planning"]);
  return valid.has(state) ? (state as PipelinePhase) : "idle";
}

function extractQuizStatus(data: Record<string, unknown> | undefined): string {
  if (!data) return "draft";
  return (data as Record<string, string>).quiz_status || "draft";
}

// ── Store ─────────────────────────────────────────────────────────────

export const useQuizStore = create<QuizState>((set, get) => ({
  sessionId: null,
  materialId: null,
  phase: "idle",
  quizStatus: "draft",
  title: "",
  studentId: "",

  questions: [],
  answers: {},
  results: [],
  misconceptions: [],
  socraticHints: [],
  summary: null,
  planItems: [],
  planSummary: "",

  loading: false,
  error: null,

  // ── createSession ────────────────────────────────────────────────
  async createSession(materialId, opts = {}) {
    set({ loading: true, error: null });
    try {
      const resp = await api.createSession({
        material_id: materialId,
        title: opts.title || "新测验",
        question_count: opts.questionCount || 10,
        difficulty: opts.difficulty || "medium",
        student_id: opts.studentId || "",
      });
      const d = resp.data;
      set({
        sessionId: d.session_id,
        materialId,
        phase: extractPhase(d as unknown as Record<string, unknown>),
        quizStatus: extractQuizStatus(d as unknown as Record<string, unknown>),
        title: opts.title || "新测验",
        studentId: opts.studentId || "",
        loading: false,
      });
      return d.session_id;
    } catch (e: unknown) {
      set({ error: errorMessage(e), loading: false });
      return null;
    }
  },

  // ── fetchQuestions ───────────────────────────────────────────────
  // 可能触发 IDLE → PARSING → QUIZ_GEN 两次 LLM 调用，耗时 30s+
  async fetchQuestions(sessionId) {
    set({ loading: true, error: null });
    try {
      const resp = await api.getQuestions(sessionId);
      const d = resp.data;
      set({
        questions: d.questions,
        phase: extractPhase(d as unknown as Record<string, unknown>),
        quizStatus: extractQuizStatus(d as unknown as Record<string, unknown>),
        loading: false,
      });
    } catch (e: unknown) {
      set({ error: errorMessage(e), loading: false });
    }
  },

  // ── setAnswer ────────────────────────────────────────────────────
  setAnswer(questionId, answer) {
    set((s) => ({ answers: { ...s.answers, [questionId]: answer } }));
  },

  // ── submitAnswers ────────────────────────────────────────────────
  // 提交后 phase 变为 evaluating（后端在 proceed() 中已写入 DB 再执行 LLM）
  async submitAnswers() {
    const { sessionId, questions, answers } = get();
    if (!sessionId) return;
    set({ loading: true, error: null });
    try {
      const payload = {
        answers: questions.map((q) => ({
          question_id: q.question_id,
          student_answer: answers[q.question_id] ?? "",
          time_spent_seconds: 30,
          hints_used: 0,
          attempt_number: 1,
        })),
      };
      const resp = await api.submitAnswers(sessionId, payload);
      set({
        phase: extractPhase(resp.data as unknown as Record<string, unknown>),
        quizStatus: "submitted",
        loading: false,
      });
    } catch (e: unknown) {
      set({ error: errorMessage(e), loading: false });
    }
  },

  // ── fetchResults ─────────────────────────────────────────────────
  async fetchResults(sessionId) {
    set({ loading: true, error: null });
    try {
      const resp = await api.getResults(sessionId);
      set({
        results: resp.data.attempts,
        misconceptions: resp.data.misconceptions,
        socraticHints: resp.data.socratic_hints || [],
        summary: resp.data.summary || null,
        phase: extractPhase(resp.data as unknown as Record<string, unknown>),
        loading: false,
      });
    } catch (e: unknown) {
      set({ error: errorMessage(e), loading: false });
    }
  },

  // ── generatePlan ─────────────────────────────────────────────────
  async generatePlan(sessionId) {
    set({ loading: true, error: null });
    try {
      const resp = await api.generatePlan(sessionId);
      set({
        planItems: resp.data.plan_items,
        planSummary: resp.data.summary,
        phase: extractPhase(resp.data as unknown as Record<string, unknown>),
        quizStatus: "reviewed",
        loading: false,
      });
    } catch (e: unknown) {
      set({ error: errorMessage(e), loading: false });
    }
  },

  // ── reset / clearError ───────────────────────────────────────────
  reset() {
    set({
      sessionId: null,
      phase: "idle",
      quizStatus: "draft",
      title: "",
      questions: [],
      answers: {},
      results: [],
      misconceptions: [],
      socraticHints: [],
      summary: null,
      planItems: [],
      planSummary: "",
      loading: false,
      error: null,
    });
  },

  clearError() {
    set({ error: null });
  },
}));
