"use client";

/**
 * A stable door to the open-data request, next to the numbers that motivate it.
 *
 * The request form existed only inside the chat, and only when a narrow
 * combination held — an INFORMAZIONE answer whose access mode was M4, M5 or
 * M6. On the paths a visitor actually walks it never appeared, so a feature
 * that works was, in practice, one that nobody could reach.
 *
 * It belongs here because this is the page where someone reads how little
 * their comune publishes. Asking for it to be opened is the natural next move
 * from that number, and putting the two anywhere else separates the problem
 * from the only thing a citizen can do about it.
 *
 * Nothing about the citizen is collected. The text is generated, their own
 * mail client sends it, and the counter records one anonymous tally per
 * comune — the same design the chat already used, kept deliberately.
 */

import { useState } from "react";
import Segnalazione from "@/components/Segnalazione";
import type { Integration } from "@/lib/api";

export default function ChiediApertura({ enti }: { enti: Integration[] }) {
  const [aperto, setAperto] = useState<string | null>(null);

  if (enti.length === 0) return null;

  return (
    <section className="panel" id="apertura">
      <h2>Chiedi al tuo comune di aprire questi dati</h2>
      <p className="lede">
        I numeri qui sopra descrivono un problema che un&apos;amministrazione
        può risolvere in un pomeriggio, se qualcuno glielo chiede. La richiesta
        è già scritta: parte dalla tua casella e arriva alla PEC dell&apos;ente,
        che è tenuto a rispondere.
      </p>

      <ul className="apertura">
        {enti.map((e) => {
          const destinatario = e.pec || e.urp_email;
          const attivo = aperto === e.codice_istat;
          return (
            <li key={e.codice_istat} className="apertura__ente">
              <div className="apertura__testa">
                <div>
                  <h3>{e.ente}</h3>
                  <span className="apertura__conteggio">
                    {e.segnalazioni_count === 0
                      ? "nessuna richiesta finora"
                      : `${e.segnalazioni_count} ${
                          e.segnalazioni_count === 1
                            ? "richiesta inviata"
                            : "richieste inviate"
                        }`}
                  </span>
                </div>
                <button
                  type="button"
                  className="button button--ghost"
                  aria-expanded={attivo}
                  onClick={() => setAperto(attivo ? null : e.codice_istat)}
                >
                  {attivo ? "Chiudi" : "Prepara la richiesta"}
                </button>
              </div>

              {attivo && (
                <div className="apertura__corpo">
                  <Segnalazione
                    codiceIstat={e.codice_istat}
                    ente={e.ente}
                    office={
                      destinatario
                        ? {
                            nome: e.urp_nome ?? "Protocollo",
                            telefono: null,
                            email: e.urp_email,
                            orari: null,
                            pec: e.pec,
                          }
                        : null
                    }
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {/* Said plainly, because a counter beside a public body invites the
          reading that we are keeping a list of who complained. We are not:
          there is one number per comune and nothing behind it. */}
      <p className="field__hint apertura__nota">
        Il contatore è anonimo e per comune: registra quante richieste sono
        state preparate, non chi le ha mandate. Nessun dato personale passa da
        qui — la mail parte dal tuo programma di posta, e noi non la vediamo.
      </p>
    </section>
  );
}
