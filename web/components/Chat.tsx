"use client";

/**
 * The chat itself — the interactive island the server shell in `page.tsx`
 * mounts.
 *
 * Three answer shapes come back from `/api/chat` (K3) and they are kept
 * visually distinct on purpose, because conflating them is the exact failure
 * this project exists to name:
 *
 *   - matches: an answer built from data the engine could evaluate. Rendered
 *     with the same `Seal` / `data-verdict` / `criteria` idiom as `/opportunita`.
 *   - data_gap "not_published": the comune never wrote this down. Reuses the
 *     amber `.notice` treatment already used for `unknown_source` criteria
 *     elsewhere in the app — same meaning, same colour.
 *   - data_gap "none_found": nothing matched the question at all. A muted,
 *     neutral treatment, deliberately *not* amber — this is not a data gap,
 *     it is "I found nothing", and dressing it the same as the middle case
 *     would erase the distinction.
 *
 * The mock-SPID picker below is the same three personas that used to live on
 * the home page — relocated here because identity is now something the chat
 * asks for mid-conversation (D-09), not a gate the citizen passes through
 * first.
 */

import { useEffect, useId, useRef, useState } from "react";
import { Seal, Wordmark } from "@/components/Seal";
import Approfondisci from "@/components/Approfondisci";
import Segnalazione from "@/components/Segnalazione";
import SchedaDettaglio from "@/components/SchedaDettaglio";
import AccessoSimulato from "@/components/AccessoSimulato";
import { PRESETS } from "@/lib/profili-demo";
import { useProfilo } from "@/lib/profilo";
import { useRisultati } from "@/lib/risultati";

/** Stable DOM id for one card, so the side index can link straight to it. */
function ancoraDi(messageId: string, matchId: string): string {
  return `scheda-${messageId}-${matchId}`.replace(/[^a-zA-Z0-9_-]/g, "-");
}
import {
  chat,
  comuneNearby,
  login,
  type Approfondimento,
  type ChatCost,
  type ChatOut,
  type ChatTurn,
  type CostLevels,
  type Escalation,
  type InfoOut,
  type Match,
} from "@/lib/api";

/** B22 (D-25) — the segnalazione form only makes sense once every
 * institutional channel is exhausted (D-21's access-mode ladder): a comune
 * publishing structured data (M1/M2/M3) has nothing to ask it to open. */
const SEGNALAZIONE_ACCESS_MODES = new Set(["M4_connettore", "M5_nessuno", "M6_web_aperto"]);

/**
 * What the wait says while it lasts.
 *
 * The old single line read "Sto leggendo i dati del comune…", which named a
 * comune nobody had established — the same claim the hero used to make about
 * residency. These describe only what is actually happening: reading a
 * snapshot, comparing requirements, checking what was published. None of them
 * names an administration, a place or a result.
 */
const ATTESA = [
  "Sto leggendo…",
  "Cerco fra i servizi pubblicati…",
  "Confronto i requisiti…",
  "Verifico cosa è stato pubblicato davvero…",
  "Ci sono quasi…",
];

const GLYPH: Record<string, string> = {
  met: "●",
  not_met: "✕",
  unknown_source: "◐",
  unknown_profile: "◌",
};


const LEVEL_LABEL: Record<keyof CostLevels, string> = {
  L1_manuale: "manuale",
  L2_estratto: "estratto da PDF",
  L3_illeggibile: "illeggibile",
};

/** D-20 — which tier published this opportunity, always shown. */
const LIVELLO_LABEL: Record<Match["livello"], string> = {
  nazionale: "Nazionale",
  regionale: "Regionale",
  comunale: "Comunale",
};

/**
 * D-17 — a one-line caption, not a dashboard: how many seconds it took to
 * recover this answer's criteria from PDF prose, against this comune's
 * average. It says something about how closed the comune's data is, not
 * about how fast TreasureIQ is — `answer_seconds` is deliberately left out
 * so that reading doesn't compete with the answer above it.
 *
 * Every number is independently optional (D-17): a field that is `null`
 * renders nothing, never a zero, so an unmeasured cost can never be
 * mistaken for a measured one.
 */
function CostStrip({ cost }: { cost: ChatCost }) {
  const { recovery_seconds_total: total, recovery_seconds_avg_comune: avg, levels } = cost;

  const levelEntries = levels
    ? (Object.keys(LEVEL_LABEL) as (keyof CostLevels)[]).filter(
        (key) => levels[key] != null,
      )
    : [];

  if (total == null && avg == null && levelEntries.length === 0) {
    return null;
  }

  const max = Math.max(total ?? 0, avg ?? 0, 1);
  const totalPct = total != null ? Math.min(100, (total / max) * 100) : null;
  const avgPct = avg != null ? Math.min(100, (avg / max) * 100) : null;

  return (
    <div className="cost-strip" role="note">
      {(totalPct != null || avgPct != null) && (
        <svg
          className="cost-strip__bars"
          width="96"
          height="14"
          viewBox="0 0 96 14"
          aria-hidden="true"
        >
          {avgPct != null && (
            <rect x="0" y="8" width={avgPct * 0.96} height="4" fill="var(--sumi-faint)" />
          )}
          {/* --fuji was retired with the palette change, and this bar had been
              painting itself with an undefined custom property ever since. */}
          {totalPct != null && (
            <rect x="0" y="1" width={totalPct * 0.96} height="4" fill="var(--ai)" />
          )}
        </svg>
      )}
      <p className="cost-strip__text">
        {total != null && (
          <>
            Recupero dati da PDF per questa risposta: <strong>{Math.round(total)} s</strong>
            {avg != null && <> (media del comune {Math.round(avg)} s)</>}.
          </>
        )}
        {total == null && avg != null && (
          <>
            Media di recupero dati da PDF del comune: <strong>{Math.round(avg)} s</strong>.
          </>
        )}
        {levelEntries.length > 0 && (
          <span className="cost-strip__levels">
            {" "}
            {levelEntries.map((key) => `${LEVEL_LABEL[key]} ${levels![key]}`).join(" · ")}
          </span>
        )}
      </p>
    </div>
  );
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  reply?: ChatOut;
}

function MatchCard({
  match,
  ancora,
  onApri,
}: {
  match: Match;
  ancora: string;
  onApri: () => void;
}) {
  const decided = match.criteria.filter(
    (c) => c.state === "met" || c.state === "not_met",
  );
  const unpublished = match.criteria.filter((c) => c.state === "unknown_source");
  const askProfile = match.criteria.filter((c) => c.state === "unknown_profile");

  return (
    <article id={ancora} className="card" data-verdict={match.verdict}>
      <Seal verdict={match.verdict} size={40} />
      <div>
        <h3 className="card__title">{match.title}</h3>
        <p className="card__headline">{match.headline}</p>

        <div className="card__meta">
          <span className="tag">{match.verdict_label}</span>
          <span className="tag tag--livello" data-livello={match.livello}>
            {LIVELLO_LABEL[match.livello]}
          </span>
          <span>{match.kind.replace(/_/g, " ")}</span>
          {match.deadline && <span>scade il {match.deadline}</span>}
        </div>

        <ul className="criteria">
          {decided.map((c) => (
            <li key={c.key} className="criterion" data-state={c.state}>
              <span className="criterion__glyph" aria-hidden="true">
                {GLYPH[c.state]}
              </span>
              <span>
                <strong style={{ fontWeight: 600 }}>{c.label}.</strong> {c.detail}
              </span>
            </li>
          ))}

          {unpublished.length > 0 && (
            <li className="criterion" data-state="unknown_source">
              <span className="criterion__glyph" aria-hidden="true">
                {GLYPH.unknown_source}
              </span>
              <span>
                <strong style={{ fontWeight: 600 }}>Non pubblicati dal comune:</strong>{" "}
                {unpublished.map((c) => c.label.toLowerCase()).join(", ")}. Non
                sappiamo se ti riguardano.
              </span>
            </li>
          )}

          {askProfile.map((c) => (
            <li key={c.key} className="criterion" data-state={c.state}>
              <span className="criterion__glyph" aria-hidden="true">
                {GLYPH[c.state]}
              </span>
              <span>
                <strong style={{ fontWeight: 600 }}>{c.label}.</strong> {c.detail}
              </span>
            </li>
          ))}
        </ul>

        {/* Detail before departure. The link out stays, but the card now
            offers everything a citizen needs *before* leaving — which office
            to ask, by when, what was and was not checked — rather than
            handing them to a municipal site to find it themselves. */}
        <p className="card__azioni">
          <button type="button" className="card__dettagli" onClick={onApri}>
            Vedi i dettagli
          </button>
          <a href={match.source_url} target="_blank" rel="noreferrer">
            Apri la pagina ufficiale →
          </a>
        </p>
      </div>
    </article>
  );
}

function DataGapNotice({ kind }: { kind: "not_published" | "none_found" }) {
  if (kind === "not_published") {
    return (
      <p className="notice" data-gap="not_published">
        <strong>Il comune non lo ha pubblicato.</strong> Non significa che tu
        non abbia diritto: significa che questo dato manca. Verificalo
        direttamente con l&rsquo;ufficio competente.
      </p>
    );
  }
  return (
    <p className="notice notice--muted" data-gap="none_found">
      <strong>Non ho trovato nulla.</strong> Nessun servizio pubblicato sembra
      corrispondere a questa domanda. Prova a riformularla, oppure guarda la{" "}
      <a href="/opportunita">vista esperta</a>.
    </p>
  );
}

/** Only `http`/`https` URLs render as a link (R-15 — a hostile cached
 * result must never resolve to a clickable `javascript:` or bare string).
 * Anything else still shows as plain, quoted text so the citizen sees
 * exactly what the source gave us. */
function isWebUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

/**
 * D-19 — the INFORMAZIONE rail. Document, office, coverage and diagnosis are
 * facts about a public body's data; nothing here is a verdict, a criterion,
 * or a SPID prompt. If this component ever grows an eligibility badge, the
 * two-rails boundary the whole feature exists to draw has broken.
 */
function InfoAnswer({ info }: { info: InfoOut }) {
  return (
    <div className="info-answer">
      {info.document && (
        <p className="info-answer__document">
          <a href={info.document.url} target="_blank" rel="noreferrer">
            {info.document.title}
          </a>
        </p>
      )}

      <p className="info-answer__coverage">
        {info.coverage_count > 0
          ? `${info.coverage_count} ${info.coverage_count === 1 ? "risultato trovato" : "risultati trovati"} su questo argomento.`
          : "Nessun risultato pubblicato dal comune su questo argomento."}
      </p>

      {info.diagnosis.length > 0 && (
        <ul className="info-answer__diagnosis">
          {info.diagnosis.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}

      {info.integration_cost.length > 0 && (
        <ul className="info-answer__diagnosis info-answer__cost">
          {info.integration_cost.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}

      {info.office && (
        <p className="info-answer__office">
          <strong>{info.office.nome}</strong>
          {info.office.telefono ? (
            <> — tel. {info.office.telefono}</>
          ) : (
            <> — nessun numero di telefono pubblicato dal comune</>
          )}
          {info.office.email && <> · {info.office.email}</>}
          {info.office.orari && <> · {info.office.orari}</>}
        </p>
      )}

      {info.web_results.length > 0 && (
        <div className="info-answer__web" data-state="non_verificato" role="note">
          <p className="info-answer__web-label">Ricerca web · non verificato</p>
          <ul>
            {info.web_results.slice(0, 3).map((result) => (
              <li key={result.url}>
                <span className="info-answer__web-title">{result.title}</span>
                {isWebUrl(result.url) ? (
                  <a
                    className="info-answer__web-url"
                    href={result.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {result.url}
                  </a>
                ) : (
                  <span className="info-answer__web-url">{result.url}</span>
                )}
              </li>
            ))}
          </ul>
          <p className="info-answer__web-note">
            Non è una risposta di TreasureIQ: sono pagine trovate sul web, da
            verificare tu stesso prima di fidartene.
          </p>
        </div>
      )}
    </div>
  );
}

/** D-29 — what is left on the citizen's shoulders after this answer, shown
 * as its own line, never folded into `CostStrip`. The two numbers answer
 * different questions: what closed data cost TreasureIQ to recover, versus
 * what TreasureIQ could not take off the citizen. */
function EffortCaption({ effort }: { effort: number | null }) {
  if (effort == null || effort <= 0) {
    return null;
  }
  return (
    <p className="effort-caption">
      Cosa resta da fare a te: <strong>{effort}</strong>{" "}
      {effort === 1 ? "azione" : "azioni"}.
    </p>
  );
}

function EscalationGate({
  escalation,
  onResolved,
}: {
  escalation: Escalation;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { registra } = useProfilo();

  async function enter(preset: (typeof PRESETS)[number]) {
    setBusy(preset.id);
    setError(null);
    try {
      await login({
        comune_istat: "058003",
        comune_nome: "Albano Laziale",
        ...preset.profile,
      });
      // Publish what signing in actually established, so the citizen can see
      // the facts their answers are now computed from. `accesso` is recorded
      // without a codice fiscale on purpose: this flow is a simulation and
      // never reads one, and the strip says so rather than implying otherwise.
      registra({
        eta: preset.profile.eta,
        interessi: [...preset.profile.interests],
        comune: {
          nome: "Albano Laziale",
          istat: "058003",
          origine: "accesso",
          confermato: true,
        },
        accesso: true,
      });
      onResolved();
    } catch {
      setError(
        "Non riesco a raggiungere il servizio. Verifica che l'API sia in esecuzione su localhost:8010.",
      );
      setBusy(null);
    }
  }

  return (
    <div className="panel escalation" data-gap="escalation">
      <h3>Serve la tua identità</h3>
      <p className="lede" style={{ fontSize: "0.95rem" }}>
        {escalation.reason}
      </p>
      {escalation.missing_fields.length > 0 && (
        <p className="field__hint">
          Dato mancante: {escalation.missing_fields.join(", ")}
        </p>
      )}
      <p style={{ fontSize: "0.85rem", color: "var(--sumi-faint)" }}>
        Questa è una simulazione del flusso SPID: nessuna credenziale viene
        verificata e nessun dato lascia il tuo computer. Scegli un profilo per
        continuare la conversazione.
      </p>

      <div className="grid-2" style={{ marginTop: "var(--ma-4)" }}>
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            className="panel"
            onClick={() => enter(p)}
            disabled={busy !== null}
            style={{
              textAlign: "left",
              cursor: "pointer",
              padding: "var(--ma-4)",
              background: "var(--paper)",
              font: "inherit",
              opacity: busy && busy !== p.id ? 0.5 : 1,
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-display)",
                fontWeight: 700,
                display: "block",
                marginBottom: "var(--ma-1)",
              }}
            >
              {p.name}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "0.78rem",
                color: "var(--sumi-faint)",
              }}
            >
              {busy === p.id ? "Accesso in corso…" : p.detail}
            </span>
          </button>
        ))}
      </div>

      {error && (
        <p className="notice" role="alert" style={{ marginTop: "var(--ma-4)" }}>
          {error}
        </p>
      )}
    </div>
  );
}

export default function Chat() {
  const inputId = useId();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [locateNote, setLocateNote] = useState<string | null>(null);
  const { registra, profilo } = useProfilo();
  const { registra: registraTrovate, azzeraTrovate } = useRisultati();
  const accesso = profilo.accesso === true;
  const [manualLogin, setManualLogin] = useState(false);
  const [scheda, setScheda] = useState<Match | null>(null);
  const [passoAttesa, setPassoAttesa] = useState(0);

  // The wait message moves on every few seconds so a slow answer looks like
  // work in progress rather than a stall. It restarts from the first line each
  // time, so the sequence reads as a progression instead of resuming
  // mid-thought from the previous question.
  useEffect(() => {
    if (!busy) {
      setPassoAttesa(0);
      return;
    }
    const t = setInterval(() => setPassoAttesa((n) => n + 1), 2600);
    return () => clearInterval(t);
  }, [busy]);

  /** Municipal results found by the follow-up check arrive as a new answer in
   *  the transcript, not as a panel beside it: they are verdicts, and every
   *  verdict in this app is stated in exactly one place. */
  function aggiungiComunali(esito: Approfondimento) {
    const id = newId();
    setMessages((prev) => [
      ...prev,
      {
        id,
        role: "assistant",
        content: esito.esito,
        reply: {
          reply: esito.esito,
          topic: null,
          kind: "agevolazione",
          data_gap: null,
          needs_clarification: false,
          matches: esito.matches,
          spid_required: false,
          spid_reason: null,
          access_mode: null,
          citizen_effort: null,
          info: null,
          cost: null,
          escalation: null,
        } as unknown as ChatOut,
      },
    ]);
    registraTrovate(
      esito.matches.map((match) => ({
        ancora: ancoraDi(id, match.id),
        titolo: match.title,
        verdict: match.verdict,
        verdictLabel: match.verdict_label,
        livello: match.livello,
      })),
    );
  }
  const nextId = useRef(0);
  const logRef = useRef<HTMLDivElement>(null);

  // Keep the newest exchange in view as the transcript grows, the way a
  // messaging app does. The page is the scroller now, not the transcript, so
  // this moves the window — scrolling a box that no longer scrolls did
  // nothing at all.
  //
  // Only when the reader is already near the bottom: being yanked away from an
  // answer still being read, because a later one arrived, is worse than having
  // to scroll.
  useEffect(() => {
    if (!logRef.current) return;
    const distanzaDalFondo =
      document.documentElement.scrollHeight - window.scrollY - window.innerHeight;
    if (distanzaDalFondo > 400) return;
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }, [messages, busy]);

  function newId() {
    nextId.current += 1;
    return `m${nextId.current}`;
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;

    setError(null);
    const history: ChatTurn[] = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));
    setMessages((prev) => [...prev, { id: newId(), role: "user", content: trimmed }]);
    setInput("");
    setBusy(true);
    try {
      const out = await chat(trimmed, history);
      const id = newId();
      setMessages((prev) => [
        ...prev,
        { id, role: "assistant", content: out.reply, reply: out },
      ]);
      // Feed the side index. It stores pointers into this transcript, never
      // copies of the verdicts — the card stays the single place any result
      // is stated.
      registraTrovate(
        out.matches.map((match) => ({
          ancora: ancoraDi(id, match.id),
          titolo: match.title,
          verdict: match.verdict,
          verdictLabel: match.verdict_label,
          livello: match.livello,
        })),
      );
    } catch {
      setError(
        "Non riesco a raggiungere il servizio. Verifica che l'API sia in esecuzione su localhost:8010.",
      );
    } finally {
      setBusy(false);
    }
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    send(input);
  }

  function retryLastQuestion() {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) send(lastUser.content);
  }

  /**
   * Geolocation tells us where the citizen is *standing*, never where they
   * are *resident* — the two are routinely different (someone at the URP
   * desk, at work in a neighbouring comune, visiting family). So the button
   * only ever pre-fills the input with a question the citizen still has to
   * send themselves; it never asserts residency on their behalf, and a
   * denied permission is treated as an ordinary answer, not an error.
   */
  function locate() {
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      setLocateNote(
        "Il tuo browser non supporta la geolocalizzazione: scrivi tu il nome del comune.",
      );
      return;
    }
    setLocating(true);
    setLocateNote(null);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          const nearby = await comuneNearby(
            position.coords.latitude,
            position.coords.longitude,
          );
          if (nearby) {
            // Recorded, but explicitly unconfirmed: GPS says where someone is
            // standing, never where they are resident. The strip renders the
            // difference so a borrowed phone or a visit to family can't
            // silently become a residency claim.
            registra({
              comune: {
                nome: nearby.nome,
                istat: nearby.codice_istat,
                origine: "geolocalizzazione",
                confermato: false,
              },
            });
            setInput(
              `Sei a ${nearby.nome}? Confermi che è il tuo comune di residenza?`,
            );
          } else {
            setLocateNote(
              "Non troviamo un comune supportato vicino a te: scrivi tu il nome del comune.",
            );
          }
        } catch {
          setLocateNote(
            "Non riesco a verificare la tua posizione in questo momento: scrivi tu il nome del comune.",
          );
        } finally {
          setLocating(false);
        }
      },
      (geoError) => {
        // Permission denial is a normal, expected answer — not an error state.
        setLocating(false);
        setLocateNote(
          geoError.code === geoError.PERMISSION_DENIED
            ? "Nessun problema: scrivi tu il nome del tuo comune."
            : "Non riesco a determinare la tua posizione: scrivi tu il nome del comune.",
        );
      },
      { timeout: 8000 },
    );
  }

  return (
    <section className="chat" aria-label="Conversazione con TreasureIQ">
      <div className="locate">
        <button
          type="button"
          className="locate__button"
          onClick={locate}
          disabled={locating}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M12 2c-4.4 0-8 3.6-8 8 0 6 8 12 8 12s8-6 8-12c0-4.4-3.6-8-8-8Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            />
            <circle cx="12" cy="10" r="2.6" fill="currentColor" />
          </svg>
          {locating ? "Localizzazione…" : "Usa la mia posizione"}
        </button>
      </div>
      {locateNote && (
        <p className="locate__note" role="status">
          {locateNote}
        </p>
      )}

      <div className="chat__log" aria-live="polite" ref={logRef}>
        {messages.length === 0 && (
          <p className="chat__hint">
            Ad esempio: &laquo;ho la bolletta elettrica troppo alta&raquo;,
            &laquo;ci sono bandi per informatici in scadenza?&raquo;
          </p>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`bubble bubble--${m.role}`}>
            {/* Who is speaking, said once per bubble. Alignment alone carries
                it for a sighted reader on a wide screen and for nobody else:
                on a phone the bubbles nearly touch both edges, and a screen
                reader hears an undifferentiated run of paragraphs. */}
            <p className="bubble__chi">
              {m.role === "user" ? (
                "Tu"
              ) : (
                <>
                  <Wordmark size={18} />
                  TIQ
                </>
              )}
            </p>
            <p>{m.content}</p>

            {m.reply && (
              <div className="chat__answer">
                {m.reply.cost && <CostStrip cost={m.reply.cost} />}

                {m.reply.kind === "informazione" ? (
                  // D-19 — the INFORMAZIONE rail never renders a verdict, a
                  // criterion or a SPID gate. If `info` itself is missing,
                  // this bubble stays empty rather than falling through to
                  // AGEVOLAZIONE furniture below.
                  m.reply.info && (
                    <>
                      <InfoAnswer info={m.reply.info} />
                      {m.reply.access_mode &&
                        SEGNALAZIONE_ACCESS_MODES.has(m.reply.access_mode) &&
                        m.reply.info.codice_istat &&
                        m.reply.info.ente && (
                          <Segnalazione
                            codiceIstat={m.reply.info.codice_istat}
                            ente={m.reply.info.ente}
                            office={m.reply.info.office}
                          />
                        )}
                    </>
                  )
                ) : (
                  <>
                    {m.reply.matches.length > 0 && (
                      <div className="feed">
                        {m.reply.matches.map((match) => (
                          // The anchor is per message, not per opportunity:
                          // the same benefit asked about twice produces two
                          // cards, and the side index has to point at the one
                          // the reader picked.
                          <MatchCard
                            key={match.id}
                            match={match}
                            ancora={ancoraDi(m.id, match.id)}
                            onApri={() => setScheda(match)}
                          />
                        ))}
                      </div>
                    )}

                    {/* Offered only when nothing municipal came back: with a
                        comunale result already on screen the question is
                        answered, and asking it again would be noise. */}
                    {m.reply.topic &&
                      !m.reply.matches.some((x) => x.livello === "comunale") && (
                        <Approfondisci
                          topic={m.reply.topic}
                          onSchede={(esito) => aggiungiComunali(esito)}
                        />
                      )}

                    {m.reply.matches.length === 0 && m.reply.data_gap && (
                      <DataGapNotice kind={m.reply.data_gap} />
                    )}

                    {m.reply.escalation?.needed && (
                      <EscalationGate
                        escalation={m.reply.escalation}
                        onResolved={retryLastQuestion}
                      />
                    )}
                  </>
                )}

                <EffortCaption effort={m.reply.citizen_effort} />
              </div>
            )}
          </div>
        ))}

        {busy && (
          <p className="chat__hint" aria-hidden="true">
            {ATTESA[passoAttesa % ATTESA.length]}
          </p>
        )}
      </div>

      {error && (
        <p className="notice" role="alert">
          {error}
        </p>
      )}

      <form className="chat__form" onSubmit={handleSubmit}>
        <label className="chat__label" htmlFor={inputId}>
          Scrivi la tua domanda
        </label>
        <div className="chat__row">
          <input
            id={inputId}
            className="chat__input"
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Scrivi qui la tua domanda…"
            autoComplete="off"
            disabled={busy}
          />
          <button type="submit" className="button" disabled={busy || !input.trim()}>
            Invia
          </button>
        </div>
      </form>

      {/* A visible but non-pushy way to reach the mock identity flow without
          waiting for the chat to ask for it (D-09 covers *why* the chat asks
          mid-conversation; this is the other, citizen-initiated door).

          Hidden once a session exists, not merely while the panel is open:
          tied only to the panel, it reappeared the moment a login succeeded,
          inviting someone who had just signed in to sign in again. The panel
          in "Sto usando" is where an active session is managed. */}
      {!manualLogin && !accesso && (
        <div className="spid-entry">
          <button
            type="button"
            className="spid-entry__button"
            onClick={() => setManualLogin(true)}
          >
            Accedi con SPID/CIE (simulazione) per risposte sul tuo profilo
          </button>
        </div>
      )}
      {/* Identity is a handoff, so it gets its own screen rather than a panel
          wedged into the transcript. The mid-conversation gate above stays
          inline: there it is attached to the one answer that needs it, and
          losing that context would cost more than the consistency gains. */}
      {manualLogin && (
        <AccessoSimulato
          onAnnulla={() => setManualLogin(false)}
          onFatto={(preset) => {
            setManualLogin(false);
            registra({
              eta: preset.profile.eta,
              interessi: [...preset.profile.interests],
              comune: {
                nome: "Albano Laziale",
                istat: "058003",
                origine: "accesso",
                confermato: true,
              },
              accesso: true,
            });
            // Signing in changes the basis of every verdict already on
            // screen. The question is asked again below, but the index has to
            // be emptied first: it only ever appends, so without this the
            // freshly computed result would sit next to the one calculated
            // before the citizen's data was known — the same benefit listed
            // twice, with two different answers and nothing saying which is
            // current.
            azzeraTrovate();
            retryLastQuestion();
          }}
        />
      )}

      {scheda && <SchedaDettaglio match={scheda} onClose={() => setScheda(null)} />}
    </section>
  );
}
