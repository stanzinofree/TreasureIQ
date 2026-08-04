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
            {/* Not "al tuo comune": the answers already draw on the national
                layer as much as the municipal one — the bonus sociale bollette
                is a state measure, and its card says so. The comune is the
                most granular administration we read, not the only one, and a
                title that says otherwise undersells the product and misleads
                about where an answer came from. */}
            <section className="hero-band">
              <div className="hero-band__inner">
                <p className="hero-claim">Ogni cittadino ha diritti.</p>
                <h1>Trovarli non dovrebbe essere una caccia al tesoro.</h1>
                <p className="lede">
                  TreasureIQ legge ciò che Stato, Regioni e Comuni hanno
                  pubblicato e lo confronta con la tua situazione. Ti mostra
                  cosa puoi ottenere e, quando i dati non bastano, evidenzia
                  esattamente cosa manca.
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
