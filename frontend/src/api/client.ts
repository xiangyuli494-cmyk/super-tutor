import type {
  APIResponse,
  MaterialUploadRequest,
  MaterialStatusResponse,
  CreateSessionRequest,
  SessionResponse,
  QuestionResponse,
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

// ── Generic helpers ──────────────────────────────────────────────────

async function request<T>(
  url: string,
  options?: RequestInit
): Promise<APIResponse<T>> {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${body}`);
  }
  return resp.json();
}

// ── Materials ────────────────────────────────────────────────────────

export function uploadMaterial(data: MaterialUploadRequest) {
  return request<MaterialStatusResponse>(`${BASE}/materials/upload`, {
    method: "POST",
    body: JSON.stringify(data),
  });
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
  return request<{ questions: QuestionResponse[] }>(
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

// ── Tokens ───────────────────────────────────────────────────────────

export function getTokenStats(projectId?: string) {
  const params = projectId ? `?project_id=${projectId}` : "";
  return request<TokenStatsResponse>(`${BASE}/tokens/stats${params}`);
}
