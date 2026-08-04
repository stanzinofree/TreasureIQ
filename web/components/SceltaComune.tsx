"use client";

import { useEffect, useId, useRef, useState } from "react";
import { cercaComuni, type ComuneScelta } from "@/lib/api";

/**
 * Far scegliere il comune da un elenco, invece di dedurlo da una frase.
 *
 * Dedurlo costava caro in tre modi diversi, tutti visti sul serio: il modello
 * poteva nominare un comune che il cittadino non aveva scritto; «Castro» sono
 * due comuni in due regioni e sceglierne uno significa dare a metà di quelle
 * persone le informazioni dell'altra metà; e «San Marino» somiglia a Marino
 * abbastanza da diventarlo. Una scelta esplicita produce un `codice_istat`,
 * che non ha omonimi, non dipende da come è scritto il nome e non può essere
 * inventato.
 *
 * Zero risultati NON vuol dire «comune non coperto». L'elenco è ISTAT, cioè
 * tutti i comuni italiani: se non c'è, quel nome non è un comune — un refuso o
 * una frazione. Sono due frasi diverse e qui restano diverse.
 */
export default function SceltaComune({
  scelto,
  onScegli,
}: {
  scelto: ComuneScelta | null;
  onScegli: (comune: ComuneScelta | null) => void;
}) {
  const inputId = useId();
  const [testo, setTesto] = useState("");
  const [esiti, setEsiti] = useState<ComuneScelta[]>([]);
  const [cercando, setCercando] = useState(false);
  const [cercato, setCercato] = useState(false);
  const richiesta = useRef(0);

  useEffect(() => {
    const q = testo.trim();
    if (q.length < 2) {
      setEsiti([]);
      setCercato(false);
      return;
    }
    // Si aspetta che smetta di scrivere: una richiesta per tasto premuto
    // servirebbe solo a far arrivare le risposte in disordine.
    const attesa = setTimeout(async () => {
      const mia = ++richiesta.current;
      setCercando(true);
      try {
        const trovati = await cercaComuni(q);
        // Una risposta lenta di una query vecchia non deve sovrascrivere
        // quella della query che l'utente sta guardando adesso.
        if (mia === richiesta.current) {
          setEsiti(trovati);
          setCercato(true);
        }
      } catch {
        if (mia === richiesta.current) {
          setEsiti([]);
          setCercato(false);
        }
      } finally {
        if (mia === richiesta.current) setCercando(false);
      }
    }, 250);
    return () => clearTimeout(attesa);
  }, [testo]);

  if (scelto) {
    return (
      <div className="scelta-comune scelta-comune--fatta">
        <span className="scelta-comune__etichetta">Comune</span>
        <strong>
          {scelto.nome} ({scelto.provincia})
        </strong>
        {!scelto.ha_portale && (
          <span className="scelta-comune__senza-portale">
            di questo comune non conosciamo il portale
          </span>
        )}
        <button
          type="button"
          className="scelta-comune__cambia"
          onClick={() => {
            onScegli(null);
            setTesto("");
            setEsiti([]);
            setCercato(false);
          }}
        >
          cambia
        </button>
      </div>
    );
  }

  return (
    <div className="scelta-comune">
      <label htmlFor={inputId} className="scelta-comune__etichetta">
        Il tuo comune
      </label>
      <input
        id={inputId}
        type="text"
        autoComplete="off"
        placeholder="es. comune di Camposampiero"
        value={testo}
        onChange={(e) => setTesto(e.target.value)}
      />

      {cercando && <p className="scelta-comune__stato">cerco…</p>}

      {esiti.length > 0 && (
        <ul className="scelta-comune__esiti">
          {esiti.map((c) => (
            <li key={c.codice_istat}>
              <button type="button" onClick={() => onScegli(c)}>
                <span className="scelta-comune__nome">{c.nome}</span>
                <span className="scelta-comune__dove">
                  {c.provincia} · {c.regione}
                </span>
                {!c.ha_portale && (
                  <span className="scelta-comune__senza-portale">
                    portale sconosciuto
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      {cercato && !cercando && esiti.length === 0 && (
        <p className="scelta-comune__stato scelta-comune__stato--vuoto">
          Nessun comune italiano si chiama così. L&apos;elenco è quello ufficiale
          ISTAT, quindi non è un comune che ci manca: controlla il nome, oppure
          potrebbe essere una frazione — in quel caso cerca il comune che la
          comprende.
        </p>
      )}
    </div>
  );
}
