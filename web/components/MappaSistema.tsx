/**
 * La mappa del sistema: chi parla con chi, e quando.
 *
 * Disegnata a mano in SVG per gli stessi motivi dei ritratti: nessuna libreria
 * di diagrammi da caricare, nessuna richiesta di rete, e resta nitida a
 * qualunque ingrandimento — che in una registrazione dello schermo conta.
 *
 * Il diagramma dice una cosa sola, e la dice con la geometria invece che con
 * le parole: **la fascia di sopra succede prima della domanda e finisce in
 * git; la fascia di sotto succede mentre il cittadino aspetta**. Le due non si
 * mescolano mai, ed è per questo che una risposta letta al volo non può
 * travestirsi da dato verificato.
 *
 * Nota sul lessico: qui non ci sono microservizi. Ci sono due processi (un
 * front-end e un'API), un motore di ricerca che interroghiamo solo all'ultimo
 * gradino, e un'ingestione che gira a parte e lascia file versionati. Chiamarla
 * "architettura a microservizi" farebbe più scena e sarebbe falso.
 */

const BOX = {
  offline: { fill: "var(--paper-raised)", stroke: "var(--kasumi)" },
  vivo: { fill: "var(--ai-wash)", stroke: "var(--ai)" },
  esterno: { fill: "var(--paper-sunken)", stroke: "var(--kasumi)" },
} as const;

function Nodo({
  x,
  y,
  w = 150,
  h = 46,
  tipo = "offline",
  titolo,
  riga,
}: {
  x: number;
  y: number;
  w?: number;
  h?: number;
  tipo?: keyof typeof BOX;
  titolo: string;
  riga?: string;
}) {
  const s = BOX[tipo];
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} fill={s.fill} stroke={s.stroke} strokeWidth="1.5" />
      <text x={x + w / 2} y={riga ? y + 20 : y + h / 2 + 4} className="mappa__titolo">
        {titolo}
      </text>
      {riga && (
        <text x={x + w / 2} y={y + 34} className="mappa__riga">
          {riga}
        </text>
      )}
    </g>
  );
}

/** Una freccia dritta, orizzontale o verticale. Niente curve: un diagramma
 * che serve a spiegare non deve chiedere di essere seguito con il dito. */
function Freccia({
  x1,
  y1,
  x2,
  y2,
  etichetta,
  tratteggio,
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  etichetta?: string;
  tratteggio?: boolean;
}) {
  return (
    <g>
      <line
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        stroke="var(--sumi-faint)"
        strokeWidth="1.5"
        strokeDasharray={tratteggio ? "5 4" : undefined}
        markerEnd="url(#punta)"
      />
      {etichetta && (
        /* Su una freccia verticale l'etichetta si sposta di lato: centrata
           finirebbe sopra la linea, e su questa figura le linee verticali
           attraversano i divisori delle fasce. */
        <text
          x={y1 === y2 ? (x1 + x2) / 2 : x1 + 8}
          y={y1 === y2 ? y1 - 7 : (y1 + y2) / 2}
          className="mappa__etichetta"
          textAnchor={y1 === y2 ? "middle" : "start"}
        >
          {etichetta}
        </text>
      )}
    </g>
  );
}

export default function MappaSistema() {
  return (
    <figure className="mappa">
      <svg viewBox="0 0 940 600" role="img" aria-labelledby="mappa-titolo mappa-desc">
        <title id="mappa-titolo">Mappa del sistema TreasureIQ</title>
        <desc id="mappa-desc">
          Due fasce. Sopra, l&apos;ingestione che gira prima della domanda e lascia uno
          snapshot versionato in git. Sotto, il percorso di una domanda: dal browser al
          front-end, all&apos;API, alla classificazione dell&apos;intento, e da lì su uno dei due
          binari — agevolazione, deciso da un motore deterministico, o informazione,
          composta da documento e ufficio. Fuori copertura si legge il portale del comune
          in diretta e, se non è leggibile, si cerca sul web marcando il risultato come non
          verificato.
        </desc>

        <defs>
          <marker id="punta" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">
            <path d="M0,0 L0,6 L8,3 z" fill="var(--sumi-faint)" />
          </marker>
        </defs>

        {/* ── Fascia 1: prima della domanda ─────────────────────────────── */}
        <text x="20" y="26" className="mappa__fascia">
          PRIMA DELLA DOMANDA · gira a parte, finisce in git
        </text>
        <line x1="20" y1="36" x2="920" y2="36" stroke="var(--kasumi)" strokeWidth="1" />

        <Nodo x={20} y={56} tipo="esterno" titolo="Portale del comune" riga="WP REST · HTML" />
        <Nodo x={215} y={56} titolo="Connettore" riga="ingest/" />
        <Nodo x={410} y={56} titolo="Opportunity" riga="schema comune" />
        <Nodo x={605} y={56} titolo="Estrazione" riga="modello · in cache" />
        <Nodo x={800} y={56} w={120} titolo="data/seed" riga="versionato" />

        <Freccia x1={170} y1={79} x2={213} y2={79} />
        <Freccia x1={365} y1={79} x2={408} y2={79} />
        <Freccia x1={560} y1={79} x2={603} y2={79} />
        <Freccia x1={755} y1={79} x2={798} y2={79} />

        <Nodo x={605} y={140} titolo="Pagella" riga="readiness.py" />
        <Freccia x1={860} y1={104} x2={860} y2={140} />
        <line x1="680" y1="140" x2="860" y2="140" stroke="var(--sumi-faint)" strokeWidth="1.5" />

        {/* ── Fascia 2: durante la domanda ──────────────────────────────── */}
        <text x="20" y="228" className="mappa__fascia">
          DURANTE LA DOMANDA · il cittadino sta aspettando
        </text>
        <line x1="20" y1="238" x2="920" y2="238" stroke="var(--kasumi)" strokeWidth="1" />

        <Nodo x={20} y={258} tipo="vivo" titolo="Cittadino" riga="browser" />
        <Nodo x={215} y={258} tipo="vivo" titolo="web" riga="Next · stessa origine" />
        <Nodo x={410} y={258} tipo="vivo" titolo="api" riga="FastAPI" />
        <Nodo x={605} y={258} tipo="vivo" titolo="Che forma ha?" riga="modello · solo questo" />

        <Freccia x1={170} y1={281} x2={213} y2={281} />
        <Freccia x1={365} y1={281} x2={408} y2={281} />
        <Freccia x1={560} y1={281} x2={603} y2={281} />

        {/* Il bivio dei due rail. */}
        <Nodo x={800} y={230} w={120} h={40} titolo="Agevolazione" />
        <Nodo x={800} y={286} w={120} h={40} titolo="Informazione" />
        <Freccia x1={755} y1={272} x2={798} y2={252} />
        <Freccia x1={755} y1={290} x2={798} y2={306} />

        <Nodo x={605} y={348} titolo="Motore" riga="regole · nessun modello" />
        <Nodo x={330} y={348} titolo="Snapshot" riga="documento · ufficio" />
        <Freccia x1={860} y1={270} x2={860} y2={348} />
        <line x1="680" y1="348" x2="860" y2="348" stroke="var(--sumi-faint)" strokeWidth="1.5" />
        <Freccia x1={860} y1={326} x2={860} y2={348} />
        <Freccia x1={603} y1={371} x2={482} y2={371} />

        {/* I gradini fuori copertura. */}
        <text x="20" y="436" className="mappa__fascia">
          SE IL COMUNE NON È CENSITO
        </text>
        <line x1="20" y1="446" x2="920" y2="446" stroke="var(--kasumi)" strokeWidth="1" />

        <Nodo x={20} y={470} w={175} titolo="2 · Portale, ora" riga="verbatim · non conservato" />
        <Nodo x={250} y={470} w={175} titolo="3 · Ricerca web" riga="SearXNG · non verificato" />
        <Nodo x={480} y={470} w={190} h={46} tipo="vivo" titolo="Scheda civica" riga="ogni riga con la sua fonte" />
        <Freccia x1={198} y1={493} x2={248} y2={493} />
        <Freccia x1={428} y1={493} x2={478} y2={493} />
        <Freccia x1={405} y1={394} x2={405} y2={468} tratteggio etichetta="1 · snapshot" />

        <text x="690" y="490" className="mappa__nota">
          I gradini si scendono in ordine.
        </text>
        <text x="690" y="508" className="mappa__nota">
          Un dato trovato non si presenta
        </text>
        <text x="690" y="526" className="mappa__nota">
          mai come un dato letto.
        </text>
      </svg>

      <figcaption className="mappa__legenda">
        <span>
          <i className="mappa__bollo mappa__bollo--offline" /> gira prima, versionato
        </span>
        <span>
          <i className="mappa__bollo mappa__bollo--vivo" /> succede mentre aspetti
        </span>
        <span>
          <i className="mappa__bollo mappa__bollo--esterno" /> non è nostro
        </span>
      </figcaption>
    </figure>
  );
}
