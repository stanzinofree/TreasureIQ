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
 */

import { readiness, type Readiness } from "@/lib/api";

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

export default async function DataQuality() {
  let report: Readiness | null = null;
  try {
    report = await readiness("058003");
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

  return (
    <div className="stack">
      <section>
        <p className="eyebrow">Pagella sulla qualità dei dati</p>
        <h1>{report.ente}</h1>
        <p className="lede">
          Quanto i dati pubblicati da questo comune sono utilizzabili da un
          motore come TreasureIQ. Il punteggio è calcolato solo da ciò che
          l&apos;ingestion ha effettivamente recuperato: nessun valore è
          assegnato a mano, quindi il confronto fra comuni ha significato.
        </p>
      </section>

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
            {report.score.toFixed(1)}
          </span>
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--sumi-faint)" }}>
            / 100 · qualità {report.grade} · {report.total_records} servizi
          </span>
        </div>

        <div style={{ marginTop: "var(--ma-8)" }}>
          {report.dimensions.map((d) => (
            <Dimension key={d.key} dimension={d} />
          ))}
        </div>
      </section>

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
    </div>
  );
}
