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
 *  Il chip `comune` non porta mai il bottone: `ChatOut.filtri` lo riporta come
 *  eco INFORMATIVA di cosa il testo nomina, non del comune usato per il
 *  routing (oggi `_resolve_comune` resta ristretto al profilo/ISTAT scelto).
 *  Renderlo rimovibile-con-re-query lascerebbe credere che togliendolo cambi
 *  il comune cercato — falso. Un chip senza «×», marcato "riconosciuto", dice
 *  la cosa vera senza doverla spiegare ogni volta. */
export default function ChipFiltri({
  filtri,
  onRimuovi,
  disabled = false,
}: {
  filtri: FiltroOut[];
  onRimuovi: (chiave: FiltroChiave) => void;
  disabled?: boolean;
}) {
  if (filtri.length === 0) return null;

  return (
    <div className="chip-filtri" role="list" aria-label="Filtri riconosciuti">
      {filtri.map((filtro, i) => {
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
            <span className="chip-filtri__etichetta">
              {ETICHETTA[filtro.chiave]}
              {dettaglio ? `: ${dettaglio}` : ""}
              {filtro.negato ? " (negato)" : ""}
            </span>
            {!rimovibile && (
              <span className="chip-filtri__nota">riconosciuto</span>
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
