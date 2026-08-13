# SPEC — ciclo 18a: discovery «leggi-prima» (chat rapida)

slug: discovery-leggi-prima

## PROBLEM
Ogni percorso runtime della chat bandi **ri-scopre da capo** (fetch live da
`comune.sito`) a ogni cache-miss, invece di leggere ciò che uno sweep/scan
fratello ha GIÀ persistito. Non è che lo sweep sia stretto: è **frammentazione**
su tre cassetti che non si parlano.

- `alberatura.scopri_rami` ri-crawla la home per ritrovare il link AT: **fino a 5
  fetch** per un URL già in `registro.endpoints.at`.
- `bandi_live._scopri_bandi` ri-sonda `/wp-json/wp/v2/types` per dedurre il CPT/
  rest_base già noto nella cache `mappa-connettore/{istat}.json`.
- `bandi_arricchiti` legge `piattaforma_at` solo per un badge, mai per instradare;
  `_CONNETTORE_AT_PER_PIATTAFORMA` è `{}` (dispatch morto). Sonda tutti alla cieca.

Risultato: la chat aspetta fetch inutili quando la risposta era già su disco.

## GOAL
La chat bandi risponde **veloce** perché instrada dai dati catalogati (0 rete) e
sonda solo quando il catalogato manca o è scaduto. Il taglio è misurabile: meno
fetch per risposta su Benevento (062008, Halley) e Albano (058003, WordPress),
stesso output. Nessuna migrazione `storico.db`, nessun resweep nazionale (è
ciclo18b, deferred). Il codice esce **più modulare e riusabile**: la lettura-prima
del catalogo è un seam pulito su cui agganciare i connettori AT futuri.

## IN SCOPE
- **M1 — Semina alberatura da `endpoints.at`** (taglio grosso): `scopri_rami` legge
  `registro.endpoints.at` e parte da quell'URL; fallback al crawl attuale se
  assente/`None`. Persiste i 2 rami scoperti in cache DEDICATA
  `LIVE_DIR/alberatura/{istat}/rami.json` (TTL ~14gg) così il miss bandi (8h) non
  ri-crawla i rami. Self-contained in `alberatura.py`, testabile con fixture.
- **M2 — bandi_live legge la mappa-cache prima di sondare**: se
  `mappa-connettore/{istat}.json` è calda e `amministrazione_trasparente_via ==
  "REST"`, salta il probe `/wp-json/types` e semina il rest_base noto; fallback al
  probe se fredda/stale. Campo additivo `bandi` rest_base su `MappaConnettore`
  (default, back-compat, popolato al prossimo `_sonda_mappa`).
- **M3 — Routing AT-aware + fallback freschezza**: wire `_CONNETTORE_AT_PER_
  PIATTAFORMA` come dispatch `piattaforma_at → connettori in UNION`; salta i probe
  impossibili (Halley-only senza apice WP → niente cpt/pages); cascata solo se
  TUTTI i catalogati tornano vuoti o `rilevato_il`/`ultima_scansione` oltre TTL.
- **Docs**: dopo l'esecuzione, riscrivere le pagine che descrivono la catena di
  discovery/retrieval (`/info` «come funziona», eventuali .md in `site/`) per
  riflettere il leggi-prima e la regola catalogo→cascata. Onesto: cosa si legge da
  disco, cosa resta live.
- **Misura**: contatore fetch prima/dopo per mossa, su 062008 + 058003, nel report.

## CONSTRAINTS
- Stack: Python (api/treasureiq), SQLite storico.db (versionato, NON toccato qui),
  cache JSON in LIVE_DIR, Next/React (web) — la chat consuma gli stessi endpoint.
- **VELOCITÀ CHAT = obiettivo primario**: ogni mossa deve ridurre (mai aumentare) i
  fetch per risposta; nessuna regressione di latenza sul cache-hit.
- **MODULARITÀ / RIUSO**: la lettura-prima è un helper condiviso, non copincollato
  per connettore; il dispatch `piattaforma_at→connettore` è la porta d'ingresso per
  le AT nuove (una riga in tabella, non un `if` nel motore). Niente duplicazione fra
  `bandi_live`, `alberatura`, `mappa_connettore`.
- **SICUREZZA**: ogni fetch resta dietro la guardia SSRF `fetch_guardato` (per-hop,
  host atteso). Un URL letto dal catalogo NON salta la guardia: si valida come
  quello live. Cache illeggibile = cache assente (mai crash, mai fiducia cieca).
- Non rompere i test esistenti (`test_bandi_live`, `test_registro`, alberatura,
  mappa_connettore). API in container su :8010, source non montato → `docker compose
  up -d --build api` per test live; container ha rete, host bash no; pytest in
  `api/.venv/bin/pytest` (PYTHONPATH=. da `api/`).
- Delega subagent su Sonnet/Fable, mai Opus (crediti).
- Mai commit su main. Branch `ciclo18a/discovery-leggi-prima` da
  `ciclo17/documenti-halley` (entrambi toccano `bandi_live.py`). Ogni mossa = 1
  commit.

## DECISIONS
- **D-01** Catalogo per instradare (0 rete) → cascata SOLO se il connettore scelto
  torna vuoto o il dato è oltre TTL. **MAI verify-first**: ricontrollare l'AT
  rifarebbe la sonda che volevi evitare.
- **D-02** Persistenza rami AT: cache DEDICATA `alberatura/{istat}/rami.json`, NON
  allargare `registro.endpoints` (nessun accoppiamento allo scrittore-scan; i rami
  si scoprono a chat-time, non a scan-time).
- **D-03** Union esplicita per la doppia-piattaforma (BASE + AT + sottodominio
  legacy): il dispatch può girare più connettori e deduplicare; non si perde una
  fonte per «botta sicura» su una sola.
- **D-04** `storico.db` NON toccato. Il widening census + change-detection nazionale
  è ciclo18b, deferred (prima o dopo il 14 ago, da decidere). Vedi
  memoria `discovery-tre-cassetti-leggi-prima`.
- **D-05** Fallback su miss/stale è la rete di correttezza contro classificazioni
  sbagliate/vecchie dello sweep: la cascata cieca resta come rimedio, non sparisce.
- **D-06** Degrado onesto: un catalogo assente/illeggibile → si sonda (come oggi),
  non si inventa. `NON_TROVATA`/vuoto restano dati, non errori.

## OUT OF SCOPE
- Migrazione schema `storico.db`, resweep nazionale, nuove misure analytics
  (tutto ciclo18b).
- Nuovi connettori AT/vendor: qui si prepara solo il seam del dispatch, non si
  aggiungono famiglie.
- Lettura del contenuto dei PDF (confine D-07 invariato: si porta al documento).
