/**
 * Service status — which sources TreasureIQ can currently answer from.
 *
 * Sourced from `GET /api/status`, which is itself derived from disk (the last
 * committed ingestion), never a live probe of the comune's own site. That is
 * not a shortcut: pinging a municipal server on every page load a citizen
 * happens to open would hammer infrastructure we do not own, in exchange for
 * a number that tells nobody anything about the one thing that matters here
 * — what got recovered at the last real ingestion run. `reachable` is
 * therefore `null` by design until a run has actually checked, and a `null`
 * must never be read as "down": it is rendered as "non verificato", visually
 * distinct from both "raggiungibile" and "irraggiungibile".
 */

import { status, type SourceStatus, type StatusOut } from "@/lib/api";

export const dynamic = "force-dynamic";

const OVERALL_LABEL: Record<string, string> = {
  ok: "Tutte le fonti rispondono",
  degraded: "Alcune fonti in difficoltà",
  down: "Fonti irraggiungibili",
  unknown: "Stato non verificato",
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
  state: "reachable" | "unreachable" | "unverified";
} {
  if (reachable === true) return { label: "raggiungibile", state: "reachable" };
  if (reachable === false) return { label: "irraggiungibile", state: "unreachable" };
  return { label: "non verificato", state: "unverified" };
}

function SourceRow({ source }: { source: SourceStatus }) {
  const r = reachabilityLabel(source.reachable);
  return (
    <li className="status-row" data-reachable={r.state}>
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

export default async function Monitoraggio() {
  let report: StatusOut | null = null;
  try {
    report = await status();
  } catch {
    report = null;
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
        <p className="eyebrow">Monitoraggio del servizio</p>
        <h1>{OVERALL_LABEL[overall] ?? OVERALL_LABEL.unknown}</h1>
        <p className="lede">
          Quello che TreasureIQ ha effettivamente recuperato da ciascuna fonte,
          e quando. Non un cruscotto di uptime: un&apos;istantanea onesta di
          cosa è stato ingerito l&apos;ultima volta e da dove.
        </p>
      </section>

      <section className="panel">
        <ul className="status-list">
          {(report.sources ?? []).map((s) => (
            <SourceRow key={s.codice_istat} source={s} />
          ))}
        </ul>
        {(report.sources ?? []).length === 0 && (
          <p className="lede">Nessuna fonte configurata.</p>
        )}
      </section>

      <section className="panel">
        <h2>Perché &ldquo;non verificato&rdquo; e non un pallino verde o rosso</h2>
        <p className="lede">
          Questa pagina non manda una richiesta al sito del comune ogni volta
          che qualcuno la apre. Farlo vorrebbe dire interrogare
          un&apos;infrastruttura pubblica che non gestiamo, ad ogni
          visita, per un numero che cambia in continuazione e non racconta la
          cosa che conta davvero: cosa il comune ha reso disponibile
          l&apos;ultima volta che l&apos;abbiamo effettivamente letto.
        </p>
        <p className="lede">
          &ldquo;Non verificato&rdquo; è quindi uno stato reale, non un errore
          nascosto: significa che nessuna ingestion recente ha controllato la
          raggiungibilità di quella fonte. Non significa che la fonte sia
          rotta, e non deve mai essere letto come se lo fosse — è la stessa
          onestà sui limiti dei dati che il resto del progetto applica ai
          requisiti dei bandi.
        </p>
      </section>
    </div>
  );
}
