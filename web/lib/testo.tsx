import type { ReactNode } from "react";

/** Evidenzia quattro token nel testo TIQ:
 *  - `**...**` → giallo `.tag-verifica` (l'avvertenza «da verificare tu»);
 *  - `«Modello AgID»` → verde `.tag-connettore` (il nome del MODELLO connettore,
 *    stesso chip del badge). E' il nome del modello, mai il vendor;
 *  - `[[...]]` → `.tag-comune` (il nome del comune fuori copertura, chip colorato);
 *  - `__...__` → `<strong>` grassetto vero (per «Attenzione»), distinto dal
 *    chip giallo del «da verificare».
 * Tutto il resto resta testo. Un solo split su regex alternata così i token
 * non si calpestano.
 *
 * Condiviso fra Chat.tsx e RispostaCivica.tsx: la risposta al cittadino compare
 * in un punto solo (D-fix duplicazione), ma quel punto dipende dal rail, quindi
 * la formattazione dei tag deve valere in entrambi i consumatori. Prima viveva
 * dentro Chat.tsx e la copia in RispostaCivica mostrava i marcatori grezzi. */
export function conTagVerifica(testo: string): ReactNode {
  return testo
    .split(/(\*\*.+?\*\*|«Modello AgID»|\[\[.+?\]\]|__.+?__)/g)
    .map((frammento, i) => {
      if (!frammento) return null;
      if (frammento.startsWith("**") && frammento.endsWith("**")) {
        return (
          <span className="tag-verifica" key={i}>
            {frammento.slice(2, -2)}
          </span>
        );
      }
      if (frammento.startsWith("[[") && frammento.endsWith("]]")) {
        return (
          <span className="tag-comune" key={i}>
            {frammento.slice(2, -2)}
          </span>
        );
      }
      if (frammento.startsWith("__") && frammento.endsWith("__")) {
        return <strong key={i}>{frammento.slice(2, -2)}</strong>;
      }
      if (frammento === "«Modello AgID»") {
        return (
          <span className="tag-connettore" key={i}>
            {frammento}
          </span>
        );
      }
      return <span key={i}>{frammento}</span>;
    });
}
