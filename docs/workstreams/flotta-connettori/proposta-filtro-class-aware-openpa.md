# Filtro class-aware per il connettore OpenPA

**Stato:** IMPLEMENTATO — branch `feat/openpa-filtro-class-aware`, PR dedicata.
**Origine:** campione read-only 28 comuni OpenPA (2026-08-26), Fase B.
**Vincolo:** nessuno sweep live aggiuntivo, nessun deploy, nessun aggiornamento del
catalogo finché PR + suite + review non sono verdi.

## Problema

La query eZ Find del connettore (`costruisci_query_ezfind`, `q = '<term>' and limit 20`)
**non filtra per `classIdentifier`** — e non deve, per non perdere recall (TARI vive in
`document`, non `public_service`). Su un campione di 28 comuni × 6 ServiceKey (168 query
production-faithful, limit=20):

- **solo 21/168 confermati (12,5%)**; esito dominante **ambiguo 124/168 (73,8%)**;
- dei 772 candidati che il recogniser mappa a una key, **`document` (244) e `article` (110)
  superano `public_service` (121)**: documenti e notizie contengono le keyword del servizio e
  affollano il set, facendo scattare il rifiuto per ambiguità (invariante I-1, esattamente-1);
- anche quando il gate scatta, **solo 10/21 confermati puntano a un servizio reale**; 3 puntano
  a **notizie** (destinazione sbagliata: San Prisco/TARI, Sorso+Pantelleria/carta).

## Policy effettiva (implementata)

Allow-list per `classIdentifier` applicata ai candidati **PRIMA** del gate host/recogniser e
del gate esattamente-1. **Per-key ma uniforme** sulle 6 chiavi:

| ServiceKey | classi ammesse |
|---|---|
| CARTA_IDENTITA, CAMBIO_RESIDENZA, ACCESSO_ATTI, STATO_CIVILE | `public_service`, `document`, `output` |
| TRIBUTI_IMU, TRIBUTI_TARI | `public_service`, `document`, `output` |

Escluse (prima del gate 0/≥2): `article` (notizie), `channel`, `organization`, e **tutte** le
classi non elencate (media, `topic`, `place`, …). Un candidato senza `classIdentifier`
(`native_class` = `None`) non è in allow-list → scartato: un hit non classificabile non è un
servizio confermato.

**Perché uniforme e non `public_service` secco per l'anagrafe.** `document`/`output` sono
ammessi su tutte e sei perché su OpenPA non solo i tributi ma anche parte di anagrafe/atti
vivono lì (regolamenti, moduli, nodi *«cosa puoi richiedere»* — es. ACCESSO_ATTI: San Prisco in
`document`, Paceco in `online_contact_point`). Un filtro `public_service`-only ucciderebbe
quei confermati veri. La mappa resta **per-key** (non un set globale) così una chiave può
divergere in futuro senza allargare le altre.

**IMU/TARI restano strutturalmente più deboli.** Il rumore nei tributi vive proprio in
`document`/`output` (regolamenti, moduli, avvisi) e **non è separabile per classe**: l'allow-list
lo *contiene*, non lo *risolve*. Sul campione TARI/IMU si muovono poco (vedi sotto). Resta un
problema a parte (matching sul titolo o accettazione della debolezza), non chiuso da questo filtro.

## Controfattuale misurato — ⚠️ variante per-key, non uniforme

Il controfattuale sotto è stato misurato in Fase B sotto una **variante più restrittiva**
(anagrafe/atti → `public_service` **secco**; tributi → `public_service|document|output`). La
policy implementata è **uniforme** e quindi **più permissiva sull'anagrafe** (aggiunge
`document|output` a carta/residenza/atti/stato civile): la resa reale sarà **≥** questi numeri,
non <. Non è stato rimisurato in live (nessuno sweep nazionale consentito in questa fase).

| ServiceKey | conf. oggi | conf. filtro (variante per-key) | Δ |
|---|---|---|---|
| CAMBIO_RESIDENZA | 1 | 19 | +18 |
| ACCESSO_ATTI | 4 | 12 | +8 |
| CARTA_IDENTITA | 4 | 11 | +7 |
| STATO_CIVILE | 6 | 12 | +6 |
| TRIBUTI_TARI | 3 | 6 | +3 |
| TRIBUTI_IMU | 3 | 4 | +1 |
| **TOTALE** | **21 (12,5%)** | **64 (38%)** | **+43** |

Effetti: la resa **triplica**; i confermati-notizia **spariscono** (article fuori allow-list).
I `vuoto` che crescono sono NOT_FOUND onesti (nessun servizio in classe ammessa). Il filtro può
solo **restringere** i candidati → non introduce falsi confermati; al più aumenta i `vuoto`.

## Implementazione

Il filtro è **interno al connettore OpenPA**: nessun impatto su contratti pubblici, manifest o
altri connettori.

- **`ServiceCandidate`** (`service_connectors/base.py`): nuovo campo opzionale
  `native_class: str | None = None`. Le famiglie senza classe nativa (WP, ComWeb) lo lasciano
  `None` → nessun filtro le tocca.
- **`_ServiceConnectorBase.retrieve`** (`connettore_base.py`): nuovo hook
  `_filtra_candidati(candidati, service_key)` chiamato **tra** la discovery e `_confermati`
  (host + recogniser), quindi prima del gate 0/≥2. Default **no-op**: gli altri connettori
  restano invariati.
- **`OpenPAServiceConnector`** (`openpa_service.py`): la costante `_CLASSI_AMMESSE` (allow-list
  per-key) e l'override di `_filtra_candidati` che tiene solo i candidati la cui `native_class`
  è ammessa per la key. `candidato_da_hit_ezfind` estrae ora `classIdentifier` dall'hit eZ e lo
  porta sul candidato.
- La **query** eZ Find resta invariata (nessun `classes [...]`): il filtro è post-fetch, così la
  recall non cala.

**Test fixture-driven** (`tests/test_openpa_service_connector.py`):
`test_filtro_esclude_articolo_notizia` (articolo escluso → NOT_FOUND);
`test_filtro_risolve_ambiguita_tra_servizio_e_notizia` (article scartato → esattamente 1 →
FULFILLED sul public_service); `test_filtro_mantiene_servizio_valido` e
`test_filtro_mantiene_document_per_tributi` (servizio/document validi mantenuti);
`test_filtro_zero_candidati_ammessi_not_found` (solo classi escluse/assenti → NOT_FOUND onesto);
`test_allow_list_copre_le_sei_chiavi_e_esclude_le_classi_giuste` (guardia sulla policy).

## Rischi e limiti

- **`native_class` sempre presente negli hit reali?** Nel campione sì, sempre valorizzato. Un
  hit senza classe viene scartato (conservativo): un candidato non classificabile non è un
  servizio. Rischio: perdere un raro servizio senza classe — accettato come restrizione onesta.
- **IMU/TARI**: la debolezza è strutturale (rumore in `document`/`output`), non chiusa qui.
- **Numeri non rimisurati sotto la policy uniforme**: da confermare a valle, sullo sweep dei
  ~363 OpenPA, quando (e se) autorizzato — non in questa fase.

## Prossimo passo (fuori da questa PR)

Con la PR verde e mergiata, valutare lo sweep dei ~363 comuni OpenPA per rimisurare la resa reale
sotto la policy uniforme. Nessun run nazionale finché non esplicitamente autorizzato.

## Artefatti campione

`scratchpad/openpa_campione/`: `manifest.json`
(sha256 `db996829b889aaf39cc531aa1a492d223a9c4160da200e57c216639dd5208d5d`),
`results.json`, `openpa_campione.sqlite3`, `report-fase-b.md`, `build_manifest.py`, `collect.py`.
