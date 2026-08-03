/**
 * Service status — "Stato sistemi", the full picture (v3).
 *
 * Sourced from `GET /api/status`, which is itself derived from disk (the last
 * committed ingestion), never a live probe of the comune's own site. Three
 * groups, all from the same honest evidence:
 *
 *   - Fonti — which comuni TreasureIQ can currently answer from, and how many
 *     records each holds.
 *   - Sistemi — TreasureIQ's own components. Components that are only used at
 *     ingestion time (the local LLM, the SearXNG web search) are NOT probed on
 *     every page load, so they report "non verificato" — a real state, never a
 *     masked "down".
 *   - Stato dati interni — headline numbers on what was actually recovered.
 *
 * `reachable`/`stato` are nullable by design until a run has checked them, and
 * a `null` must never be read as "down": it renders as "non verificato",
 * visually distinct from both working and broken.
 */

import {
  costi,
  status,
  type Costo,
  type InternalDatum,
  type SourceStatus,
  type StatusOut,
  type SystemComponent,
} from "@/lib/api";
import ScalaAccesso from "@/components/ScalaAccesso";

export const dynamic = "force-dynamic";

type State = "ok" | "degraded" | "down" | "unknown";

const OVERALL_LABEL: Record<string, string> = {
  ok: "Tutti i sistemi rispondono",
  degraded: "Alcuni sistemi in difficoltà",
  down: "Sistemi irraggiungibili",
  unknown: "Stato non verificato",
};

const STATE_LABEL: Record<State, string> = {
  ok: "operativo",
  degraded: "in difficoltà",
  down: "non disponibile",
  unknown: "non verificato",
};

function formatDate(iso: string | null): string {
  if (!iso) return "mai";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "mai";
  return d.toLocaleString("it-IT", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function reachabilityLabel(reachable: boolean | null): {
  label: string;
  state: State;
} {
  if (reachable === true) return { label: "raggiungibile", state: "ok" };
  if (reachable === false) return { label: "irraggiungibile", state: "down" };
  return { label: "non verificato", state: "unknown" };
}

function SourceRow({ source }: { source: SourceStatus }) {
  const r = reachabilityLabel(source.reachable);
  return (
    <li className="status-row" data-stato={r.state}>
      <span className="status-row__dot" aria-hidden="true" />
      <div className="status-row__body">
        <div className="status-row__head">
          <strong>{source.nome}</strong>
          <span className="status-row__badge">{r.label}</span>
        </div>
        <p className="status-row__meta">
          {source.records != null
            ? `${source.records.toLocaleString("it-IT")} record in archivio`
            : "nessun record in archivio"}
          {" · "}
          ultima ingestion: {formatDate(source.last_ingested)}
        </p>
      </div>
    </li>
  );
}

function ComponentRow({ component }: { component: SystemComponent }) {
  return (
    <li className="status-row" data-stato={component.stato}>
      <span className="status-row__dot" aria-hidden="true" />
      <div className="status-row__body">
        <div className="status-row__head">
          <strong>{component.nome}</strong>
          <span className="status-row__badge">
            {STATE_LABEL[component.stato as State] ?? component.stato}
          </span>
        </div>
        <p className="status-row__meta">{component.detail}</p>
      </div>
    </li>
  );
}

function DatumRow({ datum }: { datum: InternalDatum }) {
  return (
    <div className="datum-row" data-stato={datum.stato}>
      <span className="datum-row__value">{datum.value}</span>
      <div className="datum-row__body">
        <p className="datum-row__detail">
          <strong>{datum.nome}.</strong> {datum.detail}
        </p>
      </div>
    </div>
  );
}

export default async function Monitoraggio() {
  let report: StatusOut | null = null;
  try {
    report = await status();
  } catch {
    report = null;
  }

  // Fail-soft, like every other panel here: the ladder is worth showing
  // when the cost endpoint answers and never worth taking the status
  // report down for.
  let costiReport: Costo[] = [];
  try {
    costiReport = await costi();
  } catch {
    costiReport = [];
  }

  if (!report) {
    return (
      <div className="panel">
        <h2>Dati non disponibili</h2>
        <p className="lede">
          Non riesco a raggiungere il servizio. Verifica che l&apos;API sia in
          esecuzione, poi ricarica la pagina.
        </p>
      </div>
    );
  }

  const overall = report.overall ?? "unknown";

  return (
    <div className="stack">
      <section>
        <p className="eyebrow">Stato sistemi</p>
        <h1>{OVERALL_LABEL[overall] ?? OVERALL_LABEL.unknown}</h1>
        <p className="lede">
          Tre gruppi, una sola fonte di verità: quello che TreasureIQ ha
          effettivamente recuperato da ciascuna fonte, lo stato delle proprie
          componenti e i numeri su cosa è stato ingerito l&apos;ultima volta.
          Non un cruscotto di uptime: un&apos;istantanea onesta di cosa c&apos;è
          davvero.
        </p>
      </section>

      {/* The ladder goes above the three status groups on purpose. Those
          answer "is it working"; this answers "what did it take", which is the
          question the project exists to make askable. */}
      <ScalaAccesso costi={costiReport} />

      <div className="systems">
        <section className="systems__group">
          <div className="systems__group-head">
            <h2>Fonti</h2>
            <span className="systems__group-note">
              i comuni da cui TreasureIQ risponde
            </span>
          </div>
          <div className="panel">
            <ul className="status-list">
              {(report.sources ?? []).map((s) => (
                <SourceRow key={s.codice_istat} source={s} />
              ))}
            </ul>
            {(report.sources ?? []).length === 0 && (
              <p className="lede">Nessuna fonte configurata.</p>
            )}
          </div>
        </section>

        <section className="systems__group">
          <div className="systems__group-head">
            <h2>Sistemi</h2>
            <span className="systems__group-note">
              le componenti di TreasureIQ stessa
            </span>
          </div>
          <div className="panel">
            <ul className="status-list">
              {(report.sistemi ?? []).map((c) => (
                <ComponentRow key={c.nome} component={c} />
              ))}
            </ul>
          </div>
        </section>

        <section className="systems__group">
          <div className="systems__group-head">
            <h2>Stato dati interni</h2>
            <span className="systems__group-note">
              cosa è stato effettivamente recuperato
            </span>
          </div>
          <div className="panel">
            {(report.dati_interni ?? []).map((d) => (
              <DatumRow key={d.nome} datum={d} />
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <h2>Perché &ldquo;non verificato&rdquo; e non un pallino verde o rosso</h2>
        <p className="lede">
          Questa pagina non manda una richiesta al sito del comune ogni volta
          che qualcuno la apre. Farlo vorrebbe dire interrogare
          un&apos;infrastruttura pubblica che non gestiamo, ad ogni visita, per
          un numero che racconta poco. E non sonda neppure le proprie componenti
          a ogni visita: il modello linguistico locale e la ricerca web vivono
          solo durante l&apos;ingestion.
        </p>
        <p className="lede">
          &ldquo;Non verificato&rdquo; è quindi uno stato reale, non un errore
          nascosto: significa che nessun controllo recente ha riguardato quella
          voce. Non significa che sia rotta, e non deve mai essere letto come se
          lo fosse — è la stessa onestà sui limiti dei dati che il resto del
          progetto applica ai requisiti dei bandi.
        </p>
      </section>
    </div>
  );
}
