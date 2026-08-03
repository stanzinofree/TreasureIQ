/**
 * The whole picture, in aggregate, above everything else on /monitoraggio.
 *
 * Aggregate on purpose. Split per comune, these numbers answered a question
 * nobody asked: someone opening a status page wants the shape of what we hold,
 * not a three-way comparison of municipalities. Comparing them is the job of
 * /dati, and doing it in both places made neither page the one to read.
 *
 * The band leads with the finding rather than with the inventory. "94 servizi
 * letti" is an inventory; "84 su 91 senza requisiti leggibili" is the reason
 * the project exists, and it is the number a reader should leave with.
 */

import type { Panoramica as Dati } from "@/lib/api";

function dataOraIt(iso: string): string {
  const d = new Date(iso);
  const gg = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${gg}/${mm}/${d.getFullYear()}`;
}

export default function Panoramica({ dati }: { dati: Dati | null }) {
  if (!dati) return null;

  const comunali =
    dati.criteri_strutturati + dati.criteri_recuperati + dati.criteri_non_recuperati;
  const leggibili = dati.criteri_strutturati + dati.criteri_recuperati;
  const pctIlleggibili = comunali > 0 ? Math.round((dati.criteri_non_recuperati / comunali) * 100) : 0;

  const quote = [
    {
      chiave: "strutturati",
      etichetta: "Requisiti strutturati",
      valore: dati.criteri_strutturati,
      spiega: "pubblicati in un campo, leggibili senza interpretazione",
    },
    {
      chiave: "recuperati",
      etichetta: "Recuperati dalla prosa",
      valore: dati.criteri_recuperati,
      spiega: "estratti da un testo, con la frase ricontrollata sulla fonte",
    },
    {
      chiave: "illeggibili",
      etichetta: "Nessun requisito leggibile",
      valore: dati.criteri_non_recuperati,
      spiega: "il servizio è pubblicato, le condizioni per accedervi no",
    },
  ];

  const maxFonte = Math.max(...dati.fonti.map((f) => f.servizi), 1);

  return (
    <section className="panel panoramica">
      <h2>Cosa abbiamo letto finora</h2>

      {/* The finding first. An inventory of what we hold is the least
          interesting true thing on this page. */}
      <p className="panoramica__titolo">
        Su <strong>{comunali}</strong> servizi comunali letti,{" "}
        <strong>{dati.criteri_non_recuperati}</strong> non pubblicano condizioni
        che si possano leggere — il <strong>{pctIlleggibili}%</strong>.
      </p>

      <div className="quote">
        {quote.map((q) => (
          <div
            key={q.chiave}
            className="quote__parte"
            data-tipo={q.chiave}
            style={{ flexGrow: Math.max(q.valore, 0.6) }}
            title={`${q.etichetta}: ${q.valore}`}
          />
        ))}
      </div>
      <ul className="quote__legenda">
        {quote.map((q) => (
          <li key={q.chiave} data-tipo={q.chiave}>
            <span className="quote__cifra">{q.valore}</span>
            <span className="quote__etichetta">{q.etichetta}</span>
            <span className="quote__spiega">{q.spiega}</span>
          </li>
        ))}
      </ul>

      <div className="vitali">
        <div className="vitale">
          <span className="vitale__cifra">{dati.servizi_totali}</span>
          <span className="vitale__etichetta">Servizi letti</span>
        </div>
        <div className="vitale">
          <span className="vitale__cifra">{dati.enti_totali}</span>
          <span className="vitale__etichetta">Enti catalogati</span>
        </div>
        <div className="vitale">
          <span className="vitale__cifra">{leggibili}</span>
          <span className="vitale__etichetta">Servizi con condizioni leggibili</span>
        </div>
        <div className="vitale">
          <span className="vitale__cifra">
            {dati.ultimo_accesso ? dataOraIt(dati.ultimo_accesso) : "mai"}
          </span>
          <span className="vitale__etichetta">Ultima lettura delle fonti</span>
        </div>
      </div>

      <h3 className="panoramica__sotto">Da chi vengono</h3>
      <ul className="fonti-agg">
        {dati.fonti.map((f) => (
          <li key={f.tipo}>
            <span className="fonti-agg__tipo">{f.tipo}</span>
            <span className="fonti-agg__barra" role="presentation">
              <span
                className="fonti-agg__fill"
                style={{ width: `${Math.max(2, (f.servizi / maxFonte) * 100)}%` }}
              />
            </span>
            <span className="fonti-agg__cifra">
              {f.servizi} servizi · {f.enti} {f.enti === 1 ? "ente" : "enti"}
            </span>
          </li>
        ))}
      </ul>
      <p className="fonti-agg__nota">
        Le misure nazionali valgono ovunque, quelle comunali solo dove sono state
        pubblicate: è la differenza che decide cosa una risposta significa per
        chi la legge, ed è per questo che i conteggi stanno separati.
      </p>
    </section>
  );
}
