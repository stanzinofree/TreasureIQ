"use client";

/**
 * The chat itself — the interactive island the server shell in `page.tsx`
 * mounts.
 *
 * Three answer shapes come back from `/api/chat` (K3) and they are kept
 * visually distinct on purpose, because conflating them is the exact failure
 * this project exists to name:
 *
 *   - matches: an answer built from data the engine could evaluate. Rendered
 *     with the same `Seal` / `data-verdict` / `criteria` idiom the cards use
 *     everywhere else.
 *   - data_gap "not_published": the comune never wrote this down. Reuses the
 *     amber `.notice` treatment already used for `unknown_source` criteria
 *     elsewhere in the app — same meaning, same colour.
 *   - data_gap "none_found": nothing matched the question at all. A muted,
 *     neutral treatment, deliberately *not* amber — this is not a data gap,
 *     it is "I found nothing", and dressing it the same as the middle case
 *     would erase the distinction.
 *
 * The mock-SPID picker below is the same three personas that used to live on
 * the home page — relocated here because identity is now something the chat
 * asks for mid-conversation (D-09), not a gate the citizen passes through
 * first.
 */

import { useEffect, useId, useRef, useState } from "react";
import { Seal } from "@/components/Seal";
import { Marchio } from "@/components/Logo";
import EcoProfilo from "@/components/EcoProfilo";
import Segnalazione from "@/components/Segnalazione";
import SchedaDettaglio from "@/components/SchedaDettaglio";
import AccessoSimulato from "@/components/AccessoSimulato";
import SceltaComune from "@/components/SceltaComune";
import RispostaCivica from "@/components/RispostaCivica";
import PonteScala from "@/components/PonteScala";
import { PRESETS } from "@/lib/profili-demo";
import { useProfilo } from "@/lib/profilo";
import { linkFeedback, LINK_ESTERNO } from "@/lib/moduli";
import { conTagVerifica } from "@/lib/testo";
import { useRisultati } from "@/lib/risultati";
import { useScan } from "@/lib/scan";
import ScanLive from "@/components/ScanLive";

/** Stable DOM id for one card, so the side index can link straight to it. */
function ancoraDi(messageId: string, matchId: string): string {
  return `scheda-${messageId}-${matchId}`.replace(/[^a-zA-Z0-9_-]/g, "-");
}
import {
  chat,
  comuneNearby,
  fetchBandi,
  fetchMappaConnettore,
  fetchSchedaServizio,
  fetchServiziCategoria,
  login,
  type Bando,
  type CategoriaServizio,
  type ChatCost,
  type ChatOut,
  type ChatTurn,
  type ComuneAmbiguo,
  type CostLevels,
  type ConnettoreSonda,
  type InfoOut,
  type InfoWebResult,
  type MappaConnettore,
  type Match,
  type SchedaServizio,
  type ServizioLink,
} from "@/lib/api";

/** B22 (D-25) — the segnalazione form only makes sense once every
 * institutional channel is exhausted (D-21's access-mode ladder): a comune
 * publishing structured data (M1/M2/M3) has nothing to ask it to open. */
const SEGNALAZIONE_ACCESS_MODES = new Set(["M4_connettore", "M5_nessuno", "M6_web_aperto"]);

/**
 * What the wait says while it lasts.
 *
 * The old single line read "Sto leggendo i dati del comune…", which named a
 * comune nobody had established — the same claim the hero used to make about
 * residency. These describe only what is actually happening: reading a
 * snapshot, comparing requirements, checking what was published. None of them
 * names an administration, a place or a result.
 */
const ATTESA = [
  "Sto leggendo…",
  "Cerco fra i servizi pubblicati…",
  "Confronto i requisiti…",
  "Verifico cosa è stato pubblicato davvero…",
  "Ci sono quasi…",
];

const GLYPH: Record<string, string> = {
  met: "●",
  not_met: "✕",
  unknown_source: "◐",
  unknown_profile: "◌",
};


const LEVEL_LABEL: Record<keyof CostLevels, string> = {
  L1_manuale: "manuale",
  L2_estratto: "estratto da PDF",
  L3_illeggibile: "illeggibile",
};

/** D-20 — which tier published this opportunity, always shown. */
const LIVELLO_LABEL: Record<Match["livello"], string> = {
  nazionale: "Nazionale",
  regionale: "Regionale",
  comunale: "Comunale",
};

/**
 * D-17 — a one-line caption, not a dashboard: how many seconds it took to
 * recover this answer's criteria from PDF prose, against this comune's
 * average. It says something about how closed the comune's data is, not
 * about how fast TreasureIQ is — `answer_seconds` is deliberately left out
 * so that reading doesn't compete with the answer above it.
 *
 * Every number is independently optional (D-17): a field that is `null`
 * renders nothing, never a zero, so an unmeasured cost can never be
 * mistaken for a measured one.
 */
function CostStrip({ cost }: { cost: ChatCost }) {
  const { recovery_seconds_total: total, recovery_seconds_avg_comune: avg, levels } = cost;

  const levelEntries = levels
    ? (Object.keys(LEVEL_LABEL) as (keyof CostLevels)[]).filter(
        (key) => levels[key] != null,
      )
    : [];

  if (total == null && avg == null && levelEntries.length === 0) {
    return null;
  }

  const max = Math.max(total ?? 0, avg ?? 0, 1);
  const totalPct = total != null ? Math.min(100, (total / max) * 100) : null;
  const avgPct = avg != null ? Math.min(100, (avg / max) * 100) : null;

  return (
    <div className="cost-strip" role="note">
      {(totalPct != null || avgPct != null) && (
        <svg
          className="cost-strip__bars"
          width="96"
          height="14"
          viewBox="0 0 96 14"
          aria-hidden="true"
        >
          {avgPct != null && (
            <rect x="0" y="8" width={avgPct * 0.96} height="4" fill="var(--sumi-faint)" />
          )}
          {/* --fuji was retired with the palette change, and this bar had been
              painting itself with an undefined custom property ever since. */}
          {totalPct != null && (
            <rect x="0" y="1" width={totalPct * 0.96} height="4" fill="var(--ai)" />
          )}
        </svg>
      )}
      <p className="cost-strip__text">
        {total != null && (
          <>
            Recupero dati da PDF per questa risposta: <strong>{Math.round(total)} s</strong>
            {avg != null && <> (media del comune {Math.round(avg)} s)</>}.
          </>
        )}
        {total == null && avg != null && (
          <>
            Media di recupero dati da PDF del comune: <strong>{Math.round(avg)} s</strong>.
          </>
        )}
        {levelEntries.length > 0 && (
          <span className="cost-strip__levels">
            {" "}
            {levelEntries.map((key) => `${LEVEL_LABEL[key]} ×${levels![key]}`).join(" · ")}
          </span>
        )}
      </p>
    </div>
  );
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  reply?: ChatOut;
}

function MatchCard({
  match,
  ancora,
  onApri,
}: {
  match: Match;
  ancora: string;
  onApri: () => void;
}) {
  const decided = match.criteria.filter(
    (c) => c.state === "met" || c.state === "not_met",
  );
  const unpublished = match.criteria.filter((c) => c.state === "unknown_source");
  const askProfile = match.criteria.filter((c) => c.state === "unknown_profile");

  return (
    <article id={ancora} className="card" data-verdict={match.verdict}>
      <Seal verdict={match.verdict} size={40} />
      <div>
        <h3 className="card__title">{match.title}</h3>
        <p className="card__headline">{match.headline}</p>

        <div className="card__meta">
          <span className="tag">{match.verdict_label}</span>
          <span className="tag tag--livello" data-livello={match.livello}>
            {LIVELLO_LABEL[match.livello]}
          </span>
          <span>{match.kind.replace(/_/g, " ")}</span>
          {match.deadline && <span>scade il {match.deadline}</span>}
        </div>

        <ul className="criteria">
          {decided.map((c) => (
            <li key={c.key} className="criterion" data-state={c.state}>
              <span className="criterion__glyph" aria-hidden="true">
                {GLYPH[c.state]}
              </span>
              <span>
                <strong style={{ fontWeight: 600 }}>{c.label}.</strong> {c.detail}
              </span>
            </li>
          ))}

          {unpublished.length > 0 && (
            <li className="criterion" data-state="unknown_source">
              <span className="criterion__glyph" aria-hidden="true">
                {GLYPH.unknown_source}
              </span>
              <span>
                <strong style={{ fontWeight: 600 }}>Non pubblicati dal comune:</strong>{" "}
                {unpublished.map((c) => c.label.toLowerCase()).join(", ")}. Non
                sappiamo se ti riguardano.
              </span>
            </li>
          )}

          {askProfile.map((c) => (
            <li key={c.key} className="criterion" data-state={c.state}>
              <span className="criterion__glyph" aria-hidden="true">
                {GLYPH[c.state]}
              </span>
              <span>
                <strong style={{ fontWeight: 600 }}>{c.label}.</strong> {c.detail}
              </span>
            </li>
          ))}
        </ul>

        {/* Detail before departure. The link out stays, but the card now
            offers everything a citizen needs *before* leaving — which office
            to ask, by when, what was and was not checked — rather than
            handing them to a municipal site to find it themselves. */}
        <p className="card__azioni">
          <button type="button" className="card__dettagli" onClick={onApri}>
            Vedi i dettagli
          </button>
          <a href={match.source_url} target="_blank" rel="noreferrer">
            Apri la pagina ufficiale →
          </a>
        </p>
      </div>
    </article>
  );
}

function DataGapNotice({ kind }: { kind: "not_published" | "none_found" }) {
  if (kind === "not_published") {
    return (
      <p className="notice" data-gap="not_published">
        <strong>Il comune non lo ha pubblicato.</strong> Non significa che tu
        non abbia diritto: significa che questo dato manca. Verificalo
        direttamente con l&rsquo;ufficio competente.
      </p>
    );
  }
  return (
    <p className="notice notice--muted" data-gap="none_found">
      <strong>Non ho trovato nulla.</strong> Nessun servizio pubblicato sembra
      corrispondere a questa domanda. Prova a riformularla, oppure guarda{" "}
      <a href="/dati">quali dati abbiamo letto</a>.
    </p>
  );
}

/** Only `http`/`https` URLs render as a link (R-15 — a hostile cached
 * result must never resolve to a clickable `javascript:` or bare string).
 * Anything else still shows as plain, quoted text so the citizen sees
 * exactly what the source gave us. */
function isWebUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

/**
 * Le pagine che un motore di ricerca ha trovato sul sito del comune, mai un
 * verdetto. Vive fuori da InfoAnswer perché serve su DUE rail: sul rail
 * INFORMAZIONE (dentro InfoAnswer) e sul rail AGEVOLAZIONE quando il comune è
 * fuori copertura — lì la ricerca live trova le pagine (bandi, servizi) e la
 * risposta le promette («qui sotto trovi quello che ho visto»), ma senza
 * questo blocco la UI le buttava e la promessa restava vuota. Nessun giudizio
 * di spettanza qui: solo link marcati «non verificato», coerente con D-01.
 */
/**
 * Fuori copertura, dopo la ricerca, diciamo anche SE il connettore
 * raggiungerebbe questo comune — la risposta alla domanda «a ricerca fatta,
 * sappiamo cosa interrogare?». Prima si ripiegava in silenzio sulla sola
 * ricerca web anche quando il portale era strutturato e indirizzabile. Non è
 * un verdetto e non ingerisce nulla: è un badge onesto sull'indirizzabilità.
 */
function BadgeConnettore({ sonda }: { sonda: ConnettoreSonda }) {
  if (!sonda.indirizzabile) return null;
  return (
    <p className="badge-connettore" role="note">
      <span className="badge-connettore__pallino" aria-hidden />
      <strong>Raggiungibile dal connettore </strong>
      <span className="tag-connettore">Modello AgID</span>
      {sonda.uffici > 0 ? ` — ${sonda.uffici} uffici esposti` : ""}. Non ancora
      ingestionato: i bandi restano dalla ricerca web qui sopra.
    </p>
  );
}

function PagineWeb({ results }: { results: InfoWebResult[] }) {
  if (results.length === 0) return null;
  return (
    <div className="info-answer__web" data-state="non_verificato" role="note">
      <p className="info-answer__web-label">Ricerca web · non verificato</p>
      <ul>
        {results.slice(0, 3).map((result) => (
          <li key={result.url}>
            <span className="info-answer__web-title">{result.title}</span>
            {isWebUrl(result.url) ? (
              <a
                className="info-answer__web-url"
                href={result.url}
                target="_blank"
                rel="noreferrer"
              >
                {result.url}
              </a>
            ) : (
              <span className="info-answer__web-url">{result.url}</span>
            )}
          </li>
        ))}
      </ul>
      <p className="info-answer__web-note">
        Non è una risposta di TreasureIQ: sono pagine trovate sul web, da
        verificare tu stesso prima di fidartene.
      </p>
    </div>
  );
}

/**
 * Fase 1 della mappa servizi. Sotto il badge connettore di un comune fuori
 * copertura ma indirizzabile, offre le categorie di servizi che quel portale
 * espone davvero (modello AgID, 15 categorie standard): il cittadino ne tocca
 * una invece di ridigitare, e la ricerca live si restringe a quella categoria.
 *
 * NON è un verdetto e non promette il bonus: il catalogo AgID sono i servizi
 * amministrativi («come faccio la IMU»), non le agevolazioni — quelle vivono in
 * amministrazione-trasparente e restano ricerca web. Perciò il rame che questa
 * cascata fa risparmiare è sul rail informativo, mai su quello agevolazioni.
 *
 * Fetch pigro e su richiesta: la chiamata legge il portale a freddo (cache 30g)
 * e può tardare, quindi parte solo quando il badge è già a schermo. Un errore o
 * un catalogo vuoto non disegna nulla — mai un guscio rotto sotto la risposta.
 */
function MappaServizi({ istat }: { istat: string }) {
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
    return (
      <p className="mappa-servizi__carico" role="status">
        Leggo il catalogo servizi del comune…
      </p>
    );
  }
  if (!mappa) return null;

  return (
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
              {/* Non è più un link diretto: apre l'anteprima qui in chat, poi
                  da lì si va sul sito. Un passo in più, ma il cittadino sa cosa
                  sta per aprire. */}
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
}

/** Bandi e avvisi letti adesso da amministrazione trasparente del comune
 *  (`criteri-e-modalita`). Indipendente dalla mappa servizi (D-B6): niente
 *  intent-gating, si carica al mount come la sonda connettore. Nessun
 *  verdetto di apertura (D-B4) — solo data e caveat di verifica. */
function BandiComune({ istat }: { istat: string }) {
  const [bandi, setBandi] = useState<Bando[] | null>(null);
  const [stato, setStato] = useState<"idle" | "caricamento" | "pronto" | "errore">(
    "idle",
  );
  const [aperta, setAperta] = useState(false);

  useEffect(() => {
    let vivo = true;
    setStato("caricamento");
    setBandi(null);
    setAperta(false);
    fetchBandi(istat)
      .then((lista) => {
        if (!vivo) return;
        setBandi(lista);
        setStato("pronto");
      })
      .catch(() => {
        if (vivo) setStato("errore");
      });
    return () => {
      vivo = false;
    };
  }, [istat]);

  // Nessun blocco vuoto persistente (D-B5): comune senza `criteri-e-modalita`
  // o errore di lettura → il blocco non c'è, non un contenitore vuoto.
  if (stato === "errore" || (stato === "pronto" && bandi && bandi.length === 0)) {
    return null;
  }
  if (stato === "idle" || stato === "caricamento" || !bandi) {
    return null;
  }

  function formattaData(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
    const gg = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    return `${gg}/${mm}/${d.getFullYear()}`;
  }

  return (
    <div className="bandi-comune" role="group" aria-label="Bandi e avvisi del comune">
      <button
        type="button"
        className="bandi-comune__header"
        onClick={() => setAperta((a) => !a)}
        aria-expanded={aperta}
      >
        Bandi e avvisi del comune ({bandi.length})
      </button>
      {aperta && (
        <>
          <p className="bandi-comune__caveat">
            Letti adesso dal portale del comune, non verificati: controlla sul sito
            se il bando è ancora aperto.
          </p>
          <ul className="bandi-comune__lista">
            {bandi.map((b) => (
              <li key={b.url} className="bandi-comune__card">
                <span className="bandi-comune__titolo">{b.titolo}</span>
                <span className="bandi-comune__data">{formattaData(b.data)}</span>
                {b.anteprima && (
                  <span className="bandi-comune__anteprima">{b.anteprima}</span>
                )}
                <a
                  className="bandi-comune__link"
                  href={b.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Apri sul portale ↗
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/**
 * D-19 — the INFORMAZIONE rail. Document, office, coverage and diagnosis are
 * facts about a public body's data; nothing here is a verdict, a criterion,
 * or a SPID prompt. If this component ever grows an eligibility badge, the
 * two-rails boundary the whole feature exists to draw has broken.
 */
function InfoAnswer({ info }: { info: InfoOut }) {
  return (
    <div className="info-answer">
      {/* D-32 — letto adesso dal portale del comune, non preso da uno
          snapshot curato. Sta in cima perché qualifica tutto ciò che segue:
          messo in fondo si leggerebbe dopo aver già creduto all'orario. Non è
          la stessa etichetta dei risultati web più sotto — quelli vengono da
          un motore di ricerca, questo dalla fonte, ed è una differenza a
          favore che sarebbe sbagliato appiattire. */}
      {info.letto_dal_vivo && (
        <p className="info-answer__vivo" role="note">
          <span className="info-answer__vivo-bollo">letto ora</span>
          Dal portale del comune, in questo momento e alla lettera. Non è un
          dato che abbiamo verificato né conservato: controllalo alla fonte
          prima di fare un viaggio.
        </p>
      )}

      {info.document && (
        <p className="info-answer__document">
          <a href={info.document.url} target="_blank" rel="noreferrer">
            {info.document.title}
          </a>
        </p>
      )}

      {/* La copertura conta i NOSTRI record. Su una risposta letta dal vivo
          non ce ne sono per definizione — il comune non è fra quelli che
          leggiamo — e scrivere «nessun risultato pubblicato dal comune»
          sotto un orario appena letto dal portale di quel comune dice al
          cittadino l'esatto contrario di quello che ha davanti. */}
      {!info.letto_dal_vivo && (
        <p className="info-answer__coverage">
          {info.coverage_count > 0
            ? `${info.coverage_count} ${info.coverage_count === 1 ? "risultato trovato" : "risultati trovati"} su questo argomento.`
            : "Nessun risultato pubblicato dal comune su questo argomento."}
        </p>
      )}

      {info.diagnosis.length > 0 && (
        <ul className="info-answer__diagnosis">
          {info.diagnosis.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}

      {info.integration_cost.length > 0 && (
        <ul className="info-answer__diagnosis info-answer__cost">
          {info.integration_cost.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}

      {info.office && (
        <p className="info-answer__office">
          <strong>{info.office.nome}</strong>
          {info.office.telefono ? (
            <> — tel. {info.office.telefono}</>
          ) : (
            <> — nessun numero di telefono pubblicato dal comune</>
          )}
          {info.office.email && <> · {info.office.email}</>}
          {info.office.orari && <> · {info.office.orari}</>}
        </p>
      )}

      <PagineWeb results={info.web_results} />
    </div>
  );
}

/** D-29 — what is left on the citizen's shoulders after this answer, shown
 * as its own line, never folded into `CostStrip`. The two numbers answer
 * different questions: what closed data cost TreasureIQ to recover, versus
 * what TreasureIQ could not take off the citizen. */
function EffortCaption({ effort }: { effort: number | null }) {
  if (effort == null || effort <= 0) {
    return null;
  }
  return (
    <p className="effort-caption">
      Cosa resta da fare a te: <strong>{effort}</strong>{" "}
      {effort === 1 ? "azione" : "azioni"}.
    </p>
  );
}

// D-S6 (B6): scan assente/stantio (>6gg) → refresh partito in background,
// dati di QUESTO turno restano quelli in cache — nessuna attesa sincrona.
// `stato === "fresco"` → nessun indicatore, la risposta non lo segnala.
// La spia (banda che lampeggia + bottone «Ricarica») vive ora in <ScanLive>,
// alimentata da un unico store condiviso (lib/scan): stesso stato in chat e
// nel pannello a sinistra, un solo poller. Vedi ScanProvider.

// D-56/R-LOGOUT: azzerare una sessione CIE/SPID perché il turno sembra
// parlare di un'altra persona è quasi-irreversibile (bisogna rientrare).
// Niente logout automatico: si spiega e si aspetta un click esplicito.
function CambioPersonaGate({ onConferma }: { onConferma: () => void }) {
  const [confermato, setConfermato] = useState(false);

  return (
    <div className="panel escalation" data-gap="cambio_persona">
      <h3>Confermi il cambio persona?</h3>
      <p className="lede" style={{ fontSize: "0.95rem" }}>
        Sto per mettere da parte i dati della sessione attuale (età, ISEE,
        nucleo familiare, disabilità…) per non mescolarli con quelli della
        persona nuova. Non lo faccio senza il tuo consenso.
      </p>
      <div style={{ display: "flex", gap: "var(--ma-3)", marginTop: "var(--ma-4)" }}>
        <button
          type="button"
          className="panel"
          disabled={confermato}
          onClick={() => {
            setConfermato(true);
            onConferma();
          }}
          style={{ cursor: "pointer", padding: "var(--ma-3) var(--ma-4)", font: "inherit" }}
        >
          {confermato ? "Fatto — rimando la domanda…" : "Sì, metti da parte i dati e continua"}
        </button>
      </div>
    </div>
  );
}

export default function Chat() {
  const inputId = useId();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [locateNote, setLocateNote] = useState<string | null>(null);
  const { registra, profilo, dimentica } = useProfilo();
  const { registra: registraTrovate, azzeraTrovate } = useRisultati();
  const { aggiornaScan, nonceRicarica } = useScan();
  const accesso = profilo.accesso === true;
  const [manualLogin, setManualLogin] = useState(false);
  //: Aperto solo su richiesta. Un campo sempre esposto sopra la domanda si
  //: legge come un passaggio obbligato, e questo dato è facoltativo.
  const [sceltaAperta, setSceltaAperta] = useState(false);
  const [scheda, setScheda] = useState<Match | null>(null);
  const [passoAttesa, setPassoAttesa] = useState(0);

  // The wait message moves on every few seconds so a slow answer looks like
  // work in progress rather than a stall. It restarts from the first line each
  // time, so the sequence reads as a progression instead of resuming
  // mid-thought from the previous question.
  useEffect(() => {
    if (!busy) {
      setPassoAttesa(0);
      return;
    }
    const t = setInterval(() => setPassoAttesa((n) => n + 1), 2600);
    return () => clearInterval(t);
  }, [busy]);

  const nextId = useRef(0);
  // Guardia sincrona contro il doppio invio. `busy` e' stato React: due submit
  // nello stesso tick lo leggono entrambi false e partono due richieste — due
  // bolle uguali e, su comune non coperto, due scansioni live concorrenti di
  // cui una puo' fallire ("Non riesco a raggiungere il servizio"). Il ref
  // cambia all'istante, quindi il secondo invio si ferma qui.
  const invioInCorso = useRef(false);
  const logRef = useRef<HTMLDivElement>(null);

  // Keep the newest exchange in view as the transcript grows, the way a
  // messaging app does. The page is the scroller now, not the transcript, so
  // this moves the window — scrolling a box that no longer scrolls did
  // nothing at all.
  //
  // Only when the reader is already near the bottom: being yanked away from an
  // answer still being read, because a later one arrived, is worse than having
  // to scroll.
  useEffect(() => {
    if (!logRef.current) return;
    const distanzaDalFondo =
      document.documentElement.scrollHeight - window.scrollY - window.innerHeight;
    if (distanzaDalFondo > 400) return;
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }, [messages, busy]);

  function newId() {
    nextId.current += 1;
    return `m${nextId.current}`;
  }

  async function send(text: string, comuneIstatScelto?: string) {
    const trimmed = text.trim();
    if (!trimmed || busy || invioInCorso.current) return;
    invioInCorso.current = true;

    setError(null);
    const history: ChatTurn[] = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));
    setMessages((prev) => [...prev, { id: newId(), role: "user", content: trimmed }]);
    setInput("");
    setBusy(true);
    try {
      // Il codice del comune attivo, da qualunque strada sia arrivato —
      // scelto dall'elenco, rilevato dal GPS o portato dall'accesso. Il
      // profilo è l'unico posto dove sta, così non può esistere un comune
      // mostrato nella barra laterale e un altro usato per rispondere.
      // Se l'utente ha scelto un comune da una scheda di disambiguazione, quel
      // codice comanda su quello del profilo: e' la risposta a «quale dei
      // comuni omonimi?», non un cambio di residenza.
      const out = await chat(
        trimmed,
        history,
        comuneIstatScelto ?? profilo.comune?.istat ?? null,
      );
      const id = newId();
      setMessages((prev) => [
        ...prev,
        { id, role: "assistant", content: out.reply, reply: out },
      ]);
      // Alimenta l'unica spia scan condivisa (chat + pannello). L'istat viene
      // dal connettore della risposta, con ripiego sul comune scelto/profilo:
      // se lo stato è "fresco", <ScanLive> non mostra nulla; se è
      // "aggiornamento_in_corso", parte il poller e compare la banda.
      aggiornaScan(
        out.scan,
        out.connettore?.codice_istat ??
          comuneIstatScelto ??
          profilo.comune?.istat ??
          null,
      );
      // Feed the side index. It stores pointers into this transcript, never
      // copies of the verdicts — the card stays the single place any result
      // is stated.
      // Quello che TIQ ha capito della domanda diventa un filtro visibile.
      //
      // I dati c'erano gia' — estratti, usati per rispondere, e mai mostrati:
      // una persona che scriveva «ho 54 anni e sono di Roncaro» non vedeva da
      // nessuna parte che l'avessimo capita, e non aveva modo di correggerci
      // se avessimo capito il comune sbagliato.
      const capito = out.profilo_capito;
      if (capito) {
        registra({
          ...(capito.eta != null ? { eta: capito.eta } : {}),
          // Gli stessi fatti anagrafici che il motore usa devono comparire a
          // lato: finora la barra mostrava solo età e comune, così chi scriveva
          // «sono disabile» o «famiglia di 4» non vedeva che il servizio
          // l'aveva capito. I booleani si mappano solo quando veri — un `false`
          // non è un fatto da mostrare.
          ...(capito.sesso
            ? { sesso: capito.sesso, sessoDedotto: capito.sesso_dedotto }
            : {}),
          ...(capito.disabilita === true ? { disabilita: true } : {}),
          ...(capito.nucleo_familiare != null
            ? { nucleoFamiliare: capito.nucleo_familiare }
            : {}),
          ...(capito.disabilita_nucleo === true
            ? { disabilitaNucleo: true }
            : {}),
          // Il tema capito diventa un interesse mostrato: e' la risposta a
          // «cosa sto cercando», che finora la persona non vedeva scritta.
          ...(out.topic && out.topic !== "sconosciuto"
            ? { interessi: [out.topic.replace(/_/g, " ")] }
            : {}),
          ...(capito.comune_istat && capito.comune_nome
            ? {
                comune: {
                  nome: capito.comune_nome,
                  istat: capito.comune_istat,
                  origine: "dichiarato" as const,
                  // Confermato se: è coperto (lo diamo per buono), OPPURE la
                  // persona l'ha appena scelto esplicitamente (chip/elenco),
                  // OPPURE l'aveva già confermato e questo è un follow-up sullo
                  // stesso comune. Senza gli ultimi due, ogni domanda successiva
                  // su un comune non coperto risbianchettava la conferma e
                  // ricompariva «Sì, è il mio comune?» — riconferma inutile di
                  // una scelta già fatta.
                  confermato:
                    capito.comune_coperto === true ||
                    comuneIstatScelto === capito.comune_istat ||
                    (profilo.comune?.istat === capito.comune_istat &&
                      profilo.comune?.confermato === true),
                  coperto: capito.comune_coperto === true,
                },
              }
            : {}),
          // Recapiti letti al volo su comune fuori copertura → banner a
          // sinistra. Li leghiamo all'ISTAT del comune così il pannello non
          // li mostra per un comune diverso da quello a cui appartengono.
          // Su comune COPERTO scelto dal chip di profilo, `capito` non
          // echeggia istat/nome (il comune non viene dal testo): ripieghiamo
          // sul comune di profilo, a cui la risposta si riferisce comunque.
          // Senza questo, i numeri utili tornavano dall'API ma non venivano
          // mai legati, e a sinistra restava solo il link scheda.
          ...(out.numeri_utili &&
          (capito.comune_istat ?? profilo.comune?.istat) &&
          (capito.comune_nome ?? profilo.comune?.nome)
            ? {
                numeriUtili: {
                  istat: (capito.comune_istat ?? profilo.comune?.istat)!,
                  comune: (capito.comune_nome ?? profilo.comune?.nome)!,
                  telefoni: out.numeri_utili.telefoni,
                  email: out.numeri_utili.email,
                  pec: out.numeri_utili.pec,
                  fonte: out.numeri_utili.fonte,
                  fonteTipo: out.numeri_utili.fonte_tipo,
                  lettoIl: out.numeri_utili.letto_il,
                },
              }
            : {}),
        });
      }

      registraTrovate(
        out.matches.map((match) => ({
          ancora: ancoraDi(id, match.id),
          titolo: match.title,
          verdict: match.verdict,
          verdictLabel: match.verdict_label,
          livello: match.livello,
        })),
      );
    } catch {
      setError(
        "Non riesco a raggiungere il servizio. Verifica che l'API sia in esecuzione su localhost:8010.",
      );
    } finally {
      setBusy(false);
      invioInCorso.current = false;
    }
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    send(input);
  }

  function retryLastQuestion(comuneIstat?: string) {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) send(lastUser.content, comuneIstat);
  }

  // «Ricarica con dati aggiornati» (da <ScanLive>, in chat o nel pannello):
  // rilancia l'ultima domanda ora che il refresh ha riscritto il record. Il
  // bottone non chiama send direttamente — bumpa `nonceRicarica` nello store, e
  // qui reagiamo, così il rilancio usa sempre la closure fresca di send. nonce
  // parte da 0: il primo giro (mount) non deve rilanciare nulla.
  const nonceVisto = useRef(0);
  useEffect(() => {
    if (nonceRicarica === 0 || nonceRicarica === nonceVisto.current) return;
    nonceVisto.current = nonceRicarica;
    retryLastQuestion();
    // retryLastQuestion legge messages/send correnti a ogni render; qui basta
    // reagire al bump del nonce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonceRicarica]);

  // Disambiguazione a un tap: l'utente sceglie il comune giusto da una scheda,
  // rimandiamo la STESSA domanda con l'ISTAT scelto — niente da ridigitare.
  function scegliComuneAmbiguo(cand: ComuneAmbiguo) {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) send(lastUser.content, cand.codice_istat);
  }

  const [avvioBusy, setAvvioBusy] = useState<string | null>(null);

  // Un tap, non tre: sceglie il profilo, apre la sessione server e manda
  // subito la domanda pronta di quella persona. Segue enter() sopra — stessa
  // login(), stesso registra() — non il flusso di AccessoSimulato.onFatto,
  // che non apre mai una sessione server.
  async function avviaPersona(preset: (typeof PRESETS)[number]) {
    if (avvioBusy || busy) return;
    setAvvioBusy(preset.id);
    try {
      await login({
        comune_istat: "058003",
        comune_nome: "Albano Laziale",
        ...preset.profile,
      });
      registra({
        eta: preset.profile.eta,
        interessi: [...preset.profile.interests],
        comune: {
          nome: "Albano Laziale",
          istat: "058003",
          origine: "accesso",
          confermato: true,
        },
        accesso: true,
      });
      azzeraTrovate();
      // Passiamo l'ISTAT esplicito: la registra() qui sopra non e' ancora
      // applicata alla closure di send, quindi `profilo.comune?.istat` sarebbe
      // ancora vuoto e la chiamata partirebbe con comune_istat=null — niente
      // comune, niente numeri utili, niente scheda a sinistra sul primo turno.
      await send(preset.domanda, "058003");
    } catch {
      setError(
        "Non riesco a raggiungere il servizio. Verifica che l'API sia in esecuzione su localhost:8010.",
      );
    } finally {
      setAvvioBusy(null);
    }
  }

  /**
   * Geolocation tells us where the citizen is *standing*, never where they
   * are *resident* — the two are routinely different (someone at the URP
   * desk, at work in a neighbouring comune, visiting family). So the button
   * only ever pre-fills the input with a question the citizen still has to
   * send themselves; it never asserts residency on their behalf, and a
   * denied permission is treated as an ordinary answer, not an error.
   */
  function locate() {
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      setLocateNote(
        "Il tuo browser non supporta la geolocalizzazione: scrivi tu il nome del comune.",
      );
      return;
    }
    setLocating(true);
    setLocateNote(null);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          const nearby = await comuneNearby(
            position.coords.latitude,
            position.coords.longitude,
          );
          if (nearby) {
            // Recorded, but explicitly unconfirmed: GPS says where someone is
            // standing, never where they are resident. The strip renders the
            // difference so a borrowed phone or a visit to family can't
            // silently become a residency claim.
            registra({
              comune: {
                nome: nearby.nome,
                istat: nearby.codice_istat,
                origine: "geolocalizzazione",
                confermato: false,
              },
            });
            // Nessun testo precompilato nella casella della domanda. La
            // domanda «confermi che è il tuo comune?» è rivolta al cittadino,
            // e scriverla lì dentro la trasformava in una domanda che il
            // cittadino faceva a noi: partiva verso il motore, che non
            // trovava nessun servizio corrispondente e rispondeva di non
            // saperla collegare. Confermare è un gesto dell'interfaccia — i
            // due bottoni stanno nella striscia, accanto al comune a cui si
            // riferiscono.
          } else {
            setLocateNote(
              "Non troviamo un comune supportato vicino a te: scrivi tu il nome del comune.",
            );
          }
        } catch {
          setLocateNote(
            "Non riesco a verificare la tua posizione in questo momento: scrivi tu il nome del comune.",
          );
        } finally {
          setLocating(false);
        }
      },
      (geoError) => {
        // Permission denial is a normal, expected answer — not an error state.
        setLocating(false);
        setLocateNote(
          geoError.code === geoError.PERMISSION_DENIED
            ? "Nessun problema: scrivi tu il nome del tuo comune."
            : "Non riesco a determinare la tua posizione: scrivi tu il nome del comune.",
        );
      },
      { timeout: 8000 },
    );
  }

  return (
    <section className="chat" aria-label="Conversazione con TreasureIQ">
      <div className="locate">
        <button
          type="button"
          className="locate__button"
          onClick={locate}
          disabled={locating}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M12 2c-4.4 0-8 3.6-8 8 0 6 8 12 8 12s8-6 8-12c0-4.4-3.6-8-8-8Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            />
            <circle cx="12" cy="10" r="2.6" fill="currentColor" />
          </svg>
          {locating ? "Localizzazione…" : "Usa la mia posizione"}
        </button>

        {/* Due modi di rispondere alla stessa domanda, quindi due bottoni
            accanto: prima stavano in due punti diversi della pagina, e il
            secondo — un campo sopra la domanda — si leggeva come un passaggio
            obbligato invece che come l'alternativa al primo.

            «di interesse», non «il tuo»: chi chiede per un genitore anziano
            non sta dicendo dove vive, e dare per scontata la residenza è
            esattamente cio' che R-9 vieta. */}
        {!profilo.comune && (
          <button
            type="button"
            className="locate__button locate__button--secondario"
            onClick={() => setSceltaAperta((aperta) => !aperta)}
            aria-expanded={sceltaAperta}
          >
            oppure dimmi il comune di interesse
          </button>
        )}

        {/* In linea, non in un modale. Per un campo solo, una finestra
            costerebbe focus trap, Escape, clic fuori, blocco dello scroll e
            tastiera su mobile: cinque cose da azzeccare per mostrare un
            input. */}
        {sceltaAperta && !profilo.comune && (
          <SceltaComune
            onScegli={(scelto) => {
              registra({
                comune: {
                  nome: `${scelto.nome} (${scelto.provincia})`,
                  istat: scelto.codice_istat,
                  // Dichiarato dal cittadino, non rilevato: a differenza del
                  // GPS non ha bisogno di essere confermato.
                  origine: "dichiarato",
                  confermato: true,
                },
              });
              setSceltaAperta(false);
            }}
          />
        )}
      </div>
      {locateNote && (
        <p className="locate__note" role="status">
          {locateNote}
        </p>
      )}

      <div className="chat__log" aria-live="polite" ref={logRef}>
        {messages.length === 0 && (
          <>
            <p className="chat__hint">
              Ad esempio: &laquo;ho la bolletta elettrica troppo alta&raquo;,
              &laquo;ci sono bandi per informatici in scadenza?&raquo;
            </p>
            {/* Un tap sola: sceglie il profilo di prova e manda subito la
                domanda pronta di quella persona, invece di lasciare che chi
                guarda la demo componga da zero un esempio funzionante. */}
            <div className="grid-2" style={{ marginTop: "var(--ma-3)" }}>
              {PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="panel"
                  onClick={() => avviaPersona(p)}
                  disabled={avvioBusy !== null || busy}
                  style={{
                    textAlign: "left",
                    cursor: "pointer",
                    padding: "var(--ma-4)",
                    background: "var(--paper)",
                    font: "inherit",
                    opacity: avvioBusy && avvioBusy !== p.id ? 0.5 : 1,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--font-display)",
                      fontWeight: 700,
                      display: "block",
                      marginBottom: "var(--ma-1)",
                    }}
                  >
                    {p.persona}
                  </span>
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: "0.78rem",
                      color: "var(--sumi-faint)",
                    }}
                  >
                    {avvioBusy === p.id ? "Accesso in corso…" : p.situazione}
                  </span>
                </button>
              ))}
            </div>
          </>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`bubble bubble--${m.role}`}>
            {/* Who is speaking, said once per bubble. Alignment alone carries
                it for a sighted reader on a wide screen and for nobody else:
                on a phone the bubbles nearly touch both edges, and a screen
                reader hears an undifferentiated run of paragraphs. */}
            <p className="bubble__chi">
              {m.role === "user" ? (
                "Tu"
              ) : (
                <>
                  <Marchio size={22} />
                  TIQ
                  {/* Chi risponde, non un marchio in miniatura: senza questa
                      riga «TIQ» è una sigla tecnica accanto a un'icona, e chi
                      legge non sa con cosa sta parlando. */}
                  <span className="bubble__ruolo">Assistente civico</span>
                </>
              )}
            </p>
            {/* Sul rail INFORMAZIONE la sintesi è la prima riga della scheda,
                non un paragrafo sciolto sopra di essa: `RispostaCivica` la
                rende insieme allo stato, così le due cose che qualificano
                tutto il resto stanno dove si guarda per prime. */}
            {/* Il testo si nasconde solo quando la scheda civica lo ripete.
                Una scheda fatta di sole ricerche live non ripete niente: ha i
                link e non la frase, e nasconderla lasciava la risposta vuota —
                a Roncaro (PV) la persona vedeva una card bianca mentre l'API
                aveva riconosciuto il comune e cercato sul suo sito. */}
            {/* La risposta al cittadino compare UNA volta sola. Sul rail
                INFORMAZIONE la rende `RispostaCivica` (con i suoi bolli e la
                gerarchia della scheda), quindi qui la sopprimiamo: prima il
                testo usciva sia qui (tag resi) sia dentro `civica__sintesi`
                (marcatori grezzi), impilando due copie della stessa pappardella.
                Fuori da quel rail — rail AGEVOLAZIONE, oppure INFORMAZIONE senza
                `info` — RispostaCivica non gira e il testo lo rendiamo qui. */}
            {(m.reply?.kind !== "informazione" || !m.reply.info) && (
              <p>{conTagVerifica(m.content)}</p>
            )}

            {/* Nome comune ambiguo: schede cliccabili, non un elenco da
                ricopiare. Un tap sceglie e rimanda la domanda con l'ISTAT. */}
            {m.reply?.comuni_ambigui && m.reply.comuni_ambigui.length > 0 && (
              <div className="scelta-comune" role="group" aria-label="Scegli il comune">
                {m.reply.comuni_ambigui.map((cand) => (
                  <button
                    type="button"
                    key={cand.codice_istat}
                    className="scelta-comune__scheda"
                    onClick={() => scegliComuneAmbiguo(cand)}
                    disabled={busy}
                  >
                    <span className="scelta-comune__nome">{cand.nome}</span>
                    <span className="scelta-comune__prov">{cand.provincia}</span>
                  </button>
                ))}
              </div>
            )}

            {/* D-52/D-53 (acc1): quello che TIQ ha capito, TUTTO nella stessa
                riga. Il sesso dedotto dal nome e l'età non sono più testo
                fisso ma card correggibili in un tap (EcoProfilo): la
                deduzione a bassa confidenza resta marcata "— giusto?" finché
                non la si conferma o corregge, mai un filtro nascosto. */}
            {m.reply?.profilo_capito &&
              (m.reply.profilo_capito.sesso ||
                m.reply.profilo_capito.disabilita_nucleo ||
                m.reply.profilo_capito.eta != null ||
                m.reply.profilo_capito.nucleo_familiare != null) && (
                <EcoProfilo capito={m.reply.profilo_capito} />
              )}

            {m.reply && (
              <div className="chat__answer">
                {/* Il costo di recupero PDF si mostra SOLO quando abbiamo
                    davvero servito dati ingeriti: rail agevolazione con almeno
                    un match. Su disambiguazione e fuori-copertura la «media del
                    comune» è un numero che non riguarda questo comune (non lo
                    ingeriamo) — mostrarlo era una cifra fabbricata. */}
                {m.reply.kind === "agevolazione" &&
                  m.reply.matches.length > 0 &&
                  m.reply.cost &&
                  !m.reply.info && <CostStrip cost={m.reply.cost} />}

                {/* Comune a rail sia informazione che agevolazione: il badge
                    connettore sta qui, sopra i due rami, perché la sonda è
                    indifferente al kind della risposta. */}
                {m.reply.connettore && (
                  <BadgeConnettore sonda={m.reply.connettore} />
                )}

                {/* Mappa servizi a cascata: categoria → servizi del portale,
                    solo dove il connettore raggiungerebbe davvero il comune.
                    Naviga il catalogo, non decide una spettanza (D-01). */}
                {m.reply.connettore?.indirizzabile && (
                  <MappaServizi istat={m.reply.connettore.codice_istat} />
                )}

                {/* Bandi e avvisi: gate PROPRIO su `connettore` presente, non
                    `indirizzabile` (D-B6) — i bandi vengono da amministrazione
                    trasparente (scrape), indipendente dalla mappa servizi
                    (che serve solo se il portale è REST-indirizzabile). Si
                    vedono anche quando il connettore non è indirizzabile. */}
                {m.reply.connettore && (
                  <BandiComune istat={m.reply.connettore.codice_istat} />
                )}

                {m.reply.kind === "informazione" ? (
                  // D-19 — the INFORMAZIONE rail never renders a verdict, a
                  // criterion or a SPID gate. If `info` itself is missing,
                  // this bubble stays empty rather than falling through to
                  // AGEVOLAZIONE furniture below.
                  m.reply.info && (
                    <>
                      <RispostaCivica reply={m.content} info={m.reply.info} />
                      {m.reply.access_mode &&
                        SEGNALAZIONE_ACCESS_MODES.has(m.reply.access_mode) &&
                        m.reply.info.codice_istat &&
                        m.reply.info.ente && (
                          <Segnalazione
                            codiceIstat={m.reply.info.codice_istat}
                            ente={m.reply.info.ente}
                            office={m.reply.info.office}
                          />
                        )}
                      {m.reply.info.codice_istat && (
                        <PonteScala
                          istat={m.reply.info.codice_istat}
                          nome={
                            m.reply.info.ente_nome ??
                            profilo.comune?.nome ??
                            m.reply.info.ente ??
                            "il comune"
                          }
                        />
                      )}
                    </>
                  )
                ) : (
                  <>
                    {m.reply.matches.length > 0 && (
                      <div className="feed">
                        {m.reply.matches.map((match) => (
                          // The anchor is per message, not per opportunity:
                          // the same benefit asked about twice produces two
                          // cards, and the side index has to point at the one
                          // the reader picked.
                          <MatchCard
                            key={match.id}
                            match={match}
                            ancora={ancoraDi(m.id, match.id)}
                            onApri={() => setScheda(match)}
                          />
                        ))}
                      </div>
                    )}

                    {/* Fuori copertura la ricerca live gira su QUESTO rail: la
                        risposta promette «qui sotto trovi quello che ho visto»,
                        e le pagine vivono in `info.web_results`. Senza questo
                        blocco restavano invisibili (InfoAnswer non gira sul rail
                        agevolazione) e la promessa era vuota. Non è un verdetto:
                        link marcati «non verificato», coerente con D-01. */}
                    {m.reply.info && (
                      <PagineWeb results={m.reply.info.web_results} />
                    )}
                    {(() => {
                      const comunale = m.reply!.matches.find(
                        (match) => match.livello === "comunale" && match.ente_codice_istat,
                      );
                      if (!comunale || !comunale.ente_codice_istat) return null;
                      return (
                        <PonteScala
                          istat={comunale.ente_codice_istat}
                          nome={comunale.ente ?? profilo.comune?.nome ?? "il comune"}
                        />
                      );
                    })()}

                    {/* Una scheda i cui requisiti sono tutti «non pubblicato» è
                        il momento in cui il cittadino ha la prova davanti agli
                        occhi: è lì che ha senso offrirgli un'azione concreta —
                        chiedere al proprio comune di aprire quei dati. */}
                    {m.reply.matches.some(
                      (x) =>
                        x.livello === "comunale" &&
                        x.criteria.some((c) => c.state === "unknown_source"),
                    ) && (
                      <p className="chiedi-inline">
                        Molti requisiti qui non sono stati pubblicati.{" "}
                        <a href="/dati#apertura">
                          Puoi chiedere al tuo comune di aprirli →
                        </a>
                      </p>
                    )}

                    {m.reply.data_gap === "cambio_persona" && (
                      <CambioPersonaGate
                        onConferma={() => {
                          dimentica();
                          retryLastQuestion();
                        }}
                      />
                    )}

                    {/* «Non ho trovato nulla» contraddice le pagine appena
                        mostrate: fuori copertura la ricerca live spesso torna
                        proprio dei risultati web, e negarli sotto i link è la
                        stessa bugia che il rail live esiste per evitare. */}
                    {m.reply.matches.length === 0 &&
                      m.reply.data_gap &&
                      m.reply.data_gap !== "cambio_persona" &&
                      !m.reply.comuni_ambigui?.length &&
                      !(m.reply.info && m.reply.info.web_results.length > 0) &&
                      /* Fuori copertura la premessa «Attenzione» dice già il
                         «non ho trovato»: il box grigio lo ripeterebbe. Lo
                         togliamo quando c'è la scheda di lato o la mappa sotto. */
                      !m.reply.connettore &&
                      !m.reply.numeri_utili && (
                        <DataGapNotice kind={m.reply.data_gap} />
                      )}

                  </>
                )}

                <EffortCaption effort={m.reply.citizen_effort} />
              </div>
            )}
          </div>
        ))}

        {busy && (
          <p className="chat__hint" aria-hidden="true">
            {ATTESA[passoAttesa % ATTESA.length]}
          </p>
        )}
      </div>

      {/* Spia scan del comune, sotto l'intera conversazione: banda che lampeggia
          mentre il refresh gira, poi bottone «Ricarica con dati aggiornati».
          Stesso stato mostrato nel pannello a sinistra (un solo store). */}
      <ScanLive variante="chat" />

      {/* Feedback esterno (D-S7): discreto, sotto l'intera conversazione, non
          per-messaggio. Compare appena c'è almeno una risposta da giudicare —
          prima di allora non c'è niente su cui dare un parere. */}
      {messages.some((m) => m.role === "assistant") && (
        <p className="chiedi-inline">
          Com&apos;è andata?{" "}
          <a href={linkFeedback()} {...LINK_ESTERNO}>
            Lascia un feedback →
          </a>
        </p>
      )}

      {error && (
        <p className="notice" role="alert">
          {error}
        </p>
      )}

      <form className="chat__form" onSubmit={handleSubmit}>
        <label className="chat__label" htmlFor={inputId}>
          Scrivi la tua domanda
        </label>
        <div className="chat__row">
          <input
            id={inputId}
            className="chat__input"
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Scrivi qui la tua domanda…"
            autoComplete="off"
            disabled={busy}
          />
          <button type="submit" className="button" disabled={busy || !input.trim()}>
            Invia
          </button>
        </div>
      </form>

      {/* A visible but non-pushy way to reach the mock identity flow without
          waiting for the chat to ask for it (D-09 covers *why* the chat asks
          mid-conversation; this is the other, citizen-initiated door).

          Hidden once a session exists, not merely while the panel is open:
          tied only to the panel, it reappeared the moment a login succeeded,
          inviting someone who had just signed in to sign in again. The panel
          in "Sto usando" is where an active session is managed. */}
      {!manualLogin && !accesso && (
        <div className="spid-entry">
          <button
            type="button"
            className="spid-entry__button"
            onClick={() => setManualLogin(true)}
          >
            Accedi con SPID/CIE (simulazione) per risposte sul tuo profilo
          </button>
        </div>
      )}
      {/* Identity is a handoff, so it gets its own screen rather than a panel
          wedged into the transcript. The mid-conversation gate above stays
          inline: there it is attached to the one answer that needs it, and
          losing that context would cost more than the consistency gains. */}
      {manualLogin && (
        <AccessoSimulato
          onAnnulla={() => setManualLogin(false)}
          onFatto={(preset) => {
            setManualLogin(false);
            registra({
              eta: preset.profile.eta,
              interessi: [...preset.profile.interests],
              comune: {
                nome: "Albano Laziale",
                istat: "058003",
                origine: "accesso",
                confermato: true,
              },
              accesso: true,
            });
            // Signing in changes the basis of every verdict already on
            // screen. The question is asked again below, but the index has to
            // be emptied first: it only ever appends, so without this the
            // freshly computed result would sit next to the one calculated
            // before the citizen's data was known — the same benefit listed
            // twice, with two different answers and nothing saying which is
            // current.
            azzeraTrovate();
            // ISTAT esplicito: la registra() qui sopra non e' ancora nella
            // closure di send, quindi senza passarlo il re-invio partirebbe con
            // comune_istat=null e la scheda numeri utili non comparirebbe.
            retryLastQuestion("058003");
          }}
        />
      )}

      {scheda && <SchedaDettaglio match={scheda} onClose={() => setScheda(null)} />}
    </section>
  );
}
