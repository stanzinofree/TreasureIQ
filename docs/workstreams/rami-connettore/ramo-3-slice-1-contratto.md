# Ramo 3 — Slice 1: contratto di richiesta modulistica

> Stato: **contratto approvato** (review 2026-08-23, 4 correzioni recepite),
> in implementazione. Slice 1 del piano operativo
> (`ramo-3-modulistica-piano.md`, §6 e §10.3). Il flusso SP esistente resta
> invariato (Slice 0, no-regressione).
>
> Correzioni di review recepite: (1) `ServiceKey` vive in `catalog/`, non in
> `chat/`; (2) il builder accetta `ServiceKey`, non stringa libera; (3)
> capability `services` centralizzata in `CAPABILITY_SERVICES`,
> `request_from_recognition` **non** toccato; (4) marker ristretti
> (`residenza` isolato rimosso, `cie` a parola intera).

## 0. Cosa risolve questa slice

Il flusso MODULISTICA di oggi (`respond._risposta_modulistica`) risolve
**entrypoint di portale**, non **servizi**. Il `service_id` passato a
`planner.service_portal_request` è *letteralmente l'URL* del
`ServicePortalCandidate` confermato. Conseguenza (piano §2): «mi serve il
modulo della carta d'identità» produce sempre una lista di portali, perché il
sistema non ha un'identità del servizio richiesto.

La Slice 1 introduce quell'identità come **asse deterministico separato**: un
`service_key` normalizzato, riconosciuto dal testo con la stessa disciplina
dello scorer intent (vocabolario chiuso, nessun LLM, nessun ripiego sul
servizio più vicino).

**Slice 1 = solo il contratto.** Vocabolario `ServiceKey`, funzione di
riconoscimento, firma del request-builder, test golden. Non tocca cache
(Slice 2), connettore (Slice 3), `DataBatch`/dispatcher (Slice 5), aggancio SP
(Slice 6) né oracolo Rust (Slice 7). Il flusso SP attuale resta invariato
(Slice 0, no-regressione).

## 1. `service_key` — identità normalizzata del servizio

### 1.1 Vocabolario chiuso

Un enum, non stringa libera, coerente con `Topic`. **Vive in
`catalog/service_contracts.py`** (correzione review #1): è un contratto di
dominio condiviso tra chat, planner, cache e connettori — chat *riconosce* la
chiave ma non *possiede* il vocabolario.

```python
# catalog/service_contracts.py
class ServiceKey(str, Enum):
    CARTA_IDENTITA = "carta_identita"
    CAMBIO_RESIDENZA = "cambio_residenza"
    ACCESSO_ATTI = "accesso_atti"
    STATO_CIVILE = "stato_civile"
    TRIBUTI = "tributi"
```

I cinque valori sono esattamente quelli indicati dal piano (§6, Slice 1). È un
insieme di partenza estendibile per aggiunta, mai per ripiego: un servizio non
in vocabolario resta `None`, non viene mappato sul valore più vicino.

`ServiceKey` è **ortogonale** a `Topic`. `Topic.MODULISTICA` resta unico
(D-R3-1); `service_key` è un secondo asse letto dallo stesso messaggio. I tre
`ServiceAccessMode` (INFORMATION/DOWNLOAD/AUTHENTICATED_ONLINE) restano un
**esito** dei dati trovati, non entrano qui.

### 1.2 Riconoscimento deterministico

Funzione pura, marker-based, **fuori dal contratto del modello** — vive in
`chat/service_key.py` e importa `ServiceKey` da `catalog/`. Stesso pattern di
`_beneficiary_role_da_testo` e `filtri.riconosci_filtri`, così i due backend
intent (`model` e `scorer`/`rust`) producono lo stesso esito e la Slice 7
(oracolo TOML/PyO3) non è un prerequisito:

```python
def riconosci_service_key(message: str) -> ServiceKey | None:
    """service_key dai SOLI marcatori nel testo. Nessun LLM, nessun
    servizio vicino indovinato. Ambiguo (due chiavi distinte) -> None."""
```

Marker (correzione review #4: `residenza` isolato rimosso perché troppo
generico; `cie`/`imu`/`tari` a **parola intera** via `\b`, non substring —
`cie` in «società» non deve scattare). Solo forma esatta, casefold, niente
stemming semantico:

| `service_key` | marker substring | marker parola-intera |
|---|---|---|
| `CARTA_IDENTITA` | «carta d'identità», «carta di identità» (+ varianti senza accento) | `cie` |
| `CAMBIO_RESIDENZA` | «cambio residenza», «cambio di residenza», «trasferimento (di) residenza» | — |
| `ACCESSO_ATTI` | «accesso agli atti», «accesso atti» | — |
| `STATO_CIVILE` | «stato civile», «certificato di nascita», «certificato di morte», «matrimonio» | — |
| `TRIBUTI` | «tributi», «tassa rifiuti» | `imu`, `tari` |

Regole del riconoscitore (identiche allo scorer):

1. **Determinismo.** Stessa frase → stesso `service_key`, sempre.
2. **Nessun ripiego.** Zero marker → `None` (mai il servizio più vicino).
3. **Ambiguità → `None`.** Due chiavi distinte marcate nello stesso messaggio
   → `None` (non si sceglie la prima). La disambiguazione tra servizi è
   compito del handler a valle (piano §7), non del riconoscitore; a livello di
   chiave l'esito onesto è «non deciso».
4. **Trappole toponimo/connettivi.** Riusare le stoplist già esistenti
   (`connettivi-nome-falsi-candidati`, `parola-comune-toponimo-esatto`) per i
   marker che collidono con nomi comuni (es. «residenza» come toponimo). Da
   verificare in review; non introdurre nuova logica di comune qui.

Il riconoscitore vive come step deterministico separato in `chat/service_key.py`,
**non** dentro `_ModelIntent`/`ChatIntent`: tiene il modello fuori dalla scelta
del servizio (D-R3-7), evita di rigenerare l'oracolo scorer, e mantiene
`service_key` un asse ortogonale a `ChatIntent` (per questo
`request_from_recognition` non va toccato, correzione review #3).

## 2. Contratto di richiesta

### 2.1 Nuovo request-builder (separato da SP)

Il piano (§4) vuole `DataRequest(capability=forms/services, selection=service_key)`
sulla superficie del **dato ordinario**, distinta dal portale servizi (D-R3-2).
`service_portal_request` resta com'è: è il sotto-caso `AUTHENTICATED_ONLINE`,
agganciato solo alla Slice 6. Si aggiunge un builder gemello in
`catalog/planner.py`:

```python
def service_request(
    *,
    source_id: str,
    service_key: ServiceKey,           # tipo, non stringa libera (review #2)
    freshness: FreshnessPolicy | None = None,
) -> DataRequest:
    """Richiesta deterministica di un servizio riconosciuto.

    ``service_key`` è un valore ``ServiceKey``: il tipo stesso impedisce a
    qualunque caller di sintetizzare una capability da testo arbitrario.
    """
    return DataRequest(
        request_id=f"chat:{source_id}:{Surface.ORDINARY_DATA.value}:{service_key.value}",
        source_id=source_id,
        surface=Surface.ORDINARY_DATA,
        capability=CAPABILITY_SERVICES,   # costante condivisa (review #3)
        selection={"service_key": service_key.value},
        freshness=freshness or FreshnessPolicy(max_age_seconds=86400),
        manifest_revision=1,
    )
```

Simmetrico a `service_portal_request` (stessa forma `request_id`, stessa
disciplina di provenienza), ma superficie `ORDINARY_DATA` e `AccessMode`
diretto/mediato — non `INDIRECT`. Il `request_id` usa `service_key.value`.

### 2.2 Capability

Capability `"services"` centralizzata in **`CAPABILITY_SERVICES`**
(`catalog/contracts.py`, accanto a `CAPABILITY_NOTICES`), riusata da builder e
planner così nessun caller riscrive la stringa (correzione review #3).
Confermato il riuso di `services` e non una nuova `forms`: `ServiceReference`
rappresenta un **servizio** — che può esporre anche un'opzione `DOWNLOAD` — non
solo un file scaricabile.

`request_from_recognition` **non** va modificato in questa slice: `service_key`
è un asse separato da `ChatIntent`, quindi il dispatcher chiamerà direttamente
`service_request` (correzione review #3).

### 2.3 Cosa NON fa il builder in Slice 1

Nessun caller in `respond.py` viene aggiunto ora: `service_request` esiste ma è
0-caller finché la Slice 5 non lo aggancia. Come fu per `service_portal_request`
(esportato in 3E, primo caller chat solo dopo). Questo mantiene la slice
piccola e reversibile (§10.5).

## 3. Test golden (Slice 1)

Tutti unit, nessuna rete, nessun modello. File proposto:
`api/tests/test_service_key.py` (+ un caso in `test_catalog_planner.py` per il
builder).

### 3.1 Riconoscimento — tabella golden

| # | messaggio | atteso |
|---|---|---|
| 1 | «mi serve il modulo della carta d'identità» | `CARTA_IDENTITA` |
| 2 | «voglio fare il cambio di residenza» | `CAMBIO_RESIDENZA` |
| 3 | «come faccio l'accesso agli atti» | `ACCESSO_ATTI` |
| 4 | «certificato di nascita» | `STATO_CIVILE` |
| 5 | «devo pagare la TARI» | `TRIBUTI` |
| 6 | «vorrei un contributo per l'affitto» | `None` (fuori vocabolario) |
| 7 | «ciao» | `None` |
| 8 | «carta d'identità e cambio residenza» | `None` (ambiguo, §1.2 r.3) |
| 9 | «residenza» | `None` (marker isolato rimosso, review #4) |
| 10 | «carta d'identità e accesso agli atti» | `None` (ambiguo) |
| 11 | «modulo per il passaporto» | `None` (vicino ma fuori vocabolario) |
| 12 | «cambio di residenza» | `CAMBIO_RESIDENZA` |
| 13 | «apertura di una società» | `None` (`cie` substring non scatta) |

### 3.2 Invarianti

- **Determinismo**: ogni frase della tabella, invocata due volte, dà lo stesso
  esito (`riconosci_service_key(m) == riconosci_service_key(m)`).
- **Chiusura**: nessun input produce un valore non in `ServiceKey`.
- **Nessun ripiego**: un messaggio con un servizio *vicino ma non in
  vocabolario* (es. «passaporto») → `None`, mai `CARTA_IDENTITA`.
- **Builder**: `service_request(source_id="058003", service_key="carta_identita")`
  → `DataRequest` con `surface=ORDINARY_DATA`, `capability="services"`,
  `selection == {"service_key": "carta_identita"}`, `request_id` deterministico;
  e **non** `SERVICE_PORTAL` (confine D-R3-2).

### 3.3 No-regressione (gate Slice 0)

I test SP esistenti (`test_chat_modulistica.py`,
`test_catalog_service_portal_executor.py`) restano verdi invariati: la Slice 1
non tocca `_risposta_modulistica` né `service_portal_request`.

## 4. Decisioni chiuse in review (2026-08-23)

1. **Collocazione**: `ServiceKey` in `catalog/service_contracts.py`;
   riconoscitore in `chat/service_key.py`.
2. **Builder tipizzato**: `service_request(service_key: ServiceKey)`, mai
   stringa libera; `request_id` usa `.value`.
3. **Capability**: `CAPABILITY_SERVICES = "services"` centralizzata;
   `request_from_recognition` invariato.
4. **Marker**: `residenza` isolato rimosso; `cie`/`imu`/`tari` a parola intera.

## 5. Artefatti Slice 1

| File | Contenuto |
|---|---|
| `catalog/service_contracts.py` | enum `ServiceKey` |
| `catalog/contracts.py` | costante `CAPABILITY_SERVICES` |
| `catalog/planner.py` | builder `service_request(...)` (0-caller) |
| `chat/service_key.py` | `riconosci_service_key(message)` |
| `tests/test_service_key.py` | golden recognizer + builder |

Tutto il resto (cache, connettore, DataBatch, aggancio SP, oracolo Rust) è
esplicitamente **fuori** dalla Slice 1. Il flusso SP esistente
(`_risposta_modulistica`, `service_portal_request`) resta invariato.

## 6. Handoff — failure preesistenti fuori scope

La suite completa alla chiusura Slice 1: **1367 passed, 6 skipped, 3 failed**.
I 3 failure sono **preesistenti su HEAD pulito** (verificato con
`git stash` + rerun: falliscono senza le modifiche Slice 1) e **fuori scope**
dal contratto modulistica — nessun riferimento a
`service_key`/`planner`/`contracts`. Non bloccano il ramo.

- `tests/test_wp_pages_caratterizzazione.py::test_pdf_budget_and_audit_trail`
- `tests/test_wp_pages_caratterizzazione.py::test_corpus_truncation_and_segment_boundaries`
- `tests/test_wp_pages_caratterizzazione.py::test_recovery_level_and_notes`

Sintomo: limite byte PDF (`skipping PDF … oltre il limite di 2097152 byte`) e
soglie di troncamento corpus. Riproduzione:

```
docker build -q -t treasureiq-api-dev --target dev api
docker run --rm -v "$(pwd)/api:/src" -v "$(pwd)/data:/data:ro" \
  --tmpfs /test-state:rw,exec,nosuid,nodev -e TREASUREIQ_DATA_DIR=/data \
  -e TREASUREIQ_CONVERSATION_DB=/test-state/conversations.sqlite3 -w /src \
  treasureiq-api-dev python -m pytest -q tests/test_wp_pages_caratterizzazione.py
```

Da promuovere a **workstream separato** (indagine limite PDF) dopo la chiusura
del contratto modulistica — non prima.
