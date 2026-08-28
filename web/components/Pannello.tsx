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
import MappaServizi from "@/components/MappaServizi";
import ProfiloNoto from "@/components/ProfiloNoto";
import ScanLive from "@/components/ScanLive";
import {
  fetchRecapitiComune,
  fetchRegistroComune,
  type RecapitiComune,
  type RegistroComune,
} from "@/lib/api";
import { useProfilo, type NumeriUtiliProfilo } from "@/lib/profilo";
import { useRisultati } from "@/lib/risultati";
import { dataLeggibile } from "@/lib/date";

const LIVELLO_LABEL: Record<string, string> = {
  comunale: "Comunale",
  regionale: "Regionale",
  nazionale: "Nazionale",
};

/** Una riga di recapito nella card comune: etichetta + valore linkato. Non
 * si rende se il valore manca (nessun campo vuoto spacciato per dato). */
function RigaRecapito({
  etichetta,
  valore,
  href,
}: {
  etichetta: string;
  valore: string;
  href: string;
}) {
  return (
    <div className="card-comune__riga">
      <dt>{etichetta}</dt>
      <dd>
        <a href={href}>{valore}</a>
      </dd>
    </div>
  );
}

/** Card unica del comune: logo (o monogramma civico neutro, mai uno stemma
 * finto — D-02) + nome, i riferimenti principali (telefono, PEC, indirizzo),
 * e sotto la nota su cosa è cambiato dall'ultima scansione.
 *
 * Due fonti, una card. Il registro locale (CONTRATTO-O2) dà logo, nome,
 * `cambiato` e i `recapiti` ufficiali IPA (PEC + indirizzo, statici, letti a
 * read-time — nessuna fetch al portale parte da qui, D-01/D-11). Il telefono
 * — che l'IPA non espone in modo affidabile — arriva dai `numeri` letti al
 * volo quando presenti. PEC preferisce la fonte IPA (autoritativa), ripiega
 * sul live. Registro assente (comune mai scansionato) degrada a glifo+nome
 * dal profilo più, se ci sono, i soli numeri live: mai un guscio rotto. */
function CardComune({
  istat,
  nome,
  numeri,
}: {
  istat: string;
  nome: string;
  numeri: NumeriUtiliProfilo | null;
}) {
  const [registro, setRegistro] = useState<RegistroComune | null>(null);
  // Recapiti IPA per un comune NON censito: il registro fa 404, ma PEC e
  // indirizzo istituzionali esistono comunque (indice IPA, per ISTAT). Senza
  // questo, la card di un comune fuori copertura mostrava solo il telefono
  // letto dal vivo — spesso sballato. Uniforma la card qualunque sia il
  // connettore (coperto o fuori copertura).
  const [recapitiIpa, setRecapitiIpa] = useState<RecapitiComune | null>(null);

  // Stessa guardia anti-stale delle altre fetch client-side del pannello
  // (v. `MappaServizi` in Chat.tsx): un cambio di comune azzera subito la
  // card e scarta la risposta della fetch precedente se arriva in ritardo.
  useEffect(() => {
    let vivo = true;
    setRegistro(null);
    setRecapitiIpa(null);
    if (!istat) return; // comune senza ISTAT (fuori copertura): solo numeri live
    fetchRegistroComune(istat)
      .then((r) => {
        if (!vivo) return;
        setRegistro(r);
        // Comune non censito: il registro è vuoto ma i recapiti IPA no.
        if (r === null) {
          fetchRecapitiComune(istat)
            .then((rec) => {
              if (vivo) setRecapitiIpa(rec);
            })
            .catch(() => {
              if (vivo) setRecapitiIpa(null);
            });
        }
      })
      .catch(() => {
        if (vivo) setRegistro(null);
      });
    return () => {
      vivo = false;
    };
  }, [istat]);

  const nomeMostrato = registro?.nome ?? nome;

  // Riferimenti: telefono dal live (IPA non ce l'ha), PEC e indirizzo
  // IPA-first (dal record se censito, dall'indice IPA se fuori copertura),
  // con fallback live per la PEC. Un solo valore per riga.
  const telefono = numeri?.telefoni?.[0] ?? null;
  const pec =
    registro?.recapiti?.pec ?? recapitiIpa?.pec ?? numeri?.pec?.[0] ?? null;
  const indirizzo =
    registro?.recapiti?.indirizzo ?? recapitiIpa?.indirizzo ?? null;
  // Codice Univoco IPA: identità dell'ente, non un recapito. Statico, dallo
  // stesso indice (elenco nazionale), quindi mostrato accanto agli altri
  // riferimenti IPA — anche per un comune che di PEC/indirizzo non ne ha.
  const codiceIpa =
    registro?.recapiti?.codice_ipa ?? recapitiIpa?.codice_ipa ?? null;
  const fonteRecapiti = registro?.recapiti?.fonte ?? recapitiIpa?.fonte ?? null;
  const haRecapiti = Boolean(telefono || pec || indirizzo || codiceIpa);

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

      {haRecapiti && (
        <dl className="card-comune__recapiti">
          {telefono && (
            <RigaRecapito
              etichetta="Telefono"
              valore={telefono}
              href={`tel:${telefono.replace(/\s+/g, "")}`}
            />
          )}
          {pec && (
            <RigaRecapito etichetta="PEC" valore={pec} href={`mailto:${pec}`} />
          )}
          {indirizzo && (
            <RigaRecapito
              etichetta="Indirizzo"
              valore={indirizzo}
              href={`https://www.openstreetmap.org/search?query=${encodeURIComponent(
                indirizzo,
              )}`}
            />
          )}
          {codiceIpa && (
            <div className="card-comune__riga">
              <dt>Codice IPA</dt>
              <dd>
                <code className="card-comune__codice">{codiceIpa}</code>
              </dd>
            </div>
          )}
        </dl>
      )}

      {fonteRecapiti && (pec || indirizzo || codiceIpa) && (
        <p className="card-comune__fonte">Riferimenti da {fonteRecapiti}.</p>
      )}

      {registro &&
        (registro.prima_scansione ? (
          <p className="card-comune__nota">
            Prima scansione il {dataLeggibile(registro.ultima_scansione)}, niente da
            confrontare.
          </p>
        ) : (
          registro.cambiato && (
            <p className="card-comune__nota card-comune__nota--cambiato">
              Cambiato dall&apos;ultima scansione ({dataLeggibile(
                registro.ultima_scansione,
              )}): {registro.cambiato.campi.join(", ")}.
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

      {(profilo.comune?.istat || numeri) && (
        <CardComune
          istat={profilo.comune?.istat ?? ""}
          nome={profilo.comune?.nome ?? numeri?.comune ?? ""}
          numeri={numeri}
        />
      )}

      {/* Servizi del comune (mappa AgID a cascata), spostati qui dalla chat per
          tenerla pulita. Si mostra solo se il portale è REST-indirizzabile:
          altrimenti MappaServizi non disegna nulla. */}
      {profilo.comune?.istat && (
        <MappaServizi istat={profilo.comune.istat} variante="pannello" />
      )}

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
