# Ramo 3 — Slice 5: wiring runtime del connettore modulistica

**Stato:** design (v5, precisazione review #4 — contratto lock non ambiguo), **approvato**. Slice 5 può partire.
**Branch previsto:** `feat/ramo3-sp-increment1` (stesso ramo delle slice precedenti).
**Dipende da:** Slice 3 (resolver cache-first), Slice 4 (connettore WP/AgID + fetcher).

---

## §0 — Scopo

Chiudere la catena di Ramo 3: una domanda tipo «Mi serve il **modulo della carta
d'identità** del Comune di Albano» deve arrivare al **connettore WP/AgID reale**
(Slice 4), risolvere `ServiceKey → ServiceReference` con le sue opzioni di
accesso (pagina informativa, PDF/DOC scaricabile, online-autenticato solo se
davvero linkato), e produrre **`DataBatch` + risposta chat**.

Due buchi da colmare, entrambi già predisposti ma non collegati:

1. **Registry vuoto.** `resolve_service` (Slice 3) istanzia un
   `ConnectorRegistry()` **vuoto** → `registry.resolve(...)` ritorna sempre
   `None`. Nessun connettore è registrato nel runtime.
2. **Topic sul ramo sbagliato.** `Topic.MODULISTICA` oggi (increment 1, commit
   `273dc4a`) instrada al **puntatore SP** (`ServicePortalConnettore`,
   `SERVICE_PORTAL/INDIRECT`): indica la *porta* del portale, non recupera il
   *modulo*. Va instradato al **resolver** (`ORDINARY_DATA/CAPABILITY_SERVICES`,
   `MEDIATED`).

**Vincolo del committente (esplicito):** collegare MODULISTICA al resolver
producendo DataBatch e risposta **senza riusare il vecchio ramo SP come
fallback**. Miss del resolver → risposta onesta (chiedi comune / rimando URP),
mai il puntatore SP a coprire il buco.

---

## §1 — Architettura

Catena nuova (specularmente a uffici/bandi, ma sul resolver):

```
Topic.MODULISTICA
  → riconosci_service_key(message)            # 0/≥2 → chiedi, mai indovina
  → service_request(source_id, service_key)   # ORDINARY_DATA + CAPABILITY_SERVICES (planner, già esiste)
  → resolve_service_with_meta(request, mappa, registry=<popolato>, platform_id=mappa.piattaforma_id)
        ├─ cache-first (Slice 2)   # CachedService → ResolvedService(from_cache=True, retrieved_at cache), no rete
        └─ registry.resolve → WordPressAgidServiceConnector.retrieve  # Slice 4, live via EsecutoreFetch
  → ResolvedService | None                        # envelope: reference + retrieved_at + from_cache + connector
  → service_reference_batch(resolved, request)    # NUOVO builder → DataBatch MEDIATED, Freshness dall'envelope
  → build_query_plan + select_batch               # catena canonica, tracciabilità
  → ChatAnswer(data_batches, query_plan, selected_data_batch, info=InfoAnswer(service=ServiceAnswer(...)))
```

### 1.0 — Envelope di risoluzione (correzione review #1, blocking)

**Problema.** `resolve_service` ritorna la sola `ServiceReference` → si perde
`CachedService.retrieved_at` (quando il connettore ha **risolto** il servizio) e
il `ConnectorRef` di provenienza. `ServiceReference.discovered_at` (quando è
stata **scoperta la pagina**) **non** è un sostituto: usarlo per la freshness
mentirebbe sul momento del servizio. Senza envelope, `service_reference_batch`
non può costruire una `Freshness` corretta né indicare il connettore dopo un
cache hit.

**Soluzione.** Envelope interno + funzione parallela che lo restituisce (la
`resolve_service` esistente resta per i chiamanti che vogliono solo la
reference):

```python
class ResolvedService(_StrictModel):
    reference: ServiceReference
    retrieved_at: datetime      # quando il connettore ha RISOLTO (cache o live)
    from_cache: bool
    connector: ConnectorRef

def resolve_service_with_meta(request, *, mappa, esito=None,
                              registry=None, platform_id="") -> ResolvedService | None: ...
```

Regola di freshness (imposta qui, non nel builder del batch):

| Provenienza | `FreshnessStatus` | `retrieved_at` | `connector` |
|-------------|-------------------|----------------|-------------|
| **cache hit** | `FRESH` | `CachedService.retrieved_at` | `CachedService.connector` |
| **live** | `LIVE` | timestamp della chiamata | `ConnectorResult.connector` |

- `reference.discovered_at` **non** è mai usato come sostituto di `retrieved_at`.

**Cambio schema cache (correzione review #2, blocking).** Contraddizione nella
v2: `CachedService` **non** ha oggi il campo `connector` — porta solo
`service_key`, `reference`, `retrieved_at`, `schema_version` — e
`service_cache.carica()` ritorna la **sola** `ServiceReference`. Senza connettore
in cache non si può soddisfare «cache hit con connector preservato». Quindi:

- aggiungere `connector: ConnectorRef` a `CachedService`;
- `SERVICE_CACHE_SCHEMA_VERSION = 2` → le cache v1 diventano **miss** e si
  rigenerano (coerente con la guardia di versione già esistente, nessuna
  migrazione rischiosa);
- `salva(...)` accetta e persiste il `connector` (da `ConnectorResult.connector`);
- `carica(...)` restituisce l'informazione completa (la `CachedService`, o una
  tupla `reference + retrieved_at + connector`) così che
  `resolve_service_with_meta` costruisca l'envelope senza reinventare la
  provenienza.
- **Scartata** la derivazione da `reference.provider_platform`: perde
  nome/versione del connettore e non è universale.

### 1.1 — Registry popolato + politica di fetch (buco 1 + correzione review #2)

Nuovo factory in `catalog` (proposto `default_service_registry()`), che **non**
istanzia un `HttpxServiceFetcher` grezzo ma un fetcher che passa dalla
**`PoliticaFetch`/`EsecutoreFetch`** (Fase 2):

```python
def default_service_registry(esecutore: EsecutoreFetch) -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(WordPressAgidServiceConnector(EsecutoreServiceFetcher(esecutore)))
    return reg
```

**Perché (review #2).** Il `HttpxServiceFetcher` di Slice 4 apre `httpx` diretto:
una cache-miss dalla chat bypasserebbe rate-limit per dominio, budget, backoff,
timeout centralizzati e telemetria. Il cache-first riduce il traffico ma **non**
sostituisce il limite operativo.

**Contratto preciso di `EsecutoreServiceFetcher`** (implementa lo stesso Protocol
`ServiceFetcher`). L'API reale è
`esecutore.esegui(url, *, **fetch_kwargs) → EsitoFetch(consentito, fetched, motivo)`
con `fetch_kwargs` inoltrati a `fetch_guardato` e `fetched = (headers, bytes,
url_finale) | None` (**bytes**, non testo). L'adapter:

- **`host_atteso`** = host del portale ufficiale (da `base_url`/`official_host`),
  passato a ogni chiamata → `fetch_guardato` valida host su URL iniziale **e a
  ogni hop** + check SSRF IP (`host_risolve_a_ip_sicuro`). L'adapter **non**
  duplica alcun controllo host/redirect nel connettore: è già di `fetch_guardato`.
- **`max_bytes` distinti**: uno per la ricerca REST (JSON piccolo), uno più ampio
  per l'HTML della pagina servizio. Costanti dedicate.
- **`timeout`** esplicito (dal coordinatore, §quale-esecutore).
- **Decodifica UTF-8** dei bytes; `cerca_servizi` fa `json.loads` sul testo e
  costruisce i `ServiceCandidate`; `leggi_pagina` ritorna il testo HTML.
- **`consentito=False`** (rate-limit/budget) → **miss** (`()` per la ricerca,
  `None` per la pagina), **senza retry autonomo**: il retry/backoff è della
  politica, non dell'adapter.
- **`fetched is None`** o risposta **non decodificabile/JSON malformato** → miss.
- Params REST **bakeati nell'URL** (come Slice 4).

- **`HttpxServiceFetcher` (Slice 4) resta** come fetcher di basso livello e per
  i test unitari del confine HTTP; il **runtime** usa l'adapter guardato.
- **Iniettabile.** `resolve_service_with_meta` accetta già `registry`. Il ramo
  chat passa `default_service_registry(service_query_fetch_coordinator)`; i test
  passano un registry con **stub-fetcher** → nessuna rete, nessun esecutore reale.
- **Confine famiglie.** Il registry contiene solo WP/AgID (pilota); le altre
  entrano nello stesso factory in slice successive.

### 1.2 — Quale `EsecutoreFetch`: coordinatore condiviso (correzione review #2)

**Non** l'esecutore dello sweep (ha budget per-lotto), **non** uno creato
per-messaggio, **non** legato alla sessione browser (la sessione non governa
risorse di rete). Le query live dei servizi hanno un profilo diverso: richieste
distribuite nel tempo e tra utenti.

- **`service_query_fetch_coordinator`**: `EsecutoreFetch` dedicato alle query
  live dei servizi, **istanza condivisa a livello di processo/container**.
- Policy **separata** da quella dello sweep; budget e rate-limit per dominio
  **configurabili**.
- La **cache servizi con TTL 24h** (Slice 2) è la **prima barriera**; il
  coordinatore è il limite operativo per ciò che la cache non copre.
- Il runtime **non** crea un nuovo budget per ogni messaggio: il factory riceve
  il coordinatore, non lo istanzia.
- **D-S5-1** (registry per-richiesta) resta: è il *registry* a essere
  per-richiesta, l'*esecutore* è condiviso di processo.

**Budget con finestra e reset (correzione review #3, D-S5-9).** `BudgetDominio`
oggi (catalog/fetch_policy.py) è un tetto **per-passata**: `consuma/disponibile/
rimanente`, **nessun reset**. Va benissimo per lo sweep (vive una passata), ma un
coordinatore di processo, esaurito il budget, resterebbe bloccato su
`budget_esaurito` **per sempre**. Serve una **finestra temporale con reset
per-dominio**:

- **finestra scorrevole configurabile** — env
  `TREASUREIQ_SERVICE_QUERY_BUDGET_WINDOW_S` (durata) e
  `TREASUREIQ_SERVICE_QUERY_BUDGET` (tetto per dominio nella finestra);
- il reset azzera il **solo conteggio del budget** per dominio quando la finestra
  è scaduta; **rate-limit (intervallo minimo) e backoff dei fallimenti restano
  intatti** — sono discipline diverse dal budget;
- realizzazione: un budget con finestra (variante dedicata o parametro opzionale
  `finestra_s` su `BudgetDominio`, `None` = comportamento per-passata attuale per
  non toccare la semantica dello sweep). La semantica sweep **non** cambia.

**Thread-safety / serializzazione per-dominio (correzione review #3, D-S5-10).**
La chat chiama il resolver via `asyncio.to_thread` → più richieste possono usare
lo **stesso** `EsecutoreFetch` in parallelo. `LimitatoreDominio`, `BudgetDominio`
e lo stato dei fallimenti **non** hanno lock oggi: sotto concorrenza il
rate-limit sarebbe solo dichiarato, non rispettato (due thread leggono
`disponibile()`/`prossimo_consentito()` prima che l'altro registri). Contratto:

- **lock globale** (di mappa) usato **solo** per creare/recuperare il lock del
  dominio (`dict[str, Lock]` guardata dal lock di mappa), poi **rilasciato
  subito**;
- **lock del singolo dominio** mantenuto per l'**intera** sequenza *decidi →
  sleep → fetch → registra*: lo slot non è mai deciso da un thread e consumato
  da un altro prima della registrazione (nessuna finestra di doppia decisione);
- domini **diversi** procedono in parallelo — il loro I/O e `sleep` non si
  serializzano a vicenda;
- il **lock globale non è mai tenuto** durante `sleep` o I/O (solo la lookup del
  lock di dominio), quindi non è un punto di serializzazione tra domini;
- (alternativa scartata per questa fase: prenotazione atomica dello slot prima di
  rilasciare il lock di dominio — più complessa, non necessaria ora);
- la protezione vive nel **coordinatore/variante locked**, non nel percorso
  sweep (single-thread), così non si destabilizza la Fase 2 esistente.

### 1.3 — platform_id (buco per il supports)

`WordPressAgidServiceConnector.supports()` richiede
`platform_id ∈ _PIATTAFORME_WP_AGID`. La fonte è **`mappa.piattaforma_id`**
(già popolato dalla sonda). Se `None` o famiglia diversa → `supports` False →
`registry.resolve` None → `resolve_service` None → **miss onesto** (nessun
connettore per quella piattaforma, non un errore).

### 1.4 — DataBatch da ServiceReference (buco per la risposta)

Builder puro che confeziona **l'envelope** in un `DataBatch`
`ORDINARY_DATA/CAPABILITY_SERVICES`, `access_mode=MEDIATED`,
`service_references=(resolved.reference,)`, `status=FULFILLED`, e **`Freshness`
dall'envelope** (mai da `discovered_at`):

```python
def service_reference_batch(resolved: ResolvedService, request: DataRequest) -> DataBatch: ...
```

- Prende `ResolvedService`, non la sola reference: `freshness =
  Freshness(status=FRESH|LIVE, retrieved_at=resolved.retrieved_at)` e
  `connector=resolved.connector`.
- Vale **sia per cache-hit sia per live**: **stessa forma**, freshness diversa
  (§5, test esplicito).
- `records` del batch = una riga **tipizzata** per opzione, con `service_id`
  esplicito della reference (**D-S5-3**): `{service_id, mode, url, source_url,
  requires_authentication, authentication}`.

### 1.5 — Forma risposta chat

`ServiceReference.options` porta 1..N opzioni tipizzate. Il ramo deve
presentarle senza appiattirle:

- **INFORMATION** → pagina ufficiale del servizio (sempre presente): la fonte
  citata (`DocumentAnswer`/`InfoAnswer.document`, come il ramo SP).
- **DOWNLOAD** → **il modulo** (PDF/DOC same-host): è il cuore di Ramo 3. Va
  reso come link scaricabile esplicito, distinto dalla pagina.
- **AUTHENTICATED_ONLINE** → procedura online: `spid_required=True`,
  motivazione dai metodi realmente presenti (riuso di `_spid_reason_da_metodi`,
  già scritto in increment 1), **mai** presentata come «modulo da scaricare»
  (D-R3-6). TIQ non accede né compila (D-R3-5).

Testo `reply` **fisso** (D-07): URL/ruolo/metodi/titoli solo nei campi
strutturati, mai interpolati nella prosa passata al verbalizzatore.

**Contratto UX (D-S5-4, approvato).** La modulistica è un caso del **rail
informativo**: si aggancia a `InfoAnswer`, già il contenitore usato dalla UI,
**non** a un campo `service` di primo livello in `ChatAnswer`.

```python
@dataclass
class ServiceLink:
    url: str
    label: str                      # etichetta fissa/derivata, non testo libero
    authentication: tuple[AuthenticationMethod, ...] = ()

@dataclass
class ServiceAnswer:
    service_id: str
    title: str
    information: ServiceLink | None
    downloads: list[ServiceLink]
    authenticated_online: list[ServiceLink]

# InfoAnswer:
    service: ServiceAnswer | None = None
```

La UI (`web/components/Chat.tsx`, dentro `InfoAnswer`) mostra distintamente:
«Informazioni sul servizio», «Scarica il modulo», «Procedura online»;
l'indicazione di autenticazione compare **solo** sull'opzione autenticata.

---

## §2 — Il ramo `_risposta_modulistica` riscritto

Sostituisce il corpo dell'increment-1 (la testa — precedenza comune profilo >
scelta > nominato, gate I6 «comune non noto → chiedi» — **resta identica**,
memoria «ricerca live cieca al comune di profilo»).

1. Risolvi `target_istat` (invariato).
2. `service_key = riconosci_service_key(message)`.
   - `None` (0 o ≥2 chiavi) → **chiedi** quale pratica, elenco chiuso del
     vocabolario; mai il vicino, mai indovinare (coerente con Slice 1).
3. `mappa = _da_cache(target_istat)`; se `None` o `piattaforma_id` assente →
   miss onesto (rimando URP).
4. `request = service_request(source_id=target_istat, service_key=service_key)`.
5. `resolved = await asyncio.to_thread(resolve_service_with_meta, request,
   mappa=mappa, registry=default_service_registry(service_query_fetch_coordinator),
   platform_id=mappa.piattaforma_id)`.
6. `resolved is None` → **miss onesto** (rimando URP), **niente fallback SP**.
7. `batch = service_reference_batch(resolved, request)`;
   `plan = build_query_plan(request)`; `selected = select_batch(plan, (batch,))`.
8. `info = InfoAnswer(..., service=<ServiceAnswer da resolved.reference.options>)`;
   `ChatAnswer(..., data_batches=[batch], query_plan=plan,
   selected_data_batch=selected, info=info, access_mode=MEDIATED)`.

> **Nota integrazione.** `service_query_fetch_coordinator` è un `EsecutoreFetch`
> **condiviso di processo** (§1.2), non creato per-messaggio né preso dalla
> sessione. Da definire in fase di wiring dove il modulo lo costruisce una volta
> (policy servizi dedicata, budget/rate-limit configurabili) e come la chat vi
> accede.

Sul **vecchio ramo SP**: vedi D-S5-2.

---

## §3 — Decisioni (review #1: tutte confermate)

| ID | Decisione | Esito |
|----|-----------|-------|
| **D-S5-1** | Lifecycle del registry | **Approvato**: per-richiesta. |
| **D-S5-2** | Sorte del ramo SP-pointer (increment 1) | **Approvato**: dormiente, **nessun fallback**. Non cablato per MODULISTICA; conservato per un futuro topic `SERVICE_PORTAL`; `_spid_reason_da_metodi` resta riusato per AUTHENTICATED_ONLINE. |
| **D-S5-3** | Forma dei `records` del DataBatch | **Approvato**: una riga per opzione, **schema tipizzato** con `service_id` esplicito — `{service_id, mode, url, source_url, requires_authentication, authentication}`. |
| **D-S5-4** | Superficie risposta multi-opzione | **Approvato**: `InfoAnswer.service: ServiceAnswer \| None` (rail informativo), **non** un campo di primo livello in `ChatAnswer`. Contratto in §1.4. |
| **D-S5-5** | Envelope di risoluzione (review #1.1) | **Approvato**: `ResolvedService{reference, retrieved_at, from_cache, connector}` + `resolve_service_with_meta`. Freshness da envelope, mai da `discovered_at`. §1.0. |
| **D-S5-6** | Fetch guardato nel live (review #2) | **Approvato**: runtime usa `EsecutoreServiceFetcher` su `EsecutoreFetch`/`fetch_guardato`; niente `httpx` grezzo nel path chat. §1.1. |
| **D-S5-7** | Cache porta il connettore (review #2, blocking) | **Nuovo**: `CachedService += connector: ConnectorRef`, `SERVICE_CACHE_SCHEMA_VERSION = 2` (v1 → miss/rigenera), `salva/carica` trasportano il connettore. No derivazione da `provider_platform`. §1.0. |
| **D-S5-8** | Coordinatore fetch dei servizi (review #2) | **Nuovo**: `service_query_fetch_coordinator`, `EsecutoreFetch` condiviso di processo, policy separata dallo sweep, budget/rate-limit configurabili, cache 24h come prima barriera; non per-messaggio, non legato alla sessione. §1.2. |
| **D-S5-9** | Budget con finestra e reset (review #3, blocking) | **Nuovo**: coordinatore di processo → budget **per-passata senza reset blocca per sempre**. Finestra scorrevole per-dominio, env `TREASUREIQ_SERVICE_QUERY_BUDGET_WINDOW_S` + `TREASUREIQ_SERVICE_QUERY_BUDGET`; reset azzera **solo** il budget, rate-limit/backoff intatti; semantica sweep (`finestra_s=None`) invariata. §1.2. |
| **D-S5-10** | Thread-safety del coordinatore (review #3/#4, blocking) | **Nuovo**: chat via `asyncio.to_thread` → più richieste sullo stesso `EsecutoreFetch`. **Lock globale** solo per lookup del lock di dominio (rilasciato subito); **lock di dominio tenuto per l'intera** *decidi→sleep→fetch→registra* (nessuna doppia decisione dello slot); domini diversi in parallelo; lock globale mai tenuto durante sleep/I/O. Solo nel coordinatore, non nel path sweep. §1.2. |

---

## §4 — Contratti e invarianti (ereditati, ribaditi)

- **I6:** comune non noto → si chiede, mai un default.
- **No URL inventati:** ogni URL viene da `ServiceReference` (host già validato
  in Slice 4), mai costruito da testo libero.
- **No auto-autenticazione:** AUTHENTICATED_ONLINE è un puntatore; TIQ non
  accede né compila (D-R3-5).
- **Deterministico:** nessun modello nel percorso dati; il testo `reply` è
  fisso, i dati nei campi strutturati (D-07).
- **`service_id`** = `{source_id}:wp:{wordpress_id}` (Slice 4), mai dal titolo.
- **Miss onesto, non SP fallback:** il vincolo centrale di questa slice.

---

## §5 — Test (golden, senza rete)

- **Registry factory:** contiene il connettore WP/AgID; `resolve` seleziona su
  `supports` (platform_id giusto/sbagliato).
- **Envelope / freshness (D-S5-5, review #1.1):**
  - **cache hit** → `ResolvedService(from_cache=True)`, `Freshness.FRESH`,
    `retrieved_at == CachedService.retrieved_at`, `connector` = quello in cache.
  - **live** → `from_cache=False`, `Freshness.LIVE`, `retrieved_at` = timestamp
    chiamata, `connector` = quello del `ConnectorResult`.
  - **stessa forma, freshness diversa:** cache hit e live producono lo **stesso**
    `DataBatch`/`ServiceAnswer` a meno del blocco freshness.
  - `reference.discovered_at` **non** compare mai nella `Freshness`.
- **Cache hit = zero rete + provenienza preservata (D-S5-5/#2):** una seconda
  richiesta identica **non** apre alcun fetch (né esecutore né httpx) **e**
  riporta il `connector` corretto nel batch.
- **Fetch guardato (D-S5-6, review #2):** il connettore del runtime, su
  cache-miss, passa dall'`EsecutoreServiceFetcher`; con un esecutore stub che
  nega (`consentito=False`) il connettore ritorna vuoto (miss onesto), **senza
  retry autonomo**, a prova che il path live rispetta la politica e non bypassa
  il limite.
- **Adapter `EsecutoreServiceFetcher` (D-S5-6):** `host_atteso` = host ufficiale;
  `max_bytes` distinti REST/HTML; decodifica UTF-8; JSON malformato o `fetched
  is None` → miss; nessun controllo host/redirect duplicato (delegato a
  `fetch_guardato`).
- **Cache schema v2 (D-S5-7):** una `CachedService` v1 (senza `connector`) →
  version-mismatch → **miss**, rigenerata; una v2 → cache hit con `connector`
  corretto nel `DataBatch`.
- **Budget con finestra + reset (D-S5-9):** consumato il budget del dominio →
  `consentito=False` (miss onesto, nessun retry); avanzata la finestra (clock
  iniettabile, non wall-clock reale nel test) → il budget del **solo** dominio
  torna disponibile; rate-limit e backoff **non** vengono azzerati dal reset.
- **Concorrenza / rate-limit (D-S5-10):** N thread sullo stesso dominio via
  `EsecutoreServiceFetcher` → le decisioni sono **serializzate**, l'intervallo
  minimo è realmente rispettato (nessuna coppia più vicina del limite) e il
  budget **non** viene sovra-consumato da race; due domini distinti procedono in
  parallelo (nessuna serializzazione incrociata).
- **Ramo MODULISTICA (stub-fetcher):**
  - service_key riconosciuta + connettore risolve → ChatAnswer con `data_batches`
    non vuoto, `access_mode=MEDIATED`, `InfoAnswer.service` con `downloads` non
    vuoto quando c'è un PDF same-host.
  - service_key `None` (0/≥2) → risposta di chiarimento, nessuna chiamata al
    fetcher.
  - `piattaforma_id` assente/altra famiglia → miss onesto, **nessun** puntatore
    SP nella risposta.
  - connettore miss (0/≥2 confermati) → miss onesto (URP), niente fallback SP.
  - comune non noto → chiede il comune (I6), nessun fetch.

---

## §6 — Fuori scope (slice successive)

- Slice 6: merge dell'entrypoint SP dall'inventario nella reference (unire
  puntatore-porta e modulo-servizio).
- Slice 7: oracolo Rust.
- Connettori altre famiglie (Municipium, URBI, jcitygov, …): stesso seam,
  stesso factory.
- Rigenerazione oracolo scorer/rust per far riconoscere MODULISTICA ai backend
  non-`model` (follow-up già noto da increment 1).
