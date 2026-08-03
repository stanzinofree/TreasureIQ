/**
 * Entry page: the chat front door.
 *
 * A citizen arrives here, not at a login screen — identity is an escalation
 * the chat asks for only when it would change the answer (D-09), not the
 * price of admission. The hero sits on the same paper as the rest of the site
 * so the page opens without a seam, and the chat follows directly beneath it.
 *
 * Above the title is the one slot that changes as the conversation learns
 * something: `ProfiloNoto` shows every fact currently being used to compute
 * answers, and shows nothing until there is one. It used to be a hardcoded
 * "Comune di Albano Laziale", which announced a residency to visitors who had
 * never stated one.
 *
 * The server shell stays a server shell: `ProfiloProvider` is the client
 * boundary, and the motto and title still render with no JS of their own.
 */

import Chat from "@/components/Chat";
import ProfiloNoto from "@/components/ProfiloNoto";
import { ProfiloProvider } from "@/lib/profilo";

export default function Home() {
  return (
    <ProfiloProvider>
      <div>
        <section className="hero-band">
          <div className="hero-band__inner">
            <ProfiloNoto />
            <h1>Chiedi al tuo comune</h1>
            <p className="lede">
              Scrivi la tua domanda in italiano. TreasureIQ la confronta con i
              servizi che il comune ha davvero pubblicato e risponde solo con
              quello che i dati confermano — o ti dice, con la stessa chiarezza,
              quando il comune non lo ha ancora scritto da nessuna parte.
            </p>
          </div>
        </section>

        <div className="chat-page">
          <Chat />
        </div>
      </div>
    </ProfiloProvider>
  );
}
