/** Typed client for the TreasureIQ API.
 *
 * `credentials: "include"` on every call: the session is an httpOnly cookie,
 * so the browser will not attach it cross-origin without this and every
 * authenticated request would silently 401 in development.
 */
// Due indirizzi diversi raggiungono la stessa API, e quale sia quello giusto
// dipende da chi lo chiede.
//
//   Browser        → nessun indirizzo: percorsi relativi. Next inoltra `/api/*`
//                    al container dell'API (vedi `rewrites` in
//                    `next.config.mjs`), quindi la chiamata resta sulla stessa
//                    origine della pagina, qualunque essa sia.
//   Server render  → dentro compose "localhost" è il container web stesso, e i
//                    server component devono usare il nome del servizio sulla
//                    rete di compose (http://api:8000).
//
// L'indirizzo assoluto lato browser è durato finché la pagina si è aperta solo
// su http://localhost:3000. Servita da un dominio vero — i domini .orb.local di
// OrbStack, che sono in HTTPS — la stessa riga chiedeva a una pagina https di
// chiamare http://localhost:8010: altra origine e contenuto misto insieme, che
// il browser blocca prima ancora di guardare l'header CORS. Un indirizzo
// relativo non ha questo problema su nessun dominio, presente o futuro.
const isServer = typeof window === "undefined";

export const API = isServer
  ? process.env.TREASUREIQ_API_INTERNAL ??
    process.env.NEXT_PUBLIC_TREASUREIQ_API ??
    "http://localhost:8010"
  : "";

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

/** Le capacità dirette del portale di un comune fuori copertura: catalogo
 *  servizi + 15 categorie AgID, per i chip a cascata. A freddo il backend
 *  legge il portale una volta (cache 30g), quindi la chiamata può tardare:
 *  la UI la lancia solo quando il badge connettore è già a schermo. */
export const fetchMappaConnettore = (codiceIstat: string) =>
  call<MappaConnettore | null>(`/api/mappa-connettore/${codiceIstat}`);

/** I servizi di una categoria: il livello sotto ai chip. Link diretti alla
 *  scheda sul portale del comune (la fonte, non un verdetto). */
export const fetchServiziCategoria = (codiceIstat: string, termId: number) =>
  call<ServizioLink[] | null>(
    `/api/mappa-connettore/${codiceIstat}/categoria/${termId}`,
  );

/** Un bando/avviso del comune, letto adesso da amministrazione trasparente
 *  (`criteri-e-modalita`). Nessun campo scadenza strutturato: `data` è la
 *  data di pubblicazione, non «apertura» (D-B4, nessun verdetto). */
export interface Bando {
  titolo: string;
  url: string;
  data: string;
  anteprima: string | null;
}

/** I bandi e avvisi del comune, indipendenti dalla mappa servizi (D-B6): il
 *  gate è solo `connettore` presente, non `indirizzabile`. Array vuoto se il
 *  comune non espone `criteri-e-modalita` (degrado silenzioso, D-B5). */
export const fetchBandi = (codiceIstat: string) =>
  call<Bando[]>(`/api/mappa-connettore/${codiceIstat}/bandi`);

/** L'anteprima di un servizio, letta adesso dalla sua pagina sul portale:
 *  descrizione + a chi è rivolto, con l'url per aprirla intera. Come l'anteprima
 *  di un bando — fonte citata, non verdetto. `url` deve stare sul portale del
 *  comune (guardia host lato server). */
export const fetchSchedaServizio = (codiceIstat: string, url: string) =>
  call<SchedaServizio | null>(
    `/api/mappa-connettore/${codiceIstat}/scheda?url=${encodeURIComponent(url)}`,
  );

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

/** URP contacts read live from the comune's own portal, on explicit request.
 * For a comune we do not ingest, we cannot say what the citizen is entitled to,
 * but we can say who to ask — and they asked for the numbers, not just links. */
export interface ContattiUrp {
  comune_nome: string;
  telefoni: string[];
  email: string[];
  pec: string[];
  /** The page the contacts were read from, so they can be checked at source. */
  fonte: string | null;
  /** Always true: read from the portal just now, never verified against a
   * dataset. Same discipline as `PaginaWeb.non_verificato` — a phone number
   * captured wrong is worse than a link, so it is never stated as a fact. */
  non_verificato: boolean;
}

export const contattiUrp = (comuneIstat: string | null) =>
  call<ContattiUrp>("/api/contatti-urp", {
    method: "POST",
    body: JSON.stringify({ comune_istat: comuneIstat }),
  });
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
export type DataGap = "not_published" | "none_found" | "cambio_persona";

/** Mirror esatto di `FiltroChiave` (`treasureiq/chat/filtri.py`). Enum chiuso:
 *  nessun'altra stringa e' un filtro valido, ne' lato lettura ne' lato
 *  override — un valore fuori catalogo qui non compilerebbe. */
export type FiltroChiave =
  | "comune"
  | "disabilita"
  | "disabilita_nucleo"
  | "figli_minori"
  | "eta"
  | "anziano"
  | "isee"
  | "nucleo_familiare"
  | "employment_status"
  | "tema";

/** Mirror esatto di `Span` (`treasureiq/chat/filtri.py`): dove nel testo del
 *  cittadino il filtro e' stato letto, per mostrare la provenienza verbatim
 *  invece che un'etichetta generica. */
export interface FiltroSpan {
  inizio: number;
  fine: number;
  testo: string;
}

/** Mirror esatto di `FiltroOut` (`api.py`, ciclo11 A6/L-3). Un filtro
 *  RICONOSCIUTO in questo turno — `sorgente` distingue cosa venne dal testo
 *  di questo messaggio da cosa venne dal profilo gia' noto o da un override
 *  del client; `span` e' `null` quando la provenienza non e' testuale. */
export interface FiltroOut {
  chiave: FiltroChiave;
  valore: string | number | boolean;
  span: FiltroSpan | null;
  sorgente: "testo" | "profilo" | "override_client";
  negato: boolean;
}

/** Mirror esatto di `FiltroOverride` (`api.py`, ciclo11 A8/A12). `azione` e'
 *  chiuso su `"rimuovi"` di proposito: il client puo' solo togliere
 *  un'evidenza sbagliata, mai iniettarne una nuova per conto del cittadino. */
export interface FiltroOverride {
  chiave: FiltroChiave;
  azione: "rimuovi";
}

/** Mirror esatto di `ChatIn.chiarimento_atteso` / `ChatOut.chiarimento`
 *  (contratto congelato ciclo12, AM-2). Enum chiuso come `FiltroChiave`:
 *  una stringa fuori catalogo qui non compilerebbe, ne' lato invio ne'
 *  lato lettura — il 422 Pydantic lato server resta come seconda difesa. */
export type Chiarimento =
  | "figli_quanti"
  | "disabile_minorenne"
  | "composizione_famiglia";

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
  /** La descrizione che il comune dà del servizio, verbatim. `null` quando il
   * record non la porta: una riga in meno, mai una riga inventata. */
  descrizione: string | null;
  /** Il giorno in cui abbiamo letto la pagina (ISO). Va in fondo e in
   * piccolo: la data conferma, non risponde. */
  verificato_il: string | null;
}

/** The office a citizen can actually call, mirrors `UrpContact` in
 * `integration.py`. Every field but `nome` is independently nullable — a
 * comune that never published a phone number is a measured fact, and the
 * UI must render that absence, never a guessed centralino. */
export interface InfoOffice {
  nome: string;
  telefono: string | null;
  email: string | null;
  /** Office hours to show: the normalized form (`OrarioSettimanale.reso`)
   *  when the page allowed structuring it, otherwise the verbatim citation. */
  orari: string | null;
  /** The verbatim hours citation from the portal, kept beside the normalized
   *  `orari` as a re-checkable source (D-07). `null` when `orari` is already
   *  the verbatim text (nothing to pair) or when there are no hours. */
  orari_fonte: string | null;
  /** Certified address from IPA. Preferred as the recipient of a formal
   * request: a PEC obliges a reply, an ordinary inbox does not. */
  pec: string | null;
  /** Physical seat of the office (or the building hosting it), read from the
   *  office card during the drill (Ramo 1). `null`/absent where the page does
   *  not publish it — honest degradation, never an invented address (D-05).
   *  Optional for back-compat with answers produced before Ramo 1. */
  indirizzo?: string | null;
  /** Who is accountable for the office, when the card publishes it structured;
   *  `null`/absent otherwise (D-05), never inferred by an LLM (D-07). */
  responsabile?: Responsabile | null;
  /** The office card was actually inspected by a platform family that has a
   *  responsabile extractor (Slice 2). Only when `true` does a null
   *  `responsabile` mean "the comune does not publish it" — which the UI may
   *  state as such. `false`/absent (URP fallback, family without extractor,
   *  failed fetch) means "never verified": the field stays hidden, never
   *  announced as absent. Optional for back-compat with pre-Slice-2 answers. */
  responsabile_ispezionato?: boolean;
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

/** Una riga di «cosa posso confermare». Mai una percentuale: un numero del
 * genere avrebbe l'aria di una misura senza esserlo. */
export interface Prova {
  stato: "confermato" | "parziale" | "mancante";
  testo: string;
}

/** Un passo che il cittadino puo' fare adesso. `tipo` dice come renderlo. */
export interface Azione {
  /** Il titolo dell'azione: cosa ottieni, non come si fa. */
  testo: string;
  url: string | null;
  tipo: "apri" | "chiama" | "email";
  /** Perché farla, in una riga. Separato dal titolo perché una frase sola
   * lunga, resa come link, torna a sembrare prosa invece che un pulsante. */
  dettaglio: string | null;
  /** L'etichetta del pulsante. */
  etichetta: string;
}

/** Composition of an INFORMAZIONE answer (mirrors respond.py's `InfoAnswer`
 * / B20b's API mapping). `diagnosis` and `integration_cost` are each a list
 * of measured-fact lines — kept as two separate lists (not concatenated)
 * because they answer different questions: what was checked, and what
 * checking it cost. `coverage_count` is a raw count of matching records;
 * the client composes the sentence around it. */
/** Un'opzione d'accesso a un servizio comunale risolto dal connettore (Ramo 3,
 * Slice 5): una porta ufficiale con la sua etichetta e — solo per la procedura
 * online — i metodi di autenticazione accettati. `authentication` è vuoto per
 * la pagina informativa e per il download del modulo. */
export interface ServiceLinkOut {
  url: string;
  label: string;
  authentication: string[];
}

/** Il servizio risolto, con le tre porte tenute DISTINTE (D-R3): la pagina
 * informativa, i moduli scaricabili e le procedure online autenticate. TIQ
 * indica la porta, non entra: nessun login, nessuna compilazione. */
export interface ServiceOut {
  service_id: string;
  title: string;
  information: ServiceLinkOut | null;
  downloads: ServiceLinkOut[];
  authenticated_online: ServiceLinkOut[];
}

export interface InfoOut {
  document: InfoDocument | null;
  office: InfoOffice | null;
  /** Il servizio risolto dal connettore (Ramo 3, Slice 5). `null` quando la
   * risposta non passa dal resolver dei servizi (la maggioranza delle
   * INFORMAZIONI): allora vale eventualmente `document`. */
  service: ServiceOut | null;
  coverage_count: number;
  diagnosis: string[];
  integration_cost: string[];
  web_results: InfoWebResult[];
  /** Vero quando ufficio e orario sono stati letti dal portale del comune
   * durante questa domanda, non presi da uno snapshot curato (D-32). Un dato
   * letto al volo e un dato verificato non devono avere lo stesso aspetto:
   * l'etichetta esiste perché la differenza si veda senza doverla dedurre dal
   * testo della risposta. */
  letto_dal_vivo: boolean;
  /** Provenienza del dato, mai un diritto: `ufficiale`, `parziale`,
   * `non_verificato`, `non_pubblicato`. Sul rail INFORMAZIONE un verdetto non
   * esiste (D-19) e questo campo non deve diventarne uno per abitudine. */
  stato: "ufficiale" | "parziale" | "non_verificato" | "non_pubblicato";
  /** Le righe di «cosa posso confermare», gia' composte dal backend: la UI le
   * rende, non le deduce dal testo della risposta. */
  prove: Prova[];
  /** I passi successivi, scritti per esteso invece che contati. */
  azioni: Azione[];
  ente_nome: string | null;
  /** B22 (D-25) — which comune this INFORMAZIONE answer is about, resolved
   * server-side from the office it already carries (`_enti_by_urp_nome` in
   * `api.py`). `null` when no ente could be resolved — nothing to count a
   * segnalazione against. */
  codice_istat: string | null;
  ente: string | null;
}

/** Quello che TreasureIQ ha capito della domanda, restituito perche' il
 *  cittadino lo veda e possa smentirlo. Ogni campo non capito resta assente,
 *  mai riempito con un valore di comodo. */
export interface ProfiloCapito {
  comune_nome: string | null;
  comune_istat: string | null;
  comune_coperto: boolean | null;
  eta: number | null;
  isee: string | null;
  nucleo_familiare: number | null;
  figli_minori: number | null;
  disabilita: boolean | null;
  sesso: "f" | "m" | null;
  /** True quando `sesso` viene da una deduzione sul nome proprio (D-52),
   *  non da una dichiarazione esplicita: bassa confidenza, va mostrato
   *  correggibile ("ho capito: donna — giusto?"), mai come un fatto. */
  sesso_dedotto: boolean;
  figli_disabili: number | null;
  disabilita_nucleo: boolean | null;
}

/** Mirror esatto di `Requirements` (`api/treasureiq/schema.py`). Ogni campo
 *  `null`/vuoto significa "non dichiarato dalla fonte", MAI "nessun vincolo"
 *  — la UI deve distinguere le due cose, mai trattare un `null` come "chiunque
 *  è ammesso". `isee_max`/`isee_min` arrivano come stringa (Decimal → JSON
 *  string in pydantic v2): vanno renderizzati letteralmente, mai riletti come
 *  number e ricalcolati. */
export interface Requirements {
  isee_max: string | null;
  isee_min: string | null;
  eta_min: number | null;
  eta_max: number | null;
  residenza_required: boolean;
  residenza_comuni: string[];
  nucleo_min: number | null;
  figli_minori_required: boolean | null;
  disabilita_required: boolean | null;
  sesso: "f" | "m" | null;
  disabilita_nucleo_required: boolean | null;
  employment_status: string[];
  other: string[];
  /** True solo quando il valore viene da un campo tipizzato della fonte, non
   *  da un'estrazione di prosa (D-05/D-05-bis). Non è un vincolo di
   *  ammissibilità: è provenienza, va mostrata come tale se mostrata. */
  source_typed: boolean;
}

/** Mirror esatto di `Money` (`schema.py`). Un importo, forse un range, forse
 *  aperto: `note` copre i casi che resistono a una struttura (es. "50% della
 *  spesa fino a capienza del fondo"). */
export interface Amount {
  min_eur: string | null;
  max_eur: string | null;
  note: string | null;
}

/** Mirror esatto di `Source` (`schema.py`), i campi usati dalla card
 *  bandi-live per citare la fonte e collegarsi al portale. */
export interface OpportunitySource {
  ente: string;
  ente_codice_istat: string | null;
  connector: string;
  url: string;
  fetched_at: string;
}

/** Mirror esatto di `Opportunity` (`schema.py`) — i campi che la card
 *  bandi-live legge davvero. Non un mirror totale del modello Python (i
 *  campi di strumentazione D-16/D-17 non servono a questa card e non sono
 *  qui), ma ogni campo presente è letterale, mai ricomposto. */
export interface Opportunity {
  id: string;
  title: string;
  summary: string | null;
  kind: string;
  requirements: Requirements;
  amount: Amount | null;
  deadline: string | null;
  source: OpportunitySource;
  confidence: string;
  extraction_notes: string[];
}

/** Mirror esatto di `Documento` (`bandi_live.py`): un allegato PDF linkato
 *  dalla pagina del bando. `url` è verbatim dalla pagina (stesso host, reso
 *  assoluto), `etichetta` è il nome-file ripulito. Puntatore alla fonte, non
 *  una lettura di essa: la card lo mostra come link di download. */
export interface Documento {
  url: string;
  etichetta: string;
}

/** Mirror esatto di `BandoArricchito` (`api/treasureiq/bandi_live.py` §5.2).
 *  `scadenza` è presente SOLO se `scadenza_verificata` (D-07 quote-gate):
 *  se `false`, `scadenza` va ignorata dalla UI anche se non è `null`. */
export interface BandoArricchito {
  opportunity: Opportunity;
  scadenza: string | null;
  scadenza_verificata: boolean;
  /** Allegati PDF linkati dalla pagina del bando (ciclo17): stessi PDF che il
   *  backend già conta in `pdfs_linked`, qui esposti come link diretti,
   *  ripuliti dal rumore e capati. Assente/vuoto = la pagina non ne linka o il
   *  bando arriva da un gradino senza HTML pieno — la card omette il blocco. */
  documenti?: Documento[];
  /** Ranking morbido profilo↔requisiti (KAPI 7): `true` se il bando risuona
   *  coi segnali del cittadino. NON è un verdetto di idoneità — è un ordine
   *  indicativo, «controlla i requisiti». `false` di default. */
  consigliato: boolean;
  /** Classificazione del bando (ciclo 8, B2): `"agevolazione"` per contributi
   *  economici, `"concorso"` per selezioni/offerte di lavoro. `null`/assente
   *  se non classificato — la UI non mostra badge in quel caso. L'ordine dei
   *  bandi resta deciso dal backend, il frontend non lo altera. */
  tipo?: "agevolazione" | "concorso" | null;
  /** Filtro tematico (ciclo 9, D-05): `true` se il titolo (fallback requisiti)
   *  del bando risponde al `tema` estratto dal messaggio. `null`/assente
   *  quando `BandiLiveEsito.tema` è assente — nessun filtro attivo, NON
   *  trattarlo come `false`. */
  corrisponde?: boolean | null;
}

/** Mirror esatto di `BandiLiveEsito` (`bandi_live.py` §5.2). Arriva dentro
 *  `ChatOut.bandi_live` sulla risposta chat quando il topic è BANDI: nessuna
 *  fetch separata, il payload è già calcolato server-side (B3). */
export interface BandiLiveEsito {
  codice_istat: string;
  comune_nome: string;
  esito:
    | "coperto_con_bandi"
    | "coperto_senza_bandi"
    | "non_coperto"
    | "comune_ignoto";
  gradino: "cpt" | "pages" | "alberatura" | null;
  verificato_il: string;
  bandi: BandoArricchito[];
  /** Tema estratto dal messaggio (ciclo 9, D-01/D-05): eco verbatim, testo
   *  breve. `null`/assente = nessun filtro tematico (D-07 retrocompat) — la UI
   *  mostra tutti i bandi espansi, senza collasso. Truthy = filtro attivo. */
  tema?: string | null;
}

/* ── Connettore (contratto D-09, mirror di `treasureiq/connettore.py`) ──── */

/** Una voce dell'indice amministrativo del portale: nome e dove sta. */
export interface AreaAmministrativa {
  nome: string;
  url: string;
}

/** Un bando trovato nell'indice di Amministrazione Trasparente. `pdf_url`
 *  `null` quando il bando non porta un PDF collegato — flag di presenza,
 *  non promessa di contenuto leggibile. */
export interface BandoAT {
  titolo: string;
  url: string;
  pdf_url: string | null;
}

/** L'indice AT del portale (D-11): bandi attivi verbatim, `pdf_presenti`
 *  come flag — l'analisi del PDF resta su richiesta del cittadino
 *  (`postAtAnalisi`), mai automatica di massa. */
export interface AmministrazioneTrasparente {
  indice_url: string | null;
  bandi_attivi: BandoAT[];
  pdf_presenti: boolean;
  /** Piattaforma di amministrazione trasparente riconosciuta a parte dal
   *  portale principale (due-connettori, B5 ciclo 16). `"NON_TROVATA"` è
   *  copertura onesta — non un placeholder da nascondere — e va mostrata
   *  come tale. Opzionale: assente nelle risposte non ancora classificate. */
  piattaforma_at?: string;
}

/** Chi risponde di un ufficio (accountability). Best-effort: solo dove la
 *  scheda lo pubblica strutturato, mai inferito da un LLM (D-07). `nome`
 *  sempre presente; `ruolo`/`email` `null` = non pubblicato (D-05). */
export interface Responsabile {
  nome: string;
  ruolo: string | null;
  email: string | null;
}

/** Un ufficio letto dal connettore, coi suoi recapiti verbatim (D-07:
 *  nessuna cifra passa da un LLM). `source_typed` distingue un recapito
 *  tipizzato dal portale (`tel:`/`mailto:`) da uno solo scritto in prosa —
 *  provenienza, mai un giudizio di qualità. Ogni campo recapito assente va
 *  reso come riga onesta «non pubblicato», mai omesso in silenzio (D-05).
 *  `indirizzo`/`responsabile` additivi (Ramo 1): `null`/assenti dove la scheda
 *  non li pubblica — degrado onesto, mai un valore inventato. Opzionali per
 *  compatibilità coi dati esistenti privi di questi campi. */
export interface UfficioConnettore {
  nome: string;
  url: string;
  telefoni: string[];
  email: string[];
  pec: string[];
  orari: string | null;
  source_typed: boolean;
  letto_il: string;
  indirizzo?: string | null;
  responsabile?: Responsabile | null;
}

/** Mirror esatto di `EsitoConnettore` (`api/treasureiq/connettore.py`): il
 *  contratto D-09, quello che una scansione di piattaforma produce, letta
 *  ADESSO (non ingerita) — «letto ora», mai uno snapshot curato. */
export interface EsitoConnettore {
  codice_istat: string;
  piattaforma: string;
  letto_il: string;
  aree_amministrative: AreaAmministrativa[];
  uffici: UfficioConnettore[];
  amministrazione_trasparente: AmministrazioneTrasparente | null;
}

/** Un segmento di testo estratto dal PDF, verbatim da pypdf (D-07): mai
 *  passato da un LLM, mai riformattato — le cifre restano quelle stampate
 *  nel documento. */
export interface AtAnalisiSegmento {
  kind: string;
  url: string;
  pagina: number | null;
  testo: string;
}

/** Esito dell'analisi di UN allegato PDF già elencato in un `BandoAT`
 *  (D-11, `POST /api/at-analisi`), mirror di `ATAnalisiResponse`
 *  (`api/treasureiq/api.py`). Mai una scansione di massa: un `pdf_url` alla
 *  volta, host-guarded lato backend. */
export interface AtAnalisiEsito {
  pdf_url: string;
  segmenti: AtAnalisiSegmento[];
  note: string[];
}

/** Mirror di `ATAnalisiRequest` (`api/treasureiq/api.py`). */
export const postAtAnalisi = (codiceIstat: string, pdfUrl: string) =>
  call<AtAnalisiEsito>("/api/at-analisi", {
    method: "POST",
    body: JSON.stringify({ codice_istat: codiceIstat, pdf_url: pdfUrl }),
  });

export interface ChatOut {
  /** Opaque anonymous conversation token, retained by the browser cookie for 90 days. */
  conversation_id: string;
  profilo_capito: ProfiloCapito | null;
  reply: string;
  /** The topic this answer was retrieved for. The API has always sent it;
   * declaring it lets the follow-up check reuse it instead of re-running
   * intent extraction, which keeps that request deterministic. */
  topic: string | null;
  matches: Match[];
  data_gap: DataGap | null;
  cost: ChatCost | null;
  /** D-19 rail marker. */
  kind: QuestionKind;
  /** D-29 — residual actions left on the citizen after this answer (a
   * count, never an estimate). `null` off the INFORMAZIONE rail. Always
   * rendered apart from `cost`: the two answer different questions and
   * must never be summed or share a line. */
  citizen_effort: number | null;
  /** The deterministic access route this answer was composed at. During the
   * catalog migration this can be the new `direct`/`mediated`/`indirect`/
   * `unavailable` vocabulary or the legacy `M*_...` value for municipalities
   * not imported yet. `null` off the INFORMAZIONE rail. */
  access_mode:
    | "direct"
    | "mediated"
    | "indirect"
    | "unavailable"
    | "M2_prosa_api"
    | "M4_connettore"
    | "M5_nessuno"
    | "M6_web_aperto"
    | string
    | null;
  /** One entry per measured catalog surface. */
  source_access: SourceAccess[];
  /** `null` on the AGEVOLAZIONE rail — an eligibility answer never carries
   * INFORMAZIONE furniture, and vice versa (D-19). */
  info: InfoOut | null;
  /** Presente solo fuori copertura, dopo la sonda AgID: dice se il connettore
   * raggiungerebbe questo comune. `null` sui comuni coperti o non sondati. */
  connettore: ConnettoreSonda | null;
  /** Recapiti del comune. Su un comune coperto vengono dallo store (`_da_store`);
   * fuori copertura sono letti al volo dal portale. Non è una risposta di
   * TreasureIQ: la UI lo mostra come card nel pannello a sinistra. `null` solo
   * quando non c'è nessun recapito né a store né dallo scrape. */
  numeri_utili: NumeriUtili | null;
  /** Candidati di disambiguazione quando il nome comune è ambiguo. La UI li
   * rende come schede cliccabili: un tap sceglie e rimanda la domanda. */
  comuni_ambigui: ComuneAmbiguo[] | null;
  /** B6 — stato dello scan del comune, se presente. Consumato da <ScanLive>
   * (via ScanProvider): banda «sto aggiornando» + bottone «Ricarica», mostrati
   * uguali in chat e nel pannello. */
  scan?: ScanStato | null;
  /** B3/B4 (KAPI 7, bandi-live-agid) — esito della scansione bandi-live a due
   * gradini per il comune del profilo, presente solo sul topic BANDI. `null`
   * fuori da quel topic o finché il backend non lo valorizza (§5.2). */
  bandi_live?: BandiLiveEsito | null;
  /** B4/B5 (ciclo 10) — esito del connettore letto ORA (contratto D-09,
   *  `EsitoConnettore`), quando la risposta è stata composta leggendo il
   *  portale al volo invece che dallo store ingerito. `null`/assente sui
   *  comuni serviti dallo store o finché il backend non lo valorizza.
   *  Nome campo allineato al modello backend (`EsitoConnettore`) — da
   *  riconfermare in integrazione con l'arm B4. */
  esito_connettore?: EsitoConnettore | null;
  /** Ciclo11/A6-L-3 — i filtri civici RICONOSCIUTI in questo turno
   * (`riconosci_filtri`), gia' proiettati dal backend: la lista non include
   * le chiavi appena tolte da `filtri_override` nella stessa richiesta. */
  filtri: FiltroOut[];
  /** Ciclo12/B1 — slot di dialogo pendente: quale pezzo mancante TIQ ha
   *  appena chiesto (dentro `reply`, nessun bubble nuovo). `null` = nessuna
   *  domanda pendente. Il client la conserva e la rimanda come
   *  `ChatIn.chiarimento_atteso` nel turno immediatamente successivo, poi
   *  la azzera (uno slot vale un turno, non bloccante — D-04). */
  chiarimento?: Chiarimento | null;
}

export interface SourceAccess {
  surface: "ordinary_data" | "transparency";
  access_mode: "direct" | "mediated" | "indirect" | "unavailable";
  platform_id: string | null;
  platform_compatibility: string;
  measured_at: string;
}

/** Un candidato di disambiguazione comune. `codice_istat` serve a rimandare la
 *  domanda con la scelta fatta, senza far ridigitare il nome. */
export interface ComuneAmbiguo {
  nome: string;
  provincia: string;
  codice_istat: string;
}

/** Esito della sonda AgID su un comune fuori copertura. Non un verdetto:
 *  `indirizzabile` = il portale espone l'API uffici del modello AgID, `uffici`
 *  è quanti ne elenca (conteggio strutturale, mai una spettanza). */
export interface ConnettoreSonda {
  /** Il comune sondato: si passa a `fetchMappaConnettore` per i chip categoria. */
  codice_istat: string;
  indirizzabile: boolean;
  uffici: number;
  rest_base: string | null;
  /** ISO dell'ultima scansione sweep del comune (registro locale). null = mai
   *  scansionato: il badge omette il segmento «ultima scansione». */
  ultima_scansione: string | null;
}

/** Una categoria standard del modello AgID e quanti servizi vi ricadono in un
 *  comune. `conteggio` è un conteggio strutturale del catalogo, mai una
 *  spettanza. Le categorie a zero non arrivano qui (chip su vicolo vuoto). */
export interface CategoriaServizio {
  nome: string;
  conteggio: number;
  /** Term della tassonomia: serve a scendere di livello. `0` se il portale non lo espone. */
  id: number;
  slug: string;
}

/** Un servizio del catalogo comunale: titolo + link alla scheda sul portale.
 *  È la foglia della cascata — la fonte citata, non un verdetto (D-01). */
export interface ServizioLink {
  titolo: string;
  url: string;
}

/** L'anteprima di un servizio letta dalla sua pagina: cosa è e a chi è rivolto,
 *  con l'url per aprirla intera. Fonte citata, non verdetto (D-01). */
export interface SchedaServizio {
  titolo: string;
  url: string;
  descrizione: string | null;
  a_chi: string | null;
  cosa_ottieni: string | null;
}

/** Le capacità dirette del portale di un comune: il catalogo servizi e le 15
 *  categorie del modello AgID. Serve i chip a cascata, non un verdetto: dice
 *  per quali strade dirette potremmo rispondere, mai cosa spetta (D-01). */
export interface MappaConnettore {
  codice_istat: string;
  nome: string;
  sito: string | null;
  servizi: {
    esposto: boolean;
    totale: number;
    categorie: CategoriaServizio[];
  };
  uffici: { esposto: boolean; totale: number };
}

/** Cosa il portale di un comune ha detto sui propri orari di sportello, e
 *  quando gliel'abbiamo chiesto (`OrariLive` in `sonda_live.py`). Senza
 *  `citazione` non c'è nessun orario da mostrare, solo la constatazione che
 *  non l'abbiamo trovato. */
export interface OrariLive {
  codice_istat: string;
  nome: string;
  sito: string | null;
  indirizzabilita: "api_uffici" | "solo_html" | "irraggiungibile";
  recuperabilita: "campo_tipizzato" | "prosa" | "assente";
  ufficio: string | null;
  ufficio_url: string | null;
  citazione: string | null;
  letto_il: string;
}

/** L'aderenza AgID di un comune coperto: checklist fissa di 4 superfici
 *  (servizi, uffici, trasparenza, contatti), mai una cifra digitata (D-S2).
 *  `superfici` porta la provenienza — quale via ha contato per la % (D-S4). */
export interface AderenzaAgid {
  percento: number;
  esposte: number;
  definite: number;
  superfici: { nome: string; via: "REST" | "scrape" | null }[];
}

/** La scheda completa di un comune scansionato (`SchedaComuneOut` in
 *  `api.py`, contratto pinnato in `plan.md`). `aderenza` è sempre `null`
 *  quando `connettore_tipo != "agid"` — mai una % su un connettore che non
 *  la può misurare (D-S2). */
export interface SchedaComune {
  codice_istat: string;
  nome: string;
  sito: string | null;
  /** Quando questo record è stato scansionato, dal record store — mai un
   *  timestamp calcolato al volo. */
  scansionato_il: string;
  connettore_tipo: "agid" | "solo-html" | "non-sondato";
  aderenza: AderenzaAgid | null;
  servizi: { esposto: boolean; totale: number; categorie: CategoriaServizio[] };
  uffici: { esposto: boolean; totale: number };
  contatti: {
    telefoni: string[];
    pec: string[];
    email: string[];
    fonte: string;
    letto_il: string;
  } | null;
  orari: OrariLive | null;
  /** Solo host del comune (D-S8): mai un logo letto da un dominio estraneo. */
  logo_url: string | null;
  /** Famiglia piattaforma dal censimento nazionale (storico.db), non dallo
   *  scan-mappa: il vendor riconosciuto anche quando `connettore_tipo` cade su
   *  "solo-html" perché il portale non espone REST AgID. `classificato_da` è la
   *  provenienza (sonda vs riclassificazione). `null` = comune non censito.
   *  `piattaforma_at` può valere "non_trovata"/"ignota": non sono vendor. */
  piattaforma: string | null;
  piattaforma_at: string | null;
  at_url: string | null;
  classificato_da: string | null;
}

export const fetchSchedaComune = (codiceIstat: string) =>
  call<SchedaComune | null>(`/api/comune/${codiceIstat}`);

/** Mirror esatto di `RegistroComune` (CONTRATTO-O2, congelato in `plan.md`,
 *  `api/treasureiq/registro.py`). `logo_b64` arriva già come data-uri: il
 *  logo è stato catturato una volta, alla scansione (D-11) — la UI non fa
 *  MAI una fetch verso il dominio del comune per ottenerlo (D-01). */
export interface RegistroComune {
  codice_istat: string;
  nome: string;
  logo_b64: string | null;
  dominio: string;
  piattaforma: string;
  endpoints: {
    amministrazione: string | null;
    servizi: string | null;
    mappa: string | null;
    at: string | null;
  };
  /** ISO, mai un `now()` ricalcolato lato client (stile D-10 ciclo 10). */
  ultima_scansione: string;
  uffici_snapshot: { nome: string; url: string }[];
  prima_scansione: boolean;
  /** `null` = nessun cambiamento rilevato, oppure `prima_scansione: true`
   *  (in quel caso non c'è una scansione precedente con cui confrontare). */
  cambiato: { campi: string[] } | null;
  /** Recapiti + identità ufficiali IPA (PEC, indirizzo, Codice Univoco IPA),
   *  innestati a read-time dal backend. `null` = ente senza nulla nell'indice
   *  IPA; ogni campo può mancare da solo. Statico, non da scansione portale.
   *  `codice_ipa` viene dall'elenco nazionale, non da `ipa-recapiti.json`. */
  recapiti: {
    pec: string | null;
    indirizzo: string | null;
    codice_ipa: string | null;
    fonte: string;
  } | null;
}

/** Il registro di un comune, letto SOLO dal disco lato backend (D-01/D-11):
 *  nessuna rete verso il portale del comune parte da qui. `404` = comune mai
 *  scansionato — la card lato UI degrada onestamente a glifo+nome dal
 *  profilo, non a un errore. */
export const fetchRegistroComune = async (
  codiceIstat: string,
): Promise<RegistroComune | null> => {
  const res = await fetch(`${API}/api/registro/${codiceIstat}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as RegistroComune;
};

/** Recapiti ufficiali IPA (PEC + indirizzo) per QUALSIASI comune, censito o
 *  meno. Serve la card di un comune fuori copertura, che nel registro non ha
 *  ancora un record (404): così mostra i recapiti istituzionali, non solo il
 *  telefono letto dal vivo. Statico, letto da disco lato backend. */
export interface RecapitiComune {
  pec: string | null;
  indirizzo: string | null;
  codice_ipa: string | null;
  fonte: string;
}

export const fetchRecapitiComune = async (
  codiceIstat: string,
): Promise<RecapitiComune | null> => {
  const res = await fetch(`${API}/api/recapiti/${codiceIstat}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as RecapitiComune;
};

/** Stato dello scan di un comune, per il rail chat (B6). `stato` distingue
 *  un record fresco da uno che si sta aggiornando in questo momento — la UI
 *  non li rende uguali. */
export interface ScanStato {
  stato: "fresco" | "aggiornamento_in_corso";
  // null per un comune mai scansionato: il backend non inventa una data.
  ultimo_scan: string | null;
}

/** Recapiti del comune letti al volo dal portale. Nessun numero è verificato.
 *  `fonte_tipo` è sempre «scansione web»; `letto_il` è l'ora del controllo
 *  (ISO 8601), che il pannello rende come «ultimo controllo». */
export interface NumeriUtili {
  telefoni: string[];
  email: string[];
  pec: string[];
  fonte: string | null;
  fonte_tipo: string;
  letto_il: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ConversationTranscript {
  conversation_id: string | null;
  messages: ChatTurn[];
}

export const chat = (
  message: string,
  history: ChatTurn[] = [],
  comuneIstat: string | null = null,
  filtriOverride: FiltroOverride[] | null = null,
  chiarimentoAtteso: Chiarimento | null = null,
) =>
  call<ChatOut>("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      history,
      comune_istat: comuneIstat,
      filtri_override: filtriOverride,
      chiarimento_atteso: chiarimentoAtteso,
    }),
  });

/** Reopen the server-side anonymous transcript carried by the browser cookie. */
export const openConversation = () =>
  call<ConversationTranscript>("/api/conversation");

/** Immediately deletes the anonymous conversation state and its browser token. */
export const forgetConversation = () =>
  call<{ status: "forgotten" }>("/api/conversation", { method: "DELETE" });

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

/** Latest catalog measurements for the internal monitoring view. */
export interface CatalogAccess {
  municipality_istat: string;
  surface: "ordinary_data" | "transparency";
  access_mode: "direct" | "mediated" | "indirect" | "unavailable";
  platform_id: string | null;
  platform_compatibility: string;
  measured_at: string;
  measurement_id: string;
}

export const catalogAccess = () => call<CatalogAccess[]>("/api/catalog/access");
export const catalogAccessFor = (codiceIstat: string) =>
  call<CatalogAccess[]>(`/api/catalog/access/${encodeURIComponent(codiceIstat)}`);

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

/** Result of `GET /api/censimento/comune/{codice_istat}` — nullable: `null`
 * finché quel comune non è mai stato spazzolato dal censimento nazionale
 * (checkout fresco, o comune fuori censimento). Non è un errore, e il
 * chiamante non deve inventare cifre quando lo vede: sta zitto (D-41/D-44). */
export interface PortaleComune {
  piattaforma: string;
  aderenza: number | null;
  rilevato_il: string;
}

export const portaleComune = async (istat: string) =>
  call<PortaleComune | null>(`/api/censimento/comune/${encodeURIComponent(istat)}`);

/** B22 (D-25) — the anonymous per-comune segnalazione counter, keyed by
 * `codice_istat`. Never carries anything besides a count: no IP, no
 * session, no citizen text (`SegnalazioneIn`/routes in `api.py`). */
export const segnalazioni = () => call<Record<string, number>>("/api/segnalazioni");

export const inviaSegnalazione = (codiceIstat: string) =>
  call<Record<string, number>>("/api/segnalazioni", {
    method: "POST",
    body: JSON.stringify({ codice_istat: codiceIstat }),
  });

/** D-01 ciclo 6 — il feedback va al nostro server e basta: nessuna mail
 *  esposta, nessuna issue GitHub, nessun invio a terzi (SMTP deferred). */
export const inviaFeedback = (testo: string, voto: number | null) =>
  call<{ ok: boolean }>("/api/feedback", {
    method: "POST",
    body: JSON.stringify({ testo, voto }),
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

/* ── Censimento dei portali comunali ─────────────────────────────────────── */

export interface PiattaformaRiga {
  piattaforma: string;
  comuni: number;
  /** `null` finché nessun dataset di popolazione è stato caricato. Mai zero:
   *  uno zero disegnerebbe "nessun cittadino servito", che è falso. */
  popolazione: number | null;
  servizi: number;
  con_catalogo: number;
  /** In quante regioni compare. Uno = piattaforma regionale, venti = prodotto nazionale. */
  regioni: number;
  regione_prima: string | null;
  comuni_prima: number;
}

export interface FornitoreRiga {
  piattaforma: string;
  /** Contro quale denominatore è calcolata l'aderenza. Due basi diverse non
   *  vanno messe nella stessa classifica: vedi la nota nella pagina. */
  base_misura: string | null;
  comuni: number;
  misurati: number;
  aderenza_media: number | null;
  aderenza_minima: number | null;
  impronte: number;
}

export interface SezioneRiga {
  sezione: string;
  manca_su: number;
  misurati: number;
}

export interface VincoliRiga {
  /** `compilato` | `vuoto` | `assente`. */
  stato: string;
  comuni: number;
}

/** Mirror di `PiattaformaAtOut` (`api/treasureiq/api.py`): distinta dalla
 *  `PiattaformaOut` del portale principale (D-09, due-connettori) — questa
 *  è la piattaforma di amministrazione-trasparente, GROUP BY a parte.
 *  `"NON_TROVATA"` è copertura onesta, non un placeholder da nascondere. */
export interface PiattaformaAtRiga {
  piattaforma_at: string;
  comuni: number;
  popolazione: number | null;
  regioni: number;
  regione_prima: string | null;
  comuni_prima: number;
}

export interface Censimento {
  rilevato_il: string | null;
  date_disponibili: string[];
  piattaforme: PiattaformaRiga[];
  fornitori: FornitoreRiga[];
  sezioni_mancanti: SezioneRiga[];
  vincoli: VincoliRiga[];
  /** Opzionale: assente nelle risposte precedenti al ciclo 16. */
  piattaforme_at?: PiattaformaAtRiga[];
}

export interface Connettore {
  piattaforma: string;
  livello: "modello" | "catalogo" | "firma";
  firma: string;
  rotta_servizi: string | null;
  note: string | null;
}

export const getCensimento = () => call<Censimento>("/api/censimento");

export const getConnettori = () => call<Connettore[]>("/api/connettori");
