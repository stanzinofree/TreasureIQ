# T0 Step 3 — Programma di esecuzione (per Codex)

> **Confermato da Codex il 2026-08-21.** Le firme pubbliche restano
> `ComuneNoto`; `MunicipalityRecord` è interno al registry e viene convertito
> al confine. `_tutti` resta una funzione disponibile per `chat/respond.py`,
> senza cache propria. Si procede un gruppo alla volta.

> Documento di programma, prodotto da Claude (analisi Fable) il 2026-08-21. Esecutore: Codex.
> Fonte di verità dei vincoli: `docs/workstreams/t0-codice-istat/planning.md` (Step 3 APPROVATO),
> `done.md` (inventario Step 0, contratti Step 1-2), `execution.md` (trappola doppia cache).
> **Freeze attivo**: solo edit di codice + test su un branch locale. Nessun commit, nessun push,
> nessun deploy, nessuna rigenerazione o scrittura di `data/comuni-istat.json`.

## 0. Perimetro

Migrare i 10 siti di lettura censiti nello Step 0 a delegare a
`api/treasureiq/municipality_registry.py` (`get_registry` → `MunicipalityRegistry` → `SourceFrame`),
preservando le quattro firme pubbliche runtime:

- `sonda_live.comune_per_codice(codice) -> ComuneNoto | None`
- `sonda_live.risolvi_comune(hint) -> ComuneNoto | None`
- `sonda_live.cerca_comuni(query, *, limite=8) -> list[ComuneNoto]`
- `registro._carica_comuni_ipa() -> dict[codice, codice_ipa]`

Prima di toccare qualsiasi file, Codex **riverifica l'inventario** (potrebbe essere comparso un lettore nuovo):

```
grep -rn "comuni-istat" api/treasureiq --include="*.py"
```

Atteso: i 10 siti di `done.md` §A + il generatore `ingest/comuni_istat.py` (che NON si tocca) + docstring. Un sito nuovo non inventariato blocca il gruppo relativo finché non è classificato.

**Scoperta aggiuntiva rispetto a `done.md`** (verificata su codice, 2026-08-21): esiste un **consumatore indiretto nascosto** della cache privata: `api/treasureiq/chat/respond.py:2677` — `_tutti_comuni()` importa `sonda_live._tutti` direttamente e lo avvolge in un **terzo** `@lru_cache(maxsize=1)` (e `_frequenza_parole_nome()` ne deriva un quarto). Non è un lettore del file, ma è un dipendente del simbolo privato `_tutti`: il Gruppo 5 deve tenerlo vivo. Non riapre lo Step 0.

---

## 1. Analisi rischi — perché la migrazione è delicata lettore-per-lettore

### R1 — La doppia cache `_indice`/`_tutti` (sito 1)
`sonda_live.py:110` `_indice` e `sonda_live.py:178` `_tutti` sono **due** `@lru_cache(maxsize=1)` indipendenti sullo stesso frame. `comune_per_codice`/`risolvi_comune` leggono da un lato, `cerca_comuni` dall'altro: invalidarne una sola produce un processo che risponde con **due versioni del frame contemporaneamente** (già morso in Step 2: la fixture di parità serviva il frame reale da `_tutti` finché non le puliva entrambe — `execution.md`). Peggio: `respond.py:_tutti_comuni` aggiunge un terzo strato. Una migrazione parziale che lascia in vita una delle due cache non è uno stato intermedio accettabile: è il bug che lo Step 3 esiste per eliminare.

### R2 — Quattro fail-mode divergenti su cui i caller possono essersi adagiati
| Lettore | Oggi, frame assente | Oggi, frame corrotto (JSON rotto) |
|---|---|---|
| `sonda_live._indice` | warning + `{}` → sonda **muta** | `json.JSONDecodeError` **non gestito** al primo lookup (accidentale) |
| `registro._carica_comuni_ipa` | warning + `{}` (try/except largo) | warning + `{}` (lo stesso except ingoia tutto) |
| `registro_cli` (×2) | `SystemExit` parlante («esegui 'make frame-nazionale'») | `JSONDecodeError` grezzo |
| `dati_cli._stato` | **omissione silenziosa** della sezione dal report | `JSONDecodeError` grezzo |
| `censimento` (×5) | `FileNotFoundError` **grezzo** | `JSONDecodeError` grezzo |

Il rischio non è solo la divergenza: è che **qualche caller dipenda da un comportamento accidentale**. Esempi concreti da verificare prima di ogni gruppo: (a) uno script/Make target che distingue traceback da `SystemExit`; (b) la chat che conta sul fatto che frame corrotto = eccezione (oggi crasherebbe) e non = mutismo; (c) `dati_cli` usato in pipeline che parse-a l'output e non tollera righe nuove. La regola del programma: **assente → si preserva il fail-mode attuale esattamente; corrotto → il comportamento oggi è accidentale (eccezione grezza) e si corregge nel modo più vicino al fail-mode «assente» di quel lettore**, documentando la correzione nel test.

### R3 — 8/10 siti bypassano `ComuneNoto`
Ogni sito grezzo ha piccole assunzioni implicite sui dict (`r["codice_istat"]`, `.get("sito")`, chiavi provincia/regione passate a `censisci_molti`). Passare a `MunicipalityRecord` (frozen, auto-guardia 6 cifre) può **far emergere righe che oggi passavano zitte** — è il punto, ma va fatto dietro il validator (che le rifiuta come frame `INVALID`), non come `ValidationError` pydantic sparsa a metà comando.

### R4 — Tipo di ritorno delle firme pubbliche
`MunicipalityRecord` è un superset di `ComuneNoto` (+`codice_ipa`). Se le firme di `sonda_live` restituissero `MunicipalityRecord`, ogni `model_dump()`/serializzazione a valle (es. payload API della tendina comuni, `api.py:721`) acquisterebbe la chiave `codice_ipa`: **cambio di contratto osservabile**. Inoltre `ComuneNoto.sito` è campo obbligatorio (senza default), `MunicipalityRecord.sito` ha default `None`. Decisione: **`ComuneNoto` resta la classe di ritorno pubblica**; i wrapper convertono al confine (vedi Gruppo 5).

### R5 — Cache keyed su path e monkeypatch nei test
`get_registry` è keyed su `(path risolto, baseline)`. I test esistenti monkeypatchano `sonda_live.COMUNI_ISTAT_PATH`: i wrapper devono leggere **l'attributo di modulo a runtime di chiamata** (non catturare il valore a import-time), o i monkeypatch smettono di funzionare. Inoltre `get_registry` **non cache-a i fallimenti** (ritenta a ogni chiamata), mentre oggi `_indice` cache-a per sempre il `{}` del frame assente: per non spammare i log, il wrapper di `sonda_live` usa un flag warn-once di modulo.

### R6 — Semantica di staleness invariata
Sia le lru attuali sia `_CACHE` del registry vivono fino a fine processo: nessun lettore deve acquisire (né perdere) reload automatici. La sola invalidazione legittima resta `reset_registry_cache()` nei test.

---

## 2. Ordine di migrazione — 5 gruppi, dal più isolato al più accoppiato

**`sonda_live` NON è primo: è ultimo (Gruppo 5).** Motivo: ha 41+ caller runtime (chat, API), la doppia cache, e un consumatore nascosto del simbolo privato. I gruppi 1-4 sono batch/laterali, a raggio d'esplosione piccolo: validano il registry contro pattern d'uso reali, rodano lo schema «caratterizzazione → migrazione → parità», e lasciano `sonda_live` intatto come implementazione di riferimento finché tutti gli altri sono verdi. Migrarlo per primo renderebbe subito tautologici i test di parità dello Step 2 e concentrerebbe il rischio massimo nel momento di minima confidenza.

**Regola per ogni gruppo** (invariante, non negoziabile):
1. *Prima* della modifica: scrivere/verificare i **test di caratterizzazione** del comportamento attuale (output e fail-mode) su fixture in `tmp_path`; girarli verdi contro il codice non migrato.
2. Migrare.
3. Gli stessi test devono restare verdi **senza modifiche** (salvo i punti di correzione fail-mode dichiarati sotto, che hanno un test nuovo dedicato).
4. Suite combinata completa verde (comando in §4).

### Gruppo 1 — `dati_cli` (sito 5) — il più isolato
- **File**: `api/treasureiq/dati_cli.py` (`_stato`, riga ~46).
- **Modifica**: sostituire `json.loads(frame.read_text(...))` con `get_registry(DATA_DIR / "comuni-istat.json")`; conteggi da `registry.frame.tutti()`; `con_sito = sum(1 for r in ... if r.sito)`.
- **Fail-mode**: `FrameIOError` → **omissione della sezione, come oggi** (exit 0). `FrameInvalidError` → correzione: una riga diagnostica su stderr + sezione omessa, exit 0 (il report è per umani; l'exit code non cambia, quindi nessun caller si rompe).
- **Test**: report con fixture valida stampa `FRAME NAZIONALE : N comuni, M con sito`; frame assente → sezione assente, exit 0; frame corrotto → riga diagnostica su stderr, exit 0.

### Gruppo 2 — `registro_cli` (siti 3-4)
- **File**: `api/treasureiq/registro_cli.py` — `_comuni_tutti` (riga ~78) e `_anagrafe_comuni` (riga ~260).
- **Modifica**: entrambe passano da `get_registry(COMUNI_ISTAT_PATH)` (attenzione R5: `COMUNI_ISTAT_PATH` è importato da `sonda_live`, risolverlo a runtime). `_comuni_tutti` → `sorted(r.codice_istat for r in registry.frame.tutti())`. `_anagrafe_comuni` → `dict[str, MunicipalityRecord]`.
- **Confine dict**: `censimento.censisci_molti` (riga 1280) resta dict-based in questo gruppo: la conversione `record.model_dump()` avviene **solo** al punto di chiamata in `_fase_censimento`. Il criterio «niente dict grezzi» è soddisfatto: il dict a valle è la proiezione di un record validato, non il JSON grezzo.
- **Fail-mode**: `FrameIOError` → `SystemExit` con **lo stesso messaggio verbatim** («comuni-istat.json assente (...): esegui 'make frame-nazionale'.»). `FrameInvalidError` → correzione: `SystemExit` con messaggio nuovo parlante che elenca i codici issue (`exc.report`), sempre non-zero. Nota: l'exit-code dedicato per i batch è in «Decisioni in attesa» (`execution.md`) — lo Step 3 **non** introduce una tassonomia nuova, resta `SystemExit(msg)` (exit 1).
- **Test**: assente → `pytest.raises(SystemExit)` con match su «make frame-nazionale»; corrotto → `SystemExit` con match sul messaggio invalido; fixture valida → codici identici al pre-migrazione (caratterizzazione), valori anagrafe istanze di `MunicipalityRecord`.

### Gruppo 3 — `censimento` (siti 6-10) — la correzione più importante
- **File**: `api/treasureiq/ingest/censimento.py`, righe 1474, 1612, 1656, 1691, 1728.
- **Modifica**: un **unico** helper privato di modulo, es. `_frame_records() -> list[MunicipalityRecord]`, che chiama `get_registry(DATA_DIR / "comuni-istat.json")` e traduce `FrameIOError`/`FrameInvalidError` in `SystemExit` parlante (stesso stile del Gruppo 2). Tutti e cinque i siti lo chiamano; conversione `model_dump()` solo dove `campiona`/`censisci_molti` richiedono dict.
- **Fail-mode**: qui la correzione è **sancita** da `done.md` §D («priorità: dare a censimento la guardia che oggi non ha»): da `FileNotFoundError` grezzo → `SystemExit` con messaggio. Proprietà preservata per i caller: processo termina non-zero. Verifica pre-migrazione: `grep -rn "FileNotFoundError" api` per escludere che qualcuno catturi l'eccezione attuale attorno ai comandi censimento.
- **Test**: per il comando CLI con `TREASUREIQ_DATA_DIR` puntato a `tmp_path`: assente → `SystemExit` parlante (non traceback); corrotto → `SystemExit` con messaggio distinto; mini-frame valido → la selezione/campionamento produce gli stessi codici del pre-migrazione (caratterizzazione sul solo tratto di selezione, senza rete).

### Gruppo 4 — `registro._carica_comuni_ipa` (sito 2) — 4ª firma
- **File**: `api/treasureiq/registro.py` (righe ~70-90).
- **Modifica**: il corpo diventa `get_registry(_COMUNI_ISTAT_PATH).ipa_map()`. `_comuni_ipa_cache` resta come memo della **vista derivata** (non è una seconda cache del frame: il frame vive solo nel registry) — accettabile perché `ipa_map()` costruisce un dict da 7.8k voci a ogni chiamata.
- **Firma**: `_carica_comuni_ipa() -> dict[codice, codice_ipa]` **identica**.
- **Fail-mode**: oggi il try/except largo dà warning + `{}` sia su assente sia su corrotto → **preservato entrambi**, ma con due messaggi di log distinti (`FrameIOError` vs `FrameInvalidError`): esiti distinguibili senza cambiare il caller.
- **Test**: parità `ipa_map` vs mappa costruita a mano dalla fixture (esiste già `test_ipa_map_only_where_present`, si aggiunge il lato `registro`); assente → `{}` + warning I/O in caplog; corrotto → `{}` + warning invalid in caplog.

### Gruppo 5 — `sonda_live` (sito 1) + consumatore nascosto — l'accoppiato
- **File**: `api/treasureiq/sonda_live.py`; test `api/tests/test_municipality_registry.py` (fixture `sonda_su_frame`), `test_sonda_live.py`, `test_ricerca_comuni.py`; **verifica** (senza modifica se possibile) `api/treasureiq/chat/respond.py:2677`.
- **Pre-lavoro obbligatorio**: convertire i test di parità dello Step 2 in **golden test di caratterizzazione** (asserzioni su valori attesi letterali dalla fixture, non `assert registry.X == sonda_live.X`): dopo la delega il confronto incrociato diventa tautologico e perderebbe ogni potere di regressione.
- **Modifica** (dettaglio in §3): `_indice` e `_tutti` con `@lru_cache` **spariscono**. Le 4 funzioni pubbliche diventano thin wrapper su `_registry()`; conversione al confine `MunicipalityRecord → ComuneNoto` (R4): `ComuneNoto(codice_istat=r.codice_istat, nome=r.nome, provincia=r.provincia, regione=r.regione, sito=r.sito)`. `_tutti` sopravvive come **funzione semplice non cache-ata** (wrapper su `registry.frame.tutti()` convertito) perché `respond.py:2679` lo importa e ha già il suo lru sopra; `_indice` si elimina (nessun consumatore esterno, verificato).
- **Fail-mode**: `FrameIOError` → warning warn-once «sonda disattivata» + degradazione identica a oggi (`None`/`[]`). `FrameInvalidError` → correzione del comportamento accidentale (oggi: `JSONDecodeError` grezzo nel runtime chat): `logger.error` con i codici issue + stessa degradazione muta. Motivazione: nel runtime un crash mentre un cittadino aspetta è peggio del mutismo, e il crash odierno non è un contratto, è un incidente. `REVIEW_REQUIRED` → frame servito, `registry.warnings` propagati (già garantito da `SourceFrame`).
- **Test**: golden 4 firme; fixture `sonda_su_frame` aggiornata a `reset_registry_cache()` (i due `cache_clear()` non esistono più); il **test di unificazione cache** di §4; suite combinata piena inclusi `test_ricerca_comuni.py`, `test_ricerca_live.py`, `test_sonda_live.py`.

---

## 3. Strategia cache — come sparisce la doppia cache

### Opzione A — `sonda_live` delega a `get_registry()`; funzioni pubbliche = thin wrapper *(raccomandata)*
Un solo helper privato:

```
_registry() -> MunicipalityRegistry | None   # legge sonda_live.COMUNI_ISTAT_PATH a call-time
```

che cattura `FrameIOError`/`FrameInvalidError` (fail-mode §2-G5) e restituisce `None` (sonda muta). Le 4 firme e `_tutti` leggono da lì; nessuna `lru_cache` residua in `sonda_live`.
- **Pro**: una sola cache di frame in tutto il processo (`municipality_registry._CACHE`); un solo punto di invalidazione (`reset_registry_cache()`); coerenza garantita per costruzione — `comune_per_codice` e `cerca_comuni` non possono mai servire due versioni; i gruppi 1-4 usano già lo stesso meccanismo.
- **Contro**: i fallimenti non sono cache-ati (retry a ogni lookup: mitigato dal warn-once); la chiave `_CACHE` dipende dal path → i test che monkeypatchano `COMUNI_ISTAT_PATH` funzionano solo se il wrapper lo legge a runtime (R5).

### Opzione B — un solo `@lru_cache(1) _frame() -> SourceFrame | None` interno a `sonda_live`; `_indice`/`_tutti` funzioni semplici sopra
- **Pro**: modifica più locale; nessuna dipendenza dalla chiave path del registry.
- **Contro**: **non elimina la doppia cache a livello di processo** — quando anche `registro`/CLI usano `get_registry`, il frame vive di nuovo in due cache (lru di `sonda_live` + `_CACHE` del registry) con due invalidazioni da coordinare: è la stessa trappola un piano più in alto. Inoltre cache-a il fallimento per sempre come oggi (mutismo permanente).

### Opzione C — tenere `_indice`/`_tutti` e «invalidarle insieme» con un helper
- **Contro**: dimostrabile solo per disciplina, non per costruzione; lascia in vita il parsing grezzo; boccia il criterio 1 nello spirito. Scartata.

**Raccomandazione secca: Opzione A.** È l'unica in cui «`sonda_live` non mantiene due cache indipendenti» è vero per costruzione e verificabile con un singolo test di invalidazione.

---

## 4. Contratto di test per Codex

Build una volta per sessione (dalla root del repo, `R=$(git rev-parse --show-toplevel)`):

```
docker build -q -t treasureiq-api-dev --target dev api
```

Forma del run (il mount `:ro` su `data/` è la garanzia meccanica del criterio «nessuna scrittura sul frame»):

```
docker run --rm -v "$R/api:/src" -v "$R/data:/data:ro" \
  -e TREASUREIQ_DATA_DIR=/data -w /src treasureiq-api-dev \
  python -m pytest <TARGET> -q
```

Un gruppo è **chiuso** solo quando sono verdi, nell'ordine: (a) i suoi test di caratterizzazione pre-migrazione, (b) gli stessi test post-migrazione senza modifiche, (c) i test nuovi di fail-mode, (d) la suite combinata piena.

| Gruppo | Test richiesti (tutti deterministici, senza rete, frame solo fixture in `tmp_path`) | `<TARGET>` del run di gruppo |
|---|---|---|
| G1 | report con frame valido (conteggi esatti); assente → sezione omessa, exit 0; corrotto → diagnostica stderr, exit 0 | `tests/test_dati_cli*.py` |
| G2 | `_comuni_tutti` parità codici; `_anagrafe_comuni` → `MunicipalityRecord`; assente → `SystemExit` msg verbatim; corrotto → `SystemExit` msg invalido | `tests/test_registro_cli*.py` |
| G3 | helper unico: assente → `SystemExit` parlante (×5 comandi o parametrizzato); corrotto → `SystemExit` distinto; selezione/campione parità codici su mini-frame | `tests/test_censimento*.py` |
| G4 | parità `_carica_comuni_ipa` vs fixture; assente → `{}` + warning I/O; corrotto → `{}` + warning invalid (caplog distinti) | `tests/test_municipality_registry.py tests/test_registro*.py` |
| G5 | golden 4 firme; tipo di ritorno è `ComuneNoto` **senza** `codice_ipa` nel `model_dump()`; assente → `None`/`[]` + warn-once; corrotto → `None`/`[]` + `logger.error`; **test unificazione cache** (sotto) | `tests/test_municipality_registry.py tests/test_sonda_live.py tests/test_ricerca_comuni.py tests/test_ricerca_live.py` |

**Test di unificazione cache (G5, chiude il criterio 1)** — su fixture A e B in `tmp_path`:
1. punta `COMUNI_ISTAT_PATH` ad A, chiama le 4 firme → risposte da A;
2. punta a B **senza** reset → tutte e quattro rispondono ancora coerentemente (mai miste A/B);
3. `reset_registry_cache()` → `comune_per_codice` **e** `cerca_comuni` servono entrambe B. (È esattamente la regressione della trappola `_indice`/`_tutti`.)

**Suite combinata piena** (dopo ogni gruppo, deve restare ≥ 82 passed + i nuovi, 0 regressioni):

```
docker run --rm -v "$R/api:/src" -v "$R/data:/data:ro" \
  -e TREASUREIQ_DATA_DIR=/data -w /src treasureiq-api-dev \
  python -m pytest tests/test_frame_validation.py tests/test_municipality_registry.py \
    tests/test_sonda_live.py tests/test_ricerca_comuni.py tests/test_ricerca_live.py \
    tests/test_dati_cli*.py tests/test_registro*.py tests/test_censimento*.py -q
```

A fine Step 3, un run dell'intera `tests/` per escludere effetti collaterali sui caller (chat, api, catalog).

---

## 5. Mappatura sui criteri di accettazione (planning.md, Step 3)

| Criterio | Dove è soddisfatto | Verifica |
|---|---|---|
| `sonda_live` non mantiene due cache indipendenti del frame | G5 + Opzione A (§3): `_indice`/`_tutti` lru eliminate, unica cache in `municipality_registry._CACHE` | test unificazione cache (§4) + assenza di `lru_cache` sul frame in `sonda_live` |
| i lettori migrati non leggono più dict grezzi | G1-G5: ogni sito passa da `get_registry` → `MunicipalityRecord`; dict solo come `model_dump()` al confine `censisci_molti` | test caratterizzazione G2/G3 (`isinstance` sui valori anagrafe) |
| le quattro firme runtime restano compatibili | G4 (`_carica_comuni_ipa`) e G5 (le tre di `sonda_live`, ritorno `ComuneNoto`) | golden test G5 + parità G4; nessun caller modificato |
| errore I/O e `FrameOutcome.INVALID` distinguibili | ogni gruppo: `FrameIOError` vs `FrameInvalidError` con esito/log distinto per lettore (§2) | test fail-mode di G1, G2, G3, G4, G5 (caplog/messaggi distinti) |
| nessuna scrittura su `data/comuni-istat.json` | tutti i test su fixture `tmp_path`; docker monta `data/` `:ro` | mount `:ro` in ogni comando §4 + `git status` pulito su `data/` |
| test deterministici verdi e freeze rispettato | nessuna rete nei test nuovi; branch locale, zero commit/push/deploy | suite combinata §4 verde; log freeze in `execution.md` |

Nessun criterio scoperto.

---

## 6. Anteprima Step 4-6 — cosa lo Step 3 NON deve precludere

- **Step 4 (generatore atomico)**: `ingest/comuni_istat.py` resta intoccato; non introdurre in nessun lettore assunzioni sul *come* il file viene scritto (niente lock, niente path temporanei impliciti).
- **Step 5 (manifest/hash + provenienza baseline)**: `get_registry` è già keyed su `(path, baseline)`; non appiattire la chiave né introdurre baseline implicite nei lettori — la provenienza si aggancerà lì. **Nessun manifest/hash nello Step 3.**
- **Step 6 (diff upstream + transizioni amministrative)**: tenere `MunicipalityRecord` come unico punto di proiezione della riga (nessun lettore che ri-deriva campi dal dict), così alias/transizioni si inseriscono in un posto solo; ricordare la trappola nome-nel-path di `data/seed/{ente}_{codice}.json`.

---

## Nota di verifica (Claude, 2026-08-21)

Prima del deposito ho verificato su codice i riferimenti chiave del programma:
`sonda_live.py:110` `_indice` e `:178` `_tutti` = due `@lru_cache(maxsize=1)`;
`chat/respond.py:2677` `_tutti_comuni()` importa `sonda_live._tutti` e lo avvolge
in un terzo lru, con `_frequenza_parole_nome()` (:2683) che ne deriva un quarto.
Numeri di riga e catena confermati. Il Gruppo 5 deve tenere vivo `_tutti` come
funzione (non cache-ata) o `respond.py` perde l'universo comuni.
