/**
 * Entry page: the chat front door.
 *
 * A citizen arrives here, not at a login screen — identity is an escalation
 * the chat asks for only when it would change the answer (D-09), not the
 * price of admission. This is a server shell on purpose: the motto and
 * footer render with no client JS, and `Chat` is the one interactive island.
 */

import Chat from "@/components/Chat";
import FooterStats from "@/components/FooterStats";

export default function Home() {
  return (
    <div className="stack chat-page">
      <section className="chat-hero">
        <p className="eyebrow">Comune di Albano Laziale</p>
        <h1>Chiedi al tuo comune</h1>
        <p className="lede">
          Scrivi la tua domanda in italiano. TreasureIQ la confronta con i
          servizi che il comune ha davvero pubblicato e risponde solo con
          quello che i dati confermano — o ti dice, con la stessa chiarezza,
          quando il comune non lo ha ancora scritto da nessuna parte.
        </p>
      </section>

      <Chat />

      <footer className="chat-footer">
        <p>
          Preferisci sfogliare tu i dati?{" "}
          <a href="/opportunita">Vista esperta delle opportunità</a> ·{" "}
          <a href="/dati">Qualità dei dati dei comuni</a> ·{" "}
          <a href="/info">Come funziona TreasureIQ</a> ·{" "}
          <a href="/monitoraggio">Stato del servizio</a>.
        </p>
        <FooterStats />
      </footer>
    </div>
  );
}
