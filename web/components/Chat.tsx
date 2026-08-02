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

import { useId, useRef, useState } from "react";
import { Seal } from "@/components/Seal";
import {
  chat,
  login,
  type ChatCost,
  type ChatOut,
  type ChatTurn,
  type CostLevels,
  type Escalation,
  type Match,
} from "@/lib/api";

const GLYPH: Record<string, string> = {
  met: "●",
  not_met: "✕",
  unknown_source: "◐",
  unknown_profile: "◌",
};

const PRESETS = [
  {
    id: "famiglia",
    name: "Famiglia con figlio minore",
    detail: "38 anni · ISEE 12.000 € · nucleo di 3",
    profile: {
      eta: 38,
      isee: "12000",
      nucleo_familiare: 3,
      figli_minori: 1,
      employment_status: "occupato",
      interests: ["famiglie", "studenti"],
    },
  },
  {
    id: "pensionato",
    name: "Pensionato che vive solo",
    detail: "71 anni · ISEE 30.000 € · nucleo di 1",
    profile: {
      eta: 71,
      isee: "30000",
      nucleo_familiare: 1,
      figli_minori: 0,
      employment_status: "pensionato",
      interests: ["anziani"],
    },
  },
  {
    id: "studente",
    name: "Studente in cerca di lavoro",
    detail: "23 anni · ISEE 8.000 € · nucleo di 2",
    profile: {
      eta: 23,
      isee: "8000",
      nucleo_familiare: 2,
      figli_minori: 0,
      employment_status: "disoccupato",
      interests: ["studenti", "disoccupati"],
    },
  },
] as const;

const LEVEL_LABEL: Record<keyof CostLevels, string> = {
  L1_manuale: "manuale",
  L2_estratto: "estratto da PDF",
  L3_illeggibile: "illeggibile",
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
          {totalPct != null && (
            <rect x="0" y="1" width={totalPct * 0.96} height="4" fill="var(--yamabuki)" />
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

function MatchCard({ match }: { match: Match }) {
  const decided = match.criteria.filter(
    (c) => c.state === "met" || c.state === "not_met",
  );
  const unpublished = match.criteria.filter((c) => c.state === "unknown_source");
  const askProfile = match.criteria.filter((c) => c.state === "unknown_profile");

  return (
    <article className="card" data-verdict={match.verdict}>
      <Seal verdict={match.verdict} size={40} />
      <div>
        <h3 className="card__title">{match.title}</h3>
        <p className="card__headline">{match.headline}</p>

        <div className="card__meta">
          <span className="tag">{match.verdict_label}</span>
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

        <p style={{ marginTop: "var(--ma-4)", fontSize: "0.9rem" }}>
          <a href={match.source_url} target="_blank" rel="noreferrer">
            Apri la pagina ufficiale del comune →
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

function EscalationGate({
  escalation,
  onResolved,
}: {
  escalation: Escalation;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function enter(preset: (typeof PRESETS)[number]) {
    setBusy(preset.id);
    setError(null);
    try {
      await login({
        comune_istat: "058003",
        comune_nome: "Albano Laziale",
        ...preset.profile,
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
  const nextId = useRef(0);

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
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: "assistant", content: out.reply, reply: out },
      ]);
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

  return (
    <section className="chat" aria-label="Conversazione con TreasureIQ">
      <div className="chat__log" aria-live="polite">
        {messages.length === 0 && (
          <p className="chat__hint">
            Ad esempio: &laquo;ho la bolletta elettrica troppo alta&raquo;,
            &laquo;ci sono bandi per informatici in scadenza?&raquo;
          </p>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`bubble bubble--${m.role}`}>
            <p>{m.content}</p>

            {m.reply && (
              <div className="chat__answer">
                {m.reply.cost && <CostStrip cost={m.reply.cost} />}

                {m.reply.matches.length > 0 && (
                  <div className="feed">
                    {m.reply.matches.map((match) => (
                      <MatchCard key={match.id} match={match} />
                    ))}
                  </div>
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
              </div>
            )}
          </div>
        ))}

        {busy && (
          <p className="chat__hint" aria-hidden="true">
            Sto leggendo i dati del comune…
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
            Chiedi
          </button>
        </div>
      </form>
    </section>
  );
}
