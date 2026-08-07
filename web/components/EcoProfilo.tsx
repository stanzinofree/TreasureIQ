"use client";

/**
 * "Ho capito: …" — but the guessed facts are correctable in one tap.
 *
 * The sex is deduced from the first name (D-52), a low-confidence inference the
 * interface must never pass off as a fact. It used to end in a plain "— giusto?"
 * that could only be corrected by typing a whole sentence again. Here the guess
 * is two cards, Uomo / Donna, with the deduced one pre-selected: confirming is a
 * tap, correcting is the other tap. Age is shown as a card and can be rewritten
 * inline, so the citizen fixes a wrong "34" without re-opening the conversation.
 *
 * Nothing here states a verdict or drives a hidden filter — it only edits what
 * the strip already shows, which is why every change goes straight to `registra`.
 */

import { useState } from "react";
import { useProfilo } from "@/lib/profilo";

type Capito = {
  sesso?: "f" | "m" | null;
  sesso_dedotto?: boolean | null;
  eta?: number | null;
  nucleo_familiare?: number | null;
  disabilita_nucleo?: boolean | null;
};

const cardBase: React.CSSProperties = {
  border: "1px solid var(--linea, #cdd3da)",
  background: "transparent",
  borderRadius: 999,
  padding: "0.15em 0.7em",
  font: "inherit",
  fontSize: "0.9em",
  cursor: "pointer",
  lineHeight: 1.4,
};

const cardAttiva: React.CSSProperties = {
  ...cardBase,
  borderColor: "var(--accento, #0e7f6f)",
  background: "var(--accento-tenue, #d9f2ec)",
  fontWeight: 600,
  cursor: "default",
};

export default function EcoProfilo({ capito }: { capito: Capito }) {
  const { profilo, registra } = useProfilo();

  // The message carries a snapshot; once corrected, the live store is the
  // truth. Read sex from the store when present so the tap sticks visually.
  const sessoVivo = profilo.sesso ?? capito.sesso ?? undefined;
  const dedotto = profilo.sesso ? profilo.sessoDedotto : capito.sesso_dedotto;

  const etaViva = profilo.eta ?? capito.eta ?? undefined;

  const [modificaEta, setModificaEta] = useState(false);
  const [bozzaEta, setBozzaEta] = useState("");

  const pezzi: string[] = [];
  if (capito.nucleo_familiare != null) pezzi.push(`nucleo di ${capito.nucleo_familiare}`);
  if (capito.disabilita_nucleo) pezzi.push("un figlio con disabilità nel nucleo");

  function scegliSesso(s: "f" | "m") {
    // Confirming or correcting both end the guess: once tapped it is stated,
    // not deduced, so the "— giusto?" prompt has nothing left to ask.
    registra({ sesso: s, sessoDedotto: false });
  }

  function salvaEta() {
    const n = Number.parseInt(bozzaEta, 10);
    if (Number.isFinite(n) && n > 0 && n < 130) registra({ eta: n });
    setModificaEta(false);
    setBozzaEta("");
  }

  const nienteDaMostrare =
    sessoVivo === undefined && etaViva === undefined && pezzi.length === 0;
  if (nienteDaMostrare) return null;

  return (
    <div
      className="bubble__eco-profilo"
      style={{ opacity: 0.85, fontSize: "0.9em", marginTop: "0.4em" }}
    >
      <span style={{ marginRight: "0.4em" }}>Ho capito:</span>

      <span
        style={{ display: "inline-flex", gap: "0.4em", flexWrap: "wrap", alignItems: "center", verticalAlign: "middle" }}
      >
        {/* Sex — two cards, the guess pre-selected, correctable in one tap. */}
        {sessoVivo !== undefined && (
          <>
            <button
              type="button"
              style={sessoVivo === "m" ? cardAttiva : cardBase}
              aria-pressed={sessoVivo === "m"}
              onClick={() => scegliSesso("m")}
            >
              Uomo
            </button>
            <button
              type="button"
              style={sessoVivo === "f" ? cardAttiva : cardBase}
              aria-pressed={sessoVivo === "f"}
              onClick={() => scegliSesso("f")}
            >
              Donna
            </button>
          </>
        )}

        {/* Age — a card, tap to rewrite it inline. */}
        {etaViva !== undefined && !modificaEta && (
          <button
            type="button"
            style={cardBase}
            onClick={() => {
              setBozzaEta(String(etaViva));
              setModificaEta(true);
            }}
            title="Tocca per cambiare l'età"
          >
            {etaViva} anni
          </button>
        )}
        {modificaEta && (
          <span style={{ display: "inline-flex", gap: "0.3em", alignItems: "center" }}>
            <span>la mia età è</span>
            <input
              type="number"
              min={1}
              max={129}
              value={bozzaEta}
              onChange={(e) => setBozzaEta(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") salvaEta();
                if (e.key === "Escape") setModificaEta(false);
              }}
              autoFocus
              style={{ width: "4em", font: "inherit", fontSize: "1em", padding: "0.1em 0.3em" }}
            />
            <button type="button" style={cardAttiva} onClick={salvaEta}>
              ok
            </button>
          </span>
        )}

        {pezzi.length > 0 && <span>{pezzi.join(", ")}</span>}
      </span>

      {/* The prompt survives only until the citizen touches a card: the moment
          they confirm or correct, the guess is settled. */}
      {dedotto && <span style={{ marginLeft: "0.35em" }}>— giusto?</span>}
    </div>
  );
}
