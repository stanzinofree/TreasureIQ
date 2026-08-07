"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { fetchSchedaComune, type ScanStato } from "@/lib/api";

/**
 * Stato «scansione live del comune» condiviso fra la chat e il pannello a
 * sinistra. Vive fuori dal transcript perché lo scan è una proprietà del
 * COMUNE, non del singolo messaggio: la banda che lampeggia e il bottone
 * «Ricarica» devono comparire negli stessi due posti (chat + sidebar) e
 * riflettere un unico stato, altrimenti si sfasano.
 *
 * Un SOLO poller vive qui: mentre lo scan gira in background (fire-and-forget
 * lato API), interroghiamo la scheda del comune finché `scansionato_il` cambia
 * — segno che il refresh ha riscritto il record. Allora `finito` diventa vero,
 * la banda smette di lampeggiare e cede il posto al bottone Ricarica. Cap a 12
 * tentativi (~48s): oltre, ci fermiamo comunque. Nessun secondo poller nei
 * consumatori: leggono `scan`/`finito` da qui.
 */
type ScanCtx = {
  scan: ScanStato | null;
  istat: string | null;
  /** Il refresh di background ha riscritto il record: dati aggiornati pronti. */
  finito: boolean;
  /** Bump per chiedere alla chat di rilanciare l'ultima domanda con i dati
   *  aggiornati. La chat osserva questo numero, non riceve una callback:
   *  così il rilancio usa la closure fresca di `send`, mai una stantia. */
  nonceRicarica: number;
  aggiornaScan: (
    scan: ScanStato | null | undefined,
    istat: string | null | undefined,
  ) => void;
  chiediRicarica: () => void;
};

const Ctx = createContext<ScanCtx | null>(null);

export function ScanProvider({ children }: { children: ReactNode }) {
  const [scan, setScan] = useState<ScanStato | null>(null);
  const [istat, setIstat] = useState<string | null>(null);
  const [finito, setFinito] = useState(false);
  const [nonceRicarica, setNonce] = useState(0);
  const baseline = useRef<string | null>(null);

  const aggiornaScan = useCallback(
    (s: ScanStato | null | undefined, i: string | null | undefined) => {
      setScan(s ?? null);
      setIstat(i ?? null);
      setFinito(false);
      baseline.current = null;
    },
    [],
  );

  const chiediRicarica = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const attivo = scan?.stato === "aggiornamento_in_corso";
    if (!attivo || !istat) return;
    baseline.current = null;
    let tentativi = 0;
    const timer = setInterval(async () => {
      tentativi += 1;
      try {
        const scheda = await fetchSchedaComune(istat);
        if (scheda) {
          if (baseline.current === null) {
            baseline.current = scheda.scansionato_il;
          } else if (scheda.scansionato_il !== baseline.current) {
            setFinito(true);
            clearInterval(timer);
            return;
          }
        }
      } catch {
        // Scheda non pronta o rete muta: si riprova al giro dopo, il cap chiude.
      }
      if (tentativi >= 12) {
        setFinito(true);
        clearInterval(timer);
      }
    }, 4000);
    return () => clearInterval(timer);
  }, [scan?.stato, istat]);

  return (
    <Ctx.Provider
      value={{ scan, istat, finito, nonceRicarica, aggiornaScan, chiediRicarica }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useScan(): ScanCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useScan fuori da ScanProvider");
  return c;
}
