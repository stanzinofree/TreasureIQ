# Ramo 3 — Slice 4: connettore pilota WordPress/AgID (ServiceKey → ServiceReference)

> Stato: **implementato v3**, 2026-08-23. Recepisce le due review (v1→v2→v3):
> 4 decisioni approvate + 3 correzioni tecniche + vincoli di contratto + i
> contratti finali fissati nella review #2. Codice e golden test consegnati.

## Correzioni di review recepite

**v1 → v2**

1. **Falso presupposto su `scheda_servizio` rimosso.** `scheda_servizio`
   costruisce mappa+`_Sonda` internamente e ritorna **solo testo** (titolo,
   descrizione, `a_chi`, `cosa_ottieni`): **non** l'HTML, **non** i link PDF/DOC,
   **non** i link autenticati, e non è stub-abile. Il connettore **non** dipende
   da `SchedaServizio`. Utility nuova con contratto esplicito (§1.2).
2. **Seam di fetch iniettabile** (§1.3): i golden test restano **senza rete**.
3. **Candidato REST ≠ servizio canonico** (§2.4): niente accorpamenti; due pagine
   sullo stesso `ServiceKey` → `NOT_FOUND`; `service_id` da `source_id + id WP`.

**v2 → v3 (contratti finali, review #2)**

4. **Termine di ricerca singolare.** `SERVICE_SEARCH_TERM: dict[ServiceKey, str]`
   (un solo termine canonico per key, **una** query), non una tupla multi-query.
   Gli alias restano nel recognizer per la conferma sui titoli (§2.1).
5. **Auth su host esterno ammesso.** Il vincolo same-host vale **solo** per
   PDF/DOC. Un link autenticato collegato *sulla pagina ufficiale* verso un host
   esterno (URBI/Municipium) è **ammesso**: il connettore non lo segue né
   autentica, `source_url` resta la pagina del comune (§1.2, §2.5).
6. **`ServiceCandidate` tipizzato** (non dict grezzo) e `LinkEvidence` con tipo
   esplicito (`EvidenceKind`). Utility in **`catalog/service_page.py`** (§1.2),
   seam in **`catalog/service_connectors/base.py`** (§1.3).

**v3 → v3.1 (review del commit `8965a2e`, confine HTTP)**

7. **Guardia host sul candidato REST.** Un `link` REST verso un host esterno
   veniva usato direttamente come `source_url`/INFORMATION. Ora `_confermati`
   scarta ogni candidato il cui host ≠ host ufficiale (normalizzato `www`),
   **prima** della conferma: 0 confermati → `NOT_FOUND` (§2.4).
8. **Guardia sui redirect nel fetcher reale.** `HttpxServiceFetcher.leggi_pagina`
   non lascia più seguire i redirect a httpx: li segue a mano ricontrollando
   l'host a **ogni hop** e sull'URL finale (redirect off-host → `None`). Host
   verificato anche sull'URL iniziale. `transport` iniettabile → il confine HTTP
   è testato con `httpx.MockTransport`, senza rete (§1.3).
9. **Contesto autenticato ristretto.** `leggi_pagina_servizio` non usa più una
   finestra piatta di N caratteri: legge il **contenitore immediato** del link
   (indietro fino al confine di blocco più vicino) + `aria-label`/`title`
   dell'ancora. Una frase «servizio online» in un'altra sezione non contamina
   più un link generico (§1.2).

## 0. Cosa risolve questa slice

Slice 3 ha dato il **resolver** (cache↔connettore) e il seam (`SourceConnector`
+ `ConnectorResult.service_references` + `ConnectorRegistry`), col registry
**vuoto**. Slice 4 **rende disponibile il primo connettore di piattaforma** per
il registry (il wiring in un registry di produzione è demandato a Slice 5, §5):
dato un `ServiceKey`, interroga il portale WordPress/AgID del comune e produce
**esattamente un** `ServiceReference` con le sue `ServiceAccessOption`
(informativa, download PDF/DOC, e — solo se collegata *sulla pagina* — accesso
autenticato online).

Primo pilota di una famiglia (WP/AgID copre la fetta più grande dei comuni,
memoria `flotta-connettori-nazionale`). Le altre piattaforme sono connettori
successivi sullo **stesso** seam, non qui. Fuori scope: wiring chat/DataBatch
(Slice 5), merge dell'entrypoint SP dall'inventario (Slice 6), Rust (Slice 7).

## 1. Acquisizione: fonti, utility, seam iniettabile

Il connettore **non inventa nulla**: ogni URL proviene da una risposta REST del
portale o dall'HTML della pagina servizio.

### 1.1 Fonti (deterministiche)

1. **Mappa in cache** (`mappa_connettore`, `LIVE_DIR/mappa-connettore/`): dà
   `mappa.sito` e `mappa.servizi.esposto` + `mappa.servizi.rest_base` (il
   `rest_base` del CPT «servizi», già misurato). `sito` assente o `esposto` falso
   → `NOT_SUPPORTED` (nessuna scoperta al volo qui).
2. **Chiamata secca al CPT servizi** (pattern «connettore target singolo»,
   memoria `post-mvp-connettore-target-singolo`): una GET
   `…/wp-json/wp/v2/{rest_base}?search=<term>&per_page=N&_fields=id,title,link`.
   `search=` è WP core: query mirata, **non un crawler**. Un solo `term` (§2.1).
3. **Pagina servizio**: letta una volta sul `link` REST del candidato
   confermato → HTML da cui estrarre PDF/DOC e l'eventuale accesso autenticato.

### 1.2 Utility `catalog/service_page.py` (non `SchedaServizio`)

Normalizzatore di dati già acquisiti, **non** uno scraper e **non** un
estrattore documenti. Riceve l'HTML di **una** pagina servizio (scaricato dal
fetcher §1.3) e ritorna **evidenze tipizzate**. Contratto implementato:

```python
class EvidenceKind(str, Enum):
    DOWNLOAD = "download"
    AUTHENTICATED_ONLINE = "authenticated_online"

class LinkEvidence(_StrictModel):          # frozen
    url: AnyHttpUrl
    kind: EvidenceKind
    anchor_text: str = Field(min_length=1)
    context_text: str | None = None
    authentication: tuple[AuthenticationMethod, ...] = ()

class PaginaServizio(_StrictModel):        # frozen
    page_url: AnyHttpUrl
    links: tuple[LinkEvidence, ...] = ()

def leggi_pagina_servizio(html: str, *, page_url: str, official_host: str) -> PaginaServizio: ...
```

- **Politica di provenienza (imposta qui, non dal connettore):**
  - **DOWNLOAD**: solo `.pdf`/`.doc`/`.docx`/`.odt` **e** solo sullo stesso host
    del portale — un modulo è il file del comune, non di un terzo.
  - **AUTHENTICATED_ONLINE**: solo link con testo ancora o contesto che sono una
    chiamata esplicita a servizio online/autenticato; un generico «Area
    personale» del menu **non** è evidenza. **Host esterno ammesso** (il comune
    linka legittimamente URBI/Municipium) — il connettore non lo segue né
    autentica.
  - Mai `javascript:`/`data:`/`mailto:`/solo-frammento/non-HTTP(S).
- Utility **pura**: nessuna rete. `page_url` risolve i link relativi (`urljoin`);
  `official_host` gatea la policy same-host del DOWNLOAD. Deterministica: stesso
  HTML → stesse evidenze, in ordine di documento, deduplicate per `(url, kind)`.
- Ritorna **solo evidenze**: costruire le `ServiceAccessOption` è del connettore.

### 1.3 Seam di fetch iniettabile — `catalog/service_connectors/base.py`

Il connettore riceve un `ServiceFetcher` (Protocol), non crea `_Sonda`. Il
candidato REST è **tipizzato** (niente dict grezzi):

```python
class ServiceCandidate(_StrictModel):      # frozen
    wordpress_id: int = Field(gt=0)
    title: str = Field(min_length=1)
    url: AnyHttpUrl

class ServiceFetcher(Protocol):
    def cerca_servizi(self, *, base_url: str, rest_base: str, term: str, limit: int
                      ) -> tuple[ServiceCandidate, ...]: ...
    def leggi_pagina(self, *, url: str, official_host: str) -> str | None: ...
```

Metodi **keyword-only**. Responsabilità dell'impl. reale (`HttpxServiceFetcher`,
in `wordpress_agid.py`): costruzione URL REST, encoding del termine, `per_page`,
timeout, stato HTTP, JSON malformato, **guardia host** sulla pagina, disciplina
**no-login/no-cookie**. Nei test uno **stub** ritorna candidati/HTML da fixture;
nessun ramo tocca la rete. `HttpxServiceFetcher` è l'unica parte non coperta dai
golden (è quella che parla la rete).

## 2. ServiceKey → servizio (deterministico)

### 2.1 Termine di ricerca — nel dominio catalogo (Decisione 2)

Un solo termine canonico per key nel **contratto di dominio**, non in
`chat/service_key.py` né nel connettore:

```python
# catalog/service_contracts.py
SERVICE_SEARCH_TERM: dict[ServiceKey, str] = {
    ServiceKey.CARTA_IDENTITA: "carta d'identità",
    ServiceKey.CAMBIO_RESIDENZA: "cambio di residenza",
    ServiceKey.ACCESSO_ATTI:   "accesso agli atti",
    ServiceKey.STATO_CIVILE:   "stato civile",
    ServiceKey.TRIBUTI:        "tributi",
}
```

Responsabilità distinte, stesso vocabolario: il **recognizer** interpreta il
testo del cittadino (alias, marker); `SERVICE_SEARCH_TERM` guida **una**
acquisizione (restringe `search=`). Il titolo del candidato è comunque
confermato dal recognizer dopo (§2.2), quindi un termine basta — nessun
fan-out multi-query (aggiungerebbe traffico e ambiguità).

### 2.2 Conferma via recognizer sui titoli (Decisione 1)

Riuso di `riconosci_service_key` (unico e condiviso) applicato ai **titoli** dei
candidati REST. Il candidato è confermato **solo se**:

- `riconosci_service_key(title)` è **lo stesso `ServiceKey`** richiesto; **e**
- il titolo è **non ambiguo** (il recognizer restituisce `None` per marker in
  conflitto, quindi un titolo che marca due key è già escluso);
- **nessuna** selezione «migliore» o per vicinanza: un candidato che non
  conferma è scartato, non avvicinato.

### 2.3 Selezione (allineata alla guardia #2 del resolver)

- esattamente **un** candidato confermato → si costruisce il `ServiceReference`;
- **zero** → `NOT_FOUND` (miss onesto, mai il vicino);
- **≥2** → `NOT_FOUND` (ambiguo: la scelta tra servizi è del livello superiore).

### 2.4 Candidato REST ≠ servizio canonico (correzione #3)

- **Nessun accorpamento arbitrario**: due `link` diversi restano due candidati;
  non si fondono per «sembrare lo stesso servizio».
- Se **due pagine** confermano lo stesso `ServiceKey` → `NOT_FOUND` (§2.3, ≥2).
- **`service_id` stabile**: `"{source_id}:wp:{wordpress_id}"` (es.
  `"058003:wp:1234"`), **mai dal titolo** (il titolo cambia, l'id WP no). Idem
  risoluzione ripetuta → stesso `service_id` → cache coerente. `wordpress_id`
  validato `> 0` da `ServiceCandidate`.

### 2.5 Accesso autenticato: evidenza specifica, non menu

`AUTHENTICATED_ONLINE` **solo** da un link con evidenza *contestuale alla
pagina servizio* (bottone/callout «accedi al servizio», «presenta la domanda
online», SPID/CIE nel contesto). Un generico «Area personale» nel menu di
navigazione **non** è evidenza. L'host può essere **esterno** (§1.2): il
connettore non lo segue. Nessun merge con `SourceInventory.service_portals`
(→ Slice 6).

## 3. Forma del connettore + vincoli di contratto

Un `SourceConnector` (riuso Protocol Slice 3) in
`catalog/service_connectors/wordpress_agid.py`.

```python
class WordPressAgidServiceConnector:
    name = "wordpress_agid_service"
    version = "1"
    def __init__(self, fetcher: ServiceFetcher): ...
    def supports(self, request, *, platform_id) -> bool:
        return (request.surface is Surface.ORDINARY_DATA
                and request.capability == CAPABILITY_SERVICES
                and platform_id in _PIATTAFORME_WP_AGID)
    def retrieve(self, request, *, mappa, esito) -> ConnectorResult: ...

_PIATTAFORME_WP_AGID = frozenset(WORDPRESS_AGID_MANIFEST.platforms)
```

`supports()` è la **barriera di non-confusione** col `ServicePortalConnettore`
(`SERVICE_PORTAL`/`INDIRECT`): questo connettore raccoglie **solo**
`ORDINARY_DATA + CAPABILITY_SERVICES` su piattaforma WP/AgID. Doppia guardia col
resolver. `retrieve()` alza `ValueError` se `request.source_id != mappa.codice_istat`
(il `service_id` nasce da `source_id`: un mismatch conierebbe un'identità falsa).

### Vincoli imposti dal contratto (dalla review)

| Vincolo | Regola |
|---|---|
| `ConnectorResult.access_mode` | `MEDIATED` quando il dato è recuperato dal connettore (TIQ media, non è la fonte) |
| `ServiceReference.source_url` | il **permalink REST** del servizio (il `link` del candidato) |
| `ServiceAccessOption.source_url` | la **pagina che contiene l'evidenza** dell'opzione (la pagina del comune) |
| INFORMATION | sempre (servizio confermato): `url` e `source_url` = permalink pagina |
| DOWNLOAD | uno per PDF/DOC, `url` **assoluto o same-host normalizzato**; cross-host scartato |
| AUTHENTICATED_ONLINE | solo con **evidenza specifica in-pagina** (§2.5); host esterno ammesso; `requires_authentication=True` |
| Merge SP inventariati | **vietato** in Slice 4 (→ Slice 6) |
| `service_id` | stabile: `{source_id}:wp:{id}` (§2.4) |
| Auto-autenticazione | **mai**: nessun login/POST/cookie; TIQ non entra |
| Purezza | nessun side-effect su disco; la cache la scrive **solo** il resolver |
| `evidence` | il `ConnectorResult` cita gli URL usati (un `EvidenceRef` per opzione) |

`ServiceReference.options` ha `min_length=1`: INFORMATION garantisce sempre
almeno un'opzione a servizio confermato.

## 4. I tre casi di accettazione

| Caso | Pagina servizio contiene | `options` |
|---|---|---|
| **1. PDF** | link modulo `.pdf`/`.doc` same-host | INFORMATION + DOWNLOAD (uno per file) |
| **2. Solo autenticato** | link «accedi al servizio» con evidenza, nessun PDF | INFORMATION + AUTHENTICATED_ONLINE |
| **3. Informativa** | né PDF né accesso online (o pagina illeggibile) | INFORMATION (sola) |

Tutti: `status=FULFILLED`, `access_mode=MEDIATED`, `len(service_references)==1`
→ il resolver scrive in cache. Non trovato/ambiguo → `NOT_FOUND`, nessuna
scrittura.

## 5. Wiring col resolver (registry)

Slice 3 lascia il registry vuoto; Slice 4 lo popola col pilota:

```python
registry = ConnectorRegistry()
registry.register(WordPressAgidServiceConnector(fetcher=HttpxServiceFetcher()))
resolve_service(request, mappa=mappa, esito=esito, registry=registry,
                platform_id=platform_id)
```

Resolver invariato. `platform_id` dalla classificazione censimento (memoria
`censimento-piattaforme-comunali`); alimenta `supports()`. Nessun caller di
produzione ancora: la chat invoca il resolver in Slice 5.

## 6. Golden test (Slice 4) — consegnati

File `api/tests/test_wordpress_agid_service_connector.py`, **29 test, senza
rete** (`StubFetcher` con candidati/HTML da fixture). Tre strati:

- **`supports`/`retrieve`**: barriera di non-confusione; guard (no key / key fuori
  vocabolario / no sito / servizi non esposti / mismatch source_id → `ValueError`);
  single-confirmed → `ServiceReference` (MEDIATED, `service_id` dall'id WP,
  `source_url`=permalink); 0/≥2 confermati → `NOT_FOUND`; candidati non
  confermati scartati lasciandone uno; pagina illeggibile → sola INFORMATION;
  DOWNLOAD same-host; AUTHENTICATED_ONLINE host esterno + metodo auth; il termine
  di query è `SERVICE_SEARCH_TERM[key]`.
- **`leggi_pagina_servizio`**: PDF same-host sì / cross-host no; «Area personale»
  nudo non è evidenza; `javascript:`/`mailto:`/frammento rifiutati; link
  relativo risolto; dedup `(url, kind)`.
- **recognizer sui titoli WP**: 5 titoli realistici → key attesa; titolo ambiguo
  → `None`; titolo estraneo → `None`.

### Invarianti coperte

- **No-URL-inventato**: ogni `url` è in una fixture; asserito per campo.
- **Exactly-one o niente**: 0/≥2 confermati → `NOT_FOUND`.
- **No-auth, no-entrata**: nessuna fixture richiede login; TIQ non entra.
- **Puro**: il connettore non scrive su disco (solo il resolver).
- **Non-confusione**: nessuna richiesta `SERVICE_PORTAL` servita.
- **Provenienza corretta**: MEDIATED + source_url permalink/pagina.

## 7. Decisioni — esito review

| # | Decisione | Esito |
|---|---|---|
| 1 | `riconosci_service_key` sui titoli (unico, condiviso) | **Approvata**, test dedicati sui titoli WP (§2.2) |
| 2 | Mappa termini REST | **Approvata**, `SERVICE_SEARCH_TERM: dict[ServiceKey, str]` singolare (§2.1) |
| 3 | AUTHENTICATED_ONLINE solo in-pagina, host esterno ammesso | **Approvata** (§2.5); merge SP → Slice 6 |
| 4 | Confine con Slice 6 | **Approvata** |
| — | Utility `leggi_pagina_servizio` | **Fissata**: `catalog/service_page.py`, `LinkEvidence`+`EvidenceKind`, evidenze-non-opzioni (§1.2) |
| — | Seam `ServiceFetcher` | **Fissato**: `catalog/service_connectors/base.py`, `ServiceCandidate` tipizzato, keyword-only, `HttpxServiceFetcher` reale (§1.3) |
| — | `service_id` | **Fissato**: `{source_id}:wp:{id}` (§2.4) |
| — | `_PIATTAFORME_WP_AGID` | `frozenset(WORDPRESS_AGID_MANIFEST.platforms)` |

## 8. Fuori scope (Slice 4)

DataBatch + dispatcher chat e `Topic.MODULISTICA` (Slice 5), merge
dell'entrypoint SP dall'inventario (Slice 6), oracolo Rust (Slice 7), connettori
delle altre famiglie (medesimo seam). Flusso SP e `_risposta_modulistica`
attuali invariati finché Slice 5 non li ricabla.
