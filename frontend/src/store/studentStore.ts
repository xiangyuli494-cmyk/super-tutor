import { create } from "zustand";
import * as api from "../api/client";
import type { DashboardResponse, MasteryItem, PlanTodayResponse, WrongQuestionItem } from "../api/types";

interface StudentState {
  studentId: string;
  dashboard: DashboardResponse | null;
  mastery: MasteryItem[];
  todayPlan: PlanTodayResponse | null;
  wrongQuestions: WrongQuestionItem[];
  loading: boolean;
  error: string | null;

  setStudentId: (id: string) => void;
  fetchDashboard: () => Promise<void>;
  fetchMastery: () => Promise<void>;
  fetchTodayPlan: () => Promise<void>;
  fetchWrongQuestions: () => Promise<void>;
}

export const useStudentStore = create<StudentState>((set, get) => ({
  studentId: "student-1",
  dashboard: null,
  mastery: [],
  todayPlan: null,
  wrongQuestions: [],
  loading: false,
  error: null,

  setStudentId(id) {
    set({ studentId: id });
  },

  async fetchDashboard() {
    const { studentId } = get();
    set({ loading: true, error: null });
    try {
      const resp = await api.getDashboard(studentId);
      set({ dashboard: resp.data, loading: false });
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  async fetchMastery() {
    const { studentId } = get();
    set({ loading: true, error: null });
    try {
      const resp = await api.getMastery(studentId);
      set({ mastery: resp.data.items, loading: false });
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  async fetchTodayPlan() {
    const { studentId } = get();
    set({ loading: true, error: null });
    try {
      const resp = await api.getTodayPlan(studentId);
      set({ todayPlan: resp.data, loading: false });
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  async fetchWrongQuestions() {
    const { studentId } = get();
    set({ loading: true, error: null });
    try {
      const resp = await api.getWrongQuestions(studentId);
      set({ wrongQuestions: resp.data.items, loading: false });
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false });
    }
  },
}));
