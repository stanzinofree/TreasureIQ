"use client";

/**
 * Entry page: the mock identity step.
 *
 * This stands in for SPID. It says so on the page, in the interface's own
 * voice rather than in a disclaimer nobody reads — a demo that let a jury
 * believe we had integrated a national identity provider would be trading on
 * a claim we cannot support. Saying it plainly costs nothing and is the only
 * version of this screen worth shipping.
 *
 * The fields are the ones SPID actually releases plus the means-testing
 * attributes that would come from INPS, so the substitution path stays real:
 * swap this form for an OIDC redirect and the profile arrives in the same
 * shape.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";
import { login } from "@/lib/api";

const PRESETS = [
  {
    id: "famiglia",
    name: "Famiglia con figlio minore",
    detail: "38 anni · ISEE 12.000 € · nucleo di 3",
    profile: {
      eta: 38,
      isee: "12000",
      nucleo_familiare: 3,
      figli_minori: 1,
      employment_status: "occupato",
      interests: ["famiglie", "studenti"],
    },
  },
  {
    id: "pensionato",
    name: "Pensionato che vive solo",
    detail: "71 anni · ISEE 30.000 € · nucleo di 1",
    profile: {
      eta: 71,
      isee: "30000",
      nucleo_familiare: 1,
      figli_minori: 0,
      employment_status: "pensionato",
      interests: ["anziani"],
    },
  },
  {
    id: "studente",
    name: "Studente in cerca di lavoro",
    detail: "23 anni · ISEE 8.000 € · nucleo di 2",
    profile: {
      eta: 23,
      isee: "8000",
      nucleo_familiare: 2,
      figli_minori: 0,
      employment_status: "disoccupato",
      interests: ["studenti", "disoccupati"],
    },
  },
] as const;

export default function Home() {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function enter(preset: (typeof PRESETS)[number]) {
    setBusy(preset.id);
    setError(null);
    try {
      await login({
        comune_istat: "058003",
        comune_nome: "Albano Laziale",
        ...preset.profile,
      });
      router.push("/opportunita");
    } catch {
      setError(
        "Non riesco a raggiungere il servizio. Verifica che l'API sia in esecuzione su localhost:8000.",
      );
      setBusy(null);
    }
  }

  return (
    <div className="stack">
      <section>
        <p className="eyebrow">Comune di Albano Laziale</p>
        <h1>
          Il tuo comune pubblica 32 servizi.
          <br />
          Quanti ti riguardano davvero?
        </h1>
        <p className="lede">
          TreasureIQ legge i servizi pubblicati dal tuo comune, li confronta con
          la tua situazione e ti dice a cosa puoi accedere — e dove il comune
          non pubblica abbastanza per poterlo stabilire.
        </p>
      </section>

      <section className="panel">
        <h2>Entra con la tua identità</h2>
        <p className="lede" style={{ fontSize: "0.97rem" }}>
          Questa è una simulazione del flusso SPID. Nessuna credenziale viene
          verificata e nessun dato lascia il tuo computer: scegli un profilo per
          vedere come cambia il risultato.
        </p>

        <div className="grid-2" style={{ marginTop: "var(--ma-6)" }}>
          {PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              className="panel"
              onClick={() => enter(p)}
              disabled={busy !== null}
              style={{
                textAlign: "left",
                cursor: "pointer",
                padding: "var(--ma-4)",
                background: "var(--paper)",
                font: "inherit",
                opacity: busy && busy !== p.id ? 0.5 : 1,
              }}
            >
              <span
                style={{
                  fontFamily: "var(--font-display)",
                  fontWeight: 700,
                  display: "block",
                  marginBottom: "var(--ma-1)",
                }}
              >
                {p.name}
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "0.78rem",
                  color: "var(--sumi-faint)",
                }}
              >
                {busy === p.id ? "Accesso in corso…" : p.detail}
              </span>
            </button>
          ))}
        </div>

        {error && (
          <p className="notice" role="alert" style={{ marginTop: "var(--ma-6)" }}>
            {error}
          </p>
        )}
      </section>

      <section>
        <h2>Perché così pochi risultati sono certi</h2>
        <p className="lede">
          Dei 32 servizi che Albano Laziale pubblica, uno solo dichiara i propri
          requisiti di accesso in un campo dedicato — e lo fa in prosa libera.
          Il modello Design Comuni Italia, che il comune già usa, prevede quel
          campo: è vuoto, non assente. TreasureIQ misura questo divario e lo
          rende visibile nella{" "}
          <a href="/dati">pagella sulla qualità dei dati</a>.
        </p>
      </section>
    </div>
  );
}
