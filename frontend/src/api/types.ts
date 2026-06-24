// ── Generic API wrapper ──────────────────────────────────────────────

export interface APIResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}

// ── Materials ────────────────────────────────────────────────────────

export interface MaterialUploadRequest {
  title: string;
  content: string;
  subject?: string;
  description?: string;
}

export interface MaterialStatusResponse {
  material_id: string;
  title: string;
  status: string;
  chunk_count: number;
  subject: string;
  created_at: string;
}

// ── Quiz Sessions ────────────────────────────────────────────────────

export interface CreateSessionRequest {
  material_id: string;
  title?: string;
  question_count?: number;
  difficulty?: string;
  student_id?: string;
}

export interface SessionResponse {
  session_id: string;
  material_id: string;
  title: string;
  state: string;
  question_count: number;
}

export interface QuestionResponse {
  question_id: string;
  stem: string;
  type: string;
  difficulty: string;
  topic: string;
  options: { key: string; text: string }[];
  hints: string[];
  points: number;
  estimated_seconds: number;
}

export interface AnswerItem {
  question_id: string;
  student_answer: unknown;
  time_spent_seconds?: number;
  hints_used?: number;
  attempt_number?: number;
  confidence?: number;
}

export interface SubmitAnswersRequest {
  answers: AnswerItem[];
}

export interface SubmitAnswersResponse {
  session_id: string;
  accepted_count: number;
  state: string;
}

export interface AttemptResult {
  attempt_id: string;
  question_id: string;
  student_answer: unknown;
  is_correct: boolean;
  score: number;
  explanation?: string;
}

export interface MisconceptionTag {
  tag_id: string;
  knowledge_node_id: string;
  label: string;
  description: string;
  severity: string;
}

export interface ResultResponse {
  session_id: string;
  state: string;
  attempts: AttemptResult[];
  misconceptions: MisconceptionTag[];
  summary: Record<string, unknown>;
}

export interface PlanItem {
  item_id: string;
  knowledge_node_id: string;
  activity_type: string;
  estimated_minutes: number;
  scheduled_date?: string;
  notes?: string;
}

export interface PlanResponse {
  session_id: string;
  state: string;
  plan_items: PlanItem[];
  summary: string;
}

// ── Dashboard ────────────────────────────────────────────────────────

export interface DashboardResponse {
  student_id: string;
  total_questions_attempted: number;
  correct_count: number;
  overall_accuracy: number;
  weak_topics: string[];
  strong_topics: string[];
  recent_attempts: Record<string, unknown>[];
}

export interface MasteryItem {
  knowledge_node_id: string;
  total_attempts: number;
  correct_attempts: number;
  accuracy: number;
  last_attempt_at: string | null;
  mastery_level?: number;
  state?: string;
  sm2_next_review?: string;
  sm2_interval_days?: number;
}

export interface WrongQuestionItem {
  attempt_id: string;
  question_id: string;
  student_answer: unknown;
  is_correct: boolean;
  score: number | null;
  submitted_at: string | null;
  note: string;
}

export interface PlanTodayResponse {
  date: string;
  items: {
    item_id: string;
    knowledge_node_id: string;
    activity_type: string;
    scheduled_date: string;
    estimated_minutes: number;
    completed: boolean;
    notes: string;
  }[];
}

// ── Tokens ───────────────────────────────────────────────────────────

export interface TokenStatsResponse {
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  call_count: number;
  by_role: Record<string, number>;
  budget: number;
  used: number;
  remaining: number;
  by_tier: Record<string, number>;
}
