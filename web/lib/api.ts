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

/** A public desk, with the provenance of its own contact details: `fonte` is
 * the page they were read from, `verificato_il` when that was last checked. */
export interface Ufficio {
  nome: string;
  telefono: string | null;
  email: string | null;
  orari: string | null;
  fonte: string;
  verificato_il: string;
  /** From IPA, the register public bodies must keep current. Kept apart from
   * the fields above because it answers a different question — this is the
   * channel that legally obliges a reply — and comes from a different source,
   * so it is cited separately. */
  pec: string | null;
  pec_fonte: string | null;
  pec_verificata_il: string | null;
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
  ente_codice_istat: string | null;
  /** When this record was last read from the publishing body. Nothing here is
   * live, and how old a snapshot is belongs next to what it says. */
  letto_il: string;
  /** The publishing body's public desk, when one has been recorded and
   * verified. Null for national and regional records: pointing someone at a
   * municipal URP for an ARERA measure sends them to a counter that cannot
   * help them. */
  ufficio: Ufficio | null;
  deadline: string | null;
  confidence: string;
  /** D-20 — which administrative tier published this (`Livello` in
   * `schema.py`). Always shown on the card: it is what tells the citizen
   * whether this benefit is theirs to lose if the comune goes quiet. */
  livello: "nazionale" | "regionale" | "comunale";
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

/** What the citizen's own comune published on a topic — stated either way.
 * The ordinary answer already searches municipal and national records
 * together, so this reaches nothing the first pass missed; it exists to say
 * out loud what the first pass leaves unsaid when every result was national. */
export interface PaginaWeb {
  title: string;
  url: string;
  /** Always true. Found by a search engine, not read from a dataset: nothing
   * here was parsed, quote-gated or checked against requirements the way a
   * record is, and the interface must never present one as if it had been. */
  non_verificato: boolean;
}

export interface Approfondimento {
  esito: string;
  comune_nome: string;
  matches: Match[];
  /** Last rung of the ladder, present only when the structured records
   * turned up nothing. */
  pagine: PaginaWeb[];
}

export const approfondimento = (topic: string) =>
  call<Approfondimento>("/api/approfondimento", {
    method: "POST",
    body: JSON.stringify({ topic }),
  });
export const me = () => call<Profile>("/api/me");
// `opportunities` is gone from here with the page that used it. The endpoint
// still exists server-side; a client wrapper nobody calls would just be a
// hint that a removed page might come back.
export const readiness = (istat: string) =>
  call<Readiness>(`/api/readiness/${istat}`);

/** Every comune with a committed seed snapshot: Albano and Fonte Nuova through
 * their service APIs, Ariccia through the bespoke HTML connector — it had no
 * reachable API, which is precisely why it costs nearly double per record.
 * Genzano and Marino remain measured at zero with no snapshot, so there is
 * nothing here to score; their diagnosis is cited on `/dati` as measurement
 * evidence rather than fetched from here. */
export const readinessAll = () => call<Readiness[]>("/api/readiness");

/** One opportunity's recovery cost (`RecordCostOut` in `api.py`). */
export interface RecordCost {
  id: string;
  title: string;
  recovery_level: string | null;
  extraction_seconds: number | null;
  pdfs_linked: number | null;
  pdfs_opened: number | null;
  pdfs_skipped: number | null;
  chars_processed: number | null;
  requirements_recovered: number | null;
}

/** D-16 recovery cost per comune (`RecoveryOut` in `api.py`).
 *
 * `typed_records` and `unmeasured_records` must be rendered as different
 * things. A typed record cost nothing because the comune already published it
 * structured — that is the outcome the whole project argues for. An unmeasured
 * record is one we never looked at. Showing them as one bar would credit a
 * comune for data nobody checked.
 */
export interface Recovery {
  ente: string;
  codice_istat: string;
  records_total: number;
  typed_records: number;
  recovered_records: number;
  unmeasured_records: number;
  levels: Record<string, number>;
  seconds_total: number | null;
  seconds_avg: number | null;
  pdfs_linked_total: number;
  pdfs_opened_total: number;
  pdfs_skipped_total: number;
  requirements_recovered_total: number;
  records: RecordCost[];
}

export const recovery = (istat: string) =>
  call<Recovery>(`/api/recovery/${istat}`);
export const recoveryAll = () => call<Recovery[]>("/api/recovery");

/** Per-ente access mode + integration cost (`IntegrationOut` in `api.py`,
 * D-21). `diagnosis` and `integration_cost` are the same deterministic
 * sentences the chat's INFORMAZIONE rail composes for the same ente — this
 * page renders them, never re-authors them, so the two surfaces agree.
 * `datasets_on_dati_gov` is `null` where it was never probed (Marino) and
 * must render as "non misurato", never as `0` (D-16). */
export interface Integration {
  ente: string;
  codice_istat: string;
  access_mode: string;
  label: string;
  probe_dated: string;
  probe_method: string;
  diagnosis: string[];
  integration_cost: string[];
  datasets_on_dati_gov: number | null;
  benchmark_342: number | null;
  segnalazioni_count: number;
  /** Where a request to open this body's data goes. Certified address first:
   * a PEC obliges a reply, an ordinary inbox does not. */
  pec: string | null;
  urp_email: string | null;
  urp_nome: string | null;
}

export const integrationAll = () => call<Integration[]>("/api/integration");

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

/** D-19 — the router classifies the shape of the question, not just its
 * topic, before anything else runs. AGEVOLAZIONE is the eligibility rail
 * (verdict, criteria, SPID); INFORMAZIONE is the document/office rail below
 * and never carries any of that furniture. */
export type QuestionKind = "informazione" | "agevolazione";

/** A source page found for an INFORMAZIONE answer, when one exists. */
export interface InfoDocument {
  title: string;
  url: string;
}

/** The office a citizen can actually call, mirrors `UrpContact` in
 * `integration.py`. Every field but `nome` is independently nullable — a
 * comune that never published a phone number is a measured fact, and the
 * UI must render that absence, never a guessed centralino. */
export interface InfoOffice {
  nome: string;
  telefono: string | null;
  email: string | null;
  orari: string | null;
  /** Certified address from IPA. Preferred as the recipient of a formal
   * request: a PEC obliges a reply, an ordinary inbox does not. */
  pec: string | null;
}

/** One cached web-search hit (D-28, `M6_web_aperto`) — verbatim title and
 * URL, nothing else. `non_verificato` is always `true` on this rail; the
 * field exists so the client renders the label from data, not from a
 * hardcoded assumption about which array it is looking at. */
export interface InfoWebResult {
  title: string;
  url: string;
  non_verificato: boolean;
}

/** Composition of an INFORMAZIONE answer (mirrors respond.py's `InfoAnswer`
 * / B20b's API mapping). `diagnosis` and `integration_cost` are each a list
 * of measured-fact lines — kept as two separate lists (not concatenated)
 * because they answer different questions: what was checked, and what
 * checking it cost. `coverage_count` is a raw count of matching records;
 * the client composes the sentence around it. */
export interface InfoOut {
  document: InfoDocument | null;
  office: InfoOffice | null;
  coverage_count: number;
  diagnosis: string[];
  integration_cost: string[];
  web_results: InfoWebResult[];
  /** B22 (D-25) — which comune this INFORMAZIONE answer is about, resolved
   * server-side from the office it already carries (`_enti_by_urp_nome` in
   * `api.py`). `null` when no ente could be resolved — nothing to count a
   * segnalazione against. */
  codice_istat: string | null;
  ente: string | null;
}

export interface ChatOut {
  reply: string;
  /** The topic this answer was retrieved for. The API has always sent it;
   * declaring it lets the follow-up check reuse it instead of re-running
   * intent extraction, which keeps that request deterministic. */
  topic: string | null;
  matches: Match[];
  data_gap: DataGap | null;
  escalation: Escalation | null;
  cost: ChatCost | null;
  /** D-19 rail marker. */
  kind: QuestionKind;
  /** D-29 — residual actions left on the citizen after this answer (a
   * count, never an estimate). `null` off the INFORMAZIONE rail. Always
   * rendered apart from `cost`: the two answer different questions and
   * must never be summed or share a line. */
  citizen_effort: number | null;
  /** The access rung this answer was composed at (e.g. `M6_web_aperto`).
   * `null` off the INFORMAZIONE rail. */
  access_mode: string | null;
  /** `null` on the AGEVOLAZIONE rail — an eligibility answer never carries
   * INFORMAZIONE furniture, and vice versa (D-19). */
  info: InfoOut | null;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export const chat = (
  message: string,
  history: ChatTurn[] = [],
  comuneIstat: string | null = null,
) =>
  call<ChatOut>("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message, history, comune_istat: comuneIstat }),
  });

/** Una voce dell'elenco dei comuni italiani (ISTAT unito ai siti di IPA).
 *
 * `ha_portale` è falso per i 29 comuni che ISTAT conosce e di cui IPA non
 * pubblica il sito — fra questi Roma, che il registro chiama «Roma Capitale».
 * Vanno mostrati lo stesso: sono comuni veri, e nasconderli farebbe sembrare
 * l'elenco incompleto. Ma chi sceglie deve sapere prima di cliccare che lì
 * non andremo a leggere niente. */
export interface ComuneScelta {
  codice_istat: string;
  nome: string;
  provincia: string;
  regione: string;
  ha_portale: boolean;
}

/** Cerca fra i 7.896 comuni italiani.
 *
 * L'elenco è chiuso e completo, quindi zero risultati NON significa «comune
 * non coperto»: significa che quel nome non è un comune italiano — un refuso,
 * o il nome di una frazione. Chi chiama deve dire le due cose in modo
 * diverso. */
export const cercaComuni = (q: string) =>
  call<ComuneScelta[]>(`/api/comuni?q=${encodeURIComponent(q)}`);

/** Footer vital signs (B14 contract). Every field is independently nullable
 * — another arm is building the endpoint concurrently, and a field that
 * hasn't been measured yet must render as absent, never as zero. */
export interface StatsOut {
  app_version: string | null;
  comuni_measured: number | null;
  records_total: number | null;
  requirements_verified: number | null;
  avg_recovery_seconds: number | null;
  sources_below_full_openness_pct: number | null;
}

export const stats = () => call<StatsOut>("/api/stats");

/** Per-source health for the header status pill (B14 contract). `reachable`,
 * `last_ingested` and `records` are all independently nullable: a source
 * that has never been probed is "unknown", not "down". */
export interface SourceStatus {
  codice_istat: string;
  nome: string;
  reachable: boolean | null;
  last_ingested: string | null;
  records: number | null;
}

/** One row in the "Sistemi" group of `/api/status` — a TreasureIQ component.
 * `stato` is "ok" | "degraded" | "down" | "unknown"; "unknown" is a real,
 * honest state (unmonitored at runtime), never a masked "down". */
export interface SystemComponent {
  nome: string;
  stato: "ok" | "degraded" | "down" | "unknown";
  detail: string;
}

/** One row in the "Stato dati interni" group. `value` is pre-formatted on the
 * server so the client never re-formats a number it did not measure. */
export interface InternalDatum {
  nome: string;
  stato: "ok" | "degraded" | "down" | "unknown";
  value: string;
  detail: string;
}

export interface StatusOut {
  overall: "ok" | "degraded" | "down" | null;
  sources: SourceStatus[] | null;
  /** "Stato sistemi" — TreasureIQ's own components. Additive with the rest. */
  sistemi: SystemComponent[] | null;
  /** "Stato dati interni" — headline numbers on what was recovered. */
  dati_interni: InternalDatum[] | null;
}

export const status = () => call<StatusOut>("/api/status");

/** Result of `GET /api/comune-nearby?lat=&lon=` — nullable: there may be no
 * supported comune near the citizen's current position. This is a proximity
 * lookup only; it never asserts residency (see D-09 and the geolocation
 * copy in `Chat.tsx`). */
export interface ComuneNearby {
  codice_istat: string;
  nome: string;
}

/** The endpoint wraps its answer — `{comune_nearby, note}` — and this type
 * described the inner object as if it were the whole body. The mismatch was
 * silent in TypeScript and loud on screen: every field read as `undefined`,
 * so the confirmation prompt asked the citizen "Sei a undefined?". Unwrapped
 * here, once, rather than at each call site. */
interface ComuneNearbyBody {
  comune_nearby: ComuneNearby | null;
  note: string;
}

export const comuneNearby = async (lat: number, lon: number) => {
  const body = await call<ComuneNearbyBody>(
    `/api/comune-nearby?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`,
  );
  return body.comune_nearby;
};

/** B22 (D-25) — the anonymous per-comune segnalazione counter, keyed by
 * `codice_istat`. Never carries anything besides a count: no IP, no
 * session, no citizen text (`SegnalazioneIn`/routes in `api.py`). */
export const segnalazioni = () => call<Record<string, number>>("/api/segnalazioni");

export const inviaSegnalazione = (codiceIstat: string) =>
  call<Record<string, number>>("/api/segnalazioni", {
    method: "POST",
    body: JSON.stringify({ codice_istat: codiceIstat }),
  });

/** One component of a comune's integration cost, with the fact behind it. */
export interface VoceCosto {
  chiave: string;
  etichetta: string;
  valore: number;
  evidenza: string;
}

/** What one comune costs TreasureIQ to keep readable (D-26 rule 2).
 *
 * Never a bill to the citizen and never a grade for the administration: it is
 * our own integration cost. The components ship with the total so a reader can
 * check the arithmetic instead of trusting the number. */
export interface Costo {
  ente: string;
  codice_istat: string;
  modo: string;
  scoperta_il: string;
  eta_scoperta_giorni: number;
  scoperta_scaduta: boolean;
  soglia_riscoperta_giorni: number;
  record_totali: number;
  record_strutturati: number;
  record_recuperati_da_prosa: number;
  record_non_recuperati: number;
  /** Evidence only, deliberately outside the score: wall-clock time measures
   * our machine and their file sizes as much as their openness. */
  secondi_recupero: number | null;
  costo_totale: number;
  costo_per_record: number | null;
  voci: VoceCosto[];
}

export const costi = () => call<Costo[]>("/api/costo");

export interface FonteAggregata {
  tipo: string;
  enti: number;
  servizi: number;
}

/** Aggregate figures for the monitoring dashboard. Aggregate on purpose: the
 * per-comune breakdown lives on /dati, where comparing them is the point. */
export interface Panoramica {
  servizi_totali: number;
  enti_totali: number;
  comuni_misurati: number;
  fonti: FonteAggregata[];
  criteri_strutturati: number;
  criteri_recuperati: number;
  criteri_non_recuperati: number;
  ultimo_accesso: string | null;
  gradini: Record<string, number>;
}

export const panoramica = () => call<Panoramica>("/api/panoramica");
