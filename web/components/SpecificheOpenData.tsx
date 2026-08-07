/**
 * What a comune would have to publish for any of this to cost nothing.
 *
 * Written as a checklist an administration could hand to whoever maintains
 * their portal, not as a critique. Every line is something we had to work
 * around while reading real municipal data, and each says what it costs us
 * when it is missing — because "please publish better data" persuades nobody,
 * while "this one field is why we cannot answer your citizens" might.
 *
 * Nothing here is invented by us. The fields belong to the Design Comuni
 * Italia model that already exists; the project's position is that a new
 * standard would move the problem rather than solve it.
 */

type Requisito = {
  campo: string;
  cosa: string;
  senza: string;
  stato: "assente" | "parziale" | "presente";
};

const REQUISITI: Requisito[] = [
  {
    campo: "vincoli",
    cosa: "I requisiti di accesso in un campo strutturato, non dentro un paragrafo.",
    senza:
      "Vanno estratti dal testo, e ogni frase estratta va ricontrollata sulla fonte. È il costo più grande che paghiamo, ed è quello che nessuno paga se il campo è compilato.",
    stato: "assente",
  },
  {
    campo: "ISEE, età, nucleo familiare",
    cosa: "Le soglie come numeri, con l'unità dichiarata.",
    senza:
      "Una soglia scritta a parole non si può confrontare con la situazione di una persona: resta «non verificabile» anche quando è scritta chiaramente.",
    stato: "assente",
  },
  {
    campo: "scadenza",
    cosa: "Una data in formato macchina, e la distinzione fra «sempre aperto» e «non pubblicata».",
    senza:
      "Un campo vuoto può voler dire entrambe le cose, e le due portano il cittadino a fare cose opposte.",
    stato: "parziale",
  },
  {
    campo: "identificativo stabile",
    cosa: "Un id che non cambi quando la pagina viene rigenerata.",
    senza:
      "Non si può dire se un servizio è cambiato o è solo stato ripubblicato, e ogni lettura riparte da zero.",
    stato: "presente",
  },
  {
    campo: "API leggibile",
    cosa: "Un endpoint che restituisca i servizi in modo strutturato, anche solo in lettura.",
    senza:
      "Serve un lettore scritto per quel solo portale, che si rompe al primo restyling: è il motivo per cui leggere Ariccia costa quasi il doppio per servizio.",
    stato: "parziale",
  },
  {
    campo: "recapito dell'ufficio",
    cosa: "Ufficio competente, orari e canale certificato, aggiornati.",
    senza:
      "Un cittadino che ha capito di averne diritto non sa a chi chiedere, e un recapito sbagliato costa un viaggio a vuoto.",
    stato: "presente",
  },
];

const STATO_LABEL: Record<Requisito["stato"], string> = {
  assente: "quasi mai compilato",
  parziale: "compilato a metà",
  presente: "di solito c'è",
};

export default function SpecificheOpenData() {
  return (
    <section className="panel">
      <h2>La lista completa</h2>
      <p className="lede">
        Il campo appena descritto è il primo di questa lista e il più pesante,
        ma non è solo. Nessuno di questi è da inventare: esistono già nel
        modello Design Comuni Italia. Sono quelli che, mancando, ci obbligano a
        interpretare invece di leggere — e l&apos;etichetta a destra dice quanto
        spesso li abbiamo trovati compilati nei comuni misurati.
      </p>

      <ul className="specifiche">
        {REQUISITI.map((r) => (
          <li key={r.campo} className="specifica" data-stato={r.stato}>
            <div className="specifica__testa">
              <code>{r.campo}</code>
              <span className="specifica__stato">{STATO_LABEL[r.stato]}</span>
            </div>
            <p className="specifica__cosa">{r.cosa}</p>
            <p className="specifica__senza">
              <strong>Senza:</strong> {r.senza}
            </p>
          </li>
        ))}
      </ul>

      <p className="ciclo__nota">
        Nessuna di queste righe è un giudizio su chi amministra. Un campo vuoto
        quasi mai è pigrizia: è un gestionale che non lo esporta, un modulo nato
        in PDF, un ufficio con due persone. Serve un argomento da portare a chi
        decide i bilanci — e la cifra accanto a ogni comune su{" "}
        <a href="/dati">Qualità dei dati</a> è pensata per quello.
      </p>
    </section>
  );
}
