/**
 * "Within Albano" register (D-17/D-18, B16) — the one place on `/dati` where a
 * chart is honest, because N≈50 records actually supports a distribution.
 *
 * The ten rows below are Albano's prose pages (bandi, avvisi, contributi)
 * that went through the quote-gated PDF extractor — the only records in the
 * seed carrying D-16 recovery instrumentation. None of the four endpoints
 * this page is allowed to call (`/api/stats`, `/api/status`,
 * `/api/readiness[/{istat}]`) expose per-record cost, so this dataset is
 * committed evidence read from `data/seed/albano_058003.json` at the last
 * ingestion run, the same way the province survey is committed evidence —
 * marked with its measurement date rather than presented as live.
 *
 * No chart library, no CDN: hand-rolled SVG-free HTML/CSS bars, per the
 * project's offline-build guarantee and the dataviz skill's mark specs.
 * Colour is never the only carrier — every bar is also labelled with its
 * recovery level in text, because L1 (amber) and L3 (vermilion) fail the
 * colourblind-safe separation check on this palette (validated: ΔE 9.0,
 * below the ≥8 target) and the project already leans on text + shape
 * everywhere else (see `Seal`, `.criterion__glyph`).
 */

export type RecoveryLevel = "L1_manuale" | "L2_estratto" | "L3_illeggibile";

export interface RecoveryCostRow {
  title: string;
  kind: string;
  level: RecoveryLevel;
  seconds: number;
  pdfsLinked: number;
  pdfsOpened: number;
  requirementsRecovered: number;
}

const LEVEL_META: Record<
  RecoveryLevel,
  { label: string; swatchVar: string; short: string }
> = {
  L2_estratto: { label: "L2 · estratto da PDF", swatchVar: "var(--wakatake)", short: "L2" },
  L1_manuale: { label: "L1 · manuale", swatchVar: "var(--yamabuki)", short: "L1" },
  L3_illeggibile: { label: "L3 · illeggibile", swatchVar: "var(--shu)", short: "L3" },
};

const LEVEL_ORDER: RecoveryLevel[] = ["L2_estratto", "L1_manuale", "L3_illeggibile"];

/** Measured 2026-08-02, from the committed ingestion snapshot
 * (`data/seed/albano_058003.json`): the ten `wp_pages` records — bandi,
 * avvisi and contributi recovered from prose, as opposed to the 32 `servizi`
 * records ingested from the structured API, which carry no recovery cost
 * because nothing had to be extracted from them. */
export const ALBANO_RECOVERY_ROWS: RecoveryCostRow[] = [
  { title: "IMU – Anni 2012-2013-2014", kind: "servizio", level: "L2_estratto", seconds: 8.6216, pdfsLinked: 14, pdfsOpened: 5, requirementsRecovered: 1 },
  { title: "Raccolta differenziata", kind: "servizio", level: "L1_manuale", seconds: 7.1730, pdfsLinked: 11, pdfsOpened: 5, requirementsRecovered: 0 },
  { title: "Edilizia Residenziale Pubblica (Case popolari)", kind: "bando", level: "L2_estratto", seconds: 4.7598, pdfsLinked: 19, pdfsOpened: 5, requirementsRecovered: 2 },
  { title: "Servizio Mensa", kind: "contributo_economico", level: "L2_estratto", seconds: 3.8094, pdfsLinked: 12, pdfsOpened: 5, requirementsRecovered: 2 },
  { title: "Centrale Unica di Committenza dei Comune di Albano Laziale, Castel Gandolfo e Grottaferrata", kind: "bando", level: "L1_manuale", seconds: 2.6515, pdfsLinked: 5, pdfsOpened: 4, requirementsRecovered: 0 },
  { title: "Modulistica – Manutenzioni", kind: "contributo_economico", level: "L2_estratto", seconds: 2.6217, pdfsLinked: 9, pdfsOpened: 5, requirementsRecovered: 1 },
  { title: "Progetti per la scuola", kind: "bando", level: "L1_manuale", seconds: 1.4251, pdfsLinked: 8, pdfsOpened: 5, requirementsRecovered: 0 },
  { title: "Statistica", kind: "bando", level: "L1_manuale", seconds: 0.6899, pdfsLinked: 2, pdfsOpened: 1, requirementsRecovered: 0 },
  { title: "Modulistica – Patrimonio", kind: "servizio", level: "L1_manuale", seconds: 0.5763, pdfsLinked: 2, pdfsOpened: 2, requirementsRecovered: 0 },
  { title: "Area Assistenza e Integrazione", kind: "contributo_economico", level: "L1_manuale", seconds: 0.0002, pdfsLinked: 0, pdfsOpened: 0, requirementsRecovered: 0 },
];

function formatSeconds(s: number): string {
  return s < 0.01 ? "<0,01 s" : `${s.toLocaleString("it-IT", { maximumFractionDigits: 1 })} s`;
}

export default function RecoveryCostChart({
  rows,
  measuredAt,
}: {
  rows: RecoveryCostRow[];
  measuredAt: string;
}) {
  const sorted = [...rows].sort((a, b) => b.seconds - a.seconds);
  const max = Math.max(...rows.map((r) => r.seconds), 0.001);
  const counts = LEVEL_ORDER.map((level) => ({
    level,
    n: rows.filter((r) => r.level === level).length,
  }));
  const total = rows.length;

  return (
    <div>
      {/* Recovery split — L1/L2/L3, D-16's ladder. A stacked bar restates
          the same three counts visually, but the counts in text are what
          actually carries the information (colour is redundant here). */}
      <div className="recovery-split" role="img" aria-label={
        counts.map((c) => `${LEVEL_META[c.level].label}: ${c.n} su ${total}`).join(", ")
      }>
        <div className="recovery-split__bar">
          {counts.map(({ level, n }) =>
            n > 0 ? (
              <span
                key={level}
                className="recovery-split__segment"
                style={{ width: `${(n / total) * 100}%`, background: LEVEL_META[level].swatchVar }}
                aria-hidden="true"
              />
            ) : null,
          )}
        </div>
        <ul className="recovery-split__legend">
          {counts.map(({ level, n }) => (
            <li key={level}>
              <span
                className="recovery-split__swatch"
                style={{ background: LEVEL_META[level].swatchVar }}
                aria-hidden="true"
              />
              {LEVEL_META[level].label}: <strong style={{ fontWeight: 600 }}>{n}</strong> su {total}
            </li>
          ))}
        </ul>
      </div>

      {/* Cost per opportunity, sorted worst-first — this doubles as "which
          bandi cost most to open": the ordering is the answer. */}
      <ol className="cost-chart" aria-label="Secondi di estrazione per bando, dal più costoso">
        {sorted.map((row) => (
          <li key={row.title} className="cost-chart__row">
            <span className="cost-chart__label" title={row.title}>
              {row.title}
            </span>
            <span className="cost-chart__track">
              <span
                className="cost-chart__bar"
                style={{
                  width: `${Math.max(2, (row.seconds / max) * 100)}%`,
                  background: LEVEL_META[row.level].swatchVar,
                }}
              />
            </span>
            <span className="cost-chart__value">{formatSeconds(row.seconds)}</span>
            <span className="cost-chart__badge">{LEVEL_META[row.level].short}</span>
          </li>
        ))}
      </ol>

      <p className="field__hint" style={{ marginTop: "var(--ma-3)" }}>
        Misurato il {measuredAt}, dall&apos;ultima ingestion di Albano Laziale —
        instantanea committata, non una chiamata dal vivo.
      </p>

      {/* Screen-reader / no-JS equivalent: the same ten numbers as a table. */}
      <table className="sr-only">
        <caption>Costo di estrazione per bando, Albano Laziale, misurato il {measuredAt}</caption>
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
          {sorted.map((row) => (
            <tr key={row.title}>
              <td>{row.title}</td>
              <td>{LEVEL_META[row.level].label}</td>
              <td>{formatSeconds(row.seconds)}</td>
              <td>{row.pdfsLinked}</td>
              <td>{row.pdfsOpened}</td>
              <td>{row.requirementsRecovered}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
