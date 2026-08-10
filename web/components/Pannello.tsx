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

import { useEffect, useState } from "react";
import ProfiloNoto from "@/components/ProfiloNoto";
import ScanLive from "@/components/ScanLive";
import { fetchRegistroComune, type RegistroComune } from "@/lib/api";
import { useProfilo, type NumeriUtiliProfilo } from "@/lib/profilo";
import { useRisultati } from "@/lib/risultati";

const LIVELLO_LABEL: Record<string, string> = {
  comunale: "Comunale",
  regionale: "Regionale",
  nazionale: "Nazionale",
};

/** Data del controllo, leggibile: «6 agosto 2026». Se l'ISO è illeggibile,
 * ripiega sulla stringa grezza — mai un «Invalid Date» a schermo. */
function dataLeggibile(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("it-IT", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/** I recapiti del comune fuori copertura, letti al volo dal portale. Non è una
 * risposta di TreasureIQ: è il biglietto da visita del comune, con fonte e data
 * del controllo dichiarate. Nessun numero è verificato. */
function NumeriUtiliBanner({ numeri }: { numeri: NumeriUtiliProfilo }) {
  return (
    <section className="numeri-utili" aria-label={`Numeri utili di ${numeri.comune}`}>
      <h3 className="numeri-utili__titolo">
        Comune di {numeri.comune} · numeri utili
      </h3>
      <dl className="numeri-utili__lista">
        {numeri.telefoni.map((t) => (
          <div className="numeri-utili__riga" key={`tel-${t}`}>
            <dt>Telefono</dt>
            <dd>
              <a href={`tel:${t.replace(/\s+/g, "")}`}>{t}</a>
            </dd>
          </div>
        ))}
        {numeri.pec.map((p) => (
          <div className="numeri-utili__riga" key={`pec-${p}`}>
            <dt>PEC</dt>
            <dd>
              <a href={`mailto:${p}`}>{p}</a>
            </dd>
          </div>
        ))}
        {numeri.email.map((e) => (
          <div className="numeri-utili__riga" key={`mail-${e}`}>
            <dt>Email</dt>
            <dd>
              <a href={`mailto:${e}`}>{e}</a>
            </dd>
          </div>
        ))}
      </dl>
      <p className="numeri-utili__nota">
        Ultimo controllo via {numeri.fonteTipo} il {dataLeggibile(numeri.lettoIl)}
        {" "}· da verificare tu.
      </p>
    </section>
  );
}

/** Card comune curata dal registro locale (CONTRATTO-O2): logo o, in sua
 * assenza, un monogramma civico neutro (mai uno stemma finto, D-02) + nome
 * + una nota minimale su cosa è cambiato dall'ultima scansione. Il logo
 * arriva già come base64 dal registro — nessuna fetch verso il portale del
 * comune parte da qui (D-01/D-11), solo la lettura dell'endpoint locale.
 * 404/registro assente degrada onestamente a glifo+nome dal profilo, mai a
 * un guscio rotto. */
function CardComuneRegistro({ istat, nome }: { istat: string; nome: string }) {
  const [registro, setRegistro] = useState<RegistroComune | null>(null);

  // Stessa guardia anti-stale delle altre fetch client-side del pannello
  // (v. `MappaServizi` in Chat.tsx): un cambio di comune azzera subito la
  // card e scarta la risposta della fetch precedente se arriva in ritardo.
  useEffect(() => {
    let vivo = true;
    setRegistro(null);
    fetchRegistroComune(istat)
      .then((r) => {
        if (vivo) setRegistro(r);
      })
      .catch(() => {
        if (vivo) setRegistro(null);
      });
    return () => {
      vivo = false;
    };
  }, [istat]);

  const nomeMostrato = registro?.nome ?? nome;

  return (
    <section className="card-comune tiq-card" aria-label={`Comune di ${nomeMostrato}`}>
      <div className="card-comune__testata">
        {registro?.logo_b64 ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={registro.logo_b64}
            alt={`Logo del Comune di ${nomeMostrato}`}
            className="card-comune__logo"
          />
        ) : (
          <span className="card-comune__glifo" aria-hidden>
            {nomeMostrato.trim().charAt(0).toUpperCase()}
          </span>
        )}
        <p className="card-comune__nome">Comune di {nomeMostrato}</p>
      </div>
      {registro &&
        (registro.prima_scansione ? (
          <p className="card-comune__nota">
            Prima scansione, niente da confrontare.
          </p>
        ) : (
          registro.cambiato && (
            <p className="card-comune__nota card-comune__nota--cambiato">
              Cambiato dall&apos;ultima scansione: {registro.cambiato.campi.join(", ")}.
            </p>
          )
        ))}
    </section>
  );
}

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
  const { quantiFatti, profilo } = useProfilo();

  const filtriAttivi = filtri.livelli.size + filtri.esiti.size > 0;

  // I numeri utili si mostrano solo se sono di QUESTO comune: portano il loro
  // ISTAT proprio per non restare in vista dopo un cambio di comune.
  const numeri =
    profilo.numeriUtili && profilo.numeriUtili.istat === profilo.comune?.istat
      ? profilo.numeriUtili
      : null;

  // Render nothing at all — not an empty column — until there is something to
  // put in it. The grid collapses to a single track when this element is
  // absent (see `.workspace:has(.pannello)`), so on arrival the conversation
  // gets the whole width and sits centred, instead of being pushed aside by a
  // panel holding nothing.
  if (quantiFatti === 0 && trovate.length === 0 && numeri === null) return null;

  return (
    <aside className="pannello" aria-label="Riepilogo della conversazione">
      <ProfiloNoto />

      {profilo.comune?.istat && (
        <a
          className="pannello__scheda-link"
          href={`/comune/${profilo.comune.istat}`}
        >
          Scheda del comune →
        </a>
      )}

      {/* Spia scan del comune (banda che lampeggia → bottone «Ricarica»), stesso
          stato mostrato in chat. Sta sotto la scheda perché lì si parla del
          comune. Non renderizza nulla se nessuno scan è in corso. */}
      <ScanLive variante="pannello" />

      {profilo.comune?.istat && (
        <CardComuneRegistro
          istat={profilo.comune.istat}
          nome={profilo.comune.nome}
        />
      )}

      {numeri && <NumeriUtiliBanner numeri={numeri} />}

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
