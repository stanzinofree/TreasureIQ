import type { Metadata } from "next";

import { GraficoDiffusione } from "@/components/analytics/GraficoDiffusione";
import { GraficoPiattaforme } from "@/components/analytics/GraficoPiattaforme";
import { GraficoSezioni } from "@/components/analytics/GraficoSezioni";
import { getCensimento, type Censimento } from "@/lib/api";
import { nome } from "@/lib/palette";

export const metadata: Metadata = {
  title: "Analytics — TreasureIQ",
  description:
    "Il censimento dei portali comunali italiani: piattaforme, aderenza, sezioni mancanti.",
};

export const dynamic = "force-dynamic";

function percentuale(n: number, su: number): string {
  return su ? `${Math.round((n * 100) / su)}%` : "—";
}

export default async function AnalyticsPage() {
  let dati: Censimento | null = null;
  let errore: string | null = null;
  try {
    dati = await getCensimento();
  } catch (e) {
    errore = e instanceof Error ? e.message : "errore sconosciuto";
  }

  if (errore) {
    return (
      <main className="shell pagina">
        <div className="stack">
          <h1>Analytics</h1>
          <p className="vuoto">L&apos;API non risponde: {errore}</p>
        </div>
      </main>
    );
  }

  const censimento = dati!;
  const totale = censimento.piattaforme.reduce((s, r) => s + r.comuni, 0);
  const serviziLetti = censimento.piattaforme.reduce(
    (s, r) => s + r.servizi,
    0,
  );
  const REGIONALI = new Set(["regione_fvg", "regione_veneto", "rete_civica_lepida"]);
  const regionali = censimento.piattaforme
    .filter((r) => REGIONALI.has(r.piattaforma))
    .reduce((s, r) => s + r.comuni, 0);
  const vincoliTotale = censimento.vincoli.reduce((s, v) => s + v.comuni, 0);
  const riconosciuti = censimento.piattaforme
    .filter(
      (r) => r.piattaforma !== "ignota" && r.piattaforma !== "non_misurata",
    )
    .reduce((s, r) => s + r.comuni, 0);
  // Le piattaforme che un connettore sa davvero leggere oggi. NB: il censimento
  // etichetta la famiglia eGov col fingerprint "hgate" (CMS Halley), che il
  // connettore riclassifica a "egov" solo alla lettura profonda — vanno contati
  // entrambi. Tenere in sincrono con _LEGGIBILI in api/treasureiq/registro_cli.py.
  const LEGGIBILI = new Set([
    "municipium",
    "egov",
    "hgate",
    "peopleweb",
    "wp_design_comuni",
    "wordpress_generico",
    "comunibootstrapitalia",
    "comweb",
    "openpa",
  ]);
  const connessi = censimento.piattaforme
    .filter((r) => LEGGIBILI.has(r.piattaforma))
    .reduce((s, r) => s + r.comuni, 0);
  const scoperti = totale - connessi;

  if (!censimento.rilevato_il) {
    return (
      <main className="shell pagina">
        <div className="stack">
          <h1>Analytics</h1>
          <p className="vuoto">
            Nessuno sweep registrato. Non è un guasto: è lo stato di un progetto
            che non ha ancora misurato niente.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="shell pagina">
      <div className="stack">
        <p className="occhiello">Censimento dei portali comunali</p>
        <h1>Cosa pubblicano davvero i comuni italiani</h1>
        <p className="sottotitolo">
          Rilevamento del{" "}
          {new Date(censimento.rilevato_il).toLocaleDateString("it-IT")} su{" "}
          {totale} comuni. Ogni numero è misurato, mai stimato: dove non abbiamo
          potuto guardare la casella resta vuota.
        </p>

        <section className="tessere">
          <div className="tessera">
            <b>{totale}</b>
            <span>comuni sondati</span>
          </div>
          <div className="tessera">
            <b>{percentuale(riconosciuti, totale)}</b>
            <span>con piattaforma riconosciuta</span>
          </div>
          <div className="tessera">
            <b>{serviziLetti.toLocaleString("it-IT")}</b>
            <span>servizi contati nei cataloghi</span>
          </div>
          <div className="tessera">
            <b>{censimento.fornitori.length}</b>
            <span>fornitori con aderenza misurata</span>
          </div>
        </section>

        <h2>Su quali piattaforme girano</h2>
        <p className="nota">
          Il tema WordPress ufficiale non è il più diffuso. Chi resta grigio non
          è un fornitore: è un portale che non si è dichiarato, e quella barra
          misura quanta strada resta.
        </p>
        <GraficoPiattaforme righe={censimento.piattaforme} />
      <div className="tabella-scorrevole">
        <table>
          <caption>
            Le stesse piattaforme del grafico, con la loro diffusione geografica.
          </caption>
          <thead>
            <tr>
              <th>Piattaforma</th>
              <th>Comuni</th>
              <th>Quota</th>
              <th>Servizi contati</th>
              <th>Regioni</th>
              <th>Regione principale</th>
            </tr>
          </thead>
          <tbody>
            {censimento.piattaforme.map((p) => (
              <tr key={p.piattaforma}>
                <th scope="row">{nome(p.piattaforma)}</th>
                <td>{p.comuni}</td>
                <td>{totale ? `${((p.comuni * 100) / totale).toFixed(1)}%` : "—"}</td>
                <td>{p.servizi ? p.servizi.toLocaleString("it-IT") : "—"}</td>
                <td>{p.regioni || "—"}</td>
                <td>
                  {p.regione_prima
                    ? `${p.regione_prima} (${Math.round((p.comuni_prima * 100) / p.comuni)}%)`
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Quanti comuni un connettore sa già leggere</h2>
      <p className="nota">
        Non basta sapere su che piattaforma gira un comune: serve un connettore
        scritto per quella piattaforma. Oggi ne abbiamo per{" "}
        <strong>Municipium</strong>, per la famiglia <strong>eGov</strong> (il
        CMS Halley, che il censimento etichetta &laquo;hgate&raquo;), per i due
        vendor <strong>PeopleWeb</strong> (SoluzioniPA OpenWeb e Siscom) e per la
        famiglia <strong>WordPress-AgID</strong> (il tema ufficiale dei comuni e
        le sue varianti), e per <strong>ComWeb</strong> (ePublic) e{" "}
        <strong>OpenPA</strong> (Maggioli). Da quei comuni sappiamo tirare fuori
        uffici, servizi e amministrazione trasparente; dagli altri, per ora, no.
      </p>
      <div className="tessere">
        <div className="tessera">
          <b>{connessi.toLocaleString("it-IT")}</b>
          <span>
            comuni con connettore ({percentuale(connessi, totale)} del
            censimento)
          </span>
        </div>
        <div className="tessera">
          <b>{scoperti.toLocaleString("it-IT")}</b>
          <span>
            comuni ancora senza connettore ({percentuale(scoperti, totale)})
          </span>
        </div>
      </div>
      <p className="nota">
        &laquo;Senza connettore&raquo; non vuol dire invisibili: il censimento li
        ha misurati lo stesso. Vuol dire che il prossimo fornitore da coprire si
        sceglie da qui — la barra più alta fra i grigi è il connettore che
        sblocca più comuni per lo stesso lavoro.
      </p>

      <h2>Prodotti nazionali o piattaforme regionali?</h2>
      <p className="nota">
        La colonna «comuni» non distingue un fornitore diffuso su tutta Italia da una
        piattaforma che una Regione mette a disposizione dei propri comuni: sono due
        fenomeni diversi con lo stesso aspetto. Qui si separano da soli — in basso a
        destra i prodotti nazionali, in alto a sinistra chi sta in una regione sola e lì
        vale tutto. La dimensione del punto è il numero di comuni.
      </p>
      <GraficoDiffusione righe={censimento.piattaforme} />
      <p className="nota">
        Sono escluse le piattaforme sotto i 30 comuni: sotto quella soglia il dato
        geografico è un aneddoto, non una distribuzione.
      </p>

      <h2>Tre regioni hanno risolto il problema una volta sola</h2>
      <p className="nota">
        {regionali} comuni non stanno su un portale comprato da soli: stanno su una
        piattaforma condivisa messa a disposizione dalla propria Regione — Friuli-Venezia
        Giulia, Veneto, e la Rete Civica di Lepida in Emilia-Romagna. È il modello che
        altrove ogni comune affronta per conto suo, e sono i portali più uniformi del
        censimento.
      </p>

        <h2>Quanto aderiscono al modello AgID</h2>
        <p className="nota">
          Le due basi di misura <strong>non vanno confrontate fra loro</strong>.
          Leggendo l&apos;HTML si misura sul modello intero; leggendo i campi
          tipizzati si misura sui soli box che l&apos;API espone. A denominatore
          unico il fornitore più conforme risulterebbe ultimo.
        </p>
        <div className="tabella-scorrevole">
          <table>
            <thead>
              <tr>
                <th>Fornitore</th>
                <th>Base di misura</th>
                <th>Comuni</th>
                <th>Misurati</th>
                <th>Aderenza media</th>
                <th>Minima</th>
                <th>Impronte</th>
              </tr>
            </thead>
            <tbody>
              {censimento.fornitori.map((f) => (
                <tr key={`${f.piattaforma}-${f.base_misura}`}>
                  <th scope="row">{nome(f.piattaforma)}</th>
                  <td>
                    {f.base_misura === "schema_esposto"
                      ? "schema esposto"
                      : "modello intero"}
                  </td>
                  <td>{f.comuni}</td>
                  <td>{f.misurati}</td>
                  <td>
                    {f.aderenza_media === null
                      ? "—"
                      : `${Math.round(f.aderenza_media * 100)}%`}
                  </td>
                  <td>
                    {f.aderenza_minima === null
                      ? "—"
                      : `${Math.round(f.aderenza_minima * 100)}%`}
                  </td>
                  <td>{f.impronte}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="nota">
          <strong>Impronte</strong> conta le forme strutturali distinte viste
          per quel fornitore. Uno significa un template uniforme; molte
          significano deployment che hanno divergiato, e un connettore scritto
          su uno non calza sugli altri. È anche l&apos;allarme: quando
          l&apos;impronta si muove su molti comuni la stessa notte, quel
          fornitore ha cambiato template e qualcosa sta per rompersi.
        </p>

        <h2>Chi ha diritto? Il campo c&apos;è, ed è vuoto</h2>
      <p className="nota">
        Le piattaforme con campi tipizzati prevedono tutte un posto dove scrivere i
        requisiti di accesso — chi può chiedere quel servizio. Su {vincoliTotale} comuni
        dove la domanda si può porre, ecco cosa c&apos;è scritto.
      </p>
      <div className="tessere">
        {censimento.vincoli.map((v) => (
          <div className="tessera" key={v.stato}>
            <b>{vincoliTotale ? `${Math.round((v.comuni * 100) / vincoliTotale)}%` : "—"}</b>
            <span>
              {v.stato === "vuoto" && `${v.comuni} comuni: campo presente, lasciato vuoto`}
              {v.stato === "compilato" && `${v.comuni} comuni: requisiti pubblicati`}
              {v.stato === "assente" && `${v.comuni} comuni: la piattaforma non prevede il campo`}
            </span>
          </div>
        ))}
      </div>
      <p className="nota">
        La distinzione conta: <strong>assente</strong> è una scelta del fornitore, e quei
        comuni non potrebbero pubblicare i requisiti nemmeno volendo.{" "}
        <strong>Vuoto</strong> è una scelta del comune. Sommarli darebbe la colpa a chi
        non ce l&apos;ha.
      </p>
      <p className="nota">
        Questi numeri valgono sui comuni con campi tipizzati, non su tutti i 7.896: dove
        le schede si leggono in HTML la domanda non si può porre, e riportarli come
        &laquo;non pubblicano&raquo; sarebbe accusarli di un silenzio che non abbiamo
        misurato.
      </p>

      <h2>Cosa manca più spesso</h2>
        <p className="nota">
          In rosso le sezioni senza cui un cittadino non può agire. Una scadenza
          che non c&apos;è non si nota leggendo la pagina: la si scopre quando
          il diritto è decaduto.
        </p>
        <GraficoSezioni righe={censimento.sezioni_mancanti} />
        <div className="tabella-scorrevole">
          <table>
            <caption>
              Le stesse cifre in tabella, per chi non legge i colori.
            </caption>
            <thead>
              <tr>
                <th>Sezione del modello</th>
                <th>Manca su</th>
                <th>Portali misurati</th>
              </tr>
            </thead>
            <tbody>
              {censimento.sezioni_mancanti.map((s) => (
                <tr key={s.sezione}>
                  <th scope="row">{s.sezione.replace(/_/g, " ")}</th>
                  <td>{s.manca_su}</td>
                  <td>{s.misurati}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
