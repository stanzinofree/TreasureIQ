"use client";

import { useScan } from "@/lib/scan";
import { dataBreve } from "@/lib/date";

/**
 * La spia «scansione live» del comune, in due punti (chat e pannello) con lo
 * STESSO stato letto da {@link useScan}. Tre esiti:
 *   - nessuno scan in corso → non renderizza nulla;
 *   - scan in corso, non finito → banda gialla che lampeggia («sto leggendo…»);
 *   - scan finito → bottone «Ricarica con dati aggiornati» che rilancia
 *     l'ultima domanda con i dati appena letti (la chat ascolta `nonceRicarica`).
 *
 * `variante` cambia solo la cornice (nel flusso chat vs. incassata nel pannello
 * a sinistra), non la logica.
 */
export default function ScanLive({
  variante,
}: {
  variante: "chat" | "pannello";
}) {
  const { scan, finito, chiediRicarica } = useScan();

  if (scan?.stato !== "aggiornamento_in_corso") return null;

  const cls = `scan-live scan-live--${variante}`;

  if (!finito) {
    return (
      <p className={`${cls} scan-refresh`} role="status" aria-live="polite">
        <span className="scan-refresh__pulse" aria-hidden />
        {/* Copy neutra sulla fonte: un comune coperto risponde dai dati
            ingeriti, non dallo scrape live — «aggiornando i dati» vale in
            entrambi i casi, «dal sito» avrebbe mentito sui coperti. */}
        Sto aggiornando i dati del comune
        {scan.ultimo_scan && (
          <span className="scan-refresh__data"> · ultimo aggiornamento {dataBreve(scan.ultimo_scan)}</span>
        )}
        …
      </p>
    );
  }

  return (
    <div className={cls}>
      <button type="button" className="scan-ricarica" onClick={chiediRicarica}>
        <span className="scan-ricarica__icona" aria-hidden>
          ↻
        </span>
        Ricarica con dati aggiornati
      </button>
    </div>
  );
}
