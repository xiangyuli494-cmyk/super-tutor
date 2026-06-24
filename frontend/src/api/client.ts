import type {
  APIResponse,
  MaterialUploadRequest,
  MaterialStatusResponse,
  CreateSessionRequest,
  SessionResponse,
  QuestionsData,
  SubmitAnswersRequest,
  SubmitAnswersResponse,
  ResultResponse,
  PlanResponse,
  DashboardResponse,
  MasteryItem,
  WrongQuestionItem,
  PlanTodayResponse,
  TokenStatsResponse,
} from "./types";

const BASE = "/api/v1";

// ── Custom error class for API errors ─────────────────────────────────

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, message: string, detail = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

// ── Generic helpers ──────────────────────────────────────────────────

async function request<T>(
  url: string,
  options?: RequestInit & { timeout?: number }
): Promise<APIResponse<T>> {
  const timeout = options?.timeout ?? 120_000; // default 2 min for LLM calls
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const resp = await fetch(url, {
      headers: { "Content-Type": "application/json", ...options?.headers },
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timer);

    if (!resp.ok) {
      let detail = "";
      try {
        const errBody = await resp.json();
        detail = errBody.detail || "";
      } catch { /* ignore parse errors */ }
      throw new ApiError(resp.status, `HTTP ${resp.status}`, detail);
    }
    return resp.json();
  } catch (e: unknown) {
    clearTimeout(timer);
    if (e instanceof ApiError) throw e;
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError(408, "请求超时，服务器仍在处理中，请稍后重试");
    }
    throw e;
  }
}

// ── Materials ────────────────────────────────────────────────────────

export function uploadMaterial(data: MaterialUploadRequest) {
  return request<MaterialStatusResponse>(`${BASE}/materials/upload`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function uploadPdfFile(
  file: File,
  title: string,
  subject?: string
): Promise<APIResponse<MaterialStatusResponse>> {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title);
  if (subject) form.append("subject", subject);
  const resp = await fetch(`${BASE}/materials/upload/file`, {
    method: "POST",
    body: form,
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${body}`);
  }
  return resp.json();
}

export function getMaterialStatus(materialId: string) {
  return request<MaterialStatusResponse>(
    `${BASE}/materials/${materialId}/status`
  );
}

// ── Quiz Sessions ────────────────────────────────────────────────────

export function createSession(data: CreateSessionRequest) {
  return request<SessionResponse>(`${BASE}/sessions`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function getQuestions(sessionId: string) {
  return request<QuestionsData>(
    `${BASE}/sessions/${sessionId}/questions`
  );
}

export function submitAnswers(
  sessionId: string,
  data: SubmitAnswersRequest
) {
  return request<SubmitAnswersResponse>(
    `${BASE}/sessions/${sessionId}/answers`,
    { method: "POST", body: JSON.stringify(data) }
  );
}

export function getResults(sessionId: string) {
  return request<ResultResponse>(
    `${BASE}/sessions/${sessionId}/results`
  );
}

export function generatePlan(sessionId: string) {
  return request<PlanResponse>(`${BASE}/sessions/${sessionId}/plan`, {
    method: "POST",
  });
}

// ── Dashboard ────────────────────────────────────────────────────────

export function getDashboard(studentId: string) {
  return request<DashboardResponse>(
    `${BASE}/students/${studentId}/dashboard`
  );
}

export function getMastery(studentId: string) {
  return request<{ student_id: string; items: MasteryItem[] }>(
    `${BASE}/students/${studentId}/mastery`
  );
}

export function getWrongQuestions(
  studentId: string,
  limit = 20,
  offset = 0
) {
  return request<{
    student_id: string;
    total: number;
    items: WrongQuestionItem[];
  }>(
    `${BASE}/students/${studentId}/wrong-questions?limit=${limit}&offset=${offset}`
  );
}

export function getTodayPlan(studentId: string) {
  return request<PlanTodayResponse>(
    `${BASE}/students/${studentId}/plan/today`
  );
}

export function togglePlanItem(
  studentId: string,
  itemId: string,
  completed: boolean
) {
  return request<{ item_id: string; completed: boolean }>(
    `${BASE}/students/${studentId}/plan/items/${itemId}/toggle`,
    { method: "POST", body: JSON.stringify({ completed }) }
  );
}

// ── Tokens ───────────────────────────────────────────────────────────

export function getTokenStats(projectId?: string) {
  const params = projectId ? `?project_id=${projectId}` : "";
  return request<TokenStatsResponse>(`${BASE}/tokens/stats${params}`);
}
