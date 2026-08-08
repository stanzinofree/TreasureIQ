"use client";

/**
 * B5 (ciclo 10) — quello che il connettore ha letto ORA dal portale del
 * comune (contratto D-09, `EsitoConnettore`): uffici coi recapiti verbatim,
 * e i bandi di Amministrazione Trasparente con l'analisi PDF su richiesta
 * (D-11). Non è uno snapshot ingerito — l'etichetta «letto ora» + `letto_il`
 * lo dice sempre, stesso registro delle altre card lette dal vivo
 * (`.mappa-servizi__scheda`, `.bandi-comune`): barra sinistra ambra, mai un
 * verdetto.
 *
 * Degrado onesto (D-05): un ufficio senza un recapito mostra la riga «non
 * pubblicato», mai un campo saltato in silenzio. Nessun ufficio e nessuna
 * Amministrazione Trasparente → la card non appare affatto (non un guscio
 * vuoto).
 */

import { useState } from "react";
import {
  postAtAnalisi,
  type AtAnalisiEsito,
  type EsitoConnettore,
  type UfficioConnettore,
} from "@/lib/api";

/** `pagina` va mostrato così com'è (D-07, number-guard): nessuna
 *  ricalcolo/offset, il numero è quello che il backend ha già letto. */
function etichettaPagina(pagina: number | null): string | null {
  return pagina == null ? null : `pag. ${pagina}`;
}

function dataLeggibile(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("it-IT", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/** Una riga di recapito, o la sua assenza dichiarata — mai un campo che
 *  sparisce senza dirlo (D-05). */
function RigaRecapito({
  etichetta,
  valori,
  href,
}: {
  etichetta: string;
  valori: string[];
  href: (v: string) => string;
}) {
  return (
    <div className="scheda-letto-ora__riga">
      <dt>{etichetta}</dt>
      {valori.length > 0 ? (
        <dd>
          {valori.map((v) => (
            <a key={v} href={href(v)} className="scheda-letto-ora__link">
              {v}
            </a>
          ))}
        </dd>
      ) : (
        <dd className="scheda-letto-ora__assente">non pubblicato per questo ufficio</dd>
      )}
    </div>
  );
}

function UfficioCard({ ufficio }: { ufficio: UfficioConnettore }) {
  return (
    <li className="scheda-letto-ora__ufficio">
      <a
        className="scheda-letto-ora__ufficio-nome"
        href={ufficio.url}
        target="_blank"
        rel="noopener noreferrer"
      >
        {ufficio.nome}
      </a>
      <dl className="scheda-letto-ora__lista">
        <RigaRecapito
          etichetta="Telefono"
          valori={ufficio.telefoni}
          href={(t) => `tel:${t.replace(/\s+/g, "")}`}
        />
        <RigaRecapito
          etichetta="Email"
          valori={ufficio.email}
          href={(e) => `mailto:${e}`}
        />
        <RigaRecapito etichetta="PEC" valori={ufficio.pec} href={(p) => `mailto:${p}`} />
        <div className="scheda-letto-ora__riga">
          <dt>Orari</dt>
          <dd>
            {ufficio.orari ? (
              ufficio.orari
            ) : (
              <span className="scheda-letto-ora__assente">non pubblicato per questo ufficio</span>
            )}
          </dd>
        </div>
      </dl>
      <span className="scheda-letto-ora__provenienza">
        {ufficio.source_typed ? "recapito tipizzato dal portale" : "recapito letto in prosa"}
        {" · "}letto il {dataLeggibile(ufficio.letto_il)}
      </span>
    </li>
  );
}

/** Un bando dell'indice Amministrazione Trasparente, con il bottone di
 *  analisi PDF on-demand (D-11): niente analisi automatica di massa, parte
 *  solo se il cittadino la chiede, con stato onesto durante l'attesa. */
function BandoRow({
  codiceIstat,
  titolo,
  url,
  pdfUrl,
}: {
  codiceIstat: string;
  titolo: string;
  url: string;
  pdfUrl: string | null;
}) {
  const [stato, setStato] = useState<"idle" | "carico" | "pronto" | "errore">("idle");
  const [esito, setEsito] = useState<AtAnalisiEsito | null>(null);

  function analizza() {
    if (!pdfUrl) return;
    setStato("carico");
    setEsito(null);
    postAtAnalisi(codiceIstat, pdfUrl)
      .then((e) => {
        setEsito(e);
        setStato("pronto");
      })
      .catch(() => setStato("errore"));
  }

  return (
    <li className="scheda-letto-ora__bando">
      <a
        className="scheda-letto-ora__link"
        href={url}
        target="_blank"
        rel="noopener noreferrer"
      >
        {titolo}
      </a>
      {pdfUrl && (
        <span className="scheda-letto-ora__pdf-flag" title={pdfUrl}>
          PDF collegato
        </span>
      )}
      {pdfUrl && stato === "idle" && (
        <button type="button" className="scheda-letto-ora__analizza" onClick={analizza}>
          Analizza i PDF
        </button>
      )}
      {stato === "carico" && (
        <p className="scheda-letto-ora__carico" role="status">
          Leggo il PDF…
        </p>
      )}
      {stato === "errore" && (
        <p className="scheda-letto-ora__errore" role="alert">
          Non sono riuscito a leggere il PDF adesso: apri il documento dal link sopra.
        </p>
      )}
      {stato === "pronto" && esito && (
        <div className="scheda-letto-ora__esito-pdf">
          {esito.segmenti.length > 0 && (
            <ul className="scheda-letto-ora__requisiti">
              {esito.segmenti.map((s, i) => (
                <li key={i}>
                  {s.kind && <span className="scheda-letto-ora__segmento-kind">{s.kind}</span>}
                  {etichettaPagina(s.pagina) && (
                    <span className="scheda-letto-ora__segmento-pagina">
                      {" "}
                      ({etichettaPagina(s.pagina)})
                    </span>
                  )}
                  <p className="scheda-letto-ora__segmento-testo">{s.testo}</p>
                </li>
              ))}
            </ul>
          )}
          {esito.note.length > 0 && (
            <ul className="scheda-letto-ora__note">
              {esito.note.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

export default function SchedaLettoOra({ esito }: { esito: EsitoConnettore }) {
  const haUffici = esito.uffici.length > 0;
  const at = esito.amministrazione_trasparente;
  const haBandi = !!at && at.bandi_attivi.length > 0;

  // Degrado onesto (D-05): nessun ufficio e nessuna AT con qualcosa da
  // mostrare → nessun guscio vuoto sotto la risposta.
  if (!haUffici && !haBandi && !(at && at.pdf_presenti)) return null;

  return (
    <div className="scheda-letto-ora" role="group" aria-label="Letto ora dal portale del comune">
      <p className="scheda-letto-ora__provenienza-testa">
        Letto ora dal portale · {esito.piattaforma} · {dataLeggibile(esito.letto_il)}
      </p>

      {haUffici && (
        <ul className="scheda-letto-ora__uffici">
          {esito.uffici.map((u) => (
            <UfficioCard key={u.url || u.nome} ufficio={u} />
          ))}
        </ul>
      )}

      {at && (haBandi || at.pdf_presenti) && (
        <div className="scheda-letto-ora__at">
          <p className="scheda-letto-ora__at-titolo">
            Amministrazione trasparente
            {at.indice_url && (
              <a
                className="scheda-letto-ora__link"
                href={at.indice_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {" "}
                apri l'indice ↗
              </a>
            )}
          </p>
          {haBandi ? (
            <ul className="scheda-letto-ora__bandi">
              {at.bandi_attivi.map((b) => (
                <BandoRow
                  key={b.url}
                  codiceIstat={esito.codice_istat}
                  titolo={b.titolo}
                  url={b.url}
                  pdfUrl={b.pdf_url}
                />
              ))}
            </ul>
          ) : (
            <p className="scheda-letto-ora__at-vuoto">
              Nessun bando attivo nell'indice al {dataLeggibile(esito.letto_il)}.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
