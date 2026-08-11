"use client";

import { useEffect, useState } from "react";
import {
  fetchMappaConnettore,
  fetchSchedaServizio,
  fetchServiziCategoria,
  type CategoriaServizio,
  type MappaConnettore,
  type SchedaServizio,
  type ServizioLink,
} from "@/lib/api";

/**
 * La mappa servizi di un comune col portale REST-indirizzabile (modello AgID,
 * 15 categorie standard): il cittadino tocca una categoria invece di ridigitare
 * e la lettura live si restringe a quella. Vive nel pannello di sinistra, non in
 * chat, per tenere la conversazione pulita — la cascata è navigazione nel
 * catalogo, non una nuova domanda.
 *
 * NON è un verdetto e non promette il bonus: il catalogo AgID sono i servizi
 * amministrativi («come faccio la IMU»), non le agevolazioni — quelle vivono in
 * amministrazione-trasparente e restano ricerca web.
 *
 * Fetch pigro e su richiesta: la chiamata legge il portale a freddo (cache 30g)
 * e può tardare. Un errore o un catalogo vuoto non disegna nulla — mai un
 * guscio rotto nel pannello.
 */
export default function MappaServizi({
  istat,
  variante,
}: {
  istat: string;
  /** «pannello»: si incornicia in un accordion collassato nel pannello di
   *  sinistra e resta muto finché il catalogo non è pronto (niente riga di
   *  caricamento nella colonna). Default: inline, come stava in chat. */
  variante?: "pannello";
}) {
  const [mappa, setMappa] = useState<MappaConnettore | null>(null);
  const [stato, setStato] = useState<"carico" | "pronto" | "vuoto">("carico");

  // Livello aperto: la categoria scelta e i suoi servizi. La cascata vive tutta
  // qui, senza mandare messaggi in chat — scendere di livello è navigazione nel
  // catalogo, non una nuova domanda che rifà la ricerca web (bug fase 1).
  const [aperta, setAperta] = useState<CategoriaServizio | null>(null);
  const [servizi, setServizi] = useState<ServizioLink[] | null>(null);
  const [statoServizi, setStatoServizi] = useState<"carico" | "pronto" | "vuoto">(
    "carico",
  );

  // Terzo livello: il servizio aperto e la sua anteprima, letta adesso dalla
  // pagina. Invece di sbalzare subito sul sito si mostra qui cosa è il servizio
  // (come l'anteprima di un bando), col link per aprirlo intero. Fonte, non
  // verdetto (D-01).
  const [apertoServizio, setApertoServizio] = useState<ServizioLink | null>(null);
  const [scheda, setScheda] = useState<SchedaServizio | null>(null);
  const [statoScheda, setStatoScheda] = useState<"carico" | "pronto" | "vuoto">(
    "carico",
  );

  function chiudiTutto() {
    setAperta(null);
    setServizi(null);
    setApertoServizio(null);
    setScheda(null);
  }

  useEffect(() => {
    let vivo = true;
    setStato("carico");
    setMappa(null);
    chiudiTutto();
    fetchMappaConnettore(istat)
      .then((m) => {
        if (!vivo) return;
        if (m && m.servizi.esposto && m.servizi.categorie.length > 0) {
          setMappa(m);
          setStato("pronto");
        } else {
          setStato("vuoto");
        }
      })
      .catch(() => {
        if (vivo) setStato("vuoto");
      });
    return () => {
      vivo = false;
    };
  }, [istat]);

  function apri(cat: CategoriaServizio) {
    if (!cat.id) return; // senza term non si può filtrare: chip non-imbuto
    setAperta(cat);
    setServizi(null);
    setStatoServizi("carico");
    setApertoServizio(null);
    setScheda(null);
    fetchServiziCategoria(istat, cat.id)
      .then((lista) => {
        setServizi(lista ?? []);
        setStatoServizi(lista && lista.length > 0 ? "pronto" : "vuoto");
      })
      .catch(() => setStatoServizi("vuoto"));
  }

  function apriScheda(s: ServizioLink) {
    setApertoServizio(s);
    setScheda(null);
    setStatoScheda("carico");
    fetchSchedaServizio(istat, s.url)
      .then((sc) => {
        setScheda(sc);
        setStatoScheda(sc ? "pronto" : "vuoto");
      })
      .catch(() => setStatoScheda("vuoto"));
  }

  function tornaAiServizi() {
    setApertoServizio(null);
    setScheda(null);
  }

  if (stato === "vuoto") return null;
  if (stato === "carico") {
    // Nel pannello non mostriamo la riga di attesa: la colonna resta pulita
    // finché il catalogo non è pronto (poi appare l'accordion, già utile).
    if (variante === "pannello") return null;
    return (
      <p className="mappa-servizi__carico" role="status">
        Leggo il catalogo servizi del comune…
      </p>
    );
  }
  if (!mappa) return null;

  const corpo = (
    <div className="mappa-servizi" role="group" aria-label="Servizi del comune">
      {/* Filo di briciole: dove sei nella cascata. La scelta precedente resta
          a schermo, evidenziata e cliccabile per risalire — «scegli tra queste
          cose» con la memoria dei passi, non un menù che riparte ogni volta. */}
      <p className="mappa-servizi__briciole">
        <button
          type="button"
          className={
            "mappa-servizi__briciola" +
            (aperta ? " mappa-servizi__briciola--link" : " mappa-servizi__briciola--qui")
          }
          onClick={() => aperta && chiudiTutto()}
          disabled={!aperta}
        >
          {mappa.servizi.totale} servizi
        </button>
        {aperta && (
          <>
            <span className="mappa-servizi__freccia" aria-hidden="true">
              ›
            </span>
            {/* La categoria: «qui» quando è l'ultimo passo, link per tornare
                alla lista quando si è aperta una scheda sotto. */}
            <button
              type="button"
              className={
                "mappa-servizi__briciola" +
                (apertoServizio
                  ? " mappa-servizi__briciola--link"
                  : " mappa-servizi__briciola--qui")
              }
              onClick={() => apertoServizio && tornaAiServizi()}
              disabled={!apertoServizio}
            >
              {aperta.nome}
            </button>
          </>
        )}
        {apertoServizio && (
          <>
            <span className="mappa-servizi__freccia" aria-hidden="true">
              ›
            </span>
            <span className="mappa-servizi__briciola mappa-servizi__briciola--qui">
              {apertoServizio.titolo}
            </span>
          </>
        )}
      </p>

      {!aperta && (
        <>
          <p className="mappa-servizi__intro">
            Scegli una categoria per vedere i servizi che il comune pubblica lì:
          </p>
          <div className="mappa-servizi__chip-riga">
            {mappa.servizi.categorie.map((cat: CategoriaServizio) => (
              <button
                key={cat.nome}
                type="button"
                className="scelta-comune__scheda mappa-servizi__chip"
                onClick={() => apri(cat)}
                disabled={!cat.id}
              >
                <span className="scelta-comune__nome">{cat.nome}</span>
                <span className="mappa-servizi__chip-conteggio">{cat.conteggio}</span>
              </button>
            ))}
          </div>
        </>
      )}

      {aperta && statoServizi === "carico" && (
        <p className="mappa-servizi__carico" role="status">
          Leggo i servizi di «{aperta.nome}»…
        </p>
      )}

      {aperta && statoServizi === "vuoto" && (
        <p className="mappa-servizi__intro">
          Il portale conta {aperta.conteggio} servizi in «{aperta.nome}» ma non li
          elenca via API. Aprili dal{" "}
          {mappa.sito ? (
            <a
              href={`https://${mappa.sito}`}
              target="_blank"
              rel="noopener noreferrer"
              className="mappa-servizi__link"
            >
              portale del comune
            </a>
          ) : (
            "portale del comune"
          )}
          .
        </p>
      )}

      {aperta && !apertoServizio && statoServizi === "pronto" && servizi && (
        <ul className="mappa-servizi__servizi">
          {servizi.map((s) => (
            <li key={s.url} className="mappa-servizi__servizio">
              {/* Non è più un link diretto: apre l'anteprima qui, poi da lì si
                  va sul sito. Un passo in più, ma il cittadino sa cosa apre. */}
              <button
                type="button"
                className="mappa-servizi__servizio-tap"
                onClick={() => apriScheda(s)}
              >
                {s.titolo}
              </button>
            </li>
          ))}
        </ul>
      )}

      {apertoServizio && statoScheda === "carico" && (
        <p className="mappa-servizi__carico" role="status">
          Leggo la scheda di «{apertoServizio.titolo}»…
        </p>
      )}

      {apertoServizio && statoScheda === "vuoto" && (
        <p className="mappa-servizi__intro">
          Non sono riuscito a leggere l'anteprima adesso. Aprila direttamente sul{" "}
          <a
            href={apertoServizio.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mappa-servizi__link"
          >
            portale del comune
          </a>
          .
        </p>
      )}

      {apertoServizio && statoScheda === "pronto" && scheda && (
        // Anteprima come per un bando: cosa è il servizio, a chi è rivolto e
        // cosa si ottiene, letto adesso dalla pagina. Card GIALLA: il giallo
        // segnala «dato non certissimo», letto dal vivo, non ingerito.
        <div className="mappa-servizi__scheda">
          <span className="mappa-servizi__scheda-titolo">{scheda.titolo}</span>
          {scheda.a_chi && (
            <span className="mappa-servizi__scheda-campo">
              <span className="mappa-servizi__scheda-etichetta">A chi è rivolto</span>
              {scheda.a_chi}
            </span>
          )}
          {scheda.descrizione && (
            <span className="mappa-servizi__scheda-campo">
              <span className="mappa-servizi__scheda-etichetta">Descrizione</span>
              {scheda.descrizione}
            </span>
          )}
          {scheda.cosa_ottieni && (
            <span className="mappa-servizi__scheda-campo">
              <span className="mappa-servizi__scheda-etichetta">Cosa si ottiene</span>
              {scheda.cosa_ottieni}
            </span>
          )}
          <a
            className="mappa-servizi__scheda-btn"
            href={scheda.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Apri la scheda sul portale del comune ↗
          </a>
          <span className="mappa-servizi__scheda-footer">
            scheda generata dalla lettura live
          </span>
        </div>
      )}
    </div>
  );

  if (variante !== "pannello") return corpo;

  // Nel pannello: accordion collassato di default, così la colonna resta
  // snella e il cittadino apre i servizi solo se li vuole. L'apertura di una
  // categoria/scheda avviene dentro, senza ricaricare o toccare la chat.
  return (
    <details className="pannello__servizi">
      <summary className="pannello__servizi-testa">
        Servizi del comune
        <span className="pannello__servizi-conta">{mappa.servizi.totale}</span>
      </summary>
      {corpo}
    </details>
  );
}
