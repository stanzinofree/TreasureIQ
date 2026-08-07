/**
 * What this is, and why — written for a citizen with no technical background.
 *
 * Rendered on the server, like `/dati`: this is public information about how
 * the service works, not about a person, so there is no session to wait for.
 * The one live figure on the page (how many of Albano's services actually
 * have their access requirements filled in) is fetched from the readiness
 * report rather than typed by hand, so it cannot drift out of date the way a
 * copy-pasted number would.
 */

import { readiness, type Readiness } from "@/lib/api";
import Link from "next/link";
import CicloFlusso from "@/components/CicloFlusso";
import MappaSistema from "@/components/MappaSistema";
import SpecificheOpenData from "@/components/SpecificheOpenData";

export const dynamic = "force-dynamic";

function structuredEligibilityEvidence(report: Readiness | null): string | null {
  const dim = report?.dimensions.find((d) => d.key === "structured_eligibility");
  return dim?.evidence ?? null;
}

export default async function Info() {
  let report: Readiness | null = null;
  try {
    report = await readiness("058003");
  } catch {
    report = null;
  }
  const evidence = structuredEligibilityEvidence(report);

  return (
    <div className="stack">
      <section className="manifesto-hero">
        <div className="manifesto-hero__inner">
        {/* This page and /manifesto once opened with the same headline, which
            made them read as two drafts of one page. The split now holds: the
            manifesto says what we hold ourselves to, this says how the
            machinery actually works — the rule that decides, the sentence that
            has to be found in the source, the rungs we climb down. */}
        <p className="eyebrow">Come funziona TreasureIQ</p>
        <h1>Il meccanismo, per intero</h1>
        <p className="lede">
          TreasureIQ legge le pagine pubbliche di un comune — servizi, bandi,
          avvisi, contributi — e le confronta con la situazione di chi chiede,
          per dire a quali ha davvero accesso. Qui c&apos;è come: cosa decide un
          esito, cosa succede a un requisito che non si ritrova nella fonte, e
          fin dove scendiamo per arrivare a un dato.
        </p>
        <p className="lede">
          Se invece cerchi il perché e le cose a cui non rinunciamo, sono nel{" "}
          <Link href="/manifesto">manifesto</Link>.
        </p>
        </div>
      </section>

      <section className="panel">
        <h2>Chi parla con chi, e quando</h2>
        <p className="lede">
          Due fasce, e non si mescolano mai. Sopra, quello che gira prima che
          qualcuno faccia una domanda: finisce in file versionati, che chiunque
          può rileggere. Sotto, quello che succede mentre il cittadino aspetta.
          È questa separazione che permette a una risposta di dire da dove
          viene, invece di dirlo a parole.
        </p>
        <MappaSistema />
      </section>

      <CicloFlusso />

      <section className="panel">
        <h2>Il verdetto lo decide una regola, non un&apos;intelligenza artificiale</h2>
        <p className="lede">
          Chiedi qualcosa in linguaggio naturale — &ldquo;ho la bolletta
          troppo alta&rdquo;, &ldquo;ci sono bandi per l&apos;informatica in
          scadenza?&rdquo; — e un modello linguistico locale capisce la
          domanda e scrive la risposta in italiano semplice. Ma non è lui a
          decidere se hai diritto a qualcosa. Ogni verdetto (idoneo, da
          verificare, non determinabile, non idoneo) viene calcolato da un
          motore di regole deterministico, a partire da quello che il comune
          ha effettivamente pubblicato. Il modello riformula un risultato già
          calcolato: non aggiunge fatti, non aggiunge criteri, non decide.
        </p>
        <p className="lede">
          È una scelta di principio, non un dettaglio tecnico: un progetto che
          esiste per misurare quanto sono affidabili i dati pubblici
          non può poi affidare la risposta finale a un modello che tira a
          indovinare. Il verdetto deve poter essere ricondotto, riga per riga,
          a un dato reale — altrimenti TreasureIQ diventerebbe esattamente il
          problema che denuncia.
        </p>
      </section>

      <section className="panel">
        <h2>Un requisito compare solo se esiste la frase che lo dice</h2>
        <p className="lede">
          Quando un requisito viene estratto da un testo — un bando, un
          avviso, un PDF allegato — viene mostrato solo se nel documento
          originale esiste davvero la frase da cui è stato preso. Se quella
          frase non c&apos;è, il campo resta vuoto: non viene stimato, non
          viene dedotto, non viene &ldquo;completato&rdquo; a buon senso.
        </p>
        <p className="lede">
          Il motivo è semplice: un requisito inventato dal modello, anche se
          plausibile, potrebbe convincere qualcuno di essere idoneo (o non
          idoneo) a un beneficio a cui in realtà non ha diritto (o a cui ha
          diritto). Per un progetto che tratta di case popolari, contributi e
          agevolazioni, questa è l&apos;unica garanzia che conta davvero — e
          l&apos;unica che non è negoziabile per far sembrare il sistema più
          completo di quanto i dati permettano.
        </p>
      </section>

      <section className="panel">
        <h2>
          &ldquo;Il comune non l&apos;ha pubblicato&rdquo; non è
          &ldquo;non ho trovato nulla&rdquo;
        </h2>
        <p className="lede">
          Sono due situazioni diverse, e la risposta le distingue sempre:
        </p>
        <ul className="criteria" style={{ marginTop: "var(--ma-4)" }}>
          <li className="criterion" data-state="unknown_source">
            <span className="criterion__glyph" aria-hidden="true">
              ◐
            </span>
            <span>
              <strong style={{ fontWeight: 600 }}>Il comune non l&apos;ha pubblicato.</strong>{" "}
              Esiste un servizio o un bando che ti riguarda, ma il dato di cui
              avremmo bisogno per rispondere — una soglia ISEE, un limite
              d&apos;età, un requisito di residenza — non è scritto da nessuna
              parte nei documenti che il comune mette a disposizione. Il
              limite è nella fonte, non nella ricerca.
            </span>
          </li>
          <li className="criterion" data-state="undetermined" style={{ marginTop: "var(--ma-3)" }}>
            <span className="criterion__glyph" aria-hidden="true">
              ◌
            </span>
            <span>
              <strong style={{ fontWeight: 600 }}>Non ho trovato nulla.</strong>{" "}
              Semplicemente non esiste, tra i dati letti, niente che
              corrisponda alla tua domanda. Non è un limite del comune: è
              che la risposta non riguarda questo territorio o questo tipo di
              servizio.
            </span>
          </li>
        </ul>
      </section>

      <section className="panel">
        <h2>A chi amministra: aprire questo dato non costa nulla</h2>
        <p className="lede">
          Il tema Design Comuni Italia, che il tuo comune probabilmente già
          usa per pubblicare i servizi, prevede da solo un campo dedicato ai
          requisiti di accesso — non è uno standard nuovo da adottare, è una
          casella già presente nel pannello di amministrazione.
          {evidence ? (
            <>
              {" "}
              Su Albano Laziale, oggi, quel campo risulta{" "}
              <strong style={{ fontWeight: 600 }}>{evidence}</strong>: il
              campo esiste su tutti i servizi pubblicati, semplicemente non è
              stato riempito.
            </>
          ) : (
            " Su Albano Laziale il campo esiste su tutti i servizi pubblicati, ma è compilato solo su una minima parte."
          )}
        </p>
        <p className="lede">
          Non è un rimprovero: è una porta già aperta che nessuno ha ancora
          attraversato. Compilare quel campo, servizio per servizio, non
          richiede nuovo software, nuovi fornitori né un nuovo capitolato — è
          un pomeriggio di lavoro d&apos;ufficio che toglie a un cittadino la
          fatica di scoprire da solo, leggendo un PDF di dieci pagine, se ha
          diritto a un contributo. È probabilmente l&apos;intervento a più
          alto impatto e più basso costo che un comune può fare sui propri
          dati aperti quest&apos;anno.
        </p>
        <p className="lede">
          Vuoi vedere la misura completa, comune per comune?{" "}
          <a href="/dati">Qualità dei dati</a> mostra il punteggio, cosa manca
          e — quando i dati sono stati recuperati da un testo libero — quanto
          è costato in tempo di calcolo capire cosa c&apos;era scritto. Se ti
          interessa il perché dietro tutto questo, leggi il{" "}
          <a href="/manifesto">manifesto del progetto</a>.
        </p>
      </section>

      {/* Colophon. This used to live in a site-wide footer, which repeated the
          masthead's own navigation and — on the chat page — would have had to
          sit under the composer, stacking a second bar along the bottom edge
          the conversation already owns. Licence and provenance belong on the
          page that explains the project, not on every page. */}
      <SpecificheOpenData />

      <section className="prose">
        <h2>Licenza e provenienza</h2>
        <p className="lede">
          TreasureIQ è software libero, rilasciato sotto licenza Apache 2.0: il
          codice è leggibile, riusabile e verificabile da chiunque —{" "}
          <a href="https://github.com/stanzinofree/TreasureIQ" target="_blank" rel="noreferrer">
            il sorgente è su GitHub
          </a>
          . Un servizio che dice a un cittadino cosa gli spetta deve poter
          essere controllato nel merito, non creduto sulla parola.
        </p>
        <p className="lede">
          I dati provengono dai portali delle amministrazioni pubbliche e da
          fonti pubbliche nazionali. Nessuno di essi è una fonte di
          eleggibilità: TreasureIQ riporta quello che è stato pubblicato e
          indica dove verificarlo, ma l&apos;ultima parola resta
          all&apos;amministrazione che eroga il servizio.
        </p>
      </section>
    </div>
  );
}
