/**
 * "Within Albano" register (D-17/D-18, B16) — the one place on `/dati` where a
 * chart is honest, because N≈50 records actually supports a distribution.
 *
 * Reads `GET /api/recovery`, which rolls up the D-16 instrumentation each
 * ingestion run writes into the committed snapshots. This used to be a
 * transcribed constant, because no endpoint exposed per-record cost; it now
 * comes from the API so the chart cannot drift away from the seed behind it.
 *
 * The comparison across comuni is the point, and it only reads correctly if
 * two different zeroes stay apart:
 *
 *   typed      — the comune published it through its own structured `/servizi`
 *                API. Nothing had to be recovered, so the cost is really zero.
 *                Fonte Nuova is entirely this case: 34 typed servizi, no prose
 *                pages at all. That is the outcome the project argues for, and
 *                it should read as a win, not as an empty chart.
 *   recovered  — prose we had to open, read and quote-gate. Albano's ten
 *                `wp_pages` records. This is where the cost lives.
 *
 * A comune with nothing to recover therefore renders as a statement, not as a
 * bar of length zero — a zero-length bar would read as "fast", when the truth
 * is "there was no work to do".
 *
 * No chart library, no CDN: hand-rolled SVG-free HTML/CSS bars, per the
 * project's offline-build guarantee and the dataviz skill's mark specs.
 * Colour is never the only carrier — every bar is also labelled with its
 * recovery level in text, because L1 (amber) and L3 (vermilion) fail the
 * colourblind-safe separation check on this palette (validated: ΔE 9.0,
 * below the ≥8 target) and the project already leans on text + shape
 * everywhere else (see `Seal`, `.criterion__glyph`).
 */

import type { Recovery, RecordCost } from "@/lib/api";

export type RecoveryLevel = "L1_manuale" | "L2_estratto" | "L3_illeggibile";

const LEVEL_META: Record<
  RecoveryLevel,
  { label: string; swatchVar: string; short: string }
> = {
  L2_estratto: { label: "L2 · estratto da PDF", swatchVar: "var(--wakatake)", short: "L2" },
  L1_manuale: { label: "L1 · manuale", swatchVar: "var(--yamabuki)", short: "L1" },
  L3_illeggibile: { label: "L3 · illeggibile", swatchVar: "var(--shu)", short: "L3" },
};

const LEVEL_ORDER: RecoveryLevel[] = ["L2_estratto", "L1_manuale", "L3_illeggibile"];

function isKnownLevel(level: string | null): level is RecoveryLevel {
  return level !== null && level in LEVEL_META;
}

function formatSeconds(s: number): string {
  return s < 0.01 ? "<0,01 s" : `${s.toLocaleString("it-IT", { maximumFractionDigits: 1 })} s`;
}

/** One comune's block: the split bar, the per-record bars, and the table. */
function ComuneRecoveryBlock({ report }: { report: Recovery }) {
  const rows = report.records.filter((r) => isKnownLevel(r.recovery_level));
  const counts = LEVEL_ORDER.map((level) => ({
    level,
    n: report.levels[level] ?? 0,
  })).filter((c) => c.n > 0);
  const total = report.recovered_records;
  const max = Math.max(...rows.map((r) => r.extraction_seconds ?? 0), 0.001);

  return (
    <section style={{ marginTop: "var(--ma-4)" }}>
      <h4 className="field__label">{report.ente}</h4>

      <p className="field__hint">
        {report.typed_records} servizi già tipizzati dal comune — costo di recupero
        nullo, perché non c&apos;era nulla da estrarre.{" "}
        {total > 0
          ? `${total} pagine in prosa hanno invece richiesto estrazione.`
          : "Nessuna pagina in prosa da recuperare."}
        {report.unmeasured_records > 0
          ? ` ${report.unmeasured_records} record non misurati.`
          : ""}
      </p>

      {total === 0 ? (
        /* Not a chart. A comune that publishes everything structured has no
           distribution to draw, and drawing an empty one would invent a
           deficiency that isn't there. */
        <p className="field__hint">
          <strong style={{ fontWeight: 600 }}>Niente da recuperare.</strong> Tutto
          quello che {report.ente} pubblica passa dalla sua API dei servizi, già
          in forma leggibile da una macchina. È il caso migliore: il costo non
          ricade sul cittadino.
        </p>
      ) : (
        <>
          {/* Recovery split — L1/L2/L3, D-16's ladder. A stacked bar restates
              the same counts visually, but the counts in text are what
              actually carries the information (colour is redundant here). */}
          <div
            className="recovery-split"
            role="img"
            aria-label={counts
              .map((c) => `${LEVEL_META[c.level].label}: ${c.n} su ${total}`)
              .join(", ")}
          >
            <div className="recovery-split__bar">
              {counts.map(({ level, n }) => (
                <span
                  key={level}
                  className="recovery-split__segment"
                  style={{
                    width: `${(n / total) * 100}%`,
                    background: LEVEL_META[level].swatchVar,
                  }}
                  aria-hidden="true"
                />
              ))}
            </div>
            <ul className="recovery-split__legend">
              {counts.map(({ level, n }) => (
                <li key={level}>
                  <span
                    className="recovery-split__swatch"
                    style={{ background: LEVEL_META[level].swatchVar }}
                    aria-hidden="true"
                  />
                  {LEVEL_META[level].label}: <strong style={{ fontWeight: 600 }}>{n}</strong> su{" "}
                  {total}
                </li>
              ))}
            </ul>
          </div>

          {/* Cost per opportunity, sorted worst-first by the API — this doubles
              as "which bandi cost most to open": the ordering is the answer. */}
          <ol
            className="cost-chart"
            aria-label={`Secondi di estrazione per bando, ${report.ente}, dal più costoso`}
          >
            {rows.map((row) => {
              const level = row.recovery_level as RecoveryLevel;
              const seconds = row.extraction_seconds ?? 0;
              return (
                <li key={row.id} className="cost-chart__row">
                  <span className="cost-chart__label" title={row.title}>
                    {row.title}
                  </span>
                  <span className="cost-chart__track">
                    <span
                      className="cost-chart__bar"
                      style={{
                        width: `${Math.max(2, (seconds / max) * 100)}%`,
                        background: LEVEL_META[level].swatchVar,
                      }}
                    />
                  </span>
                  <span className="cost-chart__value">{formatSeconds(seconds)}</span>
                  <span className="cost-chart__badge">{LEVEL_META[level].short}</span>
                </li>
              );
            })}
          </ol>

          {/* Screen-reader / no-JS equivalent: the same numbers as a table. */}
          <table className="sr-only">
            <caption>Costo di estrazione per bando, {report.ente}</caption>
            <thead>
              <tr>
                <th scope="col">Bando o servizio</th>
                <th scope="col">Livello di recupero</th>
                <th scope="col">Secondi di estrazione</th>
                <th scope="col">PDF collegati</th>
                <th scope="col">PDF aperti</th>
                <th scope="col">Requisiti recuperati</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.title}</td>
                  <td>{LEVEL_META[row.recovery_level as RecoveryLevel].label}</td>
                  <td>{formatSeconds(row.extraction_seconds ?? 0)}</td>
                  <td>{row.pdfs_linked ?? "—"}</td>
                  <td>{row.pdfs_opened ?? "—"}</td>
                  <td>{row.requirements_recovered ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

export default function RecoveryCostChart({
  reports,
  measuredAt,
}: {
  reports: Recovery[];
  measuredAt: string;
}) {
  if (reports.length === 0) {
    return (
      <p className="field__hint">
        Costo di recupero non disponibile: nessuno snapshot leggibile.
      </p>
    );
  }

  // Comuni that actually paid a recovery cost first — the ones with a
  // distribution to show carry the section, and "nothing to recover" reads
  // better as the contrast that follows than as the opening.
  const ordered = [...reports].sort(
    (a, b) => b.recovered_records - a.recovered_records,
  );

  return (
    <div>
      {ordered.map((report) => (
        <ComuneRecoveryBlock key={report.codice_istat} report={report} />
      ))}

      <p className="field__hint" style={{ marginTop: "var(--ma-3)" }}>
        Misurato il {measuredAt}, dalle istantanee committate delle ultime
        ingestion — non una chiamata dal vivo ai comuni.
      </p>
    </div>
  );
}
