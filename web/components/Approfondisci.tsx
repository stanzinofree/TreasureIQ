"use client";

/**
 * "E il mio comune?" — asked explicitly, answered either way.
 *
 * Offered when every result came from a higher tier. The ordinary answer
 * already searched the comune's own records alongside the national ones, so
 * this finds nothing the first pass missed — and the button says so, because
 * a control that implied a deeper search would be promising work nobody does.
 *
 * What it adds is a stated absence. Left silent, "no municipal result" and
 * "we never looked at the comune" are indistinguishable on screen, and the
 * difference between them is the whole subject of this project.
 */

import { useRef, useState } from "react";
import { approfondimento, type Approfondimento as Esito, type PaginaWeb } from "@/lib/api";

export default function Approfondisci({
  topic,
  onSchede,
}: {
  topic: string;
  /** Hands any municipal results back to the transcript, which is where every
   *  verdict is stated — this component never renders one itself. */
  onSchede: (esito: Esito) => void;
}) {
  const [stato, setStato] = useState<"pronto" | "attesa" | "fatto" | "errore">(
    "pronto",
  );
  const [esito, setEsito] = useState<string | null>(null);
  const [pagine, setPagine] = useState<PaginaWeb[]>([]);
  const contenitore = useRef<HTMLParagraphElement | HTMLDivElement | null>(null);

  async function chiedi() {
    setStato("attesa");
    try {
      const out = await approfondimento(topic);
      setEsito(out.esito);
      setPagine(out.pagine ?? []);
      setStato("fatto");
      if (out.matches.length > 0) onSchede(out);
      // The answer replaces this button in place, so nothing moves the page:
      // on a full transcript the result appeared below the fold and looked
      // like nothing had happened. Chat's own auto-scroll only fires on new
      // messages, and this is not one.
      requestAnimationFrame(() => {
        contenitore.current?.scrollIntoView({
          block: "nearest",
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "auto"
            : "smooth",
        });
      });
    } catch {
      setEsito(
        "Non riesco a controllare i dati del comune in questo momento. Riprova.",
      );
      setStato("errore");
    }
  }

  if (stato === "fatto" || stato === "errore") {
    return (
      <div className="approfondisci__esito" role="status" data-stato={stato} ref={contenitore}>
        <p>{esito}</p>

        {/* The weakest evidence in the app, and labelled as such. These are
            pages a search engine returned from public-body domains — nothing
            was parsed, quote-gated or checked against any requirement, so they
            are offered as somewhere to start looking, never as an answer. */}
        {pagine.length > 0 && (
          <ul className="approfondisci__pagine">
            {pagine.map((p) => (
              <li key={p.url}>
                <a href={p.url} target="_blank" rel="noreferrer">
                  {p.title}
                </a>
                <span className="approfondisci__nonverif">non verificata</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <p className="approfondisci" ref={contenitore}>
      <button
        type="button"
        className="approfondisci__button"
        onClick={chiedi}
        disabled={stato === "attesa"}
      >
        {stato === "attesa" ? "Controllo…" : "E il mio comune ha pubblicato qualcosa?"}
      </button>
    </p>
  );
}
