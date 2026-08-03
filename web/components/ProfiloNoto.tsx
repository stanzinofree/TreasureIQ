"use client";

/**
 * The strip that sits where the hardcoded comune used to be.
 *
 * It answers one question — "what does this service know about me right now?"
 * — and it answers it with nothing at all until something is genuinely known.
 * A hardcoded "Comune di Albano Laziale" told every visitor a fact about
 * themselves that nobody had established; an empty strip tells the truth.
 *
 * Each fact is one chip. The comune chip carries its own provenance, because
 * a municipality guessed from GPS and one the citizen confirmed are different
 * claims and the interface should not let them look alike.
 */

import { useProfilo } from "@/lib/profilo";

function Chip({ label, value, nota }: { label: string; value: string; nota?: string }) {
  return (
    <span className="fatto">
      <span className="fatto__label">{label}</span>
      <span className="fatto__value">{value}</span>
      {nota && <span className="fatto__nota">{nota}</span>}
    </span>
  );
}

export default function ProfiloNoto() {
  const { profilo, dimentica, quantiFatti } = useProfilo();

  // Nothing known yet: render nothing. Not a placeholder, not a skeleton —
  // an empty slot is the honest state, and it keeps the hero uncluttered for
  // the visitor who has only just arrived.
  if (quantiFatti === 0) return null;

  return (
    <div className="fatti" aria-label="Informazioni che il servizio ha su di te">
      <span className="fatti__intro">Sto usando</span>

      {profilo.nome && <Chip label="Nome" value={profilo.nome} />}
      {profilo.eta !== undefined && <Chip label="Età" value={`${profilo.eta} anni`} />}

      {profilo.comune && (
        <Chip
          label="Comune"
          value={profilo.comune.nome}
          nota={
            profilo.comune.confermato
              ? undefined
              : profilo.comune.origine === "geolocalizzazione"
                ? "da confermare"
                : undefined
          }
        />
      )}

      {profilo.interessi?.length ? (
        <Chip label="Interessi" value={profilo.interessi.join(", ")} />
      ) : null}

      {profilo.codiceFiscale ? (
        <Chip label="Codice fiscale" value={mascheraCF(profilo.codiceFiscale)} />
      ) : profilo.accesso ? (
        <Chip label="Accesso" value="simulato" nota="nessun codice fiscale letto" />
      ) : null}

      <button type="button" className="fatti__clear" onClick={dimentica}>
        Dimentica
      </button>
    </div>
  );
}

/** Show enough to recognise it, not enough to reuse it. */
function mascheraCF(cf: string): string {
  if (cf.length <= 4) return cf;
  return `${"·".repeat(cf.length - 4)}${cf.slice(-4)}`;
}
