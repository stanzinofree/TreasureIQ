"use client";

/**
 * The sign-in step, as its own screen.
 *
 * Identity really is a handoff — in production the citizen leaves for SPID or
 * CIE and comes back — so the demo shows it as one: the conversation is set
 * aside, a profile is chosen, and the chat resumes with the question asked
 * again against the new data.
 *
 * What it deliberately is *not* is a replica of the SPID sign-in page. No
 * AgID mark, no provider colours, no "entra con SPID" chrome. Dressing a mock
 * flow in real credentials branding teaches people to trust that appearance,
 * which is exactly how credential phishing works — and it would be a lie about
 * what this build does, since no credential is ever checked. It says it is a
 * simulation, in the interface's own voice, before it asks anything.
 */

import { useEffect, useRef, useState } from "react";
import { login } from "@/lib/api";
import { PRESETS, type Preset } from "@/lib/profili-demo";

export default function AccessoSimulato({
  motivo,
  onFatto,
  onAnnulla,
}: {
  /** Why identity was asked for, when the chat asked rather than the citizen. */
  motivo?: string;
  onFatto: (preset: Preset) => void;
  onAnnulla: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [errore, setErrore] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const primoRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const tornaA = document.activeElement as HTMLElement | null;
    primoRef.current?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) {
        onAnnulla();
        return;
      }
      if (e.key !== "Tab") return;
      const fuochi = panelRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
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
  }, [onAnnulla, busy]);

  async function entra(preset: Preset) {
    setBusy(preset.id);
    setErrore(null);
    try {
      await login({
        comune_istat: "058003",
        comune_nome: "Albano Laziale",
        ...preset.profile,
      });
      onFatto(preset);
    } catch {
      setErrore(
        "Non riesco a caricare il profilo di prova in questo momento. Riprova.",
      );
      setBusy(null);
    }
  }

  return (
    <div className="accesso">
      <div
        className="accesso__pannello"
        role="dialog"
        aria-modal="true"
        aria-labelledby="accesso-titolo"
        ref={panelRef}
      >
        <p className="accesso__avviso">Simulazione — nessuna credenziale reale</p>

        <h2 id="accesso-titolo">Scegli un profilo di prova</h2>
        <p className="accesso__spiega">
          In un servizio reale saresti su SPID o CIE in questo momento, e
          TreasureIQ riceverebbe indietro solo i dati che servono a rispondere.
          Qui non viene verificata nessuna credenziale e niente lascia il tuo
          computer: scegli una delle situazioni qui sotto e la conversazione
          riprende usando quei dati.
        </p>
        {motivo && <p className="accesso__motivo">{motivo}</p>}

        <ul className="accesso__lista">
          {PRESETS.map((p, i) => (
            <li key={p.id}>
              <button
                type="button"
                className="accesso__profilo"
                onClick={() => entra(p)}
                disabled={busy !== null}
                ref={i === 0 ? primoRef : undefined}
              >
                <span className="accesso__nome">{p.name}</span>
                <span className="accesso__detail">{p.detail}</span>
                {busy === p.id && <span className="accesso__attesa">Accesso…</span>}
              </button>
            </li>
          ))}
        </ul>

        {errore && (
          <p className="notice" role="alert">
            {errore}
          </p>
        )}

        <button
          type="button"
          className="accesso__annulla"
          onClick={onAnnulla}
          disabled={busy !== null}
        >
          Continua senza accedere
        </button>
      </div>
    </div>
  );
}
