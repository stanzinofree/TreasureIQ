import Link from "next/link";

import { PRESETS } from "@/lib/profili-demo";

export const metadata = {
  title: "Casi demo — TreasureIQ",
  description:
    "Quattro cittadini di prova per vedere TreasureIQ all'opera senza SPID.",
};

/**
 * I casi demo, spostati qui dalla home.
 *
 * La home è un campo solo: chi arriva deve vedere la domanda, non una griglia
 * di quattro bottoni-persona. Le identità di prova (stessa lista di
 * `profili-demo`, così non divergono) vivono su questa pagina dedicata.
 *
 * Un clic NON avvia qui — questa pagina non monta la chat, quindi non ha la
 * `send()` che apre la sessione — ma rimanda a `/?persona=<id>`. La chat in
 * home consuma quel parametro al mount e apre da sola la sessione di quel
 * cittadino (effetto di handoff in `Chat.tsx`).
 *
 * Ogni figura è inventata e ancorata ad Albano Laziale (l'unico comune con
 * dati completi nella demo): il numero mostrato è un ISEE, non un reddito.
 */
export default function DemoPage() {
  return (
    <div className="workspace__main">
      <section className="hero-band">
        <div className="hero-band__inner">
          <p className="hero-claim">Casi demo</p>
          <h1>Prova TreasureIQ nei panni di un cittadino.</h1>
          <p className="lede">
            Quattro situazioni su Albano Laziale, senza SPID. Scegline una: la
            chat si apre già con il profilo e la domanda pronti, così vedi
            subito la risposta — un sì con i requisiti, o un no con la cifra che
            lo decide.
          </p>
          <p className="lede">
            <Link href="/">← Torna alla chat</Link>
          </p>
        </div>
      </section>

      <div
        className="grid-2"
        style={{ padding: "var(--ma-4)", gap: "var(--ma-3)" }}
      >
        {PRESETS.map((p) => (
          <Link
            key={p.id}
            href={`/?persona=${p.id}`}
            className="panel"
            style={{
              display: "block",
              textAlign: "left",
              padding: "var(--ma-4)",
              background: "var(--paper)",
              textDecoration: "none",
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "0.72rem",
                color: "var(--sumi-faint)",
                display: "block",
                marginBottom: "var(--ma-1)",
              }}
            >
              {p.detail}
            </span>
            <span
              style={{
                fontFamily: "var(--font-display)",
                fontWeight: 700,
                fontSize: "1.1rem",
                display: "block",
                marginBottom: "var(--ma-1)",
              }}
            >
              {p.persona} · {p.name}
            </span>
            <span
              style={{
                display: "block",
                marginBottom: "var(--ma-2)",
                color: "var(--sumi-faint)",
              }}
            >
              {p.situazione}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "0.82rem",
                display: "block",
              }}
            >
              «{p.domanda}»
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
