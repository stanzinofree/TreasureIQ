# Ramo 3 — Split semantico di `TRIBUTI` (design, pre-codice)

Stato: **IMPLEMENTATO** (Opzione A). Evidenza da probe live multi-comune
(campione WP-ricco, 24 ago 2026) + fixture ComWeb Agliè già in repo.

## Decisione (24 ago 2026)

- **D1 = Opzione A**: `TRIBUTI` rimosso; aggiunti `TRIBUTI_IMU` + `TRIBUTI_TARI`.
  Marker: `imu` (word) → IMU; `tari` (word) + `tassa rifiuti` (substr) → TARI.
  Substring `"tributi"` **eliminato** (chiudeva il falso positivo `contributi`).
- **D2 = solo IMU+TARI ora** (estensibile: CANONE_UNICO/COSAP quando l'evidenza
  mostrerà titoli puliti).
- **D3 = handler generico implementato** (commit separato, chat-flow): una
  richiesta «tributi/tasse» generica → `None` dal recogniser; il dispatcher
  `_risposta_modulistica` (`chat/respond.py`) rileva l'intento tributario
  generico (`_intento_tributario_generico`, regex whole-word che esclude
  `contributi`) e chiede «IMU o TARI?» (`data_gap="tributo_non_specificato"`,
  nessun fetch, nessuna key ombrello). La lista vocabolario di fallback ora
  elenca «…stato civile, IMU o TARI».

Effetto misurato sul campione: da **0 risoluzioni utili** a ~7 singole oneste
(WP IMU 4/6, TARI 3/6) + ComWeb Agliè che ora risolve **2 card pulite** (IMU e
TARI) invece del NOT_FOUND ambiguo. Fixture Agliè congelate come golden FULFILLED
per-tassa (`test_aglie_tributi_imu_single_card_fulfilled` /
`…_tari_single_card_fulfilled`).

## 1. Problema

`TRIBUTI` è una key-ombrello unica su una realtà intrinsecamente plurale (IMU,
TARI, canone unico, COSAP, affissioni, riscossione coattiva…). Con la regola
onesta «0 o ≥2 confermati → NOT_FOUND» e un solo termine di ricerca canonico
(`SERVICE_SEARCH_TERM[TRIBUTI] = "tributi"`), la key **non risolve quasi mai** un
singolo servizio utile.

Due difetti distinti, entrambi misurati:

### 1a. Il termine generico non risolve (0/6 utili)

Il `?search=` WP è **full-text sul contenuto**, non sul titolo: rumoroso. La
conferma per-titolo del riconoscitore condiviso filtra, ma il risultato netto su
`search=tributi` è inservibile:

| comune | confermati su `search=tributi` | esito attuale |
|---|---|---|
| 001028 Borgaro | 1 — «Servizio riscossione coattiva tributi ed entrate patrimoniali» | FULFILLED, ma su un servizio di **riscossione coattiva**, non ciò che il cittadino chiede |
| 003008 Arona | 5 (incl. falso positivo, §1b) | NOT_FOUND (≥2) |
| 003084 Lesa | 0 | NOT_FOUND (vuoto) |
| 003095 Meina | 0 | NOT_FOUND (vuoto) |
| 004009 Bagnolo | 0 | NOT_FOUND (vuoto) |
| 006009 Arquata | 0 | NOT_FOUND (vuoto) |

**0 risoluzioni utili su 6.** La key generica è, di fatto, morta.

### 1b. `"tributi"` come substring cattura `"contributi"` (falso positivo)

Marker substring `"tributi"` ⊂ `"con­tributi"` / `"contributiva"`. Titoli reali
di **contributi/erogazioni** (servizio diverso: sussidi) confermano TRIBUTI:

- `Richiesta contributi per attività associazioni` → **TRIBUTI** (errato)
- `contributiva` → **TRIBUTI** (errato)
- `contributo` singolare → None (non contiene `tributi`)

Stessa classe del bug `matrimonio` (marker troppo largo). Va corretto a
prescindere dallo split.

## 2. Evidenza: termini specifici risolvono

Contando i confermati con termine di ricerca **specifico** (`imu` / `tari`) e
conferma per-titolo:

| comune | `search=imu` → confermati | `search=tari` → confermati |
|---|---|---|
| 001028 Borgaro | 1 — «IMU» | 1 — «TARI» (l'IMU non matcha i marker TARI) |
| 003008 Arona | 1 — «…IMU» | 1 — «…TARI» |
| 003084 Lesa | 0 (solo «…agevolazione tributaria», non conferma) | 0 |
| 003095 Meina | 0 | 0 |
| 004009 Bagnolo | 1 — «Calcolo online IMU e ravvedimento IUC» | 0 |
| 006009 Arquata | 1 — «IMU» | 1 — «TARI» |

- **IMU: 4/6 FULFILLED** singolo (Borgaro, Arona, Bagnolo, Arquata); 2 vuoto onesto.
- **TARI: 3/6 FULFILLED** singolo (Borgaro, Arona, Arquata); resto vuoto onesto.
- ComWeb Agliè (fixture in repo): categoria tributi = 2 card «TARI» + «IMU». Oggi
  → NOT_FOUND (≥2). Con sub-key: TRIBUTI_IMU→IMU, TRIBUTI_TARI→TARI, **2
  risoluzioni pulite**.

Da 0 utili a ~7 risoluzioni singole oneste sul solo campione.

## 3. Opzioni

### Opzione A — Split in `TRIBUTI_IMU` + `TRIBUTI_TARI`, drop del generico (consigliata)

- Vocabolario: rimuovi `TRIBUTI`; aggiungi `TRIBUTI_IMU`, `TRIBUTI_TARI`.
- Marker: `imu` (word) → TRIBUTI_IMU; `tari` (word) + `tassa rifiuti` (substr) →
  TRIBUTI_TARI. **Elimina il substring `"tributi"`** (fonte del falso positivo
  `contributi`, e comunque non discriminante).
- `SERVICE_SEARCH_TERM`: `TRIBUTI_IMU="imu"`, `TRIBUTI_TARI="tari"`.
- `COMWEB_SERVICE_CATEGORY`: entrambe → `"tributi-finanze-e-contravvenzioni"`.
- Regola onesta immutata: 0/≥2 confermati → NOT_FOUND.
- **Pro:** massima risolvibilità; niente falso positivo; ogni key mappa un
  servizio reale che i comuni titolano in modo pulito.
- **Contro:** una richiesta *generica* «tributi/tasse» non mappa più a nessuna
  key → il chat handler deve chiedere «IMU o TARI?» (disambiguazione a monte,
  non nel connettore). Cambio di comportamento del handler.

### Opzione B — Tieni `TRIBUTI` generico **e** aggiungi `TRIBUTI_IMU`/`TRIBUTI_TARI`

- 3 key coesistono. Generico come fallback per «tasse» ombrello; specifiche per
  intento preciso.
- **Pro:** nessuna regressione per query generiche; additivo.
- **Contro:** il generico resta quasi-inutile (0/6) e ambiguo (quale key
  assegna il recognizer se il testo dice solo «IMU»? → TRIBUTI_IMU **e** overlap
  con generico se il generico mantiene `imu`/`tari`). Va definito che il generico
  perde `imu`/`tari` e tiene solo `tassa rifiuti`? Diventa incoerente. Più
  vocabolario, più superfici di test, beneficio marginale.

### Opzione C — Non splittare; correggi solo il falso positivo

- Rimuovi il substring `"tributi"`; TRIBUTI resta con `tassa rifiuti`+`imu`+`tari`.
- **Pro:** minimo, nessun cambio di contratto.
- **Contro:** non risolve il problema centrale (0/6 utili; ≥2 quando il comune
  ha IMU+TARI, cioè quasi sempre). La key resta morta. Fixa solo il rumore.

## 4. Raccomandazione

**Opzione A.** L'evidenza reale mostra che IMU/TARI sono le uniche entità
tributarie che i comuni titolano in modo discriminante e che il cittadino nomina
esplicitamente; sono già i due `_WORD_MARKERS` di TRIBUTI. Il generico è morto e
tossico (`contributi`). Estendibile in seguito (CANONE_UNICO, COSAP) quando
l'evidenza mostrerà titoli puliti — oggi non li mostra.

La disambiguazione «tributi generico → chiedi IMU/TARI» è un comportamento del
**handler chat**, coerente con la regola «ambiguo → non indovinare»: si allinea
al pattern già usato per key multiple.

## 5. Blast radius (se Opzione A approvata)

Contract change — da toccare in modo coordinato (4 punti flotta + test):

1. `catalog/service_contracts.py` — enum `ServiceKey` (rimuovi TRIBUTI, aggiungi
   TRIBUTI_IMU/TRIBUTI_TARI) + `SERVICE_SEARCH_TERM`.
2. `chat/service_key.py` — `_SUBSTRING_MARKERS`/`_WORD_MARKERS` (rimuovi substring
   `tributi`; imu→TRIBUTI_IMU, tari+tassa rifiuti→TRIBUTI_TARI).
3. `catalog/service_connectors/comweb_service.py` — `COMWEB_SERVICE_CATEGORY`
   (due key → stessa categoria).
4. Cache: le chiavi cache sono per `service_key.value` → le vecchie entry
   `…:tributi` diventano orfane (innocue, scadono; nessuna migrazione dati).
5. Test: ogni riferimento a `ServiceKey.TRIBUTI` (recogniser golden, ComWeb Agliè
   tributi 2-card, resolver, planner, chat). La regola ≥2→NOT_FOUND va
   ri-verificata dove un comune abbia ≥2 card **della stessa** sotto-tassa.
6. Handler chat: rotta «tributi» generico → prompt di disambiguazione (nuovo).

Fixture reali da congelare: IMU singolo (Borgaro/Arquata), TARI singolo
(Arona/Arquata), vuoto onesto (Lesa), e il caso ComWeb Agliè ri-mappato.

## 6. Decisioni aperte (per l'utente, prima del codice)

- **D1.** Split sì/no e quale opzione (A / B / C).
- **D2.** Se A: solo IMU+TARI ora, o includere subito CANONE_UNICO/COSAP?
  (evidenza attuale: solo IMU/TARI titolati puliti → propongo IMU+TARI).
- **D3.** Comportamento del generico «tributi» dopo lo split: prompt di
  disambiguazione nel handler (proposto) vs NOT_FOUND silenzioso.
