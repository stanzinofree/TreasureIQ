"use client";

import type { InfoOut } from "@/lib/api";

/**
 * La risposta come scheda civica, non come dump narrativo.
 *
 * Prima ogni informazione aveva lo stesso peso: la risposta al cittadino, il
 * recapito dell'ufficio, il nome del connettore, il post type WordPress e la
 * data di misurazione stavano nello stesso paragrafo, e per giunta comparivano
 * due volte — una impastata in prosa e una in blocchi, perché il backend le
 * componeva entrambe. Chi legge non ha modo di capire cosa guardare per primo.
 *
 * L'ordine qui sotto è la gerarchia, e non è arbitrario:
 *
 *   1. cosa ho trovato          — la risposta alla domanda
 *   2. il servizio              — la scheda con il titolo e il link
 *   3. cosa posso confermare    — e soprattutto cosa no
 *   4. cosa puoi fare adesso    — passi scritti, non contati
 *   5. l'ufficio                — recapiti azionabili
 *   6. la fonte                 — dominio, non URL steso nel testo
 *   7. dettagli tecnici         — chiusi
 *
 * Il tecnico non sparisce: resta consultabile e conta, perché la misura del
 * costo di accesso è il prodotto. Ma sta dietro un clic, perché non è la
 * risposta alla domanda di chi ha scritto.
 *
 * Nessuna sezione viene resa quando il dato non c'è: mai un campo vuoto, mai
 * un «N/A». Un'assenza si dichiara dove significa qualcosa — fra le prove —
 * non replicando etichette senza valore.
 */

const ETICHETTE_STATO: Record<InfoOut["stato"], string> = {
  ufficiale: "Fonte ufficiale",
  parziale: "Informazioni parziali",
  non_verificato: "Non verificato",
  non_pubblicato: "Niente di pubblicato",
};

const SEGNI: Record<string, string> = {
  confermato: "✓",
  parziale: "◐",
  mancante: "○",
};

function dominioDi(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Gli orari come li scrive il comune, spezzati in righe leggibili.
 *
 * La fonte è testo libero — «lun-ven 8:30–11:00; lun e gio anche 15:30–17:30»
 * — e non lo riscriviamo: separiamo sulle interruzioni che il comune ha già
 * messo (`;` e `|`). Riformularlo significherebbe interpretarlo, e un orario
 * interpretato male manda qualcuno davanti a una porta chiusa. */
function righeOrari(orari: string): string[] {
  return orari
    .split(/[;|]/)
    .map((r) => r.trim())
    .filter(Boolean);
}

export default function RispostaCivica({
  reply,
  info,
}: {
  reply: string;
  info: InfoOut;
}) {
  const { office, document: documento } = info;
  const telefoni = office?.telefono
    ? office.telefono.split(/[/,]/).map((t) => t.trim()).filter(Boolean)
    : [];

  return (
    <div className="civica">
      <p className="civica__stato" data-stato={info.stato}>
        {ETICHETTE_STATO[info.stato]}
      </p>

      <p className="civica__sintesi">{reply}</p>

      {info.letto_dal_vivo && (
        <p className="civica__vivo" role="note">
          <span className="civica__vivo-bollo">letto ora</span>
          Dal portale del comune, in questo momento e alla lettera. Non è un
          dato che abbiamo verificato né conservato.
        </p>
      )}

      {documento && (
        <div className="civica__servizio">
          <h3>{documento.title}</h3>
          {info.ente_nome && <p className="civica__ente">{info.ente_nome}</p>}
          <a
            className="civica__cta"
            href={documento.url}
            target="_blank"
            rel="noreferrer"
          >
            Apri la fonte ufficiale
          </a>
          <span className="civica__dominio">{dominioDi(documento.url)}</span>
        </div>
      )}

      {info.prove.length > 0 && (
        <section className="civica__blocco">
          <h4>Cosa posso confermare</h4>
          <ul className="civica__prove">
            {info.prove.map((p) => (
              <li key={p.testo} data-stato={p.stato}>
                <span aria-hidden="true">{SEGNI[p.stato]}</span>
                {p.testo}
              </li>
            ))}
          </ul>
        </section>
      )}

      {info.azioni.length > 0 && (
        <section className="civica__blocco">
          <h4>Cosa puoi fare adesso</h4>
          <ol className="civica__azioni">
            {info.azioni.map((a) => (
              <li key={a.testo}>
                {a.url ? (
                  <a href={a.url} target="_blank" rel="noreferrer">
                    {a.testo}
                  </a>
                ) : (
                  a.testo
                )}
              </li>
            ))}
          </ol>
        </section>
      )}

      {office && (
        <section className="civica__blocco">
          <h4>Ufficio competente</h4>
          <p className="civica__ufficio">{office.nome}</p>

          <div className="civica__contatti">
            {telefoni.length > 0 && (
              <div className="civica__contatto">
                <span className="civica__contatto-label">Telefono</span>
                {telefoni.map((t) => (
                  <a key={t} href={`tel:${t.replace(/\s/g, "")}`}>
                    {t}
                  </a>
                ))}
              </div>
            )}

            {office.email && (
              <div className="civica__contatto">
                <span className="civica__contatto-label">Email</span>
                <a href={`mailto:${office.email}`}>{office.email}</a>
              </div>
            )}

            {office.pec && (
              <div className="civica__contatto">
                <span className="civica__contatto-label">PEC</span>
                <a href={`mailto:${office.pec}`}>{office.pec}</a>
                <span className="civica__nota">
                  obbliga a una risposta
                </span>
              </div>
            )}

            {office.orari && (
              <div className="civica__contatto civica__contatto--orari">
                <span className="civica__contatto-label">Orari di apertura</span>
                {righeOrari(office.orari).map((riga) => (
                  <span key={riga}>{riga}</span>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {info.web_results.length > 0 && (
        <section className="civica__blocco civica__blocco--web" role="note">
          <h4>Pagine trovate sul web · non verificate</h4>
          <ul className="civica__web">
            {info.web_results.slice(0, 3).map((r) => (
              <li key={r.url}>
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.title}
                </a>
                <span className="civica__dominio">{dominioDi(r.url)}</span>
              </li>
            ))}
          </ul>
          <p className="civica__nota">
            Non è una risposta di TreasureIQ: verificale prima di fidartene.
          </p>
        </section>
      )}

      {(info.diagnosis.length > 0 || info.integration_cost.length > 0) && (
        <details className="civica__tecnico">
          <summary>Dettagli tecnici</summary>
          {info.diagnosis.length > 0 && (
            <ul>
              {info.diagnosis.map((riga) => (
                <li key={riga}>{riga}</li>
              ))}
            </ul>
          )}
          {info.integration_cost.length > 0 && (
            <ul className="civica__tecnico-costo">
              {info.integration_cost.map((riga) => (
                <li key={riga}>{riga}</li>
              ))}
            </ul>
          )}
        </details>
      )}
    </div>
  );
}
