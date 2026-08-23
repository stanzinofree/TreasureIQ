# Ramo 3 — Slice 3: contratto + connettore servizi (resolver)

> Stato: **proposta di contratto** (design), 2026-08-23. Nessuna
> implementazione: propone la Slice 3 (piano §6.3) e i golden test. Attende
> review prima di scrivere codice, come Slice 1 e 2.

## 0. Cosa risolve questa slice

Slice 1 ha dato l'identità (`ServiceKey`) e la richiesta (`service_request`).
Slice 2 ha dato lo **store** (`service_cache.carica/salva`). Manca chi, dato un
`ServiceKey`, **produce** un `ServiceReference` e **popola** la cache: il
connettore servizi + il resolver che orchestra cache↔connettore.

Slice 3 introduce **il seam e l'orchestrazione**, non un connettore reale di
piattaforma (Slice 4) né il wiring chat/DataBatch (Slice 5). Nessuna rete in
questa slice: il connettore reale che interroga il portale arriva in Slice 4;
qui il resolver è testato con uno stub.

## 1. Distinzione netta dal `ServicePortalConnettore`

I due connettori **non** vanno confusi (è il rischio di questa slice):

| | `ServicePortalConnettore` (esiste) | `ServiceConnector` servizi (Slice 3) |
|---|---|---|
| Superficie | `Surface.SERVICE_PORTAL` | `Surface.ORDINARY_DATA` |
| Capability | `authenticated_service` | `CAPABILITY_SERVICES` ("services") |
| Chiave richiesta | `selection["service_id"]` (URL entrypoint) | `selection["service_key"]` (`ServiceKey`) |
| Cosa risolve | un entrypoint SP già scoperto → **pointer** onesto | un servizio → **`ServiceReference`** normalizzato |
| AccessMode | `INDIRECT` (TIQ non entra) | `DIRECT`/`MEDIATED` sui canali pubblici del servizio |
| Output | `ConnectorResult.records` (pointer) | `ConnectorResult.service_references` (servizio) |
| Popola cache servizi | no | **sì** (via resolver) |

L'entrypoint autenticato del portale resta un **sotto-caso** — una
`ServiceAccessOption` mode `AUTHENTICATED_ONLINE` **dentro** un
`ServiceReference` — non l'unità di questo connettore (D-R3-3). Il merge
dell'opzione SP dentro il ServiceReference è Slice 6, non qui.

`supports()` del connettore servizi è vero **solo** per
`ORDINARY_DATA + CAPABILITY_SERVICES`: una richiesta `SERVICE_PORTAL` non viene
mai raccolta da questo connettore, e viceversa. È la barriera di non-confusione.

## 2. Contratto: riuso del seam esistente

`catalog/connectors.py` ha già la forma giusta:

- `SourceConnector` (Protocol): `supports(request, *, platform_id)` +
  `retrieve(request, *, mappa, esito) -> ConnectorResult`;
- `ConnectorResult` porta **già** un campo `service_references:
  tuple[ServiceReference, ...]`.

Proposta: **riusare** `SourceConnector`/`ConnectorResult`, non introdurre un
protocollo o un result paralleli. Il connettore servizi è un `SourceConnector`
che, su una richiesta servizi, popola `service_references` invece di `records`.
Un `ServiceConnector` a parte sarebbe una seconda gerarchia per lo stesso seam.

Il `ServiceReference` è già `_StrictModel` con `options` (min_length=1) e URL
ufficiali: **la provenienza è imposta dal tipo** (D-R3-7). Il connettore reale
(Slice 4) dovrà: non autenticarsi; non indovinare URL; non restituire il primo
candidato SP come servizio; non emettere un `ServiceReference` senza evidenza.
Questi sono vincoli del connettore (Slice 4); il contratto li enuncia, il
resolver impone ciò che può a valle (§3).

## 3. Resolver (`catalog/service_resolver.py`, nuovo)

L'orchestrazione cache↔connettore, separata dallo store (Slice 2 = solo store).

```python
def resolve_service(
    request: DataRequest,
    *,
    mappa: MappaConnettore,
    esito: EsitoConnettore | None,
    registry: ConnectorRegistry | None = None,   # vuoto in Slice 3
    platform_id: str = "",
) -> ServiceReference | None:
    """Cache-first: hit fresco -> ref (no rete); miss/stale -> connettore ->
    write-through in cache -> ref; nessun connettore/miss -> None.

    Nessuna scelta linguistica qui: il ServiceKey arriva già riconosciuto nel
    DataRequest (Slice 1). Nessun profilo, tema o ranking (D-07)."""
```

Passi deterministici:

1. **Guardia superficie+capability (PRIMA della cache)**: se `request.surface is
   not Surface.ORDINARY_DATA` → `ValueError`; se `request.capability !=
   CAPABILITY_SERVICES` → `ValueError`. Una richiesta incoerente (es.
   `SERVICE_PORTAL` + `service_key`) non deve trovare una voce in cache e
   bypassare `supports()`: si rifiuta subito, prima di `carica` (correzione #1).
2. **Estrai `service_key`** da `request.selection["service_key"]`; se assente o
   fuori vocabolario → `None` (nessun fallback al vicino, come il recognizer).
3. **Cache-first**: `service_cache.carica(source_id, service_key,
   policy=request.freshness)`. Hit → ritorna il `ServiceReference`, **nessuna
   rete**, connettore mai chiamato.
4. **Miss/stale** → `registry.resolve(request=…, platform_id=…)`; se `None` →
   `None` (nessuna scrittura).
5. `retrieve(request, mappa=…, esito=…)`. **Write-through** solo se:
   - `result.status is DataStatus.FULFILLED`; **e**
   - `len(result.service_references) == 1` (esattamente una: 0 o >1 richiedono
     una decisione del livello superiore, mai una scelta implicita — correzione
     #2); **e**
   - `result.source_id == request.source_id` **e** `result.request_id ==
     request.request_id` (identità del risultato — correzione #3: un risultato
     incoerente non finisce nella cache del comune giusto).
   Allora `service_cache.salva(...)` con l'unica referenza, poi ritorna il ref.
   Ogni altro caso → `None`, **nessuna scrittura**.

Scelte di disegno:

- **Write-through nel resolver**, non nel connettore: il connettore resta puro
  (nessun side-effect su disco), coerente con "i connettori sono sorgenti dati
  stupide, non decidono". Il resolver è l'unico che scrive la cache servizi.
- **`source_id` coerente**: `salva` usa `request.source_id`, la stessa chiave di
  `carica`; l'integrità nome-file↔interno è già garantita dallo store (Slice 2).
- **Riuso di `ConnectorRegistry`** (correzione #4): niente tupla o dispatch
  paralleli. `registry=None` → istanza **vuota** creata al volo (nessun default
  mutabile condiviso); Slice 4 inietta un registry popolato col pilota. Il
  resolver non conosce le piattaforme: le riceve.

### Cosa il resolver NON fa in Slice 3

- Nessun connettore reale di piattaforma (Slice 4): il registry è vuoto, i test
  usano uno stub.
- Nessun DataBatch, `QueryPlan`, `selected_data_batch` (Slice 5).
- Nessun merge dell'opzione SP nel ServiceReference (Slice 6).
- Nessun caller di produzione: `resolve_service` esiste ma la chat non lo invoca
  ancora. Nessuna rete.

## 4. Golden test (Slice 3)

Unit puri, `LIVE_DIR`→`tmp_path`, connettore **stub** (registra le chiamate).
File `api/tests/test_service_resolver.py`.

| # | scenario | atteso |
|---|---|---|
| 1 | cache-hit fresco | ritorna il ref; **connettore mai chiamato** |
| 2 | cache-miss, connettore FULFILLED con ref | ritorna il ref **e** cache popolata (carica successiva = hit) |
| 3 | cache-stale | connettore chiamato (re-resolve), cache riscritta |
| 4 | connettore NOT_FOUND | `None`, **nessuna scrittura** in cache |
| 5 | connettore FULFILLED ma `service_references` vuoto | `None`, nessuna scrittura (difensivo) |
| 5b | connettore FULFILLED con **>1** `service_references` | `None`, nessuna scrittura (correzione #2) |
| 6 | registry vuoto (nessun connettore) | `None`, nessuna scrittura |
| 7 | `selection` senza `service_key` / valore fuori vocabolario | `None` |
| 8 | `supports()` vero solo per ORDINARY_DATA+CAPABILITY_SERVICES; falso per SERVICE_PORTAL | barriera di non-confusione col SP |
| 9 | write-through preserva altre `service_key` già in cache | no-clobber (delega a Slice 2) |
| 10 | `request.surface` = SERVICE_PORTAL | `ValueError` **prima** della cache (correzione #1) |
| 11 | `request.capability` ≠ CAPABILITY_SERVICES | `ValueError` prima della cache (correzione #1) |
| 12 | risultato con `source_id`/`request_id` incoerente | `None`, nessuna scrittura (correzione #3) |

### Invarianti

- **Cache-first, no-rete su hit**: su hit fresco il connettore stub non riceve
  nessuna chiamata (asserito).
- **Write-only-on-success**: la cache è scritta **solo** su FULFILLED-con-ref;
  miss non inquina la cache.
- **Non-confusione**: una richiesta `SERVICE_PORTAL` non è mai servita dal
  connettore servizi; una richiesta servizi non è mai servita dal SP.
- **Presentation-free**: il resolver ritorna un `ServiceReference` nudo, nessun
  profilo/tema/ranking (D-07).

## 5. Decisioni da confermare in review

1. **Riuso di `SourceConnector`/`ConnectorResult.service_references`** vs un
   protocollo `ServiceConnector` + result dedicati (raccomandato il riuso: il
   campo esiste già, un solo seam).
2. **Resolver in modulo nuovo** `catalog/service_resolver.py` vs dentro
   `service_cache` (raccomandato separato: store ≠ orchestrazione).
3. **Write-through nel resolver** vs nel connettore (raccomandato il resolver:
   connettore puro, un solo scrittore della cache).
4. **Riuso di `ConnectorRegistry`** (correzione #4), istanza vuota di default in
   Slice 3, popolata col pilota in Slice 4 — un solo meccanismo di dispatch.
5. **Miss policy**: NOT_FOUND, FULFILLED-vuoto, FULFILLED->1 e identità
   incoerente → tutti `None` senza scrivere (correzioni #2/#3: mai cache di un
   non-risultato o di una scelta implicita).
6. **Guardia surface+capability prima della cache** (correzione #1): richiesta
   incoerente rifiutata con `ValueError`, mai servita dalla cache.

## 6. Fuori scope (Slice 3)

Connettore pilota per-piattaforma (Slice 4, WordPress/AgID: PDF/DOC + servizio
informativo dall'inventario), DataBatch + dispatcher chat (Slice 5), merge
opzione SP (Slice 6), oracolo Rust (Slice 7). Flusso SP esistente invariato.
