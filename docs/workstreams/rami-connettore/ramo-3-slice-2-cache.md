# Ramo 3 — Slice 2: cache canonica dei servizi risolti

> Stato: **implementata** (2026-08-23) dopo review con 3 correzioni. Design
> approvato in tutta la struttura; le correzioni sotto sono recepite nel codice
> e nei test.

## Correzioni di review recepite

1. **Versione schema — rifiutare anche il futuro.** `carica` tratta come miss
   ogni voce con `schema_version != SERVICE_CACHE_SCHEMA_VERSION` (non solo
   `<`): una cache con versione futura non è leggibile in sicurezza dal codice
   corrente e deve diventare miss.
2. **Freshness condivisa, non dalla flotta.** La logica di età vive in
   `catalog/freshness.py` (nuovo), usata da `flotta/_projection.py`,
   `catalog/notices.py` e `catalog/service_cache.py` — una sola policy
   temporale, nessun accoppiamento agli uffici.
3. **Path-safety su `source_id`.** `_percorso` non interpola una stringa grezza
   nel filesystem: `_componente_sicuro` valida il componente (`[A-Za-z0-9_-]+`,
   fullmatch) e **rifiuta** separatori di path e `..` (traversal). `source_id`
   invalido → `ValueError`.

## 0. Cosa risolve questa slice

Slice 1 ha dato l'identità del servizio (`ServiceKey`) e il builder di
richiesta (`service_request`). Manca il posto dove un `ServiceReference`
**risolto** vive tra una domanda e l'altra: un cache-hit fresco deve rispondere
**senza rete**, un miss/stale deve poter attivare il connettore live (Slice 3+).

Slice 2 introduce **solo lo store**: modello di voce, chiave, freshness,
scrittura atomica, versione di schema, API di lettura/scrittura + golden test.
Nessun connettore (Slice 3), nessun dispatcher chat (Slice 5). Il flusso SP
resta invariato.

## 1. I quattro store restano distinti

La regola del piano: la cache dei servizi risolti è **una quarta cosa**, da non
confondere con gli store esistenti.

| Store | Cosa contiene | Chi scrive | Superficie / path |
|---|---|---|---|
| `SourceInventory.service_portals` | **entrypoint** SP scoperti (URL portale, ruolo, auth) | sweep discovery | `LIVE_DIR/inventario/{istat}.json` |
| **cache servizi risolti** (Slice 2) | **`ServiceReference`** risolti: opzioni INFORMATION/DOWNLOAD/AUTHENTICATED_ONLINE per un servizio | connettore servizi (Slice 3) | `LIVE_DIR/servizi-risolti/{istat}.json` (nuovo) |
| dati curati | seed editoriale a mano | umano | `data/seed/…` |
| websearch-cache | hint di ricerca (title+url) | ricerca live | `ingest/websearch` cache |

Confini duri:

- La cache servizi **non** è l'inventario SP: l'entrypoint autenticato è un
  *sotto-caso* (una `ServiceAccessOption` mode `AUTHENTICATED_ONLINE`) di un
  `ServiceReference`, non l'unità della cache (D-R3-3).
- La cache servizi **non** è seed curato: è runtime, riscrivibile dallo sweep,
  mai commessa a mano.
- La cache servizi **non** è websearch-cache: contiene servizi ufficiali
  normalizzati con provenienza, non hit di ricerca da confermare.

## 2. Contratto della voce di cache

`ServiceReference` è già `_StrictModel`, presentation-free, e porta già
`service_id`, `title`, `source_url`, `options[]` (con `url`/`source_url`
ufficiali), `provider_platform`, `discovered_from`, `discovered_at`. Gli manca
solo la **contabilità di cache**: quando è stato *riletto* (distinto da quando
è stato *scoperto*) e con quale versione di schema.

Proposta — un wrapper, non toccare `ServiceReference`:

```python
# catalog/service_contracts.py  (accanto a ServiceReference)

SERVICE_CACHE_SCHEMA_VERSION = 1   # alza quando cambia COSA normalizziamo

class CachedService(_StrictModel):
    """Una voce della cache servizi risolti, indicizzata da service_key.

    ``reference`` è il servizio normalizzato; ``retrieved_at`` è il momento
    della RISOLUZIONE (quando il connettore l'ha prodotto), distinto da
    ``reference.discovered_at`` (quando l'entrypoint/servizio fu SCOPERTO).
    """
    service_key: ServiceKey
    reference: ServiceReference
    retrieved_at: datetime
    schema_version: int = Field(default=SERVICE_CACHE_SCHEMA_VERSION, ge=0)

class ServiceCacheFile(_StrictModel):
    """Il file per-comune: più service_key coesistono nella stessa fonte."""
    source_id: str = Field(min_length=1)
    entries: tuple[CachedService, ...] = ()
    updated_at: datetime
```

- **Chiave**: `(source_id, service_key)`. `source_id` è il file; `service_key`
  indicizza la voce dentro `entries`. Un secondo servizio per lo stesso comune
  **non** sovrascrive il primo (§3, test).
- **Nessun dato presentazionale**: la voce è solo `ServiceReference` +
  contabilità. Nessun `reply`, tema, ranking profilo, effort — coerente con
  D-07 e con `_projection` (i record sono presentation-free).
- **Provenienza**: già dentro `ServiceReference` (`source_url` + ogni
  `option.url`/`option.source_url` ufficiali). La cache non aggiunge URL.

## 3. API dello store (`catalog/service_cache.py`, nuovo)

Gemello di `mappa_connettore._da_cache`/`_in_cache` e di
`service_portal_connector._inventory_from_live` — stesso mount `LIVE_DIR`,
stessa disciplina (corrotto = miss, mount assente = degrada senza crash).

```python
def _percorso(source_id: str) -> Path:
    return LIVE_DIR / "servizi-risolti" / f"{source_id}.json"

def carica(
    source_id: str, service_key: ServiceKey, *, policy: FreshnessPolicy
) -> ServiceReference | None:
    """Cache-hit FRESCO -> ServiceReference; miss/stale/versione-vecchia -> None.

    None è il segnale con cui il dispatcher (Slice 5) attiva il connettore
    live. Nessuna rete qui: sola lettura da disco.
    """

def salva(source_id: str, service_key: ServiceKey, reference: ServiceReference) -> None:
    """Scrittura ATOMICA (.tmp + replace) della voce, preservando le altre
    service_key già presenti nel file. Mount assente -> warn, non crash."""
```

### Freshness (gate del piano §6)

`carica` applica `policy.max_age_seconds` su `retrieved_at` con la policy
**condivisa** `catalog/freshness.py` (`freshness_da_datetime`), la stessa usata
da `_projection` e `notices` — una sola logica di età, nessun accoppiamento agli
uffici:

- età ≤ `max_age_seconds` **e** `schema_version == SERVICE_CACHE_SCHEMA_VERSION`
  → **hit fresco**, ritorna `ServiceReference` (nessuna rete);
- età > soglia → **stale** → `None`;
- `schema_version != corrente` (vecchia **o futura**) → `None` (memoria
  `predicato-gating-cieco-a-nuovo-campo`: una voce con schema diverso non è
  servibile as-is);
- file assente / corrotto / chiave assente → `None`;
- `source_id` invalido (traversal/separatori) → `ValueError` (non un miss: è un
  errore del chiamante, non un dato mancante).

La `policy` è quella del `service_request` (default `max_age_seconds=86400`),
così request e cache condividono la stessa soglia senza ridefinirla.

### Cosa lo store NON fa in Slice 2

- Nessun caller: `carica`/`salva` esistono ma il connettore che riempie
  (Slice 3) e il dispatcher che legge (Slice 5) non sono in questa slice.
- Nessuna rete, nessun fetch, nessun modello.

## 4. Test golden (Slice 2)

Unit puri, `tmp_path` come `LIVE_DIR` (monkeypatch), nessuna rete. File
`api/tests/test_service_cache.py`.

| # | scenario | atteso |
|---|---|---|
| 1 | `salva` poi `carica` fresco | ritorna lo stesso `ServiceReference` |
| 2 | `carica` su fonte/chiave assente | `None` |
| 3 | voce con `retrieved_at` oltre `max_age_seconds` | `None` (stale → live) |
| 4 | voce con `schema_version` < corrente | `None` (re-read) |
| 5 | file corrotto (JSON invalido) | `None`, nessun crash |
| 6 | due `service_key` nella stessa fonte; `salva` della seconda | la prima resta leggibile (no clobber) |
| 7 | stessa `service_key`, due `source_id` diversi | voci isolate |
| 8 | mount `LIVE_DIR` non scrivibile | `salva` warn, nessuna eccezione |
| 9 | dopo `salva`, nessun file `.tmp` residuo | scrittura atomica completata |
| 10 | voce con `schema_version` **futura** | `None` (non leggibile in sicurezza) |
| 11 | `source_id` invalido / path traversal | `ValueError` (rifiuto, non miss) |
| 12 | `retrieved_at` naïve vs aware | normalizzati uguale, entrambi freschi |
| 13 | `source_id` interno ≠ nome-file | `None` (incoerente, no cross-comune) |

### Invarianti

- **No-network**: `carica` non fa I/O di rete (solo `Path.read_text`).
- **Presentation-free**: `CachedService`/`ServiceCacheFile` sono `_StrictModel`
  (`extra="forbid"`) — nessun campo presentazionale può entrare.
- **Round-trip fedele**: `carica(salva(ref)) == ref` per un `ServiceReference`
  con opzioni miste (INFORMATION + DOWNLOAD + AUTHENTICATED_ONLINE).

## 5. Decisioni da confermare in review

1. **Layout file**: per-comune con mappa `service_key → voce` (raccomandato,
   simmetrico a `inventario`/`mappa-connettore`) vs un file per
   `(source_id, service_key)`.
2. **Namespace path**: `LIVE_DIR/servizi-risolti/` (raccomandato, esplicito e
   senza collisioni con `inventario`/`mappa-connettore`).
3. **Wrapper `CachedService`** vs estendere `ServiceReference` con
   `retrieved_at`/`schema_version` (raccomandato il wrapper: non contamina il
   contratto di discovery).
4. **Freshness condivisa** — logica età estratta in `catalog/freshness.py` e
   usata da `_projection`, `notices` e `service_cache` (correzione #2: NON si
   importa dalla flotta, accoppiamento sbagliato).

## 6. Fuori scope (Slice 2)

Connettore servizi (Slice 3), pilota per-piattaforma (Slice 4), DataBatch +
dispatcher chat (Slice 5), aggancio SP come opzione (Slice 6), oracolo Rust
(Slice 7). Flusso SP esistente invariato.
