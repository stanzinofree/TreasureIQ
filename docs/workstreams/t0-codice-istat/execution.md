# T0 — Execution log

## Attività attiva

- Stato: **Step 0 completato e confermato (2026-08-21)** → inventario in
  `done.md`; Step 2 approvato, in attesa di esecuzione.
- Perimetro: analisi e inventario, nessuna modifica al runtime. Rispettato.
- Worker: fermo.
- Freeze: attivo.

### 2026-08-21 — Handoff Codex → Step 1

- Azione: confermato l'inventario dei 10 accessi diretti al frame.
- Vincolo: ampliare in futuro la migrazione agli artefatti `bandi-criteri`,
  `alberatura`, catalog shadow e profili/conversazioni.
- Step autorizzato: fixture + contratto `FrameValidator`.
- Runtime: ancora intatto; nessun deploy e nessun frame rigenerato.

### 2026-08-21 — Claude — Step 0

- Azione: inventario esaustivo degli accessi a `comuni-istat.json`.
- File coinvolti (solo letti): `sonda_live.py`, `registro.py`, `registro_cli.py`,
  `dati_cli.py`, `ingest/censimento.py`, `ingest/comuni_istat.py`.
- File scritti (docs): `done.md` (inventario), questo log, `planning.md`.
- Esito: 6 moduli / 10 siti / 4 fail-mode. Due novità: `censimento` senza
  guardia in 5 punti; 8/10 letture bypassano `ComuneNoto`.
- Blocco: nessuno. Attende valutazione Codex sull'inventario.

### 2026-08-21 — Claude — Step 1 (chiuso lato Claude, attende concordanza)

- Azione: costruito `FrameValidator` read-only + fixture + test. Nuovo modulo
  non wire-ato ad alcun lettore; nessuna scrittura su `data/comuni-istat.json`.
- File nuovi: `api/treasureiq/frame_validation.py`,
  `api/tests/test_frame_validation.py`.
- Esito: **19 passed in 0.58s** (docker dev, `tests/test_frame_validation.py`).
- Contratto completo (esiti, severità, firme, tabella policy, 7 fixture) in
  `done.md` § «Step 1 — Contratto FrameValidator».
- Policy: identità = `invalid` bloccante; opzionale mancante / schema additivo /
  `codice_ipa` condiviso / calo vs baseline (relativo, non assoluto) =
  `review_required`. «sito senza schema» = accettato (hostname nudo normale).
- Handoff Codex: contratto approvato con guardrail documentati in `done.md`;
  Step 2 può iniziare senza modificare i lettori runtime.
- Runtime: ancora intatto. Freeze rispettato.

### 2026-08-21 — Claude — Step 2 (chiuso lato Claude, attende concordanza)

- Azione: costruito `MunicipalityRegistry` + `SourceFrame` typed read-only.
  Nuovo modulo non wire-ato ad alcun lettore; nessuna scrittura sul frame.
- File nuovi: `api/treasureiq/municipality_registry.py`,
  `api/tests/test_municipality_registry.py`.
- Esito: **82 passed** (suite combinata `sonda_live` + `ricerca_comuni` +
  `frame_validation` + `municipality_registry`), 0 regressioni.
- Modello: `MunicipalityRecord` (frozen pydantic) = superset di `ComuneNoto` +
  `codice_ipa` → consolida anche la 4ª firma (mappa IPA). Auto-guardia:
  `codice_istat` non-6-cifre rifiutato anche in costruzione diretta.
- Guardrail: `SourceFrame` si costruisce solo da righe validate (rifiuta
  `INVALID`→`FrameInvalidError`); errore I/O (`FrameIOError`) distinto da
  contenuto invalido; `REVIEW_REQUIRED` accettato ma warning propagati
  (`.warnings`); `get_registry` carica una volta per (path, baseline).
- Le 4 firme replicate fedelmente (normalizzazione, guardia toponimo, chiave
  compatta, omonimi→None, ranking cerca) con **test di parità vs `sonda_live`**
  sulla stessa fixture iniettata.
- Bug preso in corsa: `sonda_live` ha **due** cache lru (`_indice` e `_tutti`);
  la fixture di parità le pulisce entrambe, altrimenti `cerca_comuni` serviva
  il frame reale. Emerso solo girando la suite combinata, non isolata.
- Blocco: attende concordanza Codex sul contratto prima dello Step 3.
- Runtime: ancora intatto. Freeze rispettato.

### 2026-08-21 — Claude (analisi Fable) — Programma Step 3 per Codex

- Azione: analizzati Step 3-6 con Fable; prodotto `step3-program.md` — programma
  d'esecuzione dettagliato che Codex implementerà (Claude non scrive il runtime).
- Contenuto: 5 gruppi di migrazione (dati_cli → registro_cli → censimento →
  registro IPA → sonda_live per ultimo), strategia cache (Opzione A: sonda_live
  delega a `get_registry`, lru doppia eliminata), contratto di test per gruppo,
  mappatura sui 6 criteri di accettazione, anteprima Step 4-6.
- Verificato su codice prima del deposito: `_indice`:110 e `_tutti`:178 (due lru
  indipendenti); scoperta nuova → `chat/respond.py:2677` avvolge `sonda_live._tutti`
  in un terzo lru (`_tutti_comuni`) + un quarto derivato (`_frequenza_parole_nome`):
  il Gruppo 5 deve tenere `_tutti` vivo come funzione. Non riapre lo Step 0.
- Decisione di contratto da confermare con Codex: le firme pubbliche restano di
  tipo `ComuneNoto` (NON `MunicipalityRecord`), conversione al confine, così il
  payload API non acquisisce `codice_ipa` (cambio osservabile evitato).
- Blocco: Codex conferma/adegua il programma, poi esegue gruppo per gruppo.
- Runtime: ancora intatto. Freeze rispettato.

## Decisioni in attesa

- Nome definitivo dei contratti (`MunicipalityRegistry`, `SourceFrame`,
  `FrameValidator` o alternative).
- Exit code dedicato per i batch con frame invalido.
- Politica di soglia per calo del conteggio.
- Forma della tabella alias/transizioni.

## Regola per gli aggiornamenti

Ogni voce deve contenere: data, agente, azione, file coinvolti, esito e
eventuale blocco. Non usare questo file per segnare attività già concluse:
spostarle in `done.md`.

### 2026-08-21 — Codex — concordanza Step 2

- `MunicipalityRecord` superset di `ComuneNoto` + `codice_ipa`: approvato.
- Provenienza/hash baseline: rimandata allo Step 5 manifest; fino ad allora
  baseline esplicita ma non autorevole.
- Caso assente chiarito: validator diretto → `INVALID/frame_absent`;
  `SourceFrame.from_path` → `FrameIOError`; contenuto presente invalido →
  `FrameInvalidError`.
- Step 3 autorizzato: delega dei lettori, con attenzione alla doppia cache
  `_indice`/`_tutti`.
- Freeze rispettato; nessuna modifica runtime effettuata da Codex.

### 2026-08-21 — Codex — Gruppo 1 `dati_cli`

- Caratterizzazione aggiunta in `api/tests/test_dati_cli.py`:
  frame valido, frame assente e frame invalido.
- `dati_cli._stato` ora legge il frame tramite `get_registry` e usa record
  typed per conteggi e presenza sito.
- Fail-mode preservato: file assente → sezione omessa, exit 0; frame invalido
  → diagnostica su stderr, sezione omessa, exit 0.
- Test: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_dati_cli.py -q`
  → **3 passed**.
- La build Docker del target dev è stata interrotta dopo accesso lento/bloccato
  al BuildKit; nessun container o dato è stato modificato. La verifica Docker
  resta da ripetere prima della chiusura complessiva dello Step 3.
- Gruppo 1: **chiuso localmente**, in attesa della suite Docker di conferma.

### 2026-08-21 — Codex — Gruppo 2 `registro_cli`

- `_comuni_tutti` e `_anagrafe_comuni` ora usano `get_registry` e leggono
  `sonda_live.COMUNI_ISTAT_PATH` a runtime, preservando i monkeypatch dei test.
- `_comuni_tutti` restituisce i codici dal registry; `_anagrafe_comuni` espone
  `dict[str, MunicipalityRecord]`.
- `_fase_censimento` proietta i record typed in dict solo al confine verso
  `censisci_molti`/`_registra`, senza usare il JSON grezzo.
- File aggiunto: `api/tests/test_registro_cli.py` con parità, file assente e
  frame invalido.
- Fail-mode: file assente mantiene `SystemExit` con il messaggio legacy
  `make frame-nazionale`; frame invalido produce `SystemExit` con i codici
  issue.
- Test gruppo + regressione: `PYTHONPATH=. .venv/bin/python -m pytest
  tests/test_registro_cli.py tests/test_dati_cli.py
  tests/test_municipality_registry.py -q` → **19 passed**.
- Suite combinata corrente: **103 passed**, inclusi frame, registry,
  `sonda_live`, ricerca, dati CLI e registro CLI.
- Gruppo 2: **chiuso localmente**, resta la conferma Docker prima del Gruppo 3.

### 2026-08-21 — Codex — Gruppo 3 `censimento`

- Verificata la pre-condizione: nessun caller cattura `FileNotFoundError` dal
  censimento; i cinque accessi diretti al frame erano tutti in `_anagrafe` e
  `_raccogli`.
- Introdotto `_frame_records()` come unico punto di caricamento: usa il
  registry typed e converte `FrameIOError`/`FrameInvalidError` in `SystemExit`
  parlante.
- Migrati i rami `solo_misurabili`, `solo_ignoti`, `tutti` e `campione`;
  `_anagrafe` proietta con `model_dump()` e le funzioni di censimento ricevono
  dict solo al confine compatibile esistente.
- Rimosse tutte le letture dirette `json.loads(...comuni-istat.json...)` dal
  modulo.
- Test aggiunti in `api/tests/test_censimento_frame.py` per record typed,
  file assente e frame invalido.
- Test gruppo + regressione:
  `PYTHONPATH=. .venv/bin/python -m pytest tests/test_censimento_frame.py
  tests/test_censimento.py tests/test_dati_cli.py tests/test_registro_cli.py
  tests/test_municipality_registry.py -q` → **63 passed**.
- Gruppo 3: **chiuso localmente**, in attesa della conferma Docker.

### 2026-08-21 — Codex — Gruppo 4 `registro._carica_comuni_ipa`

- Il corpo ora delega a `get_registry(_COMUNI_ISTAT_PATH).ipa_map()`.
- Firma e vista pubblica restano `dict[str, str]`; `_comuni_ipa_cache` rimane
  soltanto la cache della vista derivata, non una seconda lettura del frame.
- File assente o illeggibile → `{}` + warning classificato come I/O; frame
  invalido → `{}` + warning classificato come invalidità, con i codici issue.
- Aggiunti test dedicati in `api/tests/test_registro_ipa.py`.
- La configurazione logging del progetto usa un handler package-level con
  `propagate=False`; i test verificano quindi il messaggio passato al logger,
  mantenendo osservabile la distinzione senza alterare il logging globale.
- Test locali gruppo + regressioni: **51 passed** (un warning pre-esistente
  Starlette/httpx).
- Gruppo 4: **chiuso localmente**, in attesa della conferma Docker.

### 2026-08-21 — Codex — Gruppo 5 `sonda_live`

- Rimosse le due cache frame `_indice` e `_tutti` da `sonda_live`.
- Le funzioni pubbliche delegano al registry condiviso; `_tutti` resta
  disponibile come wrapper non cachato per `chat/respond.py`.
- `MunicipalityRecord` viene convertito al confine in `ComuneNoto`, quindi il
  payload pubblico non acquisisce `codice_ipa`.
- Errori di I/O degradano a `None`/lista vuota con warning una tantum; frame
  invalido degrada nello stesso modo con errore classificato.
- Aggiunto test di coerenza A/B: cambiando frame senza reset non si possono
  servire due versioni miste tra le quattro firme.
- Test Step 3 mirati: **91 passed**.
- Suite completa locale: **1050 passed, 41 skipped**, un warning pre-esistente
  Starlette/httpx.
- Gruppo 5: **chiuso localmente**, in attesa della conferma Docker.

### Nota infrastrutturale fuori scope T0

La suite Docker completa mantiene 20 failure pre-esistenti sui test che usano
la conversazione: `CONVERSATION_DB` ricade su `DATA_DIR/conversations.sqlite3`
mentre il test monta `/data:ro`. Il problema appartiene all'infrastruttura del
test/conversation DB, non alla migrazione del frame; va risolto separatamente
con fixture su tmp o mount dedicato scrivibile.

### Aggiornamento infra test — Codex — 2026-08-21

- `Makefile:test` ora monta `--tmpfs /test-state` e imposta
  `TREASUREIQ_CONVERSATION_DB=/test-state/conversations.sqlite3`.
- I 20 errori `attempt to write a readonly database` sono scomparsi.
- `make test` Docker: **1082 passed, 6 skipped, 3 failed**.
- Le 3 failure residue sono indipendenti da T0 e riguardano
  `tests/test_wp_pages_caratterizzazione.py`: l'inspector PDF attuale segnala
  il PDF buono come “OCR richiesto”, mentre quei test caratterizzano il
  comportamento precedente (`pdfs_opened=1`, segmento PDF e `L1_MANUALE`).
  Sono da trattare nel workstream PDF/OCR, non nel fix del conversation DB.

### 2026-08-21 — Claude — Gruppo 1 conferma Docker

- Azione: rivisto il diff di `dati_cli._stato` (aderente al programma:
  `get_registry` + cattura `FrameIOError`→omesso / `FrameInvalidError`→stderr
  + record typed per conteggi/`.sito`). Fornita la verifica Docker che il
  BuildKit di Codex non aveva potuto completare.
- Build: `docker build -q --target dev api` → **exit 0**.
- Test (container, `data/` montato `:ro`):
  `pytest tests/test_dati_cli.py tests/test_frame_validation.py
  tests/test_municipality_registry.py tests/test_sonda_live.py
  tests/test_ricerca_comuni.py -q` → **85 passed in 0.84s**, 0 regressioni.
- Gruppo 1: **confermato anche in Docker**. Sbloccato il Gruppo 2 (`registro_cli`).
- Runtime app intatto; nessuna scrittura sul frame (mount `:ro`). Freeze rispettato.

### 2026-08-21 — Claude — Gruppo 2 conferma Docker

- Azione: rivisto il diff `registro_cli.py` (parte migrazione frame) e fornita
  la verifica Docker.
- Migrazione frame aderente al programma: `_registry_or_exit` legge
  `sonda_live.COMUNI_ISTAT_PATH` a runtime (R5), `FrameIOError`→`SystemExit`
  legacy «make frame-nazionale» verbatim, `FrameInvalidError`→`SystemExit` con
  codici issue; `_comuni_tutti` dai record del registry; `_anagrafe_comuni`→
  `dict[str, MunicipalityRecord]`; `model_dump()` solo al confine
  `_fase_censimento`→`censisci_molti`/`_registra`. Corretto.
- Nota di scope: il diff `registro_cli.py` vs HEAD contiene anche modifiche
  NON-T0 (flag `--usa-cache/--refresh/--refresh-dati`, refactor `_scansiona_uno`,
  import `refresh_connettore`/`refresh_dati_connettore`) — verosimilmente lavoro
  pre-esistente del branch, non del Gruppo 2. Non regrediscono i test; da tenere
  separate quando si isolerà il commit T0.
- Test (container, `data/` `:ro`):
  `pytest tests/test_registro_cli.py tests/test_dati_cli.py
  tests/test_frame_validation.py tests/test_municipality_registry.py
  tests/test_sonda_live.py tests/test_ricerca_comuni.py -q` → **88 passed in 0.75s**.
- Gruppo 2: **confermato in Docker**. Sbloccato il Gruppo 3 (`censimento`, 5 siti,
  la correzione guardia più importante).
- Runtime app intatto; nessuna scrittura sul frame. Freeze rispettato.

### 2026-08-21 — Claude — Gruppo 3 conferma Docker

- Azione: rivisto il diff `ingest/censimento.py` (parte migrazione frame) e
  fornita la verifica Docker.
- Migrazione aderente al programma: `_frame_records()` unico lettore del frame;
  rami `solo_misurabili`/`solo_ignoti`/`tutti`/`campione` e `_anagrafe()` passano
  tutti da lì; `model_dump()` solo al confine; correzione guardia sancita da
  `done.md` §D → `FileNotFoundError` grezzo sostituito da `SystemExit` parlante
  (assente e invalido distinti). Nessun `json.loads(comuni-istat.json)` diretto
  residuo (i soli match restano testo di help + il nuovo lettore guardato).
- Nota di scope: il diff include anche modifiche NON-T0 (regex `_HREF_URBI_AT`,
  promozione URL URBI in `scopri_pagina_at`, `allow_one_cross_host_redirect`,
  `import html`) — lavoro AT-discovery pre-esistente del branch, non del Gruppo 3.
  Da isolare al commit T0.
- Test (container, `data/` `:ro`):
  `pytest tests/test_censimento_frame.py tests/test_registro_cli.py
  tests/test_dati_cli.py tests/test_frame_validation.py
  tests/test_municipality_registry.py tests/test_sonda_live.py
  tests/test_ricerca_comuni.py -q` → **91 passed in 0.79s**.
- Gruppo 3: **confermato in Docker**. Sbloccato il Gruppo 4
  (`registro._carica_comuni_ipa`, 4ª firma).
- Runtime app intatto; nessuna scrittura sul frame. Freeze rispettato.

### 2026-08-21 — Claude — Step 4/5/6 (generatore atomico, manifest, diff)

- **Step 4 — generatore atomico** (`ingest/comuni_istat.py`): la pubblicazione
  ora *valida prima di scrivere* (`FrameValidator().validate`); un frame
  costruito `INVALID` è rifiutato (uscita 2) e il frame esistente resta intatto.
  La scrittura passa da `write_text` diretto a `frame_manifest.write_atomic`
  (temp + `os.replace`): un generatore interrotto non lascia mai un frame
  parziale. Calo copertura resta warning (uscita 1), non rifiuto.
- **Step 5 — manifest/hash + provenienza** (`frame_manifest.py` nuovo): accanto
  al frame nasce `comuni-istat.manifest.json` (sha256, row_count, valid_codes,
  generated_at, sources, coverage). Verifica a due registri: **dura** in
  build/CI (`make verify-frame`, uscita non-zero su mismatch), **morbida** a
  runtime (`SourceFrame.from_path` logga un warning ma serve comunque il frame;
  manifest assente = silenzio, i frame storici restano legittimi). `FrameBaseline`
  acquisisce provenienza opzionale (source_path/sha256/generated_at), additiva e
  fuori dalla chiave di cache del registry.
- **Step 6 — diff upstream + transizioni** (`--diff`, `make frame-diff`): solo
  lettura. Confronta il frame con l'elenco ISTAT fresco → aggiunti / rimossi /
  rinominati; `pianifica_transizioni` etichetta SOPPRESSIONE_O_FUSIONE / RINOMINA
  / NUOVO. **Nessuna scrittura, nessuna migrazione fisica**: spostare/riscrivere
  gli artefatti keyed sul codice (seed, `storico.db`, snapshot catalogo) resta
  bloccato dal lock storage-lifecycle (planning.md §Lock). Qui si produce solo il
  piano.
- Test (container, `data/` `:ro`): suite completa **1095 passed, 6 skipped,
  3 failed** — i 3 failure sono i preesistenti PDF/OCR di
  `test_wp_pages_caratterizzazione.py`, indipendenti da T0 e non toccati. I due
  nuovi file (`test_frame_manifest.py`, `test_comuni_istat_generator.py`) →
  13 passed. Nessuna regressione (1082 → 1095 = +13 nuovi).
- T0 chiuso end-to-end (Step 0–6). Migrazione fisica delle transizioni: fase
  coordinata separata, dopo storage-lifecycle.
