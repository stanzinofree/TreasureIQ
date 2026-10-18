/**
 * The Data Readiness page — the argument aimed at public administrations.
 *
 * Rendered on the server: the score is public information about a comune, not
 * about a person, so there is no session to wait for and no reason to make the
 * reader watch a spinner.
 *
 * The page is written to be read by someone who works at the comune. Each gap
 * ends in a specific action against a field that already exists in the theme
 * they already run, because "your open data is bad" changes nothing and "this
 * named field is empty on 31 of your 32 services" is a ticket someone can pick
 * up on Monday.
 *
 * Two statistics registers live below the score panel (B16, spec D-17/D-18),
 * and they are never mixed:
 *
 *   - Across entities (N=2) — only the deliberately matched Albano/Fonte
 *     Nuova pair. Other observations remain documented cases, not a ranking.
 *   - Within Albano (N≈50 records) — here a chart is honest, because the
 *     sample actually supports a distribution: cost per opportunity, the
 *     L1/L2/L3 recovery split, which bandi cost the most to open.
 */

import {
  readinessAll,
  recoveryAll,
  integrationAll,
  costi,
  type Readiness,
  type Recovery,
  type Integration,
  type Costo,
} from "@/lib/api";
import ChiediApertura from "@/components/ChiediApertura";
import CostoTable from "@/components/CostoTable";
import RecoveryCostChart from "@/components/RecoveryCostChart";

export const dynamic = "force-dynamic";

// Takes the whole record rather than spread props: the domain object has its
// own `key` field, which would collide with React's reserved `key` prop if
// spread at the call site.
function Dimension({ dimension }: { dimension: Readiness["dimensions"][number] }) {
  const { label, earned, weight, evidence, remedy } = dimension;
  const pct = weight ? Math.round((earned / weight) * 100) : 0;
  return (
    <div className="dimension">
      <span className="dimension__label">{label}</span>
      <span className="dimension__score">
        {earned.toFixed(1)} / {weight}
      </span>
      <div
        className="meter"
        role="meter"
        aria-valuenow={earned}
        aria-valuemin={0}
        aria-valuemax={weight}
        aria-label={label}
      >
        <div className="meter__fill" style={{ width: `${pct}%` }} />
      </div>
      <p className="dimension__evidence">{evidence}</p>
      {remedy && <p className="dimension__remedy">{remedy}</p>}
    </div>
  );
}

const EVIDENCE_MEASURED_AT = "2 agosto 2026";

function nationalCatalogueEvidence(r: Readiness): string | undefined {
  return r.dimensions.find((d) => d.key === "national_catalogue")?.evidence;
}

/** D-21 access-mode + integration-cost cell — mode, label and the dated
 * probe it came from, rendered exactly as `/api/integration` returns them
 * (never re-authored client-side, D-24). `datasets_on_dati_gov` is `null`
 * where it was never probed (Marino) and reads "non misurato": collapsing
 * that into "0" would be the same conflation this project exists to fight. */
function AccessCell({ integration }: { integration: Integration | undefined }) {
  if (!integration) {
    return <span className="field__hint">non misurato</span>;
  }
  const { label, access_mode, probe_dated, probe_method, datasets_on_dati_gov } = integration;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--ma-1)" }}>
      <span>
        <strong style={{ fontWeight: 600 }}>{label}</strong> ({access_mode})
      </span>
      <span className="field__hint">
        misurato il {probe_dated} — {probe_method}
      </span>
      <span className="field__hint">
        dataset su dati.gov.it:{" "}
        {datasets_on_dati_gov === null ? "non misurato" : datasets_on_dati_gov}
      </span>
    </div>
  );
}

export default async function DataQuality() {
  let reports: Readiness[] = [];
  try {
    reports = await readinessAll();
  } catch {
    reports = [];
  }

  // Same fail-soft shape as everything else on this page: the integration
  // cost is worth showing when it is there, and never worth taking the
  // readiness tables down for.
  let costiReports: Costo[] = [];
  try {
    costiReports = await costi();
  } catch {
    costiReports = [];
  }

  // Recovery cost is a separate call so a failure here costs only the one
  // chart: the readiness tables above it are the page's spine and must still
  // render if the recovery roll-up is unavailable.
  let recoveryReports: Recovery[] = [];
  try {
    recoveryReports = await recoveryAll();
  } catch {
    recoveryReports = [];
  }

  // Same fail-soft shape as recovery above: a failure here must not take
  // down the readiness table, it just leaves the new column blank.
  let integrationReports: Integration[] = [];
  try {
    integrationReports = await integrationAll();
  } catch {
    integrationReports = [];
  }
  const integrationFor = (istat: string) =>
    integrationReports.find((i) => i.codice_istat === istat);
  const albano = reports.find((r) => r.codice_istat === "058003") ?? null;
  const fonteNuova = reports.find((r) => r.codice_istat === "058122") ?? null;
  const casiConfrontabili = [albano, fonteNuova].filter((r): r is Readiness => r !== null);

  if (reports.length === 0) {
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

  return (
    <div className="stack">
      <section>
        <p className="eyebrow">Casi misurati sulla qualità dei dati</p>
        <h1>{albano?.ente ?? "Comune di Albano Laziale"}</h1>
        <p className="lede">
          Quanto i dati pubblicati da questo comune sono utilizzabili da un
          motore come TreasureIQ. Il punteggio è calcolato solo da ciò che
          l&apos;ingestion ha effettivamente recuperato: nessun valore è
          assegnato a mano. Un confronto è mostrato solo quando i casi sono
          stati misurati con lo stesso perimetro.
        </p>
      </section>

      {albano && (
        <section className="panel">
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: "var(--ma-4)",
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-display)",
                fontSize: "clamp(3rem, 9vw, 5rem)",
                fontWeight: 700,
                lineHeight: 1,
                color: "var(--ai)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {albano.score.toFixed(1)}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--sumi-faint)" }}>
              / 100 · qualità {albano.grade} · {albano.total_records} servizi
            </span>
          </div>

          <div style={{ marginTop: "var(--ma-8)" }}>
            {albano.dimensions.map((d) => (
              <Dimension key={d.key} dimension={d} />
            ))}
          </div>
        </section>
      )}

      <section className="panel">
        <h2>Non stiamo proponendo un nuovo standard</h2>
        <p className="lede">
          Il tema Design Comuni Italia, che questo comune già utilizza, prevede
          un campo per i requisiti di accesso ai servizi. Il campo esiste su
          tutti e 32 i servizi pubblicati ed è compilato su uno. Il divario non
          si chiude adottando una specifica nuova: si chiude compilando un campo
          che è già lì.
        </p>
        <p className="lede">
          Resta un limite del modello stesso: quel campo è testo libero, quindi
          anche compilato bene richiede un&apos;interpretazione automatica prima
          di poterci fare un incrocio. Servono campi tipizzati — soglia ISEE,
          età, nucleo — accanto alla descrizione discorsiva.
        </p>
      </section>

      {/* ------------------------------------------------- across entities */}
      <section className="panel">
        <p className="eyebrow">Confronto controllato</p>
        <h2>Due comuni confrontabili, non una classifica nazionale</h2>
        <p className="lede">
          Albano Laziale e Fonte Nuova condividono provincia, famiglia di
          piattaforma e una quantità di servizi simile. Il confronto serve a
          capire cosa cambia nel dato, non a ordinare enti con misure diverse.
        </p>

        <div style={{ overflowX: "auto", marginTop: "var(--ma-6)" }}>
          <table className="data-table">
            <caption className="sr-only">
              Punteggio di qualità dei dati per i due comuni misurati nello
              stesso perimetro
            </caption>
            <thead>
              <tr>
                <th scope="col">Ente</th>
                <th scope="col">Punteggio</th>
                <th scope="col">Catalogo nazionale</th>
                <th scope="col">Diagnosi</th>
                <th scope="col">Accesso e costo di integrazione (D-21)</th>
              </tr>
            </thead>
            <tbody>
              {casiConfrontabili.map((caso) => (
                <tr key={caso.codice_istat}>
                  <th scope="row">{caso.ente}</th>
                  <td className="data-table__num">{caso.score.toFixed(1)} / 100</td>
                  <td>{nationalCatalogueEvidence(caso) ?? "—"}</td>
                  <td>
                    {caso.codice_istat === "058003"
                      ? "Caso base: misurato in diretta nella pagella sopra."
                      : "Comparatore: stesso perimetro di misura, 34 servizi contro 32."}
                  </td>
                  <td>
                    <AccessCell integration={integrationFor(caso.codice_istat)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="field__hint" style={{ marginTop: "var(--ma-4)" }}>
          Altre osservazioni storiche sono documentate nel repository, ma non
          entrano qui perché non condividono questo stesso perimetro di misura.
        </p>
      </section>

      {/* --------------------------------------------------- within Albano */}
      <section className="panel">
        <p className="eyebrow">Costo per TreasureIQ</p>
        <h2>Come cambia il lavoro per rendere un dato leggibile</h2>
        <p className="lede">
          La scala di accesso spiega il costo in generale: un campo tipizzato
          si legge direttamente; prosa e allegati richiedono estrazione; un
          connettore dedicato richiede manutenzione. I valori sotto sono casi
          verificati e datati, incluso Ariccia come esempio di percorso M4 —
          non prezzi correnti né una classifica di comuni.
        </p>
        <div style={{ marginTop: "var(--ma-6)" }}>
          <RecoveryCostChart reports={recoveryReports} measuredAt={EVIDENCE_MEASURED_AT} />
          <CostoTable costi={costiReports} />
          <ChiediApertura enti={integrationReports} />
        </div>
      </section>
    </div>
  );
}
