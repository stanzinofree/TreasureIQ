/**
 * Monitoraggio — where the data pipeline actually stands (v4).
 *
 * Sourced from `GET /api/monitoraggio`, derived from disk (aggregate counts and
 * worker metadata only, never a comune's content, never a live probe). Four
 * sections, three of them one data layer each, kept apart on purpose:
 *
 *   - Demo curata — the handful of deep-extracted MVP comuni (`data/seed`). A
 *     proof the method works, NOT national coverage.
 *   - Copertura nazionale — the shallow service maps (`data/catalog`): which
 *     comuni are catalogued, on which platform, and how many of those platforms
 *     even have a refresh reader ("eleggibili").
 *   - Refresh operativo — the continuous refresh of comuni ALREADY initialised
 *     (`data-live`). This is freshness, not discovery: it re-reads comuni that
 *     already hold a connettore record, it does not enrol new ones. The gap
 *     between "eleggibili" and "inizializzati" is the ingress pipeline still to
 *     be filled, not a slow sweep.
 *   - Sistemi — component health from real signals only; the refresh worker's
 *     state comes from its own sidecar, never from how fresh the seed is.
 */

import {
  monitoraggio,
  type MonitoraggioOut,
  type RefreshOperativo,
  type SystemComponent,
} from "@/lib/api";

export const dynamic = "force-dynamic";

type State = "ok" | "degraded" | "down" | "unknown";

const STATE_LABEL: Record<State, string> = {
  ok: "operativo",
  degraded: "in difficoltà",
  down: "non disponibile",
  unknown: "non verificato",
};

const WORKER_LABEL: Record<RefreshOperativo["worker_stato"], { label: string; state: State }> = {
  attivo: { label: "attivo", state: "ok" },
  fermo: { label: "fermo o sospeso", state: "degraded" },
  sconosciuto: { label: "stato non registrato", state: "unknown" },
};

function n(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString("it-IT");
}

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

function Tessera({ value, label }: { value: string; label: string }) {
  return (
    <div className="tessera">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

export default async function Monitoraggio() {
  let report: MonitoraggioOut | null = null;
  try {
    report = await monitoraggio();
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

  const { demo, copertura, refresh, sistemi } = report;
  const worker = WORKER_LABEL[refresh.worker_stato];
  const batch = refresh.ultimo_batch;

  return (
    <div className="stack">
      <section>
        <p className="eyebrow">Monitoraggio</p>
        <h1>Stato della pipeline dati</h1>
        <p className="lede">
          Tre livelli tenuti distinti, perché confonderli porta alla
          conclusione sbagliata: la <strong>demo curata</strong> (pochi comuni,
          dati profondi), la <strong>copertura nazionale</strong> (le mappe di
          servizio del catalogo) e il <strong>refresh operativo</strong> (la
          freschezza dei comuni già inizializzati). Solo conteggi aggregati e
          metadati: nessun contenuto dei comuni, nessuna sonda in tempo reale.
        </p>
      </section>

      <div className="systems">
        {/* 1 — Demo curata */}
        <section className="systems__group">
          <div className="systems__group-head">
            <h2>Demo curata</h2>
            {/* The (MVP) is load-bearing: a handful of comuni is a proof the
                method works, not a service that covers the country. */}
            <span className="systems__group-note">
              i comuni con estrazione profonda <strong>(MVP)</strong>
            </span>
          </div>
          <div className="panel">
            <div className="tessere">
              <Tessera value={n(demo.comuni)} label="comuni MVP" />
              <Tessera value={n(demo.record_totali)} label="record in archivio" />
              <Tessera value={n(demo.curato_nazionale)} label="record curati nazionali" />
            </div>
            <p className="status-row__meta">
              Statici, aggiornati a mano. Ultima ingestion:{" "}
              {formatDate(demo.aggiornato_il)}.
            </p>
          </div>
        </section>

        {/* 2 — Copertura nazionale */}
        <section className="systems__group">
          <div className="systems__group-head">
            <h2>Copertura nazionale</h2>
            <span className="systems__group-note">
              le mappe di servizio dal catalogo
            </span>
          </div>
          <div className="panel">
            <div className="tessere">
              <Tessera value={n(copertura.universo)} label="comuni italiani" />
              <Tessera value={n(copertura.catalogati)} label="catalogati" />
              <Tessera value={n(copertura.eleggibili)} label="eleggibili al refresh" />
            </div>
            <div className="tabella-scorrevole">
              <table>
                <caption>
                  Comuni catalogati per piattaforma. Solo le piattaforme con un
                  lettore di refresh dedicato sono eleggibili al refresh
                  continuo; le altre restano copertura statica.
                </caption>
                <thead>
                  <tr>
                    <th>Piattaforma</th>
                    <th>Comuni</th>
                    <th>Refresh</th>
                  </tr>
                </thead>
                <tbody>
                  {copertura.per_piattaforma.map((p) => (
                    <tr key={p.piattaforma}>
                      <th scope="row">{p.piattaforma}</th>
                      <td className="data-table__num">{n(p.comuni)}</td>
                      <td>{p.eleggibile ? "eleggibile" : "non eleggibile"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* 3 — Refresh operativo */}
        <section className="systems__group">
          <div className="systems__group-head">
            <h2>Refresh operativo</h2>
            <span className="systems__group-note">
              refresh continuo dei comuni già inizializzati
            </span>
          </div>
          <div className="panel">
            <div className="tessere">
              <Tessera value={n(refresh.inizializzati)} label="inizializzati / refreshabili" />
              <Tessera value={n(refresh.mai_inizializzati)} label="eleggibili mai inizializzati" />
              <Tessera value={n(refresh.eleggibili)} label="totale eleggibili" />
            </div>
            <p className="status-row__meta">
              Il refresh rilegge solo i comuni che hanno già un record connettore:
              è freschezza, non scoperta. Lo scarto fra <em>eleggibili</em> e{" "}
              <em>inizializzati</em> è la pipeline di ingresso ancora da
              completare, non uno sweep lento. Ultimo refresh:{" "}
              {formatDate(refresh.ultimo_refresh)}.
            </p>

            <ul className="status-list">
              <li className="status-row" data-stato={worker.state}>
                <span className="status-row__dot" aria-hidden="true" />
                <div className="status-row__body">
                  <div className="status-row__head">
                    <strong>Worker di refresh</strong>
                    <span className="status-row__badge">{worker.label}</span>
                  </div>
                  <p className="status-row__meta">
                    {batch ? (
                      <>
                        Ultimo batch: {n(batch.comuni)} comuni in{" "}
                        {batch.durata_s == null ? "—" : `${batch.durata_s.toLocaleString("it-IT")}s`}
                        {" · "}
                        riusciti {n(batch.riusciti)}, falliti {n(batch.falliti)},
                        senza contratto {n(batch.senza_contratto)}
                        {" · "}
                        eventi 429 {n(batch.eventi_429)}, circuiti aperti{" "}
                        {n(batch.domini_bloccati)}
                        {" · "}
                        registrato {formatDate(refresh.sidecar_aggiornato_il)}
                      </>
                    ) : (
                      "Nessuno stato operativo registrato: il worker non ha ancora scritto un batch."
                    )}
                  </p>
                </div>
              </li>
            </ul>
          </div>
        </section>

        {/* 4 — Sistemi */}
        <section className="systems__group">
          <div className="systems__group-head">
            <h2>Sistemi</h2>
            <span className="systems__group-note">
              le componenti di TreasureIQ stessa
            </span>
          </div>
          <div className="panel">
            <ul className="status-list">
              {sistemi.map((c) => (
                <ComponentRow key={c.nome} component={c} />
              ))}
            </ul>
          </div>
        </section>
      </div>

      <section className="panel">
        <h2>Perché tre livelli e non un numero solo</h2>
        <p className="lede">
          Un solo totale nasconde la differenza che conta. La demo curata dice
          quanto sappiamo fare in profondità su pochi comuni; la copertura
          nazionale dice su quanti comuni sappiamo almeno indirizzare i servizi;
          il refresh operativo dice per quanti di quelli teniamo il dato fresco.
          Sono misure diverse, e vanno lette come tali — la stessa onestà sui
          limiti dei dati che il resto del progetto applica ai requisiti dei
          bandi.
        </p>
      </section>
    </div>
  );
}
