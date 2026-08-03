/**
 * Entry page: the chat front door.
 *
 * A citizen arrives here, not at a login screen — identity is an escalation
 * the chat asks for only when it would change the answer (D-09), not the
 * price of admission.
 *
 * Two columns: a narrow panel holding what the service knows and an index of
 * what it found, and the conversation itself taking the rest. The chat is the
 * product, so it holds the width, the height and every verdict — the panel
 * only ever points back into it.
 *
 * The hero collapses once the conversation starts. That is done in CSS, with
 * `:has()` on the transcript, rather than by lifting Chat's message state up
 * here: the title and motto stay server-rendered with no JS of their own, and
 * there is no second copy of "has the conversation begun" to keep in sync.
 *
 * `ProfiloProvider` and `RisultatiProvider` are the only client boundaries.
 */

import Chat from "@/components/Chat";
import Pannello from "@/components/Pannello";
import { ProfiloProvider } from "@/lib/profilo";
import { RisultatiProvider } from "@/lib/risultati";

export default function Home() {
  return (
    <ProfiloProvider>
      <RisultatiProvider>
        <div className="workspace">
          <Pannello />

          <div className="workspace__main">
            <section className="hero-band">
              <div className="hero-band__inner">
                <h1>Chiedi al tuo comune</h1>
                <p className="lede">
                  Scrivi la tua domanda in italiano. TreasureIQ la confronta con
                  i servizi che il comune ha davvero pubblicato e risponde solo
                  con quello che i dati confermano — o ti dice, con la stessa
                  chiarezza, quando il comune non lo ha ancora scritto da
                  nessuna parte.
                </p>
              </div>
            </section>

            <Chat />
          </div>
        </div>
      </RisultatiProvider>
    </ProfiloProvider>
  );
}
