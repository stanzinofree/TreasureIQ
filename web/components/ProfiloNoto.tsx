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
import { useRisultati } from "@/lib/risultati";

function Chip({
  label,
  value,
  nota,
  onRimuovi,
}: {
  label: string;
  value: string;
  nota?: string;
  /** Omitted for facts that cannot honestly be un-known once they exist —
   * "Accesso" chief among them, since it is the login itself, not a fact
   * learned during it. */
  onRimuovi?: () => void;
}) {
  return (
    <span className="fatto">
      <span className="fatto__label">{label}</span>
      <span className="fatto__value">{value}</span>
      {nota && <span className="fatto__nota">{nota}</span>}
      {onRimuovi && (
        <button
          type="button"
          onClick={onRimuovi}
          aria-label="togli questo dato"
          style={{
            border: 0,
            background: "none",
            font: "inherit",
            color: "inherit",
            cursor: "pointer",
            padding: "0 0 0 0.35em",
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </span>
  );
}

export default function ProfiloNoto() {
  const { profilo, registra, dimentica, dimenticaComune, dimenticaFatto, dimenticaInteresse, quantiFatti } =
    useProfilo();
  const { azzeraTrovate } = useRisultati();

  // Nothing known yet: render nothing. Not a placeholder, not a skeleton —
  // an empty slot is the honest state, and it keeps the hero uncluttered for
  // the visitor who has only just arrived.
  if (quantiFatti === 0) return null;

  return (
    <div className="fatti" aria-label="Informazioni che il servizio ha su di te">
      <span className="fatti__intro">Sto usando</span>

      {profilo.nome && (
        <Chip label="Nome" value={profilo.nome} onRimuovi={() => dimenticaFatto("nome")} />
      )}
      {profilo.eta !== undefined && (
        <Chip
          label="Età"
          value={`${profilo.eta} anni`}
          onRimuovi={() => dimenticaFatto("eta")}
        />
      )}

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
          onRimuovi={dimenticaComune}
        />
      )}

      {/* Confermare è un gesto, non una domanda. La versione precedente
          scriveva «confermi che è il tuo comune di residenza?» dentro la
          casella della domanda: partiva verso il motore, che cercava un
          servizio comunale corrispondente, non lo trovava, e rispondeva di non
          saper collegare la richiesta. I bottoni stanno qui perché qui sta il
          comune a cui si riferiscono.

          Il GPS dice dove sei adesso, non dove risiedi — chi è in trasferta è
          altrove — quindi la conferma serve davvero e non è una formalità
          (R-9). */}
      {profilo.comune && !profilo.comune.confermato && (
        <span className="fatti__conferma">
          <button
            type="button"
            onClick={() =>
              registra({ comune: { ...profilo.comune!, confermato: true } })
            }
          >
            Sì, è il mio comune
          </button>
          <button
            type="button"
            className="fatti__conferma--no"
            onClick={dimenticaComune}
          >
            No, è un altro
          </button>
        </span>
      )}

      {profilo.interessi?.map((tag) => (
        <Chip
          key={tag}
          label="Interesse"
          value={tag}
          onRimuovi={() => dimenticaInteresse(tag)}
        />
      ))}

      {profilo.codiceFiscale ? (
        <Chip label="Codice fiscale" value={mascheraCF(profilo.codiceFiscale)} />
      ) : profilo.accesso ? (
        <Chip label="Accesso" value="simulato" nota="nessun codice fiscale letto" />
      ) : null}

      {/* The label has to say that this ends the session, not just that it
          tidies the strip: someone signed in would not guess that "dimentica"
          logs them out, and finding out afterwards is the wrong moment. */}
      <button
        type="button"
        className="fatti__clear"
        onClick={() => {
          // Leaving invalidates the index for the same reason arriving does:
          // every verdict in it was computed from data the service is about to
          // stop holding. The transcript keeps its history — a conversation
          // records what was said — but the summary of "what we found" cannot
          // outlive the profile it was found for.
          dimentica();
          azzeraTrovate();
        }}
        title={
          profilo.accesso
            ? "Cancella questi dati e chiude la sessione"
            : "Cancella questi dati"
        }
      >
        {profilo.accesso ? "Esci e dimentica" : "Dimentica"}
      </button>
    </div>
  );
}

/** Show enough to recognise it, not enough to reuse it. */
function mascheraCF(cf: string): string {
  if (cf.length <= 4) return cf;
  return `${"·".repeat(cf.length - 4)}${cf.slice(-4)}`;
}
