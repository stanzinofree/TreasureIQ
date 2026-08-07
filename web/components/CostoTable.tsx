/**
 * What each measured comune costs TreasureIQ to keep readable.
 *
 * This is the page's answer to "so what?". The pagella beside it grades how
 * openly a comune publishes; this says what that openness is worth in work,
 * and the two are kept apart because merging them would let our hardware and
 * their file sizes leak into a judgement of their administration.
 *
 * The headline figure is cost *per record*, not the total. A comune needing a
 * bespoke connector for fifteen records is more expensive to read than one
 * needing a parser for forty, and a total hides exactly that — which is the
 * single most useful thing an administrator could learn from this table.
 *
 * Bars are drawn from the same numbers as the text, in plain divs, and every
 * one carries its figure in writing beside it: a chart nobody can read the
 * values off is decoration.
 */

import type { Costo } from "@/lib/api";

const MODO_LABEL: Record<string, string> = {
  M1_campo_tipizzato: "Campo tipizzato",
  M2_prosa_api: "Prosa dentro l'API",
  M3_allegato: "Allegato PDF",
  M4_connettore: "Connettore su misura",
  M5_nessuno: "Nulla di pubblicato",
  M6_web_aperto: "Solo web aperto",
};

function dataIt(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

export default function CostoTable({ costi }: { costi: Costo[] }) {
  if (costi.length === 0) return null;

  const massimo = Math.max(...costi.map((c) => c.costo_per_record ?? 0), 0.01);

  return (
    <section className="panel">
      <h2>Quanto ci costa leggerli</h2>
      <p className="lede">
        Non è una pagella per il comune: è il conto di TreasureIQ. Misura il
        lavoro che serve a noi per rendere leggibile quello che loro hanno
        pubblicato — e più quel numero è alto, più quel lavoro potrebbe essere
        risparmiato a chiunque, semplicemente pubblicando i requisiti in forma
        strutturata.
      </p>

      <ul className="costo-lista">
        {costi.map((c) => {
          const perRecord = c.costo_per_record ?? 0;
          const larghezza = Math.max(2, Math.round((perRecord / massimo) * 100));
          return (
            <li key={c.codice_istat} className="costo-riga">
              <div className="costo-riga__testa">
                <h3>{c.ente}</h3>
                <span className="costo-riga__modo">
                  {MODO_LABEL[c.modo] ?? c.modo}
                </span>
              </div>

              <div className="costo-barra" role="presentation">
                <div className="costo-barra__fill" style={{ width: `${larghezza}%` }} />
              </div>
              <p className="costo-riga__cifra">
                <strong>{perRecord}</strong> per record · {c.costo_totale} in totale su{" "}
                {c.record_totali} servizi
              </p>

              {/* Where the cost comes from: how the criteria were published,
                  counted. A record with structured requirements is read once;
                  one whose criteria sit in prose buys an extraction attempt
                  every time the page is republished, and may still yield
                  nothing. */}
              <dl className="costo-conteggi">
                <div>
                  <dt>Requisiti strutturati</dt>
                  <dd>{c.record_strutturati}</dd>
                </div>
                <div>
                  <dt>Recuperati dalla prosa</dt>
                  <dd>{c.record_recuperati_da_prosa}</dd>
                </div>
                <div>
                  <dt>Tentati a vuoto</dt>
                  <dd>{c.record_non_recuperati}</dd>
                </div>
              </dl>

              <p className="costo-riga__nota">
                Via d&apos;accesso accertata il {dataIt(c.scoperta_il)}
                {c.scoperta_scaduta ? (
                  <span className="costo-riga__scaduta">
                    {" "}
                    — ha {c.eta_scoperta_giorni} giorni, oltre la soglia di{" "}
                    {c.soglia_riscoperta_giorni}: va riverificata
                  </span>
                ) : (
                  <> — entro la soglia di {c.soglia_riscoperta_giorni} giorni</>
                )}
                {c.secondi_recupero != null && (
                  <>
                    {" "}
                    · {c.secondi_recupero} s di recupero misurati
                    <span className="costo-riga__fuori"> (evidenza, non nel conto)</span>
                  </>
                )}
              </p>
            </li>
          );
        })}
      </ul>

      <p className="costo-metodo">
        Il conto è fatto di fatti contati — a che livello siamo dovuti scendere
        per leggere, quanti requisiti erano già strutturati, quanti hanno
        richiesto un&apos;estrazione e quanti l&apos;hanno restituita a vuoto. Il
        tempo di recupero è riportato ma non entra nel punteggio: misura la
        nostra macchina e il peso dei loro allegati quanto la loro apertura, e
        due esecuzioni su computer diversi non sarebbero confrontabili.
      </p>

      {/* Stated as a plan, in the future tense, and separated from the
          measurements above. A roadmap described as if it were running is the
          easiest thing to write and the fastest way to lose the credibility
          the rest of this page is spending its numbers to earn. */}
      <p className="costo-metodo costo-metodo--futuro">
        <strong>Non ancora fatto.</strong> Oggi la scoperta della via
        d&apos;accesso è manuale e ogni misura qui sopra è stata rilevata a
        mano. Il passo successivo previsto è un processo che sorvegli le
        scadenze di questa tabella, interroghi periodicamente l&apos;Indice
        della Pubblica Amministrazione per accorgersi di fonti nuove, e
        rimisuri i portali per conto proprio — così che il costo di scoperta
        non ricada su chi arriva per primo. Non c&apos;è, e finché non ci sarà
        queste cifre restano fotografie datate, non un monitoraggio.
      </p>
    </section>
  );
}
