"use client";

/**
 * B2 ciclo 6 (D-01, D-02) — il feedback sulla conversazione va al nostro
 * server e basta: nessuna issue GitHub, nessuna mail, nessun canale esterno
 * (sostituisce il link verso GitHub rimosso da `lib/moduli.ts` in questo
 * stesso ciclo). Nessun campo nome/email/PII: solo il testo del cittadino
 * e un voto opzionale (A3, D-02).
 */

import { useRef, useState } from "react";
import { inviaFeedback } from "@/lib/api";

const VOTI = [1, 2, 3, 4, 5] as const;

export default function Feedback() {
  const [testo, setTesto] = useState("");
  const [voto, setVoto] = useState<number | null>(null);
  const [inviato, setInviato] = useState(false);
  const [errore, setErrore] = useState<string | null>(null);

  // Guardia sincrona contro il doppio invio. Uno stato React (`busy`) non
  // basta: due submit nello stesso tick lo leggono entrambi false e partono
  // due richieste (memoria "doppio invio → scan live fallisce"). Il ref
  // cambia all'istante, quindi il secondo invio si ferma qui.
  const invioInCorso = useRef(false);

  async function handleSubmit(evento: React.FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    if (invioInCorso.current) return;
    const testoPulito = testo.trim();
    if (testoPulito.length === 0) return;

    invioInCorso.current = true;
    setErrore(null);
    try {
      await inviaFeedback(testoPulito, voto);
      setInviato(true);
    } catch {
      setErrore(
        "Non riesco a raggiungere il servizio. Verifica che l'API sia in esecuzione su localhost:8010.",
      );
      invioInCorso.current = false;
    }
  }

  if (inviato) {
    return (
      <p className="chiedi-inline">Grazie, il tuo feedback ci aiuta a migliorare.</p>
    );
  }

  return (
    <form className="chiedi-inline" onSubmit={handleSubmit}>
      <label htmlFor="feedback-testo">Com&apos;è andata? Lascia un feedback</label>
      <textarea
        id="feedback-testo"
        value={testo}
        onChange={(evento) => setTesto(evento.target.value)}
        maxLength={2000}
        rows={2}
        placeholder="Scrivi qui il tuo feedback…"
      />

      <div role="group" aria-label="Voto da 1 a 5, opzionale">
        {VOTI.map((n) => (
          <button
            key={n}
            type="button"
            className="button"
            aria-pressed={voto === n}
            onClick={() => setVoto(voto === n ? null : n)}
          >
            {n}
          </button>
        ))}
      </div>

      <button type="submit" className="button" disabled={testo.trim().length === 0}>
        Invia feedback
      </button>

      {errore && (
        <p className="notice" role="alert">
          {errore}
        </p>
      )}
    </form>
  );
}
