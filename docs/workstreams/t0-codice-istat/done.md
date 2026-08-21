# T0 — Done / handoff

Nessuno step implementativo è ancora chiuso.

## Analisi iniziale — Codex — 2026-08-21

- Verificato il frame corrente: 7.896 righe, codici ISTAT distinti e di sei
  cifre.
- Rilevati cinque gruppi di nomi omonimi.
- Rilevati 29 comuni senza sito, 8 senza `codice_ipa` e 3 valori IPA condivisi.
- Identificati lettori aggiuntivi in `censimento` e `dati_cli` oltre ai tre
  descritti inizialmente.
- Identificati i rischi di scrittura non atomica, hash solo a build, cache
  stale, soglia assoluta, manifest mancante e transizioni amministrative.
- Nessun codice runtime modificato e nessun frame rigenerato.

## Step 0 — Inventario accessi — Claude — 2026-08-21

Verificato sul codice, non stimato. Nessuna modifica al runtime.

### A. Lettori diretti del frame — 6 moduli, 10 siti, 4 fail-mode

Più ampio di «tre lettori» (analisi iniziale) e di «cinque» (review Codex §9.2):
`censimento` da solo apre il file in **cinque punti**.

| # | Modulo:riga | Funzione | Runtime/Batch | Cache | Guardia | Fail-mode se assente/rotto | Valida riga? |
|---|---|---|---|---|---|---|---|
| 1 | `sonda_live.py:122` | `_indice()` | runtime | `@lru_cache(1)` | `exists()` | warning + `{}` → **sonda muta** | sì (`ComuneNoto`) |
| 2 | `registro.py:82` | `_carica_comuni_ipa()` | runtime | cache propria | try/except | warning + `{}` → `codice_ipa` None | no (dict grezzo) |
| 3 | `registro_cli.py:83` | selezione comuni | batch | no | `exists()` | **`SystemExit`** parlante | no (dict grezzo) |
| 4 | `registro_cli.py:264` | anagrafe comando | batch | no | `exists()` | **`SystemExit`** parlante | no (dict grezzo) |
| 5 | `dati_cli.py:48` | report stato | batch | no | `exists()` | **omissione silenziosa** dal report | no (dict grezzo) |
| 6 | `censimento.py:1474` | comando censimento | batch | no | **nessuna** | **`FileNotFoundError` non catturato** | no (dict grezzo) |
| 7 | `censimento.py:1612` | comando censimento | batch | no | **nessuna** | **`FileNotFoundError` non catturato** | no (dict grezzo) |
| 8 | `censimento.py:1656` | comando censimento | batch | no | **nessuna** | **`FileNotFoundError` non catturato** | no (dict grezzo) |
| 9 | `censimento.py:1691` | comando censimento | batch | no | **nessuna** | **`FileNotFoundError` non catturato** | no (dict grezzo) |
| 10 | `censimento.py:1728` | comando censimento | batch | no | **nessuna** | **`FileNotFoundError` non catturato** | no (dict grezzo) |

**Quattro contratti di errore incoerenti** sullo stesso file: `{}` muto (runtime),
`SystemExit` (batch), omissione dal report (batch), crash non gestito (batch).
Provenienza a parte: `ingest/comuni_istat.py` **scrive** il frame (join ISTAT+IPA)
— è il generatore, non un lettore.

**Due scoperte che cambiano lo Step 1:**

1. **`censimento` non ha guardia in 5 punti.** Un frame assente non degrada:
   fa crashare i comandi di censimento con `FileNotFoundError` grezzo. È il
   caso peggio nascosto perché non c'è nemmeno un messaggio.
2. **8 siti su 10 leggono dict grezzo, non `ComuneNoto`.** L'unica validazione
   per-riga è in `sonda_live`. Un registro centrale che serve `ComuneNoto`
   validati elimina 8 parsing grezzi duplicati, non solo 2.

### B. Contratti runtime che restituiscono il codice (da preservare in firma)

- `sonda_live.comune_per_codice(codice) -> ComuneNoto | None` — la via non ambigua (41 caller);
- `sonda_live.risolvi_comune(hint) -> ComuneNoto | None` — token interi, `None` su omonimi;
- `sonda_live.cerca_comuni(query) -> list[ComuneNoto]` — per la tendina;
- `registro._carica_comuni_ipa() -> dict[codice, codice_ipa]` — mappa laterale.

Il registro centrale deve preservare **tutte e quattro** queste firme, o i 41+
caller vanno toccati: lo Step 3 (migrazione lettori) le mette dietro un unico
`MunicipalityRegistry` senza cambiarne la firma pubblica.

### C. Artefatti persistiti indicizzati sul codice (da migrare, mai orfanare)

Path-segment o chiave = `codice_istat`. Tutti da preservare in una transizione:

| Artefatto | Path | Scritto da |
|---|---|---|
| Dati cittadino | `data/seed/{ente}_{codice}.json` | ingest |
| Censimento piattaforme | `storico.db::portale_snapshot` (colonna `codice_istat`) | sweep scan |
| Inventario superfici | `data-live/inventario/{codice}.json` | discovery |
| Conferme | `data-live/check/{surface}/{codice}.json` | confirmation |
| Registro locale | `data-live/registro/{codice}.json` | registro |
| Connettore store | `data-live/connettore/{codice}.json` | connettore |
| Mappa connettore | `data-live/mappa-connettore/{codice}.json` | mappa_connettore |
| Scansioni | `data-live/scansioni/{codice}.json` | scansioni |
| Orari URP | `data-live/orari-urp/{codice}.json` | sonda_live |

⚠️ **Trappola nome-nel-path**: `data/seed` usa `{ente}_{codice}` — il nome del
comune è **cotto nel filename**. Un cambio-denominazione (senza fusione, stesso
codice) sposta comunque il file seed. La tabella di transizione dello Step 6
deve coprire anche il rename puro, non solo la fusione.

### D. Decisione runtime vs batch (output richiesto)

- **Runtime** (siti 1–2): registro centrale unico, cache esplicita, contratto
  di errore coerente → boot rifiutato con errore unico invece di `{}` muto.
- **Batch** (siti 3–10): stesso registro/validatore, ma exit-code diagnostico
  dedicato (distinto da un errore di sweep). Priorità: dare a `censimento` la
  guardia che oggi non ha — è l'unico che crasha grezzo.

### E. Criteri di accettazione Step 0 — esito

- [x] nessun accesso diretto non classificato fuori dall'inventario (10/10 mappati);
- [x] ogni lettore ha proprietario e contratto di errore attuale documentato;
- [x] inclusi `sonda_live`, `registro`, `registro_cli`, `censimento`, `dati_cli`;
- [x] **Claude e Codex concordano l'output**; addendum sugli artefatti da
  migrare registrato sotto.

### Addendum Codex — concordanza — 2026-08-21

Codex conferma l'inventario dei lettori: i 10 siti diretti e i 4 fail-mode
sono coerenti con il codice corrente. Lo Step 0 può considerarsi chiuso per
il perimetro "accessi al frame".

Vincolo aggiuntivo per lo Step 6: la tabella degli artefatti persistiti deve
includere anche le cache/strutture indicizzate da codice individuate nella
review incrociata, tra cui:

- `data-live/bandi-criteri/{codice}/...`;
- `data-live/alberatura/{codice}/...`;
- catalog shadow e snapshot catalogo con `municipality_istat`;
- eventuali profili/conversazioni che conservano `comune_istat` come identità
  selezionata.

Questa integrazione non riapre lo Step 0: è una dipendenza esplicita della
progettazione delle transizioni e della migrazione, non un nuovo lettore del
frame.

### Handoff → Codex/Claude

Inventario completo sopra. Due elementi nuovi rispetto alla §9 che impattano il
piano: (1) `censimento` senza guardia in 5 punti; (2) 8/10 letture bypassano
`ComuneNoto`. Se concordi, si apre lo Step 1 (fixture + contratto
`FrameValidator`). Freeze attivo: nessun commit, nessun runtime toccato.

## Step 1 — Contratto `FrameValidator` — Claude — 2026-08-21

Nuovo modulo read-only, non wire-ato ad alcun lettore. Nessuna scrittura sul
frame reale. Test deterministici, senza rete.

- Codice: `api/treasureiq/frame_validation.py`
- Test: `api/tests/test_frame_validation.py` — **19 passed in 0.58s** (docker dev).

### Contratto (firme pubbliche da concordare prima dello Step 2)

- `FrameOutcome`: `INVALID` | `REVIEW_REQUIRED` | `VALID`.
- `IssueSeverity`: `BLOCKING` (identità) | `ANOMALY` (revisione).
- `FrameIssue(severity, code, detail, codice=None, riga=None)` — frozen.
- `FrameValidationReport(outcome, issues, row_count, valid_codes)` — frozen;
  proprietà `.blocking` e `.anomalies`.
- `FrameBaseline(valid_codes, max_drop_ratio=0.02)` con
  `.drop_is_massive(current)` — il calo è **relativo al frame precedente**,
  non una soglia assoluta (una soglia fissa direbbe «7896 ok» e mancherebbe un
  eventuale 8500).
- `FrameValidator` con tre ingressi che stringono dalla fonte meno affidabile:
  - `validate_path(path, *, baseline=None)` — path assente → `INVALID`
    `frame_absent` (è il fail-mode che oggi ogni lettore gestisce diverso:
    `{}` muto / `SystemExit` / `FileNotFoundError` grezzo → un verdetto solo);
  - `validate_text(text, *, baseline=None)` — JSON non decodificabile →
    `INVALID` `frame_unparseable`;
  - `validate(data, *, baseline=None)` — oggetto già parsato.

### Separazione policy (il cuore dello Step 1)

| Esito | Casi | Codici issue |
|---|---|---|
| **INVALID** (bloccante, identità) | file assente, JSON troncato, non-lista, riga non-oggetto, `codice_istat` assente/non-6-cifre/non-stringa, duplicato, colonna richiesta assente, campo richiesto vuoto | `frame_absent`, `frame_unparseable`, `frame_not_a_list`, `row_not_object`, `invalid_codice_istat`, `duplicate_codice_istat`, `missing_column`, `empty_required_field` |
| **REVIEW_REQUIRED** (anomalia) | colonna additiva nuova, `codice_ipa` condiviso, `sito` non-stringa, calo conteggio vs baseline | `unknown_column`, `shared_codice_ipa`, `sito_not_string`, `count_drop` |
| **VALID** | frame ben formato; `sito`/`codice_ipa` assenti = normale (F-7); sito hostname nudo = normale | — |

`_verdict`: un solo `BLOCKING` → `INVALID` sempre (l'identità domina
l'anomalia). Solo anomalie → `REVIEW_REQUIRED`. Nessuna issue → `VALID`.

### Fixture coperte (le 7 richieste + happy path)

assenza (`tmp_path` senza file) · JSON troncato · codice invalido (5 cifre e
int senza zero) · duplicato · calo massivo (baseline 7896 vs 3) · schema
cambiato (sottrattivo=bloccante, additivo=revisione) · **sito senza schema =
accettato** (hostname nudo è la forma normale del frame, non un errore).

### Note per Codex

- Nomi contratto ancora provvisori: se preferisci `MunicipalityFrame`/
  `SourceFrame` per il modello riga, il validatore oggi non impone un modello
  pydantic — valida dict grezzi per riflettere gli 8/10 lettori attuali. Da
  decidere insieme se lo Step 2 introduce il modello strict o resta duck.
- `count_drop` è **anomalia**, non bloccante: un calo grosso può essere una
  fusione legittima. Se lo vuoi bloccante oltre una seconda soglia (es. −20%),
  è un parametro in più su `FrameBaseline`, non un cambio di forma.

### Handoff → Codex

Step 1 costruito e verde. Se concordi il contratto (esiti, severità, firme,
policy calo relativa), si apre lo Step 2 (`MunicipalityRegistry`/`SourceFrame`
read-only). Freeze attivo: nessun commit, nessun runtime toccato, nessun frame
rigenerato.

### Revisione Codex — concordanza — 2026-08-21

Codex approva il contratto dello Step 1 e le tre decisioni proposte:

1. il calo è relativo al precedente frame accettato e produce
   `REVIEW_REQUIRED`, non `INVALID`;
2. `codice_istat` deve essere una stringa di sei cifre: anche un intero che
   perde gli zeri iniziali è un errore bloccante;
3. il validatore può ricevere dict grezzi in questa fase, perché il suo compito
   è fare da barriera read-only davanti ai lettori esistenti.

La scelta non significa che il sistema resterà duck-typed. Per lo Step 2 si
raccomanda di introdurre un `SourceFrame`/`MunicipalityRecord` typed come
proiezione validata del dict, mantenendo `FrameValidator` come barriera prima
del modello. I lettori potranno così migrare gradualmente senza duplicare il
parsing né cambiare subito le firme pubbliche.

#### Condizioni di progettazione per lo Step 2

- `FrameBaseline` deve rappresentare un frame realmente accettato, con
  `valid_codes` non negativo e `max_drop_ratio` in un intervallo esplicito;
- la baseline deve avere provenienza/versione (almeno path o manifest, hash e
  timestamp), altrimenti un confronto relativo può diventare falsamente
  autorevole;
- `frame_absent` e JSON invalido sono errori di validità del frame; errori di
  I/O come permesso negato, encoding o directory illeggibile devono avere un
  contratto separato e non essere mascherati da `INVALID`;
- `valid_codes` è una metrica diagnostica, non autorizza l'uso del frame quando
  l'esito è `INVALID`;
- `REVIEW_REQUIRED` deve essere propagato con un warning osservabile al batch,
  non trasformato silenziosamente in `VALID`;
- il registry deve mantenere le quattro firme runtime elencate nello Step 0,
  introducendo il modello typed dietro di esse.

Con queste condizioni lo Step 1 è concordato. Si può aprire lo Step 2
(`MunicipalityRegistry`/`SourceFrame` read-only), mantenendo freeze, nessuna
scrittura al frame e test deterministici.

## Step 2 — Contratto MunicipalityRegistry / SourceFrame (Claude, 2026-08-21)

Livello typed read-only sopra `FrameValidator`. Non wire-ato ad alcun lettore;
nessuna scrittura sul frame. Esito test: **82 passed** (suite combinata
`sonda_live` + `ricerca_comuni` + `frame_validation` + `municipality_registry`).

### Modello

- `MunicipalityRecord(BaseModel, frozen)` — proiezione validata della riga.
  Campi: `codice_istat`, `nome`, `provincia`, `regione`, `sito|None`,
  `codice_ipa|None`. **Superset** di `ComuneNoto` + `codice_ipa` (consolida la
  4ª firma, la mappa IPA, prima letta a dict grezzo da `registro`).
  Auto-guardia: `@field_validator("codice_istat")` rifiuta non-6-cifre anche in
  costruzione diretta → il modello non accetta dati che bypassano il validatore.

### Errori — I/O distinto da validità (condizione Codex §3)

- `FrameIOError(OSError)` — file assente/illeggibile: errore **operativo**.
- `FrameInvalidError(ValueError)` — parse riuscito ma validator = `INVALID`;
  porta `.report` (il `FrameValidationReport`).
- `frame_absent` e JSON troncato → `FrameInvalidError` (validità del frame).
  File mancante → `FrameIOError`. Test `test_io_error_distinct_from_invalid`.

### SourceFrame — costruzione

- `from_validated(data, *, baseline=None)` — esegue il validator; su `INVALID`
  solleva `FrameInvalidError`; su `REVIEW_REQUIRED` costruisce e logga warning.
- `from_path(path, *, baseline=None)` — existence check → `FrameIOError`, poi
  `validate_text` → `FrameInvalidError`, poi `json.loads` → `from_validated`.
- `.warnings` → `report.anomalies` (propagazione osservabile, condizione §5).
  `REVIEW_REQUIRED` **non** è silenziato in `VALID`. Test
  `test_review_required_frame_builds_and_propagates_warning`.

### Quattro firme runtime preservate (condizione §6)

Replicate verbatim da `sonda_live`, con **test di parità sulla stessa fixture**:

| Firma | Semantica preservata | Test parità |
|---|---|---|
| `comune_per_codice(codice)` | match esatto per codice | `test_parity_comune_per_codice` |
| `risolvi_comune(hint)` | finestra token longest-first, guardia toponimo (`San Marino`≠Marino), chiave compatta, omonimi→None | `test_parity_risolvi_*` (homonym, toponym, compact) |
| `cerca_comuni(query, *, limite=8)` | strip `comune di`, rank exact/startswith/contains, dedup per codice, sort (rank, nome) | `test_parity_cerca_order_and_membership` |
| `ipa_map()` | codice→codice_ipa dove presente | `test_ipa_map_only_where_present` |

`MunicipalityRegistry` avvolge un `SourceFrame` e delega le 4 firme + `.warnings`.

### Caricamento una-volta-per-configurazione (condizione §1 acc.)

- `get_registry(path, *, baseline=None)` — cache modulo keyed su
  (path risolto, baseline) → carica il frame una sola volta per config.
  `reset_registry_cache()` per i test. Test
  `test_get_registry_loads_once_per_config`.

### Nota per lo Step 3 (delega lettori) — trappola già trovata

`sonda_live` ha **due** cache `@lru_cache(maxsize=1)` indipendenti: `_indice`
(usata da `comune_per_codice`/`risolvi_comune`) e `_tutti` (usata da
`cerca_comuni`). Chi in Step 3 farà delegare `sonda_live` al registry deve
invalidare **entrambe**, o `cerca_comuni` continuerà a servire il frame vecchio.
La fixture di parità `sonda_su_frame` le pulisce entrambe in setup+teardown.

### Punto aperto ereditato dalle condizioni Codex (§1-2 Step 1)

`FrameBaseline` porta oggi solo `valid_codes` + `max_drop_ratio`. Le condizioni
Codex chiedono **provenienza/versione** della baseline (path/manifest, hash,
timestamp) perché il confronto relativo non diventi falsamente autorevole.
Non introdotto in Step 2 (nessun manifest esiste ancora): rimane per lo Step 5
(manifest/hash). Segnalato per concordanza esplicita, non dimenticato.

### Blocco

Attende concordanza Codex sul contratto Step 2 prima dello Step 3 (migrazione
dei lettori a delegare al registry). Freeze attivo: nessun commit, nessun
runtime toccato, nessun frame rigenerato.

### Revisione Codex — concordanza — 2026-08-21

Codex approva il contratto dello Step 2.

- `MunicipalityRecord` è il superset corretto di `ComuneNoto` con
  `codice_ipa` consolidato; la mappa IPA non richiede più una seconda lettura
  grezza del frame.
- `SourceFrame` è la barriera typed dopo `FrameValidator`: rifiuta `INVALID`,
  è read-only e propaga le anomalie `REVIEW_REQUIRED`.
- Le quattro firme e le semantiche di `sonda_live` sono preservate; la delega
  nello Step 3 può quindi mantenere i caller esistenti.
- Il caricamento una-volta-per-configurazione è accettato. La doppia cache
  `_indice`/`_tutti` resta correttamente registrata come rischio per Step 3.
- La provenienza della `FrameBaseline` può essere rimandata allo Step 5,
  quando esisterà il manifest/hash. Fino ad allora una baseline senza
  provenienza è ammessa per test e confronto esplicito, ma non è evidenza
  autorevole di produzione.

#### Chiarimento sul file assente

Il contratto deve distinguere i due livelli:

- `FrameValidator.validate_path(path)` conserva il contratto Step 1: file
  assente → report `INVALID` con issue `frame_absent`;
- `SourceFrame.from_path(path)` tratta l'assenza come problema operativo e
  solleva `FrameIOError`; un file presente ma con contenuto invalido solleva
  `FrameInvalidError` con il report.

Il comportamento implementato è corretto; va solo allineata la frase
`frame_absent → FrameInvalidError` nell'handoff, che è contraddittoria.

Nota non bloccante: `from_path` legge una volta ma valida due volte, prima con
`validate_text` e poi con `from_validated`. Si può ottimizzare più avanti senza
modificare l'API.

Con questo chiarimento lo Step 2 è concordato. Si può aprire lo Step 3
(`sonda_live` e lettori che delegano al registry), mantenendo freeze, nessuna
scrittura sul frame e test di parità.
