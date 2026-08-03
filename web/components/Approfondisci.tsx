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

import { useState } from "react";
import { approfondimento, type Approfondimento as Esito } from "@/lib/api";

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

  async function chiedi() {
    setStato("attesa");
    try {
      const out = await approfondimento(topic);
      setEsito(out.esito);
      setStato("fatto");
      if (out.matches.length > 0) onSchede(out);
    } catch {
      setEsito(
        "Non riesco a controllare i dati del comune in questo momento. Riprova.",
      );
      setStato("errore");
    }
  }

  if (stato === "fatto" || stato === "errore") {
    return (
      <p className="approfondisci__esito" role="status" data-stato={stato}>
        {esito}
      </p>
    );
  }

  return (
    <p className="approfondisci">
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
