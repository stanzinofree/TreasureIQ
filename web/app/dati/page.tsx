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
 *   - Across entities (N=4 + Regione Lazio) — a plain table, not a bar race.
 *     With three of the four comuni at zero, a leaderboard would read as
 *     padding, and padding is fatal for a project whose whole claim is
 *     honesty about data. So this is a table with a diagnosis column.
 *   - Within Albano (N≈50 records) — here a chart is honest, because the
 *     sample actually supports a distribution: cost per opportunity, the
 *     L1/L2/L3 recovery split, which bandi cost the most to open.
 */

import { readinessAll, recoveryAll, type Readiness, type Recovery } from "@/lib/api";
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

/** Comuni without a reachable service API at all, so there was nothing for
 * ingestion to score them from. Measured 2026-08-02 by direct probe (see
 * `.kapi/spec.md`, "Verified facts") — not exposed by any of the four
 * endpoints this page calls, so it is cited here as evidence with its
 * measurement date rather than presented as a live figure. The score is
 * genuinely zero, not merely unmeasured: each was actually checked. */
const ZERO_COMUNI: {
  ente: string;
  diagnosis: string;
}[] = [
  {
    ente: "Comune di Ariccia",
    diagnosis: "WordPress con REST disattivato di proposito — 410 su /wp-json e /it/wp-json.",
  },
  {
    ente: "Comune di Genzano di Roma",
    diagnosis: "Drupal + Halley Informatica; nessun endpoint /wp-json (404). Stesso fornitore di Ciampino, che espone altrettanto nulla — è un limite di piattaforma, non solo di questo comune.",
  },
  {
    ente: "Comune di Marino",
    diagnosis: "Il sito risponde 200 su ogni percorso, incluse le rotte API, ma è un redirect via JavaScript verso un altro dominio: dietro quel 200 non c'è nessun dato reale. Un monitoraggio ingenuo lo classificherebbe sano.",
  },
];

const EVIDENCE_MEASURED_AT = "2 agosto 2026";

function nationalCatalogueEvidence(r: Readiness): string | undefined {
  return r.dimensions.find((d) => d.key === "national_catalogue")?.evidence;
}

export default async function DataQuality() {
  let reports: Readiness[] = [];
  try {
    reports = await readinessAll();
  } catch {
    reports = [];
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
  const albano = reports.find((r) => r.codice_istat === "058003") ?? null;
  const fonteNuova = reports.find((r) => r.codice_istat === "058122") ?? null;

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
        <p className="eyebrow">Pagella sulla qualità dei dati</p>
        <h1>{albano?.ente ?? "Comune di Albano Laziale"}</h1>
        <p className="lede">
          Quanto i dati pubblicati da questo comune sono utilizzabili da un
          motore come TreasureIQ. Il punteggio è calcolato solo da ciò che
          l&apos;ingestion ha effettivamente recuperato: nessun valore è
          assegnato a mano, quindi il confronto fra comuni ha significato.
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
        <p className="eyebrow">Confronto fra enti</p>
        <h2>Non è una classifica — è una tabella, ed è onesta a riguardo</h2>
        <p className="lede">
          Con tre comuni su quattro a punteggio zero, un grafico a barre
          farebbe sembrare pieno quello che è vuoto. Qui sotto c&apos;è
          esattamente quello che è stato misurato, e come — nessuna barra
          disegnata dove non c&apos;è niente da misurare.
        </p>

        <div style={{ overflowX: "auto", marginTop: "var(--ma-6)" }}>
          <table className="data-table">
            <caption className="sr-only">
              Punteggio di qualità dei dati per ente, e diagnosi quando il
              punteggio è zero
            </caption>
            <thead>
              <tr>
                <th scope="col">Ente</th>
                <th scope="col">Punteggio</th>
                <th scope="col">Catalogo nazionale</th>
                <th scope="col">Diagnosi</th>
              </tr>
            </thead>
            <tbody>
              {albano && (
                <tr>
                  <th scope="row">{albano.ente}</th>
                  <td className="data-table__num">{albano.score.toFixed(1)} / 100</td>
                  <td>{nationalCatalogueEvidence(albano) ?? "—"}</td>
                  <td>Misurato in diretta — vedi la pagella sopra.</td>
                </tr>
              )}
              {fonteNuova && (
                <tr>
                  <th scope="row">{fonteNuova.ente}</th>
                  <td className="data-table__num">{fonteNuova.score.toFixed(1)} / 100</td>
                  <td>{nationalCatalogueEvidence(fonteNuova) ?? "—"}</td>
                  <td>
                    Comparatore scelto (D-18): stessa provincia, stessa
                    famiglia di piattaforma, più servizi esposti di Albano
                    (34 contro 32) e presente sul catalogo nazionale — eppure
                    non è detto che recuperi più requisiti utilizzabili.
                  </td>
                </tr>
              )}
              {ZERO_COMUNI.map((z) => (
                <tr key={z.ente} data-zero="true">
                  <th scope="row">{z.ente}</th>
                  <td className="data-table__num">0.0 / 100</td>
                  <td>nessun dataset su dati.gov.it</td>
                  <td>{z.diagnosis}</td>
                </tr>
              ))}
              <tr data-region="true">
                <th scope="row">Regione Lazio</th>
                <td className="data-table__num">non applicabile</td>
                <td>502 dataset su dati.gov.it</td>
                <td>
                  Non un comune: il livello dove la catena di apertura dei
                  dati smette di rompersi. Sotto il livello regionale, ogni
                  ente misurato in questa tabella è a zero dataset nazionali.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="field__hint" style={{ marginTop: "var(--ma-4)" }}>
          Ariccia, Genzano di Roma, Marino e Regione Lazio: misurati il{" "}
          {EVIDENCE_MEASURED_AT} per probe diretto e ricerca su dati.gov.it
          (dettagli in <code>.kapi/spec.md</code>), non da uno degli endpoint
          live di questa pagina — quei tre comuni non hanno mai avuto un&apos;API
          di servizio raggiungibile da cui ingerire nulla.
        </p>

        <p className="lede" style={{ marginTop: "var(--ma-6)" }}>
          Il quadro peggiora, non migliora, se si allarga lo sguardo: su 119
          comuni della provincia di Roma (rilevazione IndicePA, 2 agosto
          2026), solo <strong style={{ fontWeight: 600 }}>20 (16,8%)</strong>{" "}
          espongono un&apos;API di servizio funzionante. Albano Laziale è{" "}
          <strong style={{ fontWeight: 600 }}>secondo</strong> di questi 20,
          con 32 servizi, dietro Fonte Nuova con 34. Non è un comune scelto
          perché arretrato: è quasi il migliore della provincia, e ancora non
          riesce a dire a un cittadino se ha diritto a una casa popolare.
        </p>
      </section>

      {/* --------------------------------------------------- within Albano */}
      <section className="panel">
        <p className="eyebrow">Dentro i comuni misurati</p>
        <h2>Cosa costa davvero aprire un bando</h2>
        <p className="lede">
          Qui il campione regge un grafico: i bandi, avvisi e contributi
          recuperati da testo libero e allegati PDF, con il tempo di calcolo
          speso a estrarne i requisiti e il livello della scala di recupero
          (D-16) su cui ciascuno è atterrato. Il confronto fra i due comuni
          misurati è la parte interessante: Fonte Nuova non compare con un
          grafico vuoto, ma con un costo che non esiste, perché pubblica tutto
          già strutturato.
        </p>
        <div style={{ marginTop: "var(--ma-6)" }}>
          <RecoveryCostChart reports={recoveryReports} measuredAt={EVIDENCE_MEASURED_AT} />
        </div>
      </section>
    </div>
  );
}
