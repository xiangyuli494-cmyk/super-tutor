import { create } from "zustand";
import * as api from "../api/client";
import type {
  QuestionResponse,
  AttemptResult,
  MisconceptionTag,
  PlanItem,
} from "../api/types";

interface QuizState {
  // Session
  sessionId: string | null;
  materialId: string | null;
  state: string;
  title: string;
  studentId: string;

  // Quiz data
  questions: QuestionResponse[];
  answers: Record<string, unknown>;
  results: AttemptResult[];
  misconceptions: MisconceptionTag[];
  planItems: PlanItem[];
  planSummary: string;

  // UI state
  loading: boolean;
  error: string | null;

  // Actions
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
}

export const useQuizStore = create<QuizState>((set, get) => ({
  sessionId: null,
  materialId: null,
  state: "idle",
  title: "",
  studentId: "",

  questions: [],
  answers: {},
  results: [],
  misconceptions: [],
  planItems: [],
  planSummary: "",

  loading: false,
  error: null,

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
        state: d.state,
        title: opts.title || "新测验",
        studentId: opts.studentId || "",
        loading: false,
      });
      return d.session_id;
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false });
      return null;
    }
  },

  async fetchQuestions(sessionId) {
    set({ loading: true, error: null });
    try {
      const resp = await api.getQuestions(sessionId);
      set({ questions: resp.data.questions, state: "quiz_gen", loading: false });
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  setAnswer(questionId, answer) {
    set((s) => ({ answers: { ...s.answers, [questionId]: answer } }));
  },

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
      await api.submitAnswers(sessionId, payload);
      set({ state: "evaluating", loading: false });
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  async fetchResults(sessionId) {
    set({ loading: true, error: null });
    try {
      const resp = await api.getResults(sessionId);
      set({
        results: resp.data.attempts,
        misconceptions: resp.data.misconceptions,
        state: resp.data.state,
        loading: false,
      });
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  async generatePlan(sessionId) {
    set({ loading: true, error: null });
    try {
      const resp = await api.generatePlan(sessionId);
      set({
        planItems: resp.data.plan_items,
        planSummary: resp.data.summary,
        state: resp.data.state,
        loading: false,
      });
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  reset() {
    set({
      sessionId: null,
      state: "idle",
      title: "",
      questions: [],
      answers: {},
      results: [],
      misconceptions: [],
      planItems: [],
      planSummary: "",
      loading: false,
      error: null,
    });
  },
}));
