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
  /** Omitted for facts that cannot honestly be un-known once they exist. */
  onRimuovi?: () => void;
}) {
  return (
    <span className="fatto">
      <span className="fatto__label tiq-micro">{label}</span>
      <span className="fatto__value">{value}</span>
      {nota && <span className="fatto__nota">{nota}</span>}
      {onRimuovi && (
        <button
          type="button"
          className="fatto__rimuovi"
          onClick={onRimuovi}
          aria-label="togli questo dato"
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
    <div className="fatti tiq-card" aria-label="Informazioni che il servizio ha su di te">
      <span className="fatti__intro tiq-sintesi">Sto usando</span>

      {/* Nessun chip «Nome»: `profilo.nome` non è mai popolato da alcun
          registra() (solo `comune.nome` esiste). Era JSX fantasma — rimosso. */}
      {profilo.eta !== undefined && (
        <Chip
          label="Età"
          value={`${profilo.eta} anni`}
          onRimuovi={() => dimenticaFatto("eta")}
        />
      )}

      {profilo.sesso && (
        <Chip
          label="Sesso"
          value={profilo.sesso === "f" ? "Donna" : "Uomo"}
          nota={profilo.sessoDedotto ? "dedotto dal nome" : undefined}
          onRimuovi={() => dimenticaFatto("sesso")}
        />
      )}

      {profilo.nucleoFamiliare !== undefined && (
        <Chip
          label="Nucleo"
          value={`${profilo.nucleoFamiliare} persone`}
          onRimuovi={() => dimenticaFatto("nucleoFamiliare")}
        />
      )}

      {profilo.disabilita === true && (
        <Chip
          label="Disabilità"
          value="sì"
          onRimuovi={() => dimenticaFatto("disabilita")}
        />
      )}

      {profilo.disabilitaNucleo === true && (
        <Chip
          label="Figlio con disabilità"
          value="sì"
          onRimuovi={() => dimenticaFatto("disabilitaNucleo")}
        />
      )}

      {profilo.figliMinori !== undefined && (
        <Chip
          label="Figli minori"
          value={`${profilo.figliMinori}`}
          onRimuovi={() => dimenticaFatto("figliMinori")}
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
          (R-9). Solo per `geolocalizzazione`: un comune `dichiarato` (digitato
          in chat) è già affermato dal cittadino, richiederne la
          conferma sarebbe una riconferma inutile — stessa condizione del
          chip-nota «da confermare» qui sopra. */}
      {profilo.comune &&
        !profilo.comune.confermato &&
        profilo.comune.origine === "geolocalizzazione" && (
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

      {/* The button clears the local context immediately. */}
      <button
        type="button"
        className="fatti__clear tiq-cta"
        onClick={() => {
          dimentica();
          azzeraTrovate();
        }}
        title="Cancella questi dati"
      >
        Dimentica
      </button>
    </div>
  );
}
