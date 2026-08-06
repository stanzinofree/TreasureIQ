import type { Metadata } from "next";

import {
  getCensimento,
  getConnettori,
  type Censimento,
  type Connettore,
} from "@/lib/api";
import { coloreP, nome } from "@/lib/palette";

export const metadata: Metadata = {
  title: "Connettori — TreasureIQ",
  description:
    "Le sonde di TreasureIQ: quali piattaforme comunali sappiamo leggere, e fin dove.",
};

export const dynamic = "force-dynamic";

const LIVELLI: Record<
  Connettore["livello"],
  { titolo: string; spiega: string }
> = {
  modello: {
    titolo: "Legge le schede",
    spiega:
      "Sappiamo aprire una scheda servizio e ricavarne le sezioni del modello AgID: a chi è rivolto, cosa serve, entro quando.",
  },
  catalogo: {
    titolo: "Conta il catalogo",
    spiega:
      "Sappiamo quanti servizi pubblica e quanto è fresco l'ultimo, ma non ancora leggerne il contenuto sezione per sezione.",
  },
  firma: {
    titolo: "Riconosce la piattaforma",
    spiega:
      "La sappiamo distinguere in un censimento — quindi la sappiamo contare e misurarne la diffusione — ma non leggere.",
  },
};

export default async function ConnectorsPage() {
  let connettori: Connettore[] = [];
  let censimento: Censimento | null = null;
  let errore: string | null = null;
  try {
    [connettori, censimento] = await Promise.all([
      getConnettori(),
      getCensimento(),
    ]);
  } catch (e) {
    errore = e instanceof Error ? e.message : "errore sconosciuto";
  }

  if (errore) {
    return (
      <main className="shell pagina">
        <div className="stack">
          <h1>Connettori</h1>
          <p className="vuoto">L&apos;API non risponde: {errore}</p>
        </div>
      </main>
    );
  }

  const diffusione = new Map(
    censimento?.piattaforme.map((p) => [p.piattaforma, p]) ?? [],
  );
  const ordine = censimento?.piattaforme.map((p) => p.piattaforma) ?? [];
  const perLivello = (l: Connettore["livello"]) =>
    connettori
      .filter((c) => c.livello === l)
      .sort(
        (a, b) =>
          (diffusione.get(b.piattaforma)?.comuni ?? 0) -
          (diffusione.get(a.piattaforma)?.comuni ?? 0),
      );

  return (
    <main className="shell pagina">
      <div className="stack">
        <p className="occhiello">Le sonde</p>
        <h1>Cosa sappiamo leggere, e fin dove</h1>
        <p className="sottotitolo">
          Un connettore per il modello AgID, non uno per prodotto: le sezioni di
          una scheda servizio sono le stesse su WordPress, PeopleWeb, Plone e
          Drupal. Cambia solo il tag che le contiene, e quello è un dialetto —
          non un sistema nuovo.
        </p>
        <p className="nota">
          Questo elenco è costruito dal codice, non scritto a mano. Una
          piattaforma che perde la sua declinazione sparisce da qui lo stesso
          giorno, invece di restare in vetrina a promettere una lettura che non
          facciamo più.
        </p>

        {(["modello", "catalogo", "firma"] as const).map((livello) => {
          const righe = perLivello(livello);
          if (!righe.length) return null;
          return (
            <section key={livello}>
              <h2>{LIVELLI[livello].titolo}</h2>
              <p className="nota">{LIVELLI[livello].spiega}</p>
              <ul className="schede-connettori">
                {righe.map((c) => {
                  const d = diffusione.get(c.piattaforma);
                  return (
                    <li
                      key={c.piattaforma}
                      style={{
                        borderLeftColor: coloreP(c.piattaforma, ordine),
                      }}
                    >
                      <h3>{nome(c.piattaforma)}</h3>
                      <p className="diffusione">
                        {d
                          ? `${d.comuni} ${d.comuni === 1 ? "comune" : "comuni"} nel campione`
                          : "non ancora incontrata"}
                        {d && d.servizi
                          ? ` · ${d.servizi.toLocaleString("it-IT")} servizi letti`
                          : ""}
                      </p>
                      {c.rotta_servizi && <code>{c.rotta_servizi}</code>}
                      {c.note && <p className="nota-connettore">{c.note}</p>}
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}

        <h2>Quello che non sappiamo ancora leggere</h2>
        <p className="nota">
          I portali che non si dichiarano sono la metà dei comuni italiani, e
          non sono tutti diversi fra loro: sono pochi fornitori che non firmano
          il proprio lavoro. Il censimento registra per ognuno i segnali grezzi
          — nome del server, estensioni delle rotte, directory degli asset —
          così i fornitori nuovi si raggruppano da soli interrogando lo storico,
          senza rifare un giro sull&apos;Italia.
        </p>
        {diffusione.get("ignota") && (
          <p className="nota">
            Nell&apos;ultimo rilevamento restano{" "}
            <strong>
              {diffusione.get("ignota")!.comuni} portali non riconosciuti
            </strong>
            : è la misura onesta di quanta strada manca, e cala ogni volta che
            una firma nuova entra nel censimento.
          </p>
        )}
      </div>
    </main>
  );
}
