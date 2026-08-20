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
 * The chat is anonymous: context comes from the conversation and from facts
 * the citizen explicitly provides during the exchange.
 */

import { useEffect, useId, useRef, useState } from "react";
import { Seal } from "@/components/Seal";
import { Marchio } from "@/components/Logo";
import EcoProfilo from "@/components/EcoProfilo";
import ChipFiltri from "@/components/ChipFiltri";
import Segnalazione from "@/components/Segnalazione";
import SchedaDettaglio from "@/components/SchedaDettaglio";
import SceltaComune from "@/components/SceltaComune";
import RispostaCivica from "@/components/RispostaCivica";
import SchedaLettoOra from "@/components/SchedaLettoOra";
import { useProfilo } from "@/lib/profilo";
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
  forgetConversation,
  openConversation,
  portaleComune,
  type Bando,
  type BandiLiveEsito,
  type BandoArricchito,
  type ChatCost,
  type Chiarimento,
  type ChatOut,
  type ChatTurn,
  type ComuneAmbiguo,
  type CostLevels,
  type ConnettoreSonda,
  type FiltroChiave,
  type FiltroOverride,
  type InfoOut,
  type InfoWebResult,
  type Match,
  type PortaleComune,
  type Requirements,
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
/** Data ISO → «11 ago 2026», compatta. Illeggibile → null (il segmento sparisce
 *  invece di stampare «Invalid Date»). */
function dataBreve(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("it-IT", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/**
 * Fuori copertura, dopo la ricerca, diciamo SE il connettore raggiungerebbe
 * questo comune. È una riga di stato tecnica (ciclo 15): codice comune ·
 * connettore · online · non letto in automatico · ultima scansione. Il «non
 * letto in automatico» resta esplicito perché raggiungibile ≠ letto è una
 * scelta fondante (D-05): «online» dice che il portale risponde, non che
 * abbiamo i dati. La nota sotto (ciclo 15 round 2) spiega in parole non
 * tecniche *perché* — il connettore legge solo i dati pubblicati in formato
 * aperto e standard, non fa scraping della pagina — e che aprire i dati è
 * proprio lo scopo di TIQ. Prima diceva «non ingerito», gergo che il
 * cittadino non capisce.
 */
/**
 * Ciclo 15 R5 — banner connettore UNICO, in cima a OGNI risposta comunale
 * (coperto e fuori copertura), non più due trattamenti diversi: prima il
 * coperto aveva una banda-link in fondo (PonteScala, ritirata) e il fuori
 * copertura questo banner verde in cima. Un solo posto, guidato dalla
 * copertura.
 *
 * Due fonti, una riga: la sonda AgID (`sonda`, opzionale) dà `indirizzabile`
 * e l'ultima scansione dello sweep; il censimento nazionale (`portaleComune`,
 * fetch qui) dà il NOME reale della piattaforma (wp_design_comuni, Municipium,
 * eGov…) e la percentuale di aderenza al modello. Prima il nome era hardcoded
 * «Modello AgID» — falso per i comuni WordPress.
 *
 * Muto (D-44) se non sappiamo NULLA del connettore per questo comune: né il
 * censimento conosce la piattaforma, né la sonda lo dice indirizzabile. Non
 * affermiamo copertura che non abbiamo misurato.
 */
function BadgeConnettore({
  istat,
  sonda,
}: {
  istat: string;
  sonda: ConnettoreSonda | null;
}) {
  const [portale, setPortale] = useState<PortaleComune | null>(null);

  useEffect(() => {
    let vivo = true;
    setPortale(null);
    portaleComune(istat)
      .then((esito) => {
        if (vivo) setPortale(esito);
      })
      .catch(() => {
        if (vivo) setPortale(null);
      });
    return () => {
      vivo = false;
    };
  }, [istat]);

  const indirizzabile = sonda?.indirizzabile ?? false;
  if (!portale && !indirizzabile) return null;

  // Nome piattaforma dal censimento; se il censimento non ha ancora spazzolato
  // questo comune ma la sonda lo dice indirizzabile, è per definizione il
  // modello AgID (è ciò che la sonda testa).
  const connettoreNome = portale?.piattaforma ?? "Modello AgID";
  const aderenzaPct =
    portale?.aderenza != null ? Math.round(portale.aderenza * 100) : null;
  const scan = dataBreve(sonda?.ultima_scansione ?? portale?.rilevato_il ?? null);

  return (
    <div className="badge-connettore-box" role="note">
      <p className="badge-connettore">
        <span className="badge-connettore__pallino" aria-hidden />
        <span className="badge-connettore__campo">
          <span className="badge-connettore__k">Codice comune</span>
          <span className="badge-connettore__v">{istat}</span>
        </span>
        <span className="badge-connettore__sep" aria-hidden>·</span>
        <span className="badge-connettore__campo">
          <span className="badge-connettore__k">Connettore</span>
          <span className="tag-connettore">{connettoreNome}</span>
          {aderenzaPct != null && (
            <span className="badge-connettore__v">aderenza {aderenzaPct}%</span>
          )}
        </span>
        <span className="badge-connettore__sep" aria-hidden>·</span>
        <span className="badge-connettore__stato badge-connettore__stato--online">
          online
        </span>
        <span className="badge-connettore__sep" aria-hidden>·</span>
        <span className="badge-connettore__stato badge-connettore__stato--grezzo">
          non letto in automatico
        </span>
        {scan && (
          <>
            <span className="badge-connettore__sep" aria-hidden>·</span>
            <span className="badge-connettore__campo">
              <span className="badge-connettore__k">ultima scansione</span>
              <span className="badge-connettore__v">{scan}</span>
            </span>
          </>
        )}
      </p>
      <p className="badge-connettore__nota">
        Il connettore legge solo i dati pubblicati in formato aperto e standard,
        non copia la pagina del comune. Orari e referenti che stanno solo nella
        pagina non li leggiamo ancora in automatico: se il comune li aprisse in
        un formato condiviso, TreasureIQ li mostrerebbe qui — è lo scopo del
        progetto.{" "}
        {/* Il ponte al censimento nazionale (ex-PonteScala): stessa riga, non
            più una banda a sé in fondo. */}
        <a href="/analytics">vedi com&rsquo;è messa l&rsquo;Italia{" "}→</a>
      </p>
    </div>
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

  function bandoCard(b: Bando) {
    return (
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
    );
  }

  // D-07: la lista non sparisce dietro il toggle di apertura, ma dentro resta
  // collassata a sua volta — primo bando visibile, il resto dietro «+N altri»
  // (stesso primitivo <details> di BandiLive, riusato non reinventato).
  const primo = bandi[0];
  const resto = bandi.slice(1);

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
          <ul className="bandi-comune__lista">{bandoCard(primo)}</ul>
          {resto.length > 0 && (
            <details className="bandi-comune__espandi">
              <summary className="bandi-comune__espandi-riga">
                +{resto.length} altri
              </summary>
              <ul className="bandi-comune__lista">
                {resto.map((b) => bandoCard(b))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}

/** Un criterio non nullo, per la resa generica del pannello: `etichetta`
 *  statica dell'interfaccia, `valore` copiato letteralmente dal campo
 *  tipizzato (mai ricomposto). */
type CriterioReso = { chiave: string; etichetta: string; valore: string };

/** Estrae dai `Requirements` SOLO i campi effettivamente dichiarati (§5.2):
 *  ogni valore che arriva qui è il campo tipizzato, senza alcuna concatenazione
 *  numerica — la stringa "€"/"anni"/"persone" è un'unità di misura statica
 *  dell'interfaccia, non un ricalcolo del dato (D-05). */
function criteriRequisiti(requirements: Requirements): CriterioReso[] {
  const criteri: CriterioReso[] = [];
  if (requirements.isee_max !== null) {
    criteri.push({ chiave: "isee_max", etichetta: "ISEE massimo", valore: `${requirements.isee_max} €` });
  }
  if (requirements.isee_min !== null) {
    criteri.push({ chiave: "isee_min", etichetta: "ISEE minimo", valore: `${requirements.isee_min} €` });
  }
  if (requirements.eta_min !== null) {
    criteri.push({ chiave: "eta_min", etichetta: "Età minima", valore: `${requirements.eta_min} anni` });
  }
  if (requirements.eta_max !== null) {
    criteri.push({ chiave: "eta_max", etichetta: "Età massima", valore: `${requirements.eta_max} anni` });
  }
  if (requirements.nucleo_min !== null) {
    criteri.push({
      chiave: "nucleo_min",
      etichetta: "Nucleo familiare minimo",
      valore: `${requirements.nucleo_min} persone`,
    });
  }
  if (requirements.figli_minori_required !== null) {
    criteri.push({
      chiave: "figli_minori_required",
      etichetta: "Figli minori",
      valore: requirements.figli_minori_required ? "richiesti" : "non richiesti",
    });
  }
  if (requirements.disabilita_required !== null) {
    criteri.push({
      chiave: "disabilita_required",
      etichetta: "Disabilità del richiedente",
      valore: requirements.disabilita_required ? "richiesta" : "non richiesta",
    });
  }
  if (requirements.disabilita_nucleo_required !== null) {
    criteri.push({
      chiave: "disabilita_nucleo_required",
      etichetta: "Disabilità nel nucleo",
      valore: requirements.disabilita_nucleo_required ? "richiesta" : "non richiesta",
    });
  }
  if (requirements.sesso !== null) {
    criteri.push({
      chiave: "sesso",
      etichetta: "Sesso richiesto",
      valore: requirements.sesso === "f" ? "femminile" : "maschile",
    });
  }
  if (requirements.employment_status.length > 0) {
    criteri.push({
      chiave: "employment_status",
      etichetta: "Situazione lavorativa",
      valore: requirements.employment_status.join(", "),
    });
  }
  if (requirements.residenza_comuni.length > 0) {
    criteri.push({
      chiave: "residenza_comuni",
      etichetta: "Comuni di residenza ammessi",
      valore: requirements.residenza_comuni.join(", "),
    });
  } else if (requirements.residenza_required) {
    criteri.push({ chiave: "residenza_required", etichetta: "Residenza", valore: "richiesta nel comune" });
  }
  requirements.other.forEach((voce, indice) => {
    criteri.push({ chiave: `other-${indice}`, etichetta: "Altro criterio", valore: voce });
  });
  return criteri;
}

/** Un singolo bando, con un pannello criteri richiudibile. Card gialla «letto
 *  dal vivo» (stesse classi di `BandiComune`/`MappaServizi`, riga 617): il
 *  giallo qui non è decorativo, segnala un dato estratto dal vivo, non
 *  ingerito. La scadenza si mostra SOLO se `scadenza_verificata` (D-07): una
 *  scadenza non citata testualmente dalla fonte non è mostrata, punto. */
function BandoLive({
  bando,
  verificatoIl,
  formattaData,
}: {
  bando: BandoArricchito;
  verificatoIl: string;
  formattaData: (iso: string) => string;
}) {
  const [aperto, setAperto] = useState(false);
  const { opportunity } = bando;
  const criteri = criteriRequisiti(opportunity.requirements);

  return (
    <li className="mappa-servizi__scheda">
      <span className="mappa-servizi__scheda-titolo">
        {opportunity.title}
        {bando.consigliato && (
          <span
            className="tag-verifica"
            title="In linea col tuo profilo — indicazione, non un verdetto: controlla i requisiti."
          >
            ★ in linea col tuo profilo
          </span>
        )}
        {bando.tipo && (
          <span className={`tag-tipo-bando tag-tipo-bando--${bando.tipo}`}>
            {bando.tipo === "agevolazione" ? "agevolazione" : "concorso"}
          </span>
        )}
      </span>
      {bando.tipo === "concorso" && (
        <p className="bandi-comune__caveat">
          Concorso o offerta di lavoro — verifica se è ancora aperto sul portale del comune.
        </p>
      )}
      {opportunity.summary && (
        <span className="mappa-servizi__scheda-campo">
          <span className="mappa-servizi__scheda-etichetta">Descrizione</span>
          {opportunity.summary}
        </span>
      )}
      {opportunity.amount && (
        <span className="mappa-servizi__scheda-campo">
          <span className="mappa-servizi__scheda-etichetta">Importo</span>
          {[
            opportunity.amount.min_eur !== null ? `da ${opportunity.amount.min_eur} €` : null,
            opportunity.amount.max_eur !== null ? `a ${opportunity.amount.max_eur} €` : null,
            opportunity.amount.note,
          ]
            .filter((parte): parte is string => parte !== null)
            .join(" ")}
        </span>
      )}
      {bando.scadenza_verificata && bando.scadenza && (
        <span className="mappa-servizi__scheda-campo">
          <span className="mappa-servizi__scheda-etichetta">Scadenza</span>
          {formattaData(bando.scadenza)}
        </span>
      )}
      <button
        type="button"
        className="mappa-servizi__scheda-btn"
        aria-expanded={aperto}
        onClick={() => setAperto((valore) => !valore)}
      >
        {aperto ? "Nascondi criteri" : "Vedi criteri"}
      </button>
      {aperto && (
        <>
          {criteri.length > 0 ? (
            criteri.map((criterio) => (
              <span className="mappa-servizi__scheda-campo" key={criterio.chiave}>
                <span className="mappa-servizi__scheda-etichetta">{criterio.etichetta}</span>
                {criterio.valore}
              </span>
            ))
          ) : (
            <span className="mappa-servizi__scheda-campo">
              <span className="mappa-servizi__scheda-etichetta">Criteri</span>
              Non dichiarati dalla fonte.
            </span>
          )}
        </>
      )}
      <a
        className="mappa-servizi__scheda-btn"
        href={opportunity.source.url}
        target="_blank"
        rel="noopener noreferrer"
      >
        Apri sul portale ↗
      </a>
      {/* Documenti PDF linkati dalla pagina del bando (ciclo17). Sono
          puntatori alla fonte, non una lettura: l'etichetta è il nome-file
          verbatim, il download avviene sul sito del comune. Mostrati solo se
          la pagina ne linka — mai un blocco vuoto. */}
      {bando.documenti && bando.documenti.length > 0 && (
        <span className="mappa-servizi__scheda-campo bando-live__documenti">
          <span className="mappa-servizi__scheda-etichetta">Documenti sulla pagina</span>
          <ul className="bando-live__documenti-lista">
            {bando.documenti.map((doc) => (
              <li key={doc.url}>
                <a href={doc.url} target="_blank" rel="noopener noreferrer">
                  <span className="bando-live__documenti-tipo" aria-hidden="true">
                    PDF
                  </span>{" "}
                  {doc.etichetta} ↓
                </a>
              </li>
            ))}
          </ul>
        </span>
      )}
      <span className="mappa-servizi__scheda-footer">Verificato il {formattaData(verificatoIl)}</span>
    </li>
  );
}

/** Bandi letti dal vivo direttamente sulla risposta chat (KAPI 7,
 *  bandi-live-agid, B3/B4): a differenza di `BandiComune` (sola
 *  Amministrazione Trasparente, mai un verdetto), questo pannello arriva già
 *  dentro `reply.bandi_live` — nessuna fetch qui, il payload è calcolato
 *  server-side (due gradini REST, cache TTL, D-05/D-07). Si limita a
 *  renderlo, mai a ricomporlo. */
/** Ordine dei gruppi (ciclo 9, D-04): Agevolazioni prima, poi Concorsi (stesso
 *  ordine di `_ordina_per_tipo` lato backend), «Altri» in coda per `tipo`
 *  assente — non una categoria dichiarata, solo una rete di sicurezza. */
const GRUPPI_BANDI: { tipo: "agevolazione" | "concorso" | null; etichetta: string }[] = [
  { tipo: "agevolazione", etichetta: "Agevolazioni" },
  { tipo: "concorso", etichetta: "Concorsi" },
  { tipo: null, etichetta: "Altri" },
];

function BandiLive({ esito }: { esito: BandiLiveEsito }) {
  function formattaData(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
    const gg = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    return `${gg}/${mm}/${d.getFullYear()}`;
  }

  // `comune_ignoto`: nessuna sonda tentata, nessun guscio da mostrare (D-B7).
  if (esito.esito === "comune_ignoto") return null;

  if (esito.esito === "non_coperto") {
    return (
      <div className="bandi-comune">
        <p className="bandi-comune__caveat">
          Non sono riuscito a leggere i bandi di {esito.comune_nome} dal vivo: il portale non espone
          Amministrazione Trasparente né pagine bandi in una forma che riesco a leggere.
        </p>
        <Segnalazione codiceIstat={esito.codice_istat} ente={esito.comune_nome} office={null} />
      </div>
    );
  }

  if (esito.esito === "coperto_senza_bandi") {
    return (
      <div className="bandi-comune">
        <p className="bandi-comune__caveat">
          Nessun bando pubblicato al {formattaData(esito.verificato_il)}.
        </p>
      </div>
    );
  }

  // coperto_con_bandi
  if (esito.bandi.length === 0) return null;
  return (
    <div className="bandi-comune">
      {GRUPPI_BANDI.map((gruppo) => {
        const bandiGruppo = esito.bandi.filter((bando) => (bando.tipo ?? null) === gruppo.tipo);
        // "Altri" (tipo assente) è una fogna di sicurezza, non una categoria
        // reale: la si mostra solo se contiene qualcosa. Agevolazioni/Concorsi
        // restano sempre visibili, «(0)» incluso — coerenza dei conteggi.
        if (gruppo.tipo === null && bandiGruppo.length === 0) return null;
        // Filtro tematico attivo (D-04): matched resta espanso, il resto
        // collassa dietro «▸ espandi» senza sparire — nessun bando escluso.
        // Senza filtro (D-07): stesso meccanismo, ma il collasso è solo di
        // spazio — primo bando visibile, gli altri dietro «+N altri».
        const matched = esito.tema
          ? bandiGruppo.filter((bando) => bando.corrisponde === true)
          : bandiGruppo.slice(0, 1);
        const resto = esito.tema
          ? bandiGruppo.filter((bando) => bando.corrisponde !== true)
          : bandiGruppo.slice(1);
        return (
          <div className="bandi-comune__gruppo" key={gruppo.etichetta}>
            <p className="bandi-comune__gruppo-titolo">
              {esito.tema
                ? `${gruppo.etichetta} · filtro «${esito.tema}» (${matched.length}/${bandiGruppo.length})`
                : `${gruppo.etichetta} (${bandiGruppo.length})`}
            </p>
            {matched.length > 0 && (
              <ul className="bandi-comune__lista">
                {matched.map((bando, indice) => (
                  <BandoLive
                    key={`${bando.opportunity.id}:${indice}`}
                    bando={bando}
                    verificatoIl={esito.verificato_il}
                    formattaData={formattaData}
                  />
                ))}
              </ul>
            )}
            {resto.length > 0 && (
              <details className="bandi-comune__espandi">
                <summary className="bandi-comune__espandi-riga">
                  {esito.tema
                    ? `▸ espandi altri ${resto.length} bandi che non corrispondono a «${esito.tema}»`
                    : `+${resto.length} altri`}
                </summary>
                <ul className="bandi-comune__lista">
                  {resto.map((bando, indice) => (
                    <BandoLive
                      key={`${bando.opportunity.id}:${indice}`}
                      bando={bando}
                      verificatoIl={esito.verificato_il}
                      formattaData={formattaData}
                    />
                  ))}
                </ul>
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * D-19 — the INFORMAZIONE rail. Document, office, coverage and diagnosis are
 * facts about a public body's data; nothing here is a verdict or a criterion.
 * If this component ever grows an eligibility badge, the
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

// D-S6 (B6): scan assente/stantio (>6gg) → refresh partito in background,
// dati di QUESTO turno restano quelli in cache — nessuna attesa sincrona.
// `stato === "fresco"` → nessun indicatore, la risposta non lo segnala.
// La spia (banda che lampeggia + bottone «Ricarica») vive ora in <ScanLive>,
// alimentata da un unico store condiviso (lib/scan): stesso stato in chat e
// nel pannello a sinistra, un solo poller. Vedi ScanProvider.

// A cambio esplicito di persona il profilo locale va svuotato per non
// mescolare i dati forniti nei due scambi.
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
  //: Aperto solo su richiesta. Un campo sempre esposto sopra la domanda si
  //: legge come un passaggio obbligato, e questo dato è facoltativo.
  const [sceltaAperta, setSceltaAperta] = useState(false);
  const [scheda, setScheda] = useState<Match | null>(null);
  const [passoAttesa, setPassoAttesa] = useState(0);
  const [mostraAvvisoCookie, setMostraAvvisoCookie] = useState(true);

  // A conversation is reopenable, not merely addressable: on a fresh page
  // load restore the server-side transcript before the citizen asks the next
  // question. Result cards are intentionally not reconstructed from prose;
  // the transcript remains truthful and the next answer is recomputed from
  // the deterministic data path.
  useEffect(() => {
    let attivo = true;
    openConversation()
      .then((transcript) => {
        if (!attivo || transcript.messages.length === 0) return;
        setMessages((precedenti) => {
          if (precedenti.length > 0) return precedenti;
          const ripristinati = transcript.messages.map((message, indice) => ({
            id: `restored-${indice + 1}`,
            role: message.role,
            content: message.content,
          }));
          nextId.current = ripristinati.length;
          return ripristinati;
        });
      })
      .catch(() => {
        // An unavailable transcript must not block a new anonymous chat.
      });
    return () => {
      attivo = false;
    };
  }, []);

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
  // Stessa guardia sincrona di `invioInCorso`, ma per il re-query della
  // rimozione chip (A8-client): un secondo click su un'altra × prima che
  // `busy` sia tornato true lo leggerebbe ancora false e partirebbero due
  // richieste concorrenti sullo stesso scambio.
  const rimozioneInCorso = useRef(false);
  // Ciclo11/A8-client — override accumulati per scambio (chiave = id del
  // messaggio assistente). Ogni «×» aggiunge una chiave; il ricalcolo del
  // server toglie di conseguenza quel filtro anche dalla `filtri` che torna,
  // quindi non serve tenere qui una copia della lista visibile — solo cosa
  // e' gia' stato tolto, per non rimandarlo due volte.
  const [overrideScambio, setOverrideScambio] = useState<
    Record<string, FiltroOverride[]>
  >({});
  // Ciclo12/A3 — override di SESSIONE: unione (per chiave) di tutti gli
  // override richiesti da inizio sessione, a differenza di `overrideScambio`
  // che e' per-messaggio e serve solo al ricalcolo in place di quello
  // scambio. Ora che il backend accumula i filtri dalla history (A1), un
  // filtro tolto con la «×» risorgerebbe al turno dopo se `send()` non lo
  // rimandasse sempre: questo stato e' quello che rende la rimozione
  // definitiva per la sessione (fino a dichiarazione esplicita contraria,
  // gestita lato server). Nessuna persistenza oltre il reload (localStorage
  // e' DEFERRED).
  const [overrideSessione, setOverrideSessione] = useState<FiltroOverride[]>(
    [],
  );
  // Ciclo12/A3 — slot di chiarimento pendente (B1): l'ultimo `chiarimento`
  // ricevuto dal server, da rimandare come `chiarimento_atteso` sul
  // PROSSIMO turno soltanto. Si azzera subito dopo l'invio: uno slot vale
  // un turno, non bloccante (D-04) — se il cittadino ignora la domanda e
  // chiede altro, il turno procede normale e lo slot decade.
  const [chiarimentoPendente, setChiarimentoPendente] =
    useState<Chiarimento | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  // Whether the reader is parked near the bottom, sampled *before* a new
  // message grows the page. This is the crux: measuring the distance inside
  // the autoscroll effect reads it *after* the DOM has already grown, so a
  // tall answer (a scheda is hundreds of px) pushes the bottom far below the
  // viewport and the "am I near the bottom?" check fails for exactly the
  // messages worth following — the card never scrolls into view. A scroll
  // listener records the answer while it is still true.
  const attaccatoAlFondo = useRef(true);
  useEffect(() => {
    function misura() {
      const distanzaDalFondo =
        document.documentElement.scrollHeight - window.scrollY - window.innerHeight;
      attaccatoAlFondo.current = distanzaDalFondo < 400;
    }
    misura();
    window.addEventListener("scroll", misura, { passive: true });
    window.addEventListener("resize", misura, { passive: true });
    return () => {
      window.removeEventListener("scroll", misura);
      window.removeEventListener("resize", misura);
    };
  }, []);

  // Keep the newest exchange in view as the transcript grows, the way a
  // messaging app does. The page is the scroller now, not the transcript, so
  // this moves the window — scrolling a box that no longer scrolls did
  // nothing at all.
  //
  // Only when the reader was already near the bottom (see attaccatoAlFondo):
  // being yanked away from an answer still being read, because a later one
  // arrived, is worse than having to scroll.
  useEffect(() => {
    if (!logRef.current) return;
    if (!attaccatoAlFondo.current) return;
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
    // The scroll we just triggered leaves us at the bottom; assert it so the
    // listener's post-animation sample can't flip the ref off mid-scroll.
    attaccatoAlFondo.current = true;
  }, [messages, busy]);

  function newId() {
    nextId.current += 1;
    return `m${nextId.current}`;
  }

  async function send(text: string, comuneIstatScelto?: string) {
    const trimmed = text.trim();
    if (!trimmed || busy || invioInCorso.current || rimozioneInCorso.current) return;
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
      // scelto dall'elenco o rilevato dal GPS. Il
      // profilo è l'unico posto dove sta, così non può esistere un comune
      // mostrato nella barra laterale e un altro usato per rispondere.
      // Se l'utente ha scelto un comune da una scheda di disambiguazione, quel
      // codice comanda su quello del profilo: e' la risposta a «quale dei
      // comuni omonimi?», non un cambio di residenza.
      const out = await chat(
        trimmed,
        history,
        comuneIstatScelto ?? profilo.comune?.istat ?? null,
        overrideSessione.length > 0 ? overrideSessione : null,
        chiarimentoPendente,
      );
      // Lo slot appena rimandato vale solo per questo turno (D-04): si
      // azzera qui e si ripopola solo se la risposta ne apre uno nuovo.
      setChiarimentoPendente(out.chiarimento ?? null);
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
          ...(capito.figli_minori != null
            ? { figliMinori: capito.figli_minori }
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

  async function dimenticaConversazione() {
    if (busy || rimozioneInCorso.current) return;
    rimozioneInCorso.current = true;
    setError(null);
    try {
      await forgetConversation();
      setMessages([]);
      setOverrideScambio({});
      setOverrideSessione([]);
      setChiarimentoPendente(null);
      azzeraTrovate();
      nextId.current = 0;
    } catch {
      setError("Non riesco a cancellare la conversazione in questo momento.");
    } finally {
      rimozioneInCorso.current = false;
    }
  }

  // Ciclo11/A8-client (D-04) — la «×» su un chip non ri-filtra client-side:
  // ri-manda la STESSA domanda con la chiave in `filtri_override`, cosi' il
  // ricalcolo e' vero (comune fuori copertura ricalcola davvero, non solo
  // nasconde una riga). Aggiorna IN PLACE il messaggio esistente — non
  // apre un nuovo scambio — perche' resta la stessa domanda, solo con
  // un'evidenza in meno.
  async function rimuoviFiltro(messageId: string, chiave: FiltroChiave) {
    if (busy || rimozioneInCorso.current || invioInCorso.current) return;
    const idx = messages.findIndex((m) => m.id === messageId);
    const domanda = idx > 0 ? messages[idx - 1] : null;
    if (!domanda || domanda.role !== "user") return;
    rimozioneInCorso.current = true;
    setBusy(true);
    setError(null);

    const attivi = [
      ...(overrideScambio[messageId] ?? []).filter((o) => o.chiave !== chiave),
      { chiave, azione: "rimuovi" as const },
    ];
    // Ciclo12/A3 — la stessa rimozione vale anche per la sessione: unione
    // per chiave con quanto gia' tolto in scambi precedenti, cosi' il
    // ricalcolo di QUESTO scambio non fa risorgere un filtro tolto altrove.
    const sessioneAttiva = [
      ...overrideSessione.filter((o) => o.chiave !== chiave),
      { chiave, azione: "rimuovi" as const },
    ];
    // Storia = lo scambio precedente a quella domanda, la stessa che `send`
    // avrebbe costruito la prima volta — mai le risposte proprie rimandate
    // indietro (vedi nota sopra in `send`).
    const history: ChatTurn[] = messages.slice(0, idx - 1).map((m) => ({
      role: m.role,
      content: m.content,
    }));

    try {
      const out = await chat(
        domanda.content,
        history,
        profilo.comune?.istat ?? null,
        sessioneAttiva,
      );
      setOverrideScambio((prev) => ({ ...prev, [messageId]: attivi }));
      setOverrideSessione(sessioneAttiva);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId ? { ...m, content: out.reply, reply: out } : m,
        ),
      );
    } catch {
      setError(
        "Non riesco a raggiungere il servizio. Verifica che l'API sia in esecuzione su localhost:8010.",
      );
    } finally {
      setBusy(false);
      rimozioneInCorso.current = false;
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

            {/* Ciclo11/A7 — i filtri riconosciuti nel messaggio, con la loro
                provenienza verbatim. Vive nel flusso chat (non nel pannello
                profilo): sono letture di QUESTO scambio, non fatti stabili
                del cittadino — EcoProfilo resta la sede dei fatti confermati,
                questi chip sono la lettura puntuale che li ha prodotti. */}
            {m.role === "assistant" && m.reply && m.reply.filtri.length > 0 && (
              <ChipFiltri
                filtri={m.reply.filtri}
                onRimuovi={(chiave) => rimuoviFiltro(m.id, chiave)}
                disabled={busy}
              />
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
                    indifferente al kind della risposta. Il codice comune si
                    prende dalla prima fonte disponibile — sonda, info, o il
                    primo match comunale — così il banner esce anche sul coperto
                    (dove `connettore` può mancare) e su agevolazione. */}
                {(() => {
                  // Il comune di questo turno è quello che la scheda a lato
                  // (`profilo_capito`) ha capito dal testo: è l'unico segnale
                  // sempre presente e coerente col pannello, così banner e
                  // scheda non mostrano mai due comuni diversi (bug «cambio
                  // comune»). Le altre fonti restano come rete: su alcuni rami
                  // il codice arriva solo dalla sonda o dal match comunale.
                  const istatBanner =
                    m.reply.profilo_capito?.comune_istat ??
                    m.reply.connettore?.codice_istat ??
                    m.reply.info?.codice_istat ??
                    m.reply.matches.find(
                      (x) => x.livello === "comunale" && x.ente_codice_istat,
                    )?.ente_codice_istat ??
                    null;
                  return istatBanner ? (
                    <BadgeConnettore
                      istat={istatBanner}
                      sonda={m.reply.connettore ?? null}
                    />
                  ) : null;
                })()}

                {/* La mappa servizi a cascata non sta più qui: vive nel
                    pannello di sinistra (MappaServizi), agganciata al comune di
                    profilo, per tenere la chat pulita. */}

                {/* Bandi e avvisi: gate PROPRIO su `connettore` presente, non
                    `indirizzabile` (D-B6) — i bandi vengono da amministrazione
                    trasparente (scrape), indipendente dalla mappa servizi
                    (che serve solo se il portale è REST-indirizzabile). Si
                    vedono anche quando il connettore non è indirizzabile. */}
                {m.reply.connettore && (
                  <BandiComune istat={m.reply.connettore.codice_istat} />
                )}

                {/* B4 (KAPI 7, bandi-live-agid): esito verificato del topic
                    BANDI, già dentro `reply.bandi_live` (B3) — nessuna
                    seconda fetch, mai un secondo scan dello stesso portale. */}
                {m.reply.bandi_live && <BandiLive esito={m.reply.bandi_live} />}

                {/* B5 (ciclo 10): il connettore letto ORA (contratto D-09) —
                    uffici coi recapiti verbatim e i bandi di Amministrazione
                    Trasparente, con l'analisi PDF su richiesta. Indipendente
                    dal ramo agevolazione/informazione: si mostra ovunque il
                    backend l'abbia valorizzato su questa risposta. */}
                {m.reply.esito_connettore && (
                  <SchedaLettoOra esito={m.reply.esito_connettore} />
                )}

                {m.reply.kind === "informazione" ? (
                  // D-19 — the INFORMAZIONE rail never renders a verdict, a
                  // criterion. If `info` itself is missing,
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

                {/* Ciclo 15 R4: «Cosa resta da fare a te: N azioni» rimosso.
                    Contava le azioni del blocco «Cosa puoi fare adesso», ora
                    tolto in ogni caso: il contatore era orfano ovunque. */}
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

      {/* Feedback (D-01, ciclo 6; D-06, ciclo 14): il form vive ora dietro un
          bottone nell'header dell'app (FeedbackHeader), non più agganciato
          al flusso della chat — vedi web/app/layout.tsx. */}

      {error && (
        <p className="notice" role="alert">
          {error}
        </p>
      )}

      {mostraAvvisoCookie && (
        <div className="conversation-cookie-banner" role="status">
          Questa chat usa un cookie tecnico per riaprire la conversazione sullo
          stesso browser per 90 giorni. I contenuti restano sul server e puoi
          cancellarli in qualsiasi momento.
          <button
            type="button"
            className="button button--small"
            onClick={() => setMostraAvvisoCookie(false)}
          >
            Ho capito
          </button>
        </div>
      )}

      <button
        type="button"
        className="button button--secondary"
        onClick={dimenticaConversazione}
        disabled={busy}
      >
        Dimentica conversazione
      </button>

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

      {scheda && <SchedaDettaglio match={scheda} onClose={() => setScheda(null)} />}
    </section>
  );
}
