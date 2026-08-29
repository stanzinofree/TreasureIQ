# Measurement sweep — Ramo 3 Fase 1

Strumento di **misura** della risoluzione servizi sui comuni italiani. Non è un
worker: è **sequenziale**, **read-only** (zero-write su catalogo / service-cache /
`storico.db` / mappa-cache), **checkpointato** e **resumable**. Scrive solo nella
directory `--out`.

## 1. Componenti

### Seam diagnostico — `catalog/service_connectors/connettore_base.py`

Due primitive read-only sul connettore base, usate solo dalla misura:

- **`DiagnosticaConnettore`** (`NamedTuple`): conteggi di una risoluzione senza
  coniare identità né scrivere nulla — `chiave_valida`, `target_presente`,
  `grezzi`, `filtrati`, `confermati`. Serve perché `retrieve` collassa 0 e ≥2
  confermati nello stesso `NOT_FOUND`: per distinguere **miss** (0) da **ambiguo**
  (≥2) serve il conteggio esplicito.
- **`entry_raggiungibile()`**: verifica read-only che la piattaforma esponga un
  entry-point per una `ServiceKey`, senza fetch di dati.

### Harness — `catalog/measurement_sweep.py`

CLI:

| Flag | Default | Ruolo |
|---|---|---|
| `--db` | `data/storico.db` | sorgente campione (aperta in sola lettura) |
| `--out` | `data/measure` | **unica** destinazione di scrittura |
| `--per-famiglia` | 5 | N comuni per famiglia Base (campione stratificato) |
| `--seed` | 42 | determinismo del campione |
| `--limite-comuni` | — | tetto opzionale sul totale |
| `--solo-report` | — | ricostruisce il report dal checkpoint, senza rete |
| `--tentativi` | 2 | retry su `endpoint_muto` |
| `--backoff-s` | 2.0 | backoff tra i tentativi |

Rate-limit per-dominio via `PoliticaFetch` (1 s/dominio, cap 50/dominio,
backoff 60→3600 s). Resume: salta le coppie `(comune, probe)` già in
`checkpoint.jsonl`.

### Test — `tests/test_measurement_sweep.py`

Deterministici, offline: inspector iniettato, nessuna rete. 16 casi.

## 2. Pin a tre livelli (obbligatorio in ogni report)

La base **eseguibile** di una misura non coincide con un singolo commit finché il
seam e l'harness non sono tracciati. Ogni report deve dichiarare i tre livelli:

| Livello | Cosa |
|---|---|
| **parent** | commit di `origin/main` da cui parte il lavoro |
| **codice misurato committato** | commit del branch di lavoro + delta committato vs parent |
| **delta scratch non committato** | seam + harness + test non ancora in git, con `git hash-object` di ciascuno e patch ricostruttiva |

Con questa PR il seam, l'harness e il test entrano in git: dalle misure
**successive** il terzo livello sparisce e la base torna un commit solo.

## 3. Formato report

`report.json` (in `--out`) contiene, oltre ai conteggi globali:

- **7 bucket di esito**: `fulfilled`, `ambiguita`, `fonte_assente` (con causa),
  `chiave_non_riconosciuta`, `comune_non_risolto` (con causa), `endpoint_muto`,
  `connettore_non_disponibile`.
- **`per_famiglia`**: esiti per famiglia-piattaforma Base. Le famiglie **con**
  connettore-servizi vanno lette separate da quelle con solo
  `connettore_non_disponibile` (di cui si registra comunque il **costo-sonda**).
- **`per_superficie_at`**: esiti per presenza/assenza di superficie
  Amministrazione-Trasparente.
- **Guardie di onestà**: `recognizer_falsi_positivi` / `recognizer_miss`
  (validano che le `chiave_non_riconosciuta` siano baseline attesa, non errori),
  `transient_recuperati` (muto transitorio vs assenza reale), `nota_sp` (la
  superficie SP non è censita per-comune: dichiarato, non inventato).

Il checkpoint completo (una riga per coppia) **non** va versionato: è un artefatto
di run, non una fonte. Si versiona il report sintetico (§4).

## 4. Risultati del run nazionale (2026-08-29)

Campione `--per-famiglia 60 --seed 42`: **1.229 comuni × 14 probe = 17.206
coppie**, ~13h15m. Recognizer pulito (0 falsi positivi, 0 miss).

### Funnel

| Passo | Coppie |
|---|---:|
| totali | 17.206 |
| − chiave non riconosciuta (baseline attesa) | −4.916 |
| = riconoscibili | 12.290 |
| − connettore non disponibile | −9.025 |
| = su famiglie con connettore | 3.265 |
| − comune non risolto (1.422 portale non sondabile + 218 budget) | −1.640 |
| = **raggiungono il connettore** | **1.625** |

Dei 1.625: **fulfilled 709 (43,6 %)**, fonte_assente 709 (assenza reale),
ambiguità 153, endpoint_muto 54 (1 transient recuperato).

### Famiglie con connettore

| Famiglia | fulfilled / raggiunti | Nota |
|---|---:|---|
| openpa | 310 / 529 = 58,6 % | 51 endpoint_muto = flakiness infra |
| wp_design_comuni | 140 / 370 = 37,8 % | 229 portale non sondabile |
| comweb | 213 / 576 = 37,0 % | fonte_assente domina (life-events) |
| wordpress_generico | 46 / 96 = 47,9 % | **misto**: 308/600 → nessun connettore |

- **comunibootstrapitalia** (50 comuni): fulfilled = 0 → connettore inerte,
  conferma dialetto OpenWeb (`/wp-json` 404), da trattare come order-3 OpenWeb.
- ~20 famiglie senza connettore: solo costo-sonda registrato.
- **Tutta la risoluzione vive sulla superficie AT** (703/709 fulfilled);
  `no_at` è superficie morta.

> Questa misura diventa **baseline nazionale ufficiale** solo dopo il merge di
> questa PR (seam + harness tracciati).
