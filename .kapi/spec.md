# spec — ciclo 9 · bandi-conversazionale

## PROBLEM
Il committente, in chat con contesto Benevento+bandi, chiede «ci sono bandi per la mobilità?».
Atteso: la chat trova ed evidenzia il bando di mobilità, ignora gli altri, e risponde al tema.
Reale: ri-scansiona, ri-mostra TUTTI i bandi identici, testo template invariato, il tema
«mobilità» è ignorato. «Non sembra una chat». Inoltre le card non sono raggruppate per tipo
(agevolazione/concorso), solo un badge per card.

Root (mappato): `_risposta_bandi` (respond.py:2551) ha `reply` FISSO per branch esito, mai
per tema della domanda (D-07: reply mai dal modello). `_ordina_bandi_per_profilo` (2528)
ordina per profilo cittadino, MAI filtra per parola della query. `ChatIntent` (intent.py:450)
non ha slot tema libero. Frontend `BandiLive` (Chat.tsx ~972) rende piatto, nessun raggruppo.

## IN SCOPE
1. **Filtro tematico deterministico**: estrarre un `tema` libero dal messaggio (no LLM),
   filtrare/partizionare i bandi per match sul titolo, rispondere al tema nel template fisso.
2. **Raggruppamento per tipo** lato UI: sezioni Agevolazioni / Concorsi.

## CONSTRAINTS
- **No LLM sul reply** (D-07 confermato): il testo resta template deterministico, il tema è
  eco verbatim del messaggio utente. Number-guard intatto (cifre/criteri mai toccati).
- Deadline video 14 ago → scope stretto, retrocompatibile: senza tema la chat si comporta
  ESATTAMENTE come oggi.
- File backend/frontend disgiunti dove possibile (2 arm concorrenti).
- L-3: ogni nuovo campo su `BandiLiveEsito`/`BandoArricchito` DEVE arrivare a `ChatOut` e al
  mirror `web/lib/api.ts` (assegnazione diretta stesso tipo, verificata).
- L-1: verifica LIVE su comune reale (Benevento «mobilità») come acceptance, non solo unit.
  Post-fix: rebuild `api` E `web` (build-time bundle, no source mount) + svuota ENTRAMBE le
  cache `data-live/bandi-criteri/<istat>` e `data-live/alberatura/<istat>`.

## DECISIONS
- **D-01** Estrazione tema deterministica: da `message`, togli vocabolario topic BANDI
  (`TOPIC_KEYWORDS`), stopword italiane, e slot già noti (nome comune). Token salienti
  residui (≥3 char) = `tema` (stringa breve, 1-3 parole). Nessun modello.
- **D-02** Match = hit normalizzato (accent/case-insensitive, riuso `_keyword_hit`
  respond.py:726) del `tema` su `opportunity.title` (fallback: testo requisiti). Bando che
  matcha → `corrisponde=True`.
- **D-03** Se `tema` presente e ≥1 match: partiziona matched-first, template ammette il
  filtro — «Ho cercato «{tema}» tra i bandi di {comune}: {N} corrispond{e|ono}.» Se 0 match:
  «Nessun bando corrisponde a «{tema}»; te li mostro tutti ({tot}).» Cifre verbatim.
- **D-04** Raggruppo UI per `tipo`: Agevolazioni prima (riuso ordine `_ordina_per_tipo`),
  poi Concorsi. Gruppo vuoto → intestazione con «(0)» o nascosto (DISCRETION arm frontend).
  Dentro ogni gruppo, se filtro attivo: matched espansi, non-matched collassati «▸ espandi».
- **D-05** Nuovi campi contratto: `BandiLiveEsito.tema: str | None`;
  `BandoArricchito.corrisponde: bool | None` (default None = nessun filtro). Mirror in
  `api.ts`. Proiezione a `ChatOut` verificata (L-3).
- **D-06** `tema` = eco verbatim del messaggio, **escaped** in UI (nessuna injection HTML),
  mai passato a shell/LLM. Number-guard invariato.
- **D-07** Retrocompat: nessun `tema` (utente scrive solo «bandi») → `tema=None`,
  `corrisponde=None`, nessun filtro, template odierno invariato. Il raggruppo per tipo si
  applica comunque (miglioria pura, non regressiva).

## DISCRETION (arm)
- Set esatto stopword italiane + soglia token tema.
- Se estendere il match anche al corpo/requisiti oltre al titolo.
- Rendering esatto gruppi vuoti e del collasso «▸ espandi» (accessibile, no dialog JS).
- Se il tema multi-parola richiede match di TUTTI i token o di almeno uno (default: almeno uno).

## DEFERRED
- Sinonimi/stemming avanzato del tema (es. «mobilità»↔«trasferimento»): no, match lessicale.
- Ranking semantico via modello: no (D-07 storico, crediti).
- Filtro multi-tema / query booleane: no.
- Persistenza del tema attraverso più follow-up successivi: no, per-turno.

## RISKS (5 lenti, senza esagerare)
- **Blind spot**: tema falso-positivo da stopword mal filtrata (es. «per la» → «la»). Mitig:
  soglia ≥3 char + stoplist connettivi (riusa lezione [[connettivi-nome-falsi-candidati]]).
- **Devil's advocate**: «mobilità» non nel titolo ma nel corpo → 0 match falso. Mitig: D-02
  fallback su testo requisiti; e template 0-match mostra comunque tutti (non nasconde nulla).
- **Inverted**: se tema estratto da parola comune (es. «casa») matcha troppo? Accettabile:
  mostra i match, gli altri collassati, mai esclusi del tutto.
- **Premortem**: dimenticare rebuild web → badge/gruppi non compaiono (già capitato oggi).
  Mitig: acceptance A8 richiede rebuild api+web + doppia cache.
- **Red team**: injection via tema (`<script>`), o tema enorme. Mitig: escape UI (D-06),
  cap lunghezza tema.

## ACCEPTANCE
- **A1** Benevento 062008 + «ci sono bandi per la mobilità?» → `tema="mobilità"`, ≥1
  `corrisponde=True` (bando mobilità obbligatoria), reply cita «mobilità» + conteggio, matched
  primo. LIVE.
- **A2** Benevento + tema senza riscontro (es. «bandi per la casa») → 0 match, reply «nessuno
  corrisponde a «casa»; te li mostro tutti (5)», tutti i bandi presenti.
- **A3** Benevento + «ci sono bandi?» (no tema) → `tema=None`, comportamento odierno
  invariato, tutti i bandi, template invariato.
- **A4** UI: card raggruppate per tipo (Concorsi sez.; Agevolazioni sez. — Benevento 0
  agevolazioni). Badge per card invariato.
- **A5** `tema` eco verbatim ed escaped (no injection), cifre/scadenze verbatim invariate.
- **A6** Contratto mirrorato `api.ts` (`tema`, `corrisponde`), proiettato a `ChatOut` (L-3),
  `tsc --noEmit` pulito.
- **A7** Test backend (estrazione tema, match, template 3 rami) + `npm run build` verde.
- **A8** Verifica LIVE post-rebuild (api+web ribuildati, cache doppia svuotata): Benevento
  «mobilità» → 1 match evidenziato; un comune WP coperto → filtro coerente.

## must_haves.truths
- reply mai dal modello (D-07); tema verbatim, escaped.
- senza tema = comportamento identico a oggi (retrocompat, A3).
- ogni bando resta visibile (filtro = evidenzia/collassa, mai esclude) — onestà.
- nuovi campi arrivano a ChatOut e a api.ts (L-3).

## must_haves.key_links
- `_risposta_bandi` (respond.py:2551) legge `message`, estrae `tema`, popola
  `esito.tema` + `bando.corrisponde`, sceglie template.
- estrazione tema: nuovo helper deterministico (respond.py o modulo intent), riuso
  `_keyword_hit`/stoplist connettivi.
- `BandiLiveEsito`/`BandoArricchito` (bandi_live.py) nuovi campi → `ChatOut` (api.py
  assegnazione diretta) → `web/lib/api.ts`.
- `BandiLive`/`BandoLive` (Chat.tsx ~848,972) raggruppo per tipo + collasso non-matched.
