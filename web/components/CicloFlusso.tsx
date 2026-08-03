/**
 * The whole cycle, from a sentence typed in Italian to an answer — drawn.
 *
 * The page around it explains the parts well and never showed how they
 * connect, which is the thing people actually ask about: where the model acts,
 * where it stops, and what happens when the data simply is not there. A
 * sequence with its branches visible answers that faster than four paragraphs.
 *
 * Every step here corresponds to code that runs. Where a step can fail or fall
 * through, the fall-through is drawn too: a flow diagram that shows only the
 * happy path is an advertisement, and this one has to survive being checked
 * against the software by someone sceptical.
 */

type Passo = {
  n: number;
  titolo: string;
  corpo: string;
  attore: "cittadino" | "modello" | "regola" | "dati";
  ramo?: string;
};

const PASSI: Passo[] = [
  {
    n: 1,
    titolo: "La domanda, in italiano",
    corpo:
      "Nessun modulo, nessuna categoria da scegliere. Si scrive come si direbbe a uno sportello.",
    attore: "cittadino",
  },
  {
    n: 2,
    titolo: "Comprensione",
    corpo:
      "Un modello locale ricava il tema e i dati che il cittadino ha volontariamente detto. È l'unico punto in cui interviene, e non decide nulla.",
    attore: "modello",
  },
  {
    n: 3,
    titolo: "Recupero",
    corpo:
      "Una ricerca deterministica per parole chiave sceglie quali servizi valutare, fra quelli del comune e quelli nazionali. Stessa domanda, stessi candidati.",
    attore: "dati",
  },
  {
    n: 4,
    titolo: "Valutazione",
    corpo:
      "Una regola confronta i requisiti pubblicati con quello che si sa della persona. Ogni criterio finisce in uno di quattro stati: soddisfatto, non soddisfatto, non pubblicato, manca il tuo dato.",
    attore: "regola",
  },
  {
    n: 5,
    titolo: "Risposta",
    corpo:
      "Una frase di apertura composta dai conteggi, poi una scheda per risultato con l'esito, i criteri verificati e quelli che nessuno ha pubblicato.",
    attore: "regola",
  },
  {
    n: 6,
    titolo: "Se l'identità cambierebbe l'esito",
    corpo:
      "Solo allora viene proposto l'accesso. Se i requisiti non sono pubblicati, identificarsi non servirebbe e non viene chiesto.",
    attore: "cittadino",
    ramo: "ramo condizionale",
  },
  {
    n: 7,
    titolo: "Se il comune non ha pubblicato nulla",
    corpo:
      "Lo diciamo, con quanti servizi abbiamo letto. Poi si scende all'ultimo gradino: le pagine dei portali istituzionali, marcate come non verificate.",
    attore: "dati",
    ramo: "ramo di fallimento",
  },
  {
    n: 8,
    titolo: "E si può chiedere che venga aperto",
    corpo:
      "Una richiesta già scritta, che parte dalla casella del cittadino verso la PEC certificata dell'ente. Noi contiamo solo quante ne sono partite, per comune.",
    attore: "cittadino",
  },
];

const ATTORE_LABEL: Record<Passo["attore"], string> = {
  cittadino: "cittadino",
  modello: "modello",
  regola: "regola deterministica",
  dati: "dati pubblicati",
};

export default function CicloFlusso() {
  return (
    <section className="panel">
      <h2>Il ciclo completo, dalla domanda alla risposta</h2>
      <p className="lede">
        Otto passi, e due di essi sono rami che si percorrono solo quando serve.
        L&apos;etichetta accanto a ciascuno dice <em>chi</em> agisce: è il modo
        più rapido per vedere quanto poco spazio abbia il modello.
      </p>

      <ol className="ciclo">
        {PASSI.map((p) => (
          <li key={p.n} className="ciclo__passo" data-attore={p.attore}>
            <span className="ciclo__n" aria-hidden="true">
              {p.n}
            </span>
            <div className="ciclo__corpo">
              <h3>
                {p.titolo}
                {p.ramo && <span className="ciclo__ramo">{p.ramo}</span>}
              </h3>
              <p>{p.corpo}</p>
              <span className="ciclo__attore">{ATTORE_LABEL[p.attore]}</span>
            </div>
          </li>
        ))}
      </ol>

      {/* Stated rather than left to be counted off the diagram: the ratio is
          the point of drawing it. */}
      <p className="ciclo__nota">
        Su otto passi il modello ne tocca uno, e in quello non produce
        né esiti né numeri: traduce una frase in un tema. Tutto il resto è
        codice che si può leggere e rieseguire ottenendo lo stesso risultato.
      </p>
    </section>
  );
}
