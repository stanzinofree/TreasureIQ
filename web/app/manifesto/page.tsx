/**
 * Manifesto (v3) — the outward-facing "what we do", in the register of
 * Fondazione Openpolis' /cosa-facciamo: a thesis hero, the data chain, the
 * non-negotiable principles, the areas of work and a closing call to action.
 *
 * The chain below is not decorative: each step maps to a real stage in
 * TreasureIQ's pipeline (ingestion → snapshot → quote gate → rule engine →
 * verdict → segnalazione), so numbering it 01–06 carries information, not
 * decoration. This is a server page — public information about the project.
 */

import Link from "next/link";

const CHAIN = [
  {
    num: "01",
    title: "Estraiamo",
    desc: "L'ingestion legge le pagine pubbliche del comune — servizi, bandi, avvisi, contributi, PDF allegati.",
  },
  {
    num: "02",
    title: "Raccogliamo",
    desc: "Uno snapshot su disco, riproducibile e senza rete: la demo non dipende da un'API key.",
  },
  {
    num: "03",
    title: "Verifichiamo le citazioni",
    desc: "Ogni requisito deve esistere come frase reale nella fonte. Se la frase non c'è, il campo resta vuoto.",
  },
  {
    num: "04",
    title: "Colleghiamo",
    desc: "Il motore di regole incrocia i dati pubblicati con il profilo del cittadino, requisito per requisito.",
  },
  {
    num: "05",
    title: "Decidiamo",
    desc: "Il verdetto lo calcola una regola deterministica, non un modello che tira a indovinare.",
  },
  {
    num: "06",
    title: "Attiviamo",
    desc: "Risposta in italiano semplice — e, se il comune non pubblica, la segnalazione per chiedergli di aprire il dato.",
  },
];

const PRINCIPLES = [
  {
    title: "Il verdetto lo decide una regola, non un'intelligenza artificiale",
    body: "Il modello linguistico capisce la domanda e scrive la risposta, ma non decide. Ogni verdetto — idoneo, da verificare, non determinabile, non idoneo — nasce da un motore di regole deterministico, a partire da ciò che il comune ha effettivamente pubblicato.",
  },
  {
    title: "Un requisito compare solo se esiste la frase che lo dice",
    body: "Nessun requisito viene stimato, dedotto o 'completato a buon senso'. Un requisito inventato dal modello, anche se plausibile, potrebbe convincere qualcuno di avere un diritto che non ha.",
  },
  {
    title: "'Il comune non l'ha pubblicato' non è 'non ho trovato nulla'",
    body: "Sono due fallimenti diversi e la risposta li distingue sempre: un limite nella fonte del comune, oppure una domanda a cui nessun dato corrisponde. Confonderli significherebbe mentire sul dove si è rotto.",
  },
  {
    title: "Ciò che non è misurato non è mai zero",
    body: "Un dato mai recuperato si legge 'non misurato' o 'non verificato', mai come un sicuro zero. L'intero progetto esiste per misurare quanto sono affidabili i dati pubblici: non può poi gonfiare i propri.",
  },
];

const AREAS = [
  "Lettura automatica dei bandi",
  "Pagella dei dati dei comuni",
  "Costo trasparente del recupero",
  "Segnalazioni di apertura dati",
  "Open data civici",
];

export default function Manifesto() {
  return (
    <div>
      <section className="manifesto-hero">
        <div className="manifesto-hero__inner">
          <p className="eyebrow">Manifesto</p>
          <h1>I dati del tuo comune, letti al posto tuo</h1>
          <p className="lede">
            TreasureIQ libera e raccoglie i dati che il tuo comune ha già
            pubblicato, e li trasforma in una risposta onesta: a quali
            agevolazioni hai davvero accesso — e, con la stessa chiarezza,
            quando il comune non ha scritto nulla da nessuna parte.
          </p>
        </div>
      </section>

      <section className="stack" style={{ marginTop: "var(--ma-16)" }}>
        <div>
          <p className="eyebrow">La catena del dato</p>
          <h2>Seguiamo tutta la catena, dall'ingestion alla risposta</h2>
          <p className="lede">
            Niente è saltato e niente è inventato: ogni passo della catena
            esiste nel codice e ogni prodotto ne esce verificabile.
          </p>
        </div>

        <div className="manifesto-chain">
          {CHAIN.map((s) => (
            <div key={s.num} className="step">
              <span className="step__num">{s.num}</span>
              <h3 className="step__title">{s.title}</h3>
              <p className="step__desc">{s.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="stack" style={{ marginTop: "var(--ma-16)" }}>
        <div>
          <p className="eyebrow">Principi non negoziabili</p>
          <h2>Quello a cui non rinunciamo</h2>
          <p className="lede">
            Per un progetto che tratta di case popolari, contributi e
            agevolazioni, l'onestà sui dati è l'unica garanzia che conta.
          </p>
        </div>

        <div className="stack">
          {PRINCIPLES.map((p) => (
            <div key={p.title} className="principle">
              <h3>{p.title}</h3>
              <p>{p.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="stack" style={{ marginTop: "var(--ma-16)" }}>
        <div>
          <p className="eyebrow">Aree di lavoro</p>
          <h2>Cosa facciamo</h2>
        </div>
        <ul className="area-tags">
          {AREAS.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>

        <div className="panel">
          <p className="eyebrow">Contesto</p>
          <h3 style={{ marginBottom: "var(--ma-2)" }}>Dove si inserisce Openpolis</h3>
          <p className="lede" style={{ fontSize: "0.97rem" }}>
            Le finanze dei comuni italiani sono già aperte:{" "}
            <a href="https://openbilanci.it" target="_blank" rel="noreferrer">
              Openbilanci
            </a>{" "}
            (Fondazione Openpolis, licenza CC-BY-NC) ripubblica i bilanci che i
            comuni inviano alla Ragioneria Generale dello Stato, dal database
            ufficiale <a href="https://openbdap.rgs.mef.gov.it" target="_blank" rel="noreferrer">OpenBDAP</a>.
            È un contesto finanziario utile a capire quanto spende un comune,
            ma non dice a un cittadino se ha diritto a una casa popolare:
            quello si legge solo nei requisiti che il comune pubblica (o non
            pubblica). TreasureIQ lavora su quella seconda parte, la più
            trascurata.
          </p>
        </div>
      </section>

      <section className="manifesto-cta" style={{ marginTop: "var(--ma-16)" }}>
        <h2>Prova a chiedere al tuo comune</h2>
        <p className="lede" style={{ color: "var(--sumi-soft)" }}>
          Scrivi la tua domanda e vedi cosa i dati confermano — o non
          confermano.
        </p>
        <p style={{ marginTop: "var(--ma-6)", display: "flex", gap: "var(--ma-4)", flexWrap: "wrap" }}>
          <Link className="button" href="/">
            Chiedi al tuo comune
          </Link>
          <Link className="button button--ghost" href="/dati">
            Guarda la pagella dei comuni
          </Link>
        </p>
      </section>
    </div>
  );
}
