/** Typed client for the TreasureIQ API.
 *
 * `credentials: "include"` on every call: the session is an httpOnly cookie,
 * so the browser will not attach it cross-origin without this and every
 * authenticated request would silently 401 in development.
 */
// Two different addresses reach the same API, and which one is correct depends
// on who is asking.
//
//   Browser        → the host-published port (http://localhost:8010).
//   Server render  → inside compose, "localhost" is the web container itself,
//                    so server components must use the service name on the
//                    compose network (http://api:8000).
//
// Getting this wrong is invisible in `next dev` on a laptop, where both happen
// to be the same machine, and only shows up once the app is containerised —
// which is exactly where a reviewer will run it.
const isServer = typeof window === "undefined";

export const API = isServer
  ? process.env.TREASUREIQ_API_INTERNAL ??
    process.env.NEXT_PUBLIC_TREASUREIQ_API ??
    "http://localhost:8010"
  : process.env.NEXT_PUBLIC_TREASUREIQ_API ?? "http://localhost:8010";

export type Verdict = "eligible" | "likely" | "undetermined" | "not_eligible";
export type CriterionState =
  | "met"
  | "not_met"
  | "unknown_source"
  | "unknown_profile";

export interface Criterion {
  key: string;
  label: string;
  state: CriterionState;
  detail: string;
}

export interface Match {
  id: string;
  title: string;
  summary: string | null;
  kind: string;
  verdict: Verdict;
  verdict_label: string;
  headline: string;
  relevance: number;
  criteria: Criterion[];
  notes: string[];
  needs_source_check: boolean;
  source_url: string;
  ente: string;
  deadline: string | null;
  confidence: string;
}

export interface Dimension {
  key: string;
  label: string;
  earned: number;
  weight: number;
  evidence: string;
  remedy: string;
}

export interface Readiness {
  ente: string;
  codice_istat: string;
  score: number;
  grade: string;
  total_records: number;
  dimensions: Dimension[];
}

export interface Profile {
  comune_istat: string;
  comune_nome: string;
  eta: number;
  isee: string | null;
  nucleo_familiare: number;
  figli_minori: number;
  disabilita: boolean;
  employment_status: string | null;
  interests: string[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export const login = (body: Record<string, unknown>) =>
  call<Profile>("/api/session", { method: "POST", body: JSON.stringify(body) });

export const logout = () => call<unknown>("/api/session", { method: "DELETE" });
export const me = () => call<Profile>("/api/me");
export const opportunities = (includeIneligible = false) =>
  call<Match[]>(`/api/opportunities?include_ineligible=${includeIneligible}`);
export const readiness = (istat: string) =>
  call<Readiness>(`/api/readiness/${istat}`);

/** The chat contract (K3) — must stay field-for-field identical to the
 * `ChatOut` pydantic model in `api/treasureiq/api.py`. `data_gap` carries the
 * distinction the whole project exists to make: "the comune never published
 * this" (`not_published`) is not the same failure as "nothing matched"
 * (`none_found`), and the two must never collapse into one string.
 */
export type DataGap = "not_published" | "none_found";

export interface Escalation {
  needed: boolean;
  missing_fields: string[];
  reason: string;
}

/** Per-level counts of how a criterion's evidence was recovered — a manual
 * field, one extracted from prose by the quote-gated LLM, or one that stayed
 * illegible. Counts, so an absent level is `null`, never `0` (D-17: a missing
 * measurement must never look like a measured zero). */
export interface CostLevels {
  L1_manuale: number | null;
  L2_estratto: number | null;
  L3_illeggibile: number | null;
}

/** D-17 — the data-recovery cost behind one answer, added alongside B5. Every
 * field is independently nullable; render nothing for a null field rather
 * than a zero or a placeholder. */
export interface ChatCost {
  recovery_seconds_total: number | null;
  recovery_seconds_avg_comune: number | null;
  levels: CostLevels | null;
}

export interface ChatOut {
  reply: string;
  matches: Match[];
  data_gap: DataGap | null;
  escalation: Escalation | null;
  cost: ChatCost | null;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export const chat = (message: string, history: ChatTurn[] = []) =>
  call<ChatOut>("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message, history }),
  });
