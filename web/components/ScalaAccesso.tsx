/**
 * The access ladder, drawn — and where each measured comune sits on it.
 *
 * D-21 is the spine of this project and until now it existed only as a string
 * in a JSON payload. Seeing the rungs stacked, with the comuni placed on them,
 * says in one glance what a paragraph says badly: the data is there, and how
 * far down you have to climb to reach it is the whole cost.
 *
 * Rungs with nobody on them are drawn anyway. An empty M1 is the most
 * informative row on the page — it means not one of the comuni we measured
 * publishes eligibility criteria in a typed field, which is precisely the gap
 * the project exists to point at. Hiding empty rungs would delete the finding.
 *
 * Every bar carries its count in writing. A chart whose values can only be
 * estimated by eye is decoration, and this one is evidence.
 */

import type { Costo } from "@/lib/api";

type Gradino = {
  chiave: string;
  titolo: string;
  spiega: string;
};

/** Ordered from the cheapest to read to the dearest, top to bottom. */
const GRADINI: Gradino[] = [
  {
    chiave: "M1_campo_tipizzato",
    titolo: "M1 · Campo tipizzato",
    spiega:
      "I requisiti stanno in un campo strutturato, come previsto dal modello Design Comuni Italia. Si leggono e basta.",
  },
  {
    chiave: "M2_prosa_api",
    titolo: "M2 · Prosa dentro l'API",
    spiega:
      "L'API c'è, ma i requisiti sono scritti in un paragrafo. Vanno estratti, e l'estrazione può non trovare nulla.",
  },
  {
    chiave: "M3_allegato",
    titolo: "M3 · Allegato PDF",
    spiega:
      "I requisiti sono dentro un allegato. Prima di estrarre bisogna scaricare e interpretare il documento.",
  },
  {
    chiave: "M4_connettore",
    titolo: "M4 · Connettore su misura",
    spiega:
      "Nessuna interfaccia utilizzabile: serve un lettore scritto per quel solo portale, che si rompe a ogni restyling.",
  },
  {
    chiave: "M5_nessuno",
    titolo: "M5 · Niente di raggiungibile",
    spiega:
      "Non abbiamo trovato nessuna via per leggere i servizi di questo ente in modo automatico.",
  },
  {
    chiave: "M6_web_aperto",
    titolo: "M6 · Solo web aperto",
    spiega:
      "Resta la ricerca fra i portali istituzionali: la prova più debole, e l'ultima che tentiamo.",
  },
];

export default function ScalaAccesso({ costi }: { costi: Costo[] }) {
  if (costi.length === 0) return null;

  const massimo = Math.max(...costi.map((c) => c.record_totali), 1);

  return (
    <section className="panel">
      <h2>Fin dove siamo dovuti scendere</h2>
      <p className="lede">
        Ogni comune sta sul gradino più alto che siamo riusciti a raggiungere.
        Più in basso si scende, più lavoro serve per leggere la stessa cosa — e
        più fragile diventa quello che leggiamo.
      </p>

      <ol className="scala">
        {GRADINI.map((g) => {
          const qui = costi.filter((c) => c.modo === g.chiave);
          return (
            <li key={g.chiave} className="scala__gradino" data-vuoto={qui.length === 0}>
              <div className="scala__testa">
                <h3>{g.titolo}</h3>
                <span className="scala__conta">
                  {qui.length === 0
                    ? "nessun comune"
                    : `${qui.length} ${qui.length === 1 ? "comune" : "comuni"}`}
                </span>
              </div>
              <p className="scala__spiega">{g.spiega}</p>

              {qui.length > 0 && (
                <ul className="scala__comuni">
                  {qui.map((c) => (
                    <li key={c.codice_istat}>
                      <span className="scala__nome">{c.ente}</span>
                      <span className="scala__barra" role="presentation">
                        <span
                          className="scala__barra-fill"
                          style={{ width: `${Math.max(3, (c.record_totali / massimo) * 100)}%` }}
                        />
                      </span>
                      <span className="scala__cifra">
                        {c.record_totali} servizi · {c.costo_per_record}/servizio
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>

      {/* An empty top rung is the finding, so it is said out loud rather than
          left for the reader to infer from a blank row. */}
      {costi.every((c) => c.modo !== "M1_campo_tipizzato") && (
        <p className="scala__nota">
          Nessuno dei comuni misurati pubblica i requisiti in un campo
          tipizzato, benché il campo esista nel modello nazionale. È il motivo
          per cui ogni riga qui sotto costa qualcosa.
        </p>
      )}
    </section>
  );
}
