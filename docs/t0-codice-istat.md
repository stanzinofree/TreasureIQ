# T0 — Il codice ISTAT come fondamenta

> Documento di analisi architetturale, da validare con Codex.
> Data: 2026-08-21 · Stato repository: freeze attivo, nessun commit senza accordo.
> Scopo: fissare lo stato reale del dataset dei codici comunali **prima** di
> innestarci sopra il codice modulare (registry di riconoscimento, selezione
> connettore). È la base di tutto: se questa chiave si muove, si muove tutto.

---

## 0. Perché partiamo da qui

`codice_istat` è la **chiave di join di tutto il sistema**. Ogni artefatto
persistito è indicizzato su di essa:

- `data/seed/{codice}.json` — i dati cittadino;
- `storico.db::portale_snapshot` — il censimento piattaforme;
- `data-live/inventario/{codice}.json` — l'inventario superfici;
- `data-live/check/{surface}/{codice}.json` — le conferme.

Un codice che cambia valore non è un errore visibile: **orfana in silenzio**
tutto ciò che era indicizzato sul vecchio valore. Il comune diventa «mai
scansionato» pur avendo lo storico su disco. Prima di costruire moduli sopra
questa chiave, la chiave va resa verificabile.

---

## 1. Stato attuale (fatti verificati sul codice)

### 1.1 Il file

| Proprietà | Valore |
|---|---|
| Path | `data/comuni-istat.json` |
| Dimensione | ~1,37 MB |
| Righe | 7.896 |
| Codici distinti | 7.896 (nessun duplicato **oggi**) |
| Codici non a 6 cifre | 0 **oggi** |
| Righe senza `sito` | 29 |
| Versionato in git | sì (ultimo tocco `cad70d6`, 2026-08-06) |

### 1.2 La forma

Modello `ComuneNoto` (`sonda_live.py:67`): `codice_istat`, `nome`,
`provincia`, `regione`, `sito` (opzionale). Il JSON grezzo contiene anche
`codice_ipa`, **non** mappato in `ComuneNoto` — lo legge a parte `registro.py`.

### 1.3 La provenienza

Generato da `make frame-nazionale` → `python -m treasureiq.ingest.comuni_istat`.
È il **join di due sorgenti a monte**, non una sola:

- `URL_ISTAT` = `https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.csv` → `codice_istat`, `nome`, `provincia`, `regione`;
- `URL_IPA` = dataset IndicePA → `sito`, `codice_ipa`.

**Conseguenza importante**: il nostro file cambia se cambia **una qualsiasi**
delle due sorgenti. Un check di freschezza che guarda solo ISTAT è cieco a un
cambio di `sito`/`codice_ipa` su IPA — e `sito` è proprio il `base_url` da cui
parte tutta la discovery.

### 1.4 I lettori — tre, indipendenti, con tre fail-mode diversi

Questo è il punto debole strutturale. **Non c'è un unico punto di accesso** al
dataset: tre moduli lo leggono per conto proprio, ognuno degrada in modo
diverso quando il file manca o è rotto.

| # | Chi | Cache | File assente/rotto → |
|---|---|---|---|
| 1 | `sonda_live._indice()` | `@lru_cache(maxsize=1)` | warning + `{}` → **sonda muta, degrada in silenzio** |
| 2 | `registro._carica_comuni_ipa()` | cache propria | warning + `{}` → `codice_ipa` diventa `None` in silenzio |
| 3 | `registro_cli` (righe 79, 264) | nessuna | **`SystemExit`** → fail duro |

Stesso file, tre costanti (`COMUNI_ISTAT_PATH` in `sonda_live`,
`_COMUNI_ISTAT_PATH` in `registro`), tre contratti di errore incoerenti.

### 1.5 Integrità: assente

`hashlib` è importato in `registro.py` ma serve **solo per il logo** (data-URI
sha256). Sul dataset ISTAT non c'è alcun checksum, né al load né al deploy.
La validazione è solo `ComuneNoto.model_validate` per riga (forma del singolo
record) — **non** verifica: unicità dei codici, lunghezza 6 cifre, assenza di
regressioni sul set, corrispondenza con il file committato.

---

## 2. Punti di forza (da preservare)

- **File versionato** → git è già un controllo di manomissione e uno storico.
- **Generatore deterministico e idempotente** (`ingest.comuni_istat`) → la
  rigenerazione è riproducibile, la sorgente è tracciata nel codice.
- **Chiave giusta scelta** → `codice_istat` è non ambiguo, senza omonimi
  (`comune_per_codice` è «la via che non può sbagliare»). Il problema non è la
  chiave, è la sua verificabilità.
- **Il dato «senza sito» è onesto** (29 righe) → non inventa URL.

---

## 3. Punti deboli (ordinati per rischio)

1. **[ALTO] Orfanamento silenzioso su cambio codice.** Nessuno se ne accorge:
   nessun controllo confronta il set-codici corrente col precedente.
2. **[ALTO] Tre lettori, tre fail-mode.** `sonda_live` degrada muto,
   `registro_cli` muore, `registro` perde `codice_ipa`. Un file rotto dà tre
   sintomi scollegati e nessun errore unico.
3. **[MEDIO] Nessuna integrità al load/deploy.** Corruzione disco, mount
   sbagliato, edit accidentale passano inosservati fino al primo sintomo.
4. **[MEDIO] Freschezza non monitorata.** Se ISTAT o IPA cambiano, non lo
   sappiamo finché qualcuno non rilancia `make frame-nazionale` a mano.
5. **[BASSO] `codice_ipa` fuori modello.** Un campo del dataset che vive fuori
   dal contratto tipizzato: chi lo legge (`registro`) rifà il parsing grezzo.

---

## 4. Piano di interventi — passo passo

Tre controlli, **tre frequenze diverse**. Nessuno è per-sweep: il dataset è
quasi-statico, rivalidarlo a ogni sweep è spreco.

### Step 1 — Guardia al load (ogni avvio, costo ~0)

**Cosa**: un unico punto di caricamento validato che rimpiazza i tre accessi
grezzi. Verifica invarianti forti *prima* di servire il dataset:

- ogni `codice_istat` è 6 cifre numeriche;
- i codici sono unici (nessun duplicato);
- il conteggio è ≥ una soglia di sanità (es. ≥ 7.000) — un file troncato non
  deve passare per «valido»;
- ogni riga valida `ComuneNoto`.

**Dove**: un modulo `registro_comuni` (nome da concordare) che espone
`carica_comuni() -> Registro`, consumato dai tre lettori attuali. Non tre
cache: una.

**Contratto di errore**: fallimento invariante → **si rifiuta il boot con un
errore unico e parlante**, non si degrada in `{}`. Oggi `sonda_live` che
ritorna `{}` è il fail-mode peggiore: il sistema parte «funzionante» ma muto.

**Blast radius**: `sonda_live` (41 caller su `comune_per_codice`), `registro`,
`registro_cli`. Alto — va fatto per primo e con test, ma non cambia dati.

**Test**: file valido → carica; codice a 5 cifre → errore; duplicato → errore;
file troncato (100 righe) → errore; file assente → errore unico, non tre.

### Step 2 — Sigillo al deploy (ogni build)

**Cosa**: hash sha256 del file, pinnato in repo (`data/comuni-istat.sha256` o
in un manifest), verificato al build/deploy dell'immagine.

**Perché**: git copre la manomissione nel repo; l'hash estende il controllo al
**disco del container** (corruzione, mount `:ro` sbagliato, layer stale).
Discende dallo stesso principio di `container-non-monta-sorgente-api`: l'immagine
può servire un file diverso da quello committato.

**Dove**: passo del Makefile / build. Mismatch → build rossa, non deploy silente.

**Blast radius**: nullo a runtime (solo build).

### Step 3 — Check giornaliero di freschezza upstream → diff

**Cosa**: un job giornaliero che **non rigenera** il file, ma verifica se le
sorgenti a monte si sono mosse rispetto al nostro file versionato.

**Come (economico)**:
1. richiesta condizionale (HEAD / `If-None-Match` / `If-Modified-Since`) a
   `URL_ISTAT` **e** `URL_IPA` — entrambe, per il punto 1.3;
2. se nessuna è cambiata → no-op, un log e basta;
3. se una è cambiata → download completo, rigenerazione in un file temporaneo,
   **diff normalizzato** contro `data/comuni-istat.json`;
4. il diff produce un **artefatto da rivedere a mano**, non un overwrite:
   - codici aggiunti;
   - codici rimossi (⚠️ possibile **fusione** → il vecchio codice va
     *migrato*, non cancellato: qui vivono i dati orfani dello Step 0);
   - campi cambiati a parità di codice (nome, `sito`, provincia).

**Perché evento, non automatico**: il cambio del set-codici è un **evento di
migrazione**, gattato da umano — esattamente come `REDISCOVER` non è `KEEP`.
Un overwrite automatico cancellerebbe la mappa dei codici orfani da migrare.

**Contratto**: il job **non scrive mai** `data/comuni-istat.json`. Propone. La
promozione del diff a nuovo file versionato è un'azione umana con migrazione
dei codici rimossi.

**Blast radius**: nullo sul runtime (job separato, output = report).

---

## 5. Il caso «fusione» (perché il diff non è un overwrite)

Esempio reale del dominio: due comuni si fondono → ISTAT **sopprime** i due
vecchi codici e ne **crea uno nuovo**. Se il job facesse overwrite:

- i due `data/seed/{vecchio}.json`, il loro `storico.db`, i loro `inventario/`
  diventano orfani e invisibili;
- il nuovo codice parte a vuoto, come «mai scansionato».

Con il diff-come-evento invece: il report segnala «058XXX e 058YYY rimossi →
probabile fusione in 058ZZZ», e la migrazione (re-key dei dati persistiti, o
loro archiviazione consapevole) è una decisione presa, non un effetto
collaterale silenzioso.

---

## 6. Domande aperte per Codex

1. **Punto di accesso unico**: un modulo `registro_comuni` che i tre lettori
   consumano, o basta consolidare in `sonda_live` (che ha già l'indice e la
   cache) ed esporlo agli altri due? Rischio import-circolari da valutare.
2. **Contratto di errore al load**: rifiutare il boot è giusto per l'API, ma
   `registro_cli` è una CLI di sweep — vogliamo lo stesso hard-fail lì, o un
   exit code dedicato distinto da un errore di sweep?
3. **Dove vive l'hash del deploy**: file `.sha256` accanto al dataset, o un
   manifest unico che pinnerà anche altri dataset (storico.db, ipa-recapiti)?
4. **Il job giornaliero**: dove gira? Non è lo sweep worker (orologio diverso).
   Cron separato? E dove atterra il report del diff?
5. **`codice_ipa` nel modello**: lo tiriamo dentro `ComuneNoto` ora che
   tocchiamo il caricamento, o resta lettura grezza a parte in `registro`?

---

## 7. Cosa NON fare (freeze)

- Non modificare `data/comuni-istat.json` (nessun overwrite dal job).
- Non introdurre un secondo generatore o una seconda sorgente.
- Non far scrivere il file al check di freschezza: propone, non applica.
- Nessun commit/deploy senza verifica esplicita di stato e test.

---

## 8. Ordine proposto

1. Step 1 (load guard + punto d'accesso unico) — prerequisito di tutto, blast
   radius alto, va per primo con test completi.
2. Step 2 (sigillo deploy) — indipendente, economico, subito dopo.
3. Step 3 (freschezza → diff) — l'ultimo, perché è un job nuovo e separato, e
   perché la migrazione-fusione merita una decisione a sé.

Solo dopo questi tre torniamo al **punto 1 della chat precedente**:
riconoscimento che seleziona il connettore. Su fondamenta verificate.

---

## 9. Review Codex — conclusioni condivise prima dell'implementazione

Questa sezione integra la prima analisi del documento con il codice effettivo
presente nel repository. Non è ancora una modifica al runtime: serve a far
valutare a Codex e Claude lo stesso perimetro prima di iniziare lo Step 1.

### 9.1 Cosa è confermato

- Il frame corrente contiene 7.896 righe, codici ISTAT di sei cifre e nessun
  duplicato di `codice_istat`.
- Il codice è l'identità tecnica corretta; il nome non è una chiave perché ci
  sono omonimi reali: Samone, Livo, Peglio, Castro e San Teodoro.
- I 29 comuni senza sito e gli 8 senza `codice_ipa` sono stati di dato validi:
  non devono essere trasformati in URL o codici inventati.
- Sono presenti tre `codice_ipa` condivisi da più comuni. Il codice IPA non può
  essere assunto come chiave unica del comune; va rappresentata una relazione
  uno-a-molti o almeno una segnalazione di conflitto.

### 9.2 Correzioni al perimetro originale

Il piano iniziale parlava di tre lettori, ma gli accessi effettivi sono più
ampi:

- `sonda_live` costruisce l'indice per nome e risolve per codice;
- `registro` rilegge il JSON per costruire la mappa `codice_istat → codice_ipa`;
- `registro_cli` lo legge direttamente nei comandi batch;
- `ingest.censimento` lo legge direttamente in più percorsi;
- `dati_cli` lo legge per il report di stato.

Lo Step 1 deve quindi censire tutti gli accessi e distinguere due contratti:

1. lettura runtime, che deve avere un registro centrale e un comportamento
   coerente;
2. lettura batch, che può produrre un errore diagnostico/exit code dedicato ma
   non deve duplicare parsing e validazione.

### 9.3 Corner case che il fix deve coprire

1. JSON assente, vuoto, troncato o non decodificabile.
2. Codice non stringa, con spazi, con meno/più di sei cifre, alfanumerico o
   privo dello zero iniziale.
3. Codice ISTAT duplicato.
4. Campo obbligatorio mancante o riga con campi inattesi.
5. Duplicati o conflitti di `codice_ipa`, senza far fallire l'identità ISTAT.
6. Sito assente, host senza schema, URL invalido o sito condiviso da più enti.
7. Frame valido ma drasticamente più piccolo del precedente.
8. Codici rimossi per fusione, soppressione o cambio amministrativo.
9. Aggiornamento del file mentre un processo lo sta leggendo.
10. Cache di processo che conserva il frame precedente dopo una promozione.
11. Mount runtime diverso dal file verificato durante la build.
12. Nuove colonne upstream o schema cambiato in ISTAT/IPA.

### 9.4 Decisione architetturale proposta

Non introdurre soltanto una funzione `load_json`. Separare i concetti:

- `MunicipalityRegistry`: identità corrente, lookup per codice, lookup per
  nome, alias/transizioni storiche;
- `SourceFrame`: snapshot ISTAT + IPA validato, con manifest di provenienza,
  data, hash, versione del generatore e statistiche del join;
- `FrameValidator`: invarianti del frame, confronto con il precedente e stato
  `valid`/`review_required`/`invalid`;
- lettori runtime e batch che consumano questi contratti senza riaprire il JSON
  direttamente.

La chiave corrente non deve essere rinominata durante una fusione. I dati
storici devono restare leggibili con il codice originario; l'eventuale legame
con il nuovo comune deve passare da una tabella di transizione con validità
temporale e cardinalità non necessariamente uno-a-uno.

### 9.5 Ordine operativo condiviso

Per isolare il building senza perdere l'overview globale:

1. inventario definitivo degli accessi al frame;
2. contratto e fixture del validatore, senza collegarlo al runtime;
3. registro centrale read-only con cache/invalidation esplicita;
4. migrazione dei lettori runtime e dei batch;
5. scrittura atomica del generatore;
6. manifest/hash runtime e controllo al deploy;
7. diff upstream e workflow umano per fusioni/transizioni.

Non si passa allo step successivo finché quello corrente non ha test, esito e
decisioni documentate nel workstream condiviso indicato sotto.

### 9.6 Terreno comune di lavoro

Il protocollo operativo e i passaggi tra Codex e Claude vivono in:

`docs/workstreams/t0-codice-istat/`

Il contenuto della cartella è parte del piano, non una nota privata. Il file
`README.md` descrive il protocollo; `planning.md` il piano attivo;
`execution.md` il lavoro in corso; `done.md` gli handoff chiusi.
