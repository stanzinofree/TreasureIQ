"use client";

/**
 * The side column: what the service knows, how to narrow what it found, and
 * an index back into the transcript.
 *
 * Everything here is secondary to the chat by construction — it holds no
 * answer of its own. The index rows are links into the conversation, not
 * copies of it, so there is exactly one place where any verdict is stated.
 *
 * Sections appear only once they have something to say. A permanently visible
 * "0 risultati" panel would be furniture; an absent one is a fact.
 */

import ProfiloNoto from "@/components/ProfiloNoto";
import { useRisultati } from "@/lib/risultati";

const LIVELLO_LABEL: Record<string, string> = {
  comunale: "Comunale",
  regionale: "Regionale",
  nazionale: "Nazionale",
};

export default function Pannello() {
  const {
    trovate,
    filtrate,
    filtri,
    commutaLivello,
    commutaEsito,
    azzeraFiltri,
    livelliPresenti,
    esitiPresenti,
  } = useRisultati();

  const filtriAttivi = filtri.livelli.size + filtri.esiti.size > 0;

  return (
    <aside className="pannello" aria-label="Riepilogo della conversazione">
      <ProfiloNoto />

      {trovate.length > 0 && (
        <>
          {(livelliPresenti.length > 1 || esitiPresenti.length > 1) && (
            <section className="pannello__sez">
              <h2>
                Filtri
                {filtriAttivi && (
                  <button type="button" className="pannello__reset" onClick={azzeraFiltri}>
                    azzera
                  </button>
                )}
              </h2>

              {livelliPresenti.length > 1 && (
                <div className="pannello__gruppo">
                  {livelliPresenti.map((l) => (
                    <label key={l} className="pannello__check">
                      <input
                        type="checkbox"
                        checked={filtri.livelli.has(l)}
                        onChange={() => commutaLivello(l)}
                      />
                      <span>{LIVELLO_LABEL[l] ?? l}</span>
                    </label>
                  ))}
                </div>
              )}

              {esitiPresenti.length > 1 && (
                <div className="pannello__gruppo">
                  {esitiPresenti.map((e) => (
                    <label key={e.verdict} className="pannello__check">
                      <input
                        type="checkbox"
                        checked={filtri.esiti.has(e.verdict)}
                        onChange={() => commutaEsito(e.verdict)}
                      />
                      <span>{e.label}</span>
                    </label>
                  ))}
                </div>
              )}
            </section>
          )}

          <section className="pannello__sez">
            <h2>
              Trovate
              <span className="pannello__conta">
                {filtrate.length}
                {filtrate.length !== trovate.length && ` di ${trovate.length}`}
              </span>
            </h2>

            {filtrate.length === 0 ? (
              <p className="pannello__vuoto">
                Nessuna delle {trovate.length} corrisponde ai filtri.
              </p>
            ) : (
              <ul className="pannello__indice">
                {filtrate.map((t) => (
                  <li key={t.ancora}>
                    <a href={`#${t.ancora}`} data-verdict={t.verdict}>
                      <span className="pannello__titolo">{t.titolo}</span>
                      <span className="pannello__esito">{t.verdictLabel}</span>
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </aside>
  );
}
