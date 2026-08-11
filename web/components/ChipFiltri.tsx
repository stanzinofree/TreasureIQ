"use client";

import type { FiltroChiave, FiltroOut } from "@/lib/api";

/** Etichette IT per ogni chiave dell'enum chiuso `FiltroChiave` (ciclo11,
 *  A7). Un `Record` esaustivo: se il backend aggiunge una chiave e il mirror
 *  TS non viene aggiornato, `tsc` segnala qui il buco invece di lasciare un
 *  chip senza etichetta a runtime. */
const ETICHETTA: Record<FiltroChiave, string> = {
  eta: "Età",
  isee: "ISEE",
  disabilita: "Disabilità",
  disabilita_nucleo: "Disabilità nel nucleo",
  nucleo_familiare: "Nucleo",
  figli_minori: "Figli minori",
  anziano: "Over 65",
  employment_status: "Situazione lavorativa",
  comune: "Comune",
  tema: "Tema",
};

function formattaValore(chiave: FiltroChiave, valore: FiltroOut["valore"]): string | null {
  if (typeof valore === "boolean") return valore ? null : "no";
  return String(valore);
}

/** Chip di un filtro riconosciuto nel messaggio (A7). Mostra la provenienza
 *  (`span.testo`, verbatim) quando c'e', e un bottone «×» quando il filtro e'
 *  davvero rimovibile con re-query (D-04).
 *
 *  Il chip `comune` NON si mostra qui (ciclo 15): collideva col badge verde del
 *  connettore — due marcatori per lo stesso fatto («questo comune») — e per
 *  giunta portava l'ISTAT grezzo (`110003`), illeggibile. L'identità del comune
 *  vive già nella card a sinistra (nome + logo) e la sua raggiungibilità nel
 *  BadgeConnettore: un solo posto per dirlo, come chiesto. Qui restano i soli
 *  filtri del cittadino (età, ISEE, tema…). */
export default function ChipFiltri({
  filtri,
  onRimuovi,
  disabled = false,
}: {
  filtri: FiltroOut[];
  onRimuovi: (chiave: FiltroChiave) => void;
  disabled?: boolean;
}) {
  // Fuori il chip comune prima del conteggio: se era l'unico filtro, la lista
  // non si disegna affatto (niente riga vuota sotto il messaggio).
  const daMostrare = filtri.filter((f) => f.chiave !== "comune");
  if (daMostrare.length === 0) return null;

  return (
    <div className="chip-filtri" role="list" aria-label="Filtri riconosciuti">
      {daMostrare.map((filtro, i) => {
        const rimovibile = filtro.chiave !== "comune";
        const dettaglio = formattaValore(filtro.chiave, filtro.valore);
        const provenienza = filtro.span?.testo ?? null;
        return (
          <span
            className="chip-filtri__voce"
            role="listitem"
            key={`${filtro.chiave}-${i}`}
            title={
              provenienza
                ? `rilevato da: "${provenienza}"`
                : filtro.sorgente === "profilo"
                  ? "dal profilo"
                  : "riconosciuto"
            }
          >
            <span className="chip-filtri__etichetta tiq-micro">
              {ETICHETTA[filtro.chiave]}
              {dettaglio ? `: ${dettaglio}` : ""}
              {filtro.negato ? " (negato)" : ""}
            </span>
            {!rimovibile && (
              <span className="chip-filtri__nota tiq-micro">riconosciuto</span>
            )}
            {rimovibile && (
              <button
                type="button"
                className="chip-filtri__rimuovi"
                onClick={() => onRimuovi(filtro.chiave)}
                disabled={disabled}
                aria-label={`Rimuovi filtro ${ETICHETTA[filtro.chiave]}`}
              >
                ×
              </button>
            )}
          </span>
        );
      })}
    </div>
  );
}
