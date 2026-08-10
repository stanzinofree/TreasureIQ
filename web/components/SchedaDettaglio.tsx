"use client";

/**
 * The full record, opened from a card and read before leaving for the site.
 *
 * The card in the transcript answers one question — does this apply to me —
 * and stays short so a conversation stays readable. Everything the citizen
 * needs *before* acting lives here: which office to ask, by when, what was
 * checked, what nobody published, and only then the link out.
 *
 * Nothing is invented to fill a section. A missing office, a missing deadline
 * and an unpublished criterion each say so in words, because "not published"
 * is a finding about the administration, not an empty slot in our layout.
 */

import { useEffect, useRef } from "react";
import { Seal } from "@/components/Seal";
import type { Criterion, Match } from "@/lib/api";

const LIVELLO_LABEL: Record<string, string> = {
  comunale: "Comunale",
  regionale: "Regionale",
  nazionale: "Nazionale",
};

/** Stessa mappa verdict→colore del Seal (D-03): la banda è un segnale-dato,
 *  non un secondo verdetto — positivo→verde, chiaramente-negativo→ambra,
 *  tutto il resto (probabile/indeterminato)→neutra. */
const BANDA_VERDICT: Record<Match["verdict"], "verde" | "ambra" | "neutra"> = {
  eligible: "verde",
  likely: "neutra",
  undetermined: "neutra",
  not_eligible: "ambra",
};

const STATO_LABEL: Record<Criterion["state"], string> = {
  met: "Soddisfatto",
  not_met: "Non soddisfatto",
  unknown_source: "Non pubblicato",
  unknown_profile: "Manca il tuo dato",
};

function dataIt(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

/** "oggi", "ieri", "3 giorni fa" — the age of a reading, in the terms someone
 *  judges freshness by. The exact date rides alongside it, because "12 giorni
 *  fa" is easy to feel and impossible to check. */
function eta(iso: string): string {
  // Calendar days, not elapsed hours. Measuring the gap in milliseconds made
  // a record read yesterday evening report itself as "oggi", because fifteen
  // hours floors to zero — the one direction this must never round, since it
  // overstates how fresh the data is.
  const letto = new Date(iso);
  const aMezzanotte = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const giorni = Math.round((aMezzanotte(new Date()) - aMezzanotte(letto)) / 86_400_000);
  if (giorni <= 0) return "oggi";
  if (giorni === 1) return "ieri";
  if (giorni < 30) return `${giorni} giorni fa`;
  const mesi = Math.floor(giorni / 30);
  return mesi === 1 ? "un mese fa" : `${mesi} mesi fa`;
}

export default function SchedaDettaglio({
  match,
  onClose,
}: {
  match: Match;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const chiudiRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // Focus moves in on open and back out on close, and Tab is kept inside:
    // a dialog a keyboard user can tab out of, into a page they cannot see,
    // is a trap of the worse kind.
    const tornaA = document.activeElement as HTMLElement | null;
    chiudiRef.current?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const fuochi = panelRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button, [tabindex]:not([tabindex="-1"])',
      );
      if (!fuochi?.length) return;
      const primo = fuochi[0];
      const ultimo = fuochi[fuochi.length - 1];
      if (e.shiftKey && document.activeElement === primo) {
        e.preventDefault();
        ultimo.focus();
      } else if (!e.shiftKey && document.activeElement === ultimo) {
        e.preventDefault();
        primo.focus();
      }
    }

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      tornaA?.focus?.();
    };
  }, [onClose]);

  const decisi = match.criteria.filter(
    (c) => c.state === "met" || c.state === "not_met",
  );
  const nonPubblicati = match.criteria.filter((c) => c.state === "unknown_source");
  const mancanti = match.criteria.filter((c) => c.state === "unknown_profile");

  return (
    <div className="modale" onClick={onClose}>
      <div
        className="modale__pannello tiq-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="scheda-titolo"
        ref={panelRef}
        onClick={(e) => e.stopPropagation()}
      >
        <span
          className={`tiq-card__banda tiq-card__banda--${BANDA_VERDICT[match.verdict]}`}
          aria-hidden="true"
        />
        <header className="modale__testa">
          <Seal verdict={match.verdict} size={40} />
          <div>
            <h2 id="scheda-titolo">{match.title}</h2>
            <p className="modale__esito tiq-sintesi">{match.headline}</p>
          </div>
          <button
            type="button"
            className="modale__chiudi"
            onClick={onClose}
            ref={chiudiRef}
            aria-label="Chiudi la scheda"
          >
            ✕
          </button>
        </header>

        <div className="modale__tag">
          <span className="tag" data-verdict={match.verdict}>
            {match.verdict_label}
          </span>
          <span className="tag">{LIVELLO_LABEL[match.livello] ?? match.livello}</span>
          <span className="tag">{match.kind}</span>
        </div>

        <dl className="modale__dati">
          <div>
            <dt>Ente</dt>
            <dd>{match.ente}</dd>
          </div>
          {/* The age of the reading belongs beside what it says. Nothing here
              is live: this is a snapshot, and a service that hides how old its
              snapshot is asks to be trusted about something it has not
              checked recently. */}
          <div>
            <dt>Letto</dt>
            <dd>
              {eta(match.letto_il)}{" "}
              <span className="modale__quando">({dataIt(match.letto_il)})</span>
            </dd>
          </div>
          <div>
            <dt>Termini</dt>
            <dd>
              {match.deadline ? (
                dataIt(match.deadline)
              ) : (
                <span className="modale__assente">
                  Nessuna scadenza pubblicata — verifica sulla pagina ufficiale
                </span>
              )}
            </dd>
          </div>
        </dl>

        {/* Who to ask. Shown with the date the contacts were last checked and
            a link to where they were read: a phone number with no provenance
            is one nobody can be held to, and a wrong one costs a person a
            trip to a closed counter. */}
        <section className="modale__sez">
          <h3>A chi chiedere</h3>
          {match.ufficio ? (
            <>
              <p className="modale__ufficio-nome">{match.ufficio.nome}</p>
              <dl className="modale__dati">
                {match.ufficio.telefono && (
                  <div>
                    <dt>Telefono</dt>
                    <dd>
                      <a href={`tel:${match.ufficio.telefono.split(" ")[0]}`}>
                        {match.ufficio.telefono}
                      </a>
                    </dd>
                  </div>
                )}
                {match.ufficio.email && (
                  <div>
                    <dt>Email</dt>
                    <dd>
                      <a href={`mailto:${match.ufficio.email}`}>{match.ufficio.email}</a>
                    </dd>
                  </div>
                )}
                {match.ufficio.orari && (
                  <div>
                    <dt>Orari</dt>
                    <dd>{match.ufficio.orari}</dd>
                  </div>
                )}
              </dl>
              <p className="modale__provenienza">
                Telefono, email e orari letti dal sito del comune (
                {match.ufficio.fonte}), verificati il{" "}
                {dataIt(match.ufficio.verificato_il)}.
              </p>

              {/* The certified address is kept apart from the counter details
                  above. It answers a different question — this is the channel
                  that obliges an answer, not the one that is quickest — and it
                  comes from a different source, so it carries its own. */}
              {match.ufficio.pec && (
                <div className="modale__pec">
                  <dl className="modale__dati">
                    <div>
                      <dt>PEC — richiesta formale</dt>
                      <dd>
                        <a href={`mailto:${match.ufficio.pec}`}>{match.ufficio.pec}</a>
                      </dd>
                    </div>
                  </dl>
                  <p className="modale__provenienza">
                    Dall&apos;
                    <a
                      href={match.ufficio.pec_fonte ?? "https://indicepa.gov.it"}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Indice della Pubblica Amministrazione
                    </a>
                    , il registro che ogni ente è tenuto a mantenere aggiornato
                    {match.ufficio.pec_verificata_il &&
                      ` — letto il ${dataIt(match.ufficio.pec_verificata_il)}`}
                    . Una PEC obbliga l&apos;ente a risponderti.
                  </p>
                </div>
              )}
            </>
          ) : (
            <p className="modale__assente">
              Non abbiamo un ufficio di riferimento verificato per questo ente.
              {match.livello !== "comunale" &&
                " È una misura nazionale: lo sportello del tuo comune non la gestisce."}
            </p>
          )}
        </section>

        {decisi.length > 0 && (
          <section className="modale__sez">
            <h3>Cosa è stato verificato</h3>
            <ul className="modale__criteri">
              {decisi.map((c) => (
                <li key={c.key} data-stato={c.state}>
                  <strong>{c.label}</strong> — {c.detail}
                  <span className="modale__stato">{STATO_LABEL[c.state]}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {(nonPubblicati.length > 0 || mancanti.length > 0) && (
          <section className="modale__sez">
            <h3>Cosa non è stato possibile verificare</h3>
            <ul className="modale__criteri">
              {nonPubblicati.map((c) => (
                <li key={c.key} data-stato={c.state}>
                  <strong>{c.label}</strong> — {c.detail}
                  <span className="modale__stato">{STATO_LABEL[c.state]}</span>
                </li>
              ))}
              {mancanti.map((c) => (
                <li key={c.key} data-stato={c.state}>
                  <strong>{c.label}</strong> — {c.detail}
                  <span className="modale__stato">{STATO_LABEL[c.state]}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {match.notes.length > 0 && (
          <section className="modale__sez">
            <h3>Note dell&apos;estrazione</h3>
            <ul className="modale__note">
              {match.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </section>
        )}

        <footer className="modale__piede">
          <a
            className="button"
            href={match.source_url}
            target="_blank"
            rel="noreferrer"
          >
            Apri la pagina ufficiale →
          </a>
          <p className="modale__avviso">
            L&apos;ultima parola è dell&apos;ente: questa scheda riporta quello
            che ha pubblicato, non una decisione.
          </p>
        </footer>
      </div>
    </div>
  );
}
