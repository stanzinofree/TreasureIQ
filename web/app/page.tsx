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
 * `ProfiloProvider`, `RisultatiProvider` and `ScanProvider` are the only
 * client boundaries. `ScanProvider` holds the comune's live-scan status so the
 * chat and the panel show one shared indicator (band + «Ricarica»), not two.
 */

import Chat from "@/components/Chat";
import Pannello from "@/components/Pannello";
import { ProfiloProvider } from "@/lib/profilo";
import { RisultatiProvider } from "@/lib/risultati";
import { ScanProvider } from "@/lib/scan";

export default function Home() {
  return (
    <ProfiloProvider>
      <RisultatiProvider>
        <ScanProvider>
          <div className="workspace">
            <Pannello />

          <div className="workspace__main">
            {/* Not "al tuo comune": the answers already draw on the national
                layer as much as the municipal one — the bonus sociale bollette
                is a state measure, and its card says so. The comune is the
                most granular administration we read, not the only one, and a
                title that says otherwise undersells the product and misleads
                about where an answer came from. */}
            {/* One short, honest welcome. It names what the service does
                (finds the official page, says when it was read) and what it
                does not (decide or file anything): no promise of benefits,
                no claim of national completeness. */}
            <section className="hero-band">
              <div className="hero-band__inner">
                <h1>
                  Chiedi un servizio pubblico.{" "}
                  <span className="hero-band__evidenza">Ti mostriamo la fonte.</span>
                </h1>
                <p className="lede">
                  Scrivi cosa ti serve e per quale comune. TreasureIQ cerca
                  nelle pagine pubblicate da Comuni, Regioni e Stato, ti porta
                  al link ufficiale e dice quando lo ha letto. Se un dato manca,
                  te lo dice.
                </p>
                <p className="hero-band__limiti">
                  Non invia pratiche e non decide al posto dell&apos;ufficio:
                  per requisiti e scadenze fa fede la fonte ufficiale.
                </p>
              </div>
            </section>

            <Chat />
          </div>
          </div>
        </ScanProvider>
      </RisultatiProvider>
    </ProfiloProvider>
  );
}
