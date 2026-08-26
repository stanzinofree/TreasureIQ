"use client";

import { useState } from "react";

import type { InfoOut } from "@/lib/api";
import { conTagVerifica } from "@/lib/testo";

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

/** Un solo bollo di stato: provenienza e completezza in un'etichetta sola, per
 * non moltiplicare i marcatori sulla stessa risposta. «Fonte parziale» tiene
 * insieme «viene dall'ufficiale» e «non c'è tutto»; il dettaglio di cosa manca
 * resta nelle righe ◐ di «Cosa sappiamo dalla fonte», non in un secondo bollo. */
const ETICHETTA_STATO: Record<InfoOut["stato"], string> = {
  ufficiale: "Fonte ufficiale",
  parziale: "Fonte parziale",
  non_verificato: "Ricerca web",
  non_pubblicato: "Niente di pubblicato",
};

/** La data di lettura, scritta come la scriverebbe una persona. */
function dataVerifica(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("it-IT", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/** Copia negli appunti senza dire di averlo fatto se non è vero. */
function Copia({ valore, cosa }: { valore: string; cosa: string }) {
  const [fatto, setFatto] = useState(false);
  return (
    <button
      type="button"
      className="civica__copia"
      aria-label={`Copia ${cosa}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(valore);
          setFatto(true);
          setTimeout(() => setFatto(false), 2000);
        } catch {
          // Il browser può negare gli appunti (permesso, contesto non
          // sicuro). Non fingiamo la riuscita: il valore resta selezionabile
          // a mano, che è esattamente ciò che il cittadino farebbe comunque.
          setFatto(false);
        }
      }}
    >
      {fatto ? "Copiato" : "Copia"}
    </button>
  );
}

const SEGNI: Record<string, string> = {
  confermato: "✓",
  parziale: "◐",
  mancante: "○",
};

/** Colore della banda-stato in cima alla card: dato visivo (D-03), non
 *  verdetto. Segue la stessa provenienza del bollo in `ETICHETTA_STATO`. */
const BANDA_STATO: Record<InfoOut["stato"], string> = {
  ufficiale: "verde",
  parziale: "ambra",
  non_pubblicato: "ambra",
  non_verificato: "neutra",
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
    .split(/[;|]| · /)
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

  // Ciclo 15 R4 — una regola per sezione, uguale in OGNI access_mode (niente
  // più il booleano `compatto` che accendeva/spegneva 4 sezioni in blocco solo
  // sul fuori-copertura, lasciando il coperto gonfio). La sintesi in prosa (lo
  // «spiegone») è ridondante appena la scheda ha contenuto strutturato — titolo
  // del servizio, prove, contatti o pagine web dicono già la stessa cosa. La
  // mostriamo SOLO quando è l'unica risposta possibile (nessun blocco
  // strutturato), altrimenti è un preambolo doppione (era il caso di Albano).
  const soloProsa =
    !documento &&
    info.prove.length === 0 &&
    !office &&
    info.web_results.length === 0;
  const telefoni = office?.telefono
    ? office.telefono.split(/[/,]/).map((t) => t.trim()).filter(Boolean)
    : [];

  // Il «pippone» sul dato live non sta più sempre a schermo: il bollo ambra
  // «letto ora» apre a richiesta una nota che spiega cos'è (fonte, non
  // verdetto). Meno rumore sotto ogni risposta, spiegazione a un tap.
  const [spiegaVivo, setSpiegaVivo] = useState(false);

  return (
    <div className="civica tiq-card">
      <span
        className={`tiq-card__banda tiq-card__banda--${BANDA_STATO[info.stato]}`}
        aria-hidden="true"
      />
      <p className="civica__bolli">
        <span className="civica__stato" data-stato={info.stato}>
          {ETICHETTA_STATO[info.stato]}
        </span>
        {info.letto_dal_vivo && (
          <span className="civica__vivo-wrap">
            <button
              type="button"
              className="civica__vivo-bollo"
              aria-expanded={spiegaVivo}
              onClick={() => setSpiegaVivo((v) => !v)}
            >
              letto ora
            </button>
            {spiegaVivo && (
              <span className="civica__vivo-nota" role="note">
                Dal portale del comune, in questo momento e alla lettera. Non è
                un dato che abbiamo verificato né conservato.
              </span>
            )}
          </span>
        )}
      </p>

      {soloProsa && (
        <p className="civica__sintesi tiq-sintesi">{conTagVerifica(reply)}</p>
      )}

      {documento && (
        <div className="civica__servizio">
          <h3>{documento.title}</h3>
          {info.ente_nome && <p className="civica__ente">{info.ente_nome}</p>}
          {documento.descrizione && (
            <p className="civica__descrizione">{documento.descrizione}</p>
          )}
          <p className="civica__servizio-piede">
            <a
              className="civica__cta tiq-cta"
              href={documento.url}
              target="_blank"
              rel="noreferrer"
            >
              Apri la fonte ufficiale
            </a>
            <span className="civica__dominio">{dominioDi(documento.url)}</span>
          </p>
          {documento.verificato_il && (
            <p className="civica__verifica">
              Letta da TreasureIQ il {dataVerifica(documento.verificato_il)}
            </p>
          )}
        </div>
      )}

      {info.prove.length > 0 && (
        <section className="civica__blocco">
          {/* «Cosa sappiamo dalla fonte», non «cosa posso confermare»: il
              soggetto della riga è il dato del comune, non noi. */}
          <h4>Cosa sappiamo dalla fonte</h4>
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

      {/* Ciclo 15 R4: «Cosa puoi fare adesso» rimosso. Su un comune coperto le
          azioni erano passi generici («Consulta il servizio», «Verifica i
          documenti») già coperti dalla card del servizio (Apri la fonte) e dai
          contatti dell'ufficio (Chiama/Scrivi). Un blocco separato di CTA era
          rumore ridondante. La card e i contatti restano gli unici CTA. */}

      {office && (
        <section className="civica__blocco">
          <h4>Ufficio competente</h4>
          <p className="civica__ufficio">{office.nome}</p>

          {/* Chi risponde dell'ufficio (accountability, Ramo 1). Best-effort:
              solo dove la scheda lo pubblica, mai inferito (D-07). `email`
              personale non è quasi mai pubblicata → di norma nome + ruolo. */}
          {office.responsabile && (
            <p className="civica__responsabile">
              <span className="civica__responsabile-label">Responsabile</span>
              <span className="civica__responsabile-nome">
                {office.responsabile.nome}
              </span>
              {office.responsabile.ruolo && (
                <span className="civica__responsabile-ruolo">
                  {office.responsabile.ruolo}
                </span>
              )}
              {office.responsabile.email && (
                <a href={`mailto:${office.responsabile.email}`}>
                  {office.responsabile.email}
                </a>
              )}
            </p>
          )}

          {/* Assenza ONESTA (Slice 2): la diciamo solo quando la scheda è stata
              davvero ispezionata da una famiglia con estrattore responsabile e
              il nominativo non c'era. Senza quel segnale (`responsabile` null
              ma mai verificato: URP di ripiego, famiglia senza estrattore,
              fetch fallita) il campo resta nascosto — mai spacciato per
              «non pubblicato». */}
          {!office.responsabile && office.responsabile_ispezionato && (
            <p className="civica__responsabile civica__responsabile--assente">
              <span className="civica__responsabile-label">Responsabile</span>
              <span className="civica__responsabile-assente">
                non pubblicato dal Comune
              </span>
            </p>
          )}

          <div className="civica__contatti">
            {telefoni.length > 0 && (
              <div className="civica__contatto">
                <span className="civica__contatto-label">Telefono</span>
                {telefoni.map((t) => (
                  <a key={t} href={`tel:${t.replace(/\s/g, "")}`}>
                    {t}
                  </a>
                ))}
                <span className="civica__contatto-azioni">
                  <a
                    className="civica__mini-cta"
                    href={`tel:${telefoni[0].replace(/\s/g, "")}`}
                  >
                    Chiama
                  </a>
                  <Copia valore={telefoni.join(" ")} cosa="il telefono" />
                </span>
              </div>
            )}

            {office.email && (
              <div className="civica__contatto">
                <span className="civica__contatto-label">Email</span>
                <a href={`mailto:${office.email}`}>{office.email}</a>
                <span className="civica__contatto-azioni">
                  <a className="civica__mini-cta" href={`mailto:${office.email}`}>
                    Scrivi
                  </a>
                  <Copia valore={office.email} cosa="l'email" />
                </span>
              </div>
            )}

            {office.pec && (
              <div className="civica__contatto">
                <span className="civica__contatto-label">PEC</span>
                <a href={`mailto:${office.pec}`}>{office.pec}</a>
                {/* «Obbliga a una risposta» non è vero: la PEC dà ricevute con
                    valore legale e tracciabilità, non un dovere di risposta che
                    dipende dal procedimento. Qui si dice cosa fa davvero. */}
                <span className="civica__nota">
                  Comunicazione tracciata, con ricevute di invio e consegna
                </span>
                <span className="civica__contatto-azioni">
                  <a className="civica__mini-cta" href={`mailto:${office.pec}`}>
                    Scrivi via PEC
                  </a>
                  <Copia valore={office.pec} cosa="la PEC" />
                </span>
              </div>
            )}

            {office.indirizzo && (
              <div className="civica__contatto">
                <span className="civica__contatto-label">Indirizzo</span>
                <span className="civica__indirizzo">{office.indirizzo}</span>
                {/* Onestà semantica (Ramo 1): l'indirizzo è la sede
                    dell'edificio/ente ospitante, spesso condivisa da più
                    uffici — «dove vado di persona», non un recapito esclusivo
                    di questo ufficio. */}
                <span className="civica__nota">
                  Sede dell'edificio, può ospitare più uffici
                </span>
                <span className="civica__contatto-azioni">
                  <Copia valore={office.indirizzo} cosa="l'indirizzo" />
                </span>
              </div>
            )}

            {office.orari && (
              <div className="civica__contatto civica__contatto--orari">
                <span className="civica__contatto-label">Orari di apertura</span>
                {righeOrari(office.orari).map((riga) => (
                  <span key={riga}>{riga}</span>
                ))}
                {/* La fonte verbatim accanto alla forma normalizzata: il
                    cittadino può ricontrollare parola per parola contro la
                    pagina del comune (D-07). Solo quando `orari` è la forma
                    pulita — se `orari` è già il verbatim, `orari_fonte` è null
                    e non si ripete la stessa riga due volte. */}
                {office.orari_fonte && (
                  <span className="civica__contatto-fonte">
                    dal portale: «{office.orari_fonte}»
                  </span>
                )}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Ciclo 15 R4: «Dettagli tecnici» (diagnosis + integration_cost, D-21)
          rimosso dalla scheda del cittadino: è diagnostica di integrazione, non
          una risposta. Resta accessibile su pannello/monitoraggio. */}

      {/* D-05: dopo tutto il verificato (prove, ufficio) —
          sempre visibile, mai un collapse, perché non è un dettaglio da
          nascondere ma contenuto di natura diversa (non verificato). */}
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
    </div>
  );
}
