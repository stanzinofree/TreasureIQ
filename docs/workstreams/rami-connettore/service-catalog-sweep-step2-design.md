# service_catalog — Step 2 (esecuzione reale) · design

Design dell'esecuzione **reale** (con rete) dello sweep `service_catalog`, da
approvare **prima** di scrivere codice. Il run reale resta sospeso: questo
documento fissa i vincoli, poi si implementa con test net-free, poi — solo dopo
il gate dei test — si lancia il campione con un comando esplicito.

Precede: [service-catalog-sweep-piano.md](service-catalog-sweep-piano.md) (Step 1,
spedito) e [service-catalog-campione-20.md](service-catalog-campione-20.md)
(campione pinnato).

## Scopo e non-scopi

- **Scopo**: risolvere `ServiceKey → ServiceReference` per i **20 ISTAT
  pinnati**, scrivendo il catalogo (`servizi-risolti/`) solo sui successi, con
  metriche per-run, budget per dominio, resume sicuro.
- **Non-scopo**: fan-out nazionale (gate successivo); nuove famiglie di
  connettore (solo WP/AgID + ComWeb); qualunque scrittura su `storico.db`;
  scelta di lingua/profilo/tema (il resolver non decide, instrada).

## Contratti riusati (non reinventare)

La maggior parte dei nove vincoli è **già** soddisfatta dal codice esistente.
Step 2 è orchestrazione, non nuovi contratti dati.

| Meccanismo esistente | File | Cosa garantisce già |
|---|---|---|
| `resolve_service_with_meta` | `catalog/service_resolver.py:50` | cache-first; scrive **solo** su `FULFILLED` + esattamente 1 reference + match source/request; `None` su miss/empty/multi/connettore-assente → **nessuna cache negativa** |
| `service_cache.salva` | `catalog/service_cache.py:105` | upsert atomico `.tmp`+`replace()`, **merge per-key** (preserva le altre chiavi); mount assente → warning, non crash |
| `service_cache.carica` | `catalog/service_cache.py:78` | hit solo se fresco + schema-version corrente; è lo **stato di resume** |
| `_nuovo_esecutore` + `PoliticaFetch` | `sweep_worker.py:52` | executor **per-lotto** con `intervallo_minimo_s` / `massimo_per_dominio` / backoff — separato dal coordinatore di processo della chat |
| `default_service_registry(esecutore)` | `catalog/service_registry.py:49` | registry WP/AgID + ComWeb sopra l'executor iniettato (i test passano stub → niente rete) |
| `mappa_connettore(istat)` | `mappa_connettore.py` | cache-first + probe live: procura la mappa ai 6 comweb che non ce l'hanno |

## I nove vincoli → dove vivono

1. **Solo i 20 ISTAT pinnati** → gate nuovo in `_run_service_catalog` (reale):
   il lotto è l'**intersezione** con la lista pinnata; qualsiasi comune fuori
   lista è rifiutato. La lista vive in un'unica costante (letta dal manifest o
   inlined con riferimento al manifest), non ripetuta.
2. **Executor separato da chat** → `_nuovo_esecutore(config)` (istanza per-lotto),
   **mai** `service_query_fetch_coordinator()` (quello è il coordinatore di
   processo della chat).
3. **Budget/rate-limit/backoff per dominio** → `PoliticaFetch` dentro
   `_nuovo_esecutore`; molti comuni condividono host SaaS → il budget per-dominio
   è già l'argine corretto.
4. **Una risoluzione per ogni ServiceKey** → loop `for chiave in ServiceKey`
   (le 5), una `resolve_service_with_meta` per chiave.
5. **Cache solo su FULFILLED con reference valida** → garantito da
   `resolve_service_with_meta` (Guard 2/3): scrive solo con status FULFILLED,
   1 reference, source/request coerenti.
6. **Miss e vuoti senza cache negativa** → `resolve_*` ritorna `None` e **non
   scrive** su miss/empty/multi. Nessun record "negativo" viene mai salvato.
7. **Metriche per-run atomiche dopo ogni comune** → file dedicato (sotto),
   `.tmp`+`replace()` dopo **ogni comune completato**, non a fine lotto.
8. **Resume sicuro, nessuna scrittura su storico.db** → la cache servizi È lo
   stato: re-run dello stesso comando → chiavi già risolte tornano `from_cache`
   (0 rete). Nessun ramo tocca `storico.db`.
9. **Exit code distinti** → vedi tabella exit code.

## Flusso `_run_service_catalog` (ramo reale)

Oggi il ramo reale ritorna `EXIT_SERVICE_REAL_NOT_READY` (3). Step 2 lo
sostituisce con:

1. **Gate ingresso**: se non `--execute` (conferma esplicita) → ritorna 3
   (invariato: la rete non parte per errore). Se il lotto non è ⊆ dei 20 ISTAT
   pinnati → rifiuto esplicito (niente fan-out silenzioso).
2. **Setup**: `esecutore = _nuovo_esecutore(config)`; `registry =
   default_service_registry(esecutore)`. Un executor, un registry, per tutto il
   lotto (il budget per-dominio ricorda gli host tra comuni).
3. **Per ogni comune** (ordine ISTAT, deterministico):
   a. `mappa = mappa_connettore(istat)` (cache-first + probe). `None` → riga
      `senza_mappa`, prosegui.
   b. `platform_id = leggi_registro(istat).piattaforma`.
   c. per ognuna delle 5 `ServiceKey`: `req = service_request(source_id=istat,
      service_key=k, namespace="service-catalog")`;
      `res = resolve_service_with_meta(req, mappa=mappa, registry=registry,
      platform_id=platform_id)`. Classifica: `from_cache` (res.from_cache) /
      `risolto_live` (res non-None, non cache) / `miss` (res None).
   d. **metriche atomiche**: aggiorna il file per-run dopo il comune.
   e. **errori per-comune**: eccezione durante la mappa/risoluzione di *un*
      comune → conta `errore`, non abortire il lotto (isolamento per-comune, come
      il resto dello sweep).
4. **Budget**: se l'executor segnala budget-per-dominio esaurito (finestra
   satura) → **fermare** il lotto, salvare le metriche, ritornare exit 5. Il
   seam esatto di rilevazione (eccezione dedicata vs stato dell'executor) è
   l'unico punto da confermare in implementazione — `PoliticaFetch` è la fonte.

### Exit code

| Code | Nome | Significato |
|---:|---|---|
| 0 | OK | lotto completo, nessun errore per-comune, budget non bloccante |
| 3 | `EXIT_SERVICE_REAL_NOT_READY` | invocato reale senza `--execute`: la rete non parte |
| 4 | `EXIT_SERVICE_PARTIAL_ERRORS` | lotto finito ma ≥1 comune ha sollevato eccezione |
| 5 | `EXIT_SERVICE_BUDGET_BLOCKED` | fermato dal budget per-dominio prima di completare |

Miss ed EMPTY **non** sono errori: sono esiti onesti, exit 0.

## Metriche per-run

- **Path**: `LIVE_DIR/service-catalog-metriche/ultimo.json` — separato da
  `storico.db` e dalla cache `servizi-risolti/`. Scrittura atomica
  `.tmp`+`replace()` dopo ogni comune.
- **Schema** (bozza): `avviato_il`, `comuni_totali`, `comuni_completati`,
  conteggi per esito (`from_cache`, `risolti_live`, `miss`, `senza_mappa`,
  `errore`), righe per-comune (istat, piattaforma, per-key: esito), riepilogo
  per-piattaforma, stato budget (`bloccato: bool`, domini toccati).
- **Read-time**: le metriche descrivono un run; non alimentano l'analytics né la
  chat. Sola diagnostica del catalogo.

## Resume e idempotenza

Nessuno stato di ripresa proprietario. La cache servizi è lo stato: interruzione
a metà lotto → i comuni fatti restano in `servizi-risolti/`; il re-run dello
stesso comando li ritrova `from_cache` (0 fetch) e prosegue dai mancanti. Le
metriche si rigenerano dal re-run. Nessun ramo scrive `storico.db`.

## Comando esplicito

Non riusa il loop generico dello sweep. Invocazione dedicata e conferma
esplicita, es.:

```
TREASUREIQ_SWEEP_MODE=service_catalog \
  python -m treasureiq.sweep_worker --execute --once
```

`--execute` è il flag di conferma della rete (assente → exit 3). Il lotto è
ristretto ai 20 pinnati. Nessun `--dry-run` qui: il dry-run resta il ramo di
censimento.

## Mappa per i 6 comweb — probe live **guardata** (decisione)

`resolve_service_with_meta` esige un `MappaConnettore` il cui `codice_istat`
combacia, e `retrieve` legge sito/piattaforma dalla mappa. 498/500 comweb non
hanno mappa su disco. Serve una mappa **reale**, non sintetica → si usa
`mappa_connettore(istat)` cache-first + **probe live**.

**Problema.** Oggi `mappa_connettore()` → `_sonda_mappa()` guida `_Sonda`
(httpx grezzo) direttamente: una probe così **bypasserebbe** `EsecutoreFetch`,
host guard, budget e rate-limit dello sweep. Inaccettabile in un run nazionale.

**Vincolo (obbligatorio prima dell'implementazione):**

1. **Executor iniettato.** La probe mappa riceve l'`EsecutoreFetch` dello sweep;
   nuovo seam `mappa_connettore(istat, *, esecutore=None)` (e `_sonda_mappa(...,
   esecutore=None)`). `esecutore=None` = comportamento attuale (`_Sonda` grezzo),
   così i **14 chiamanti esistenti** restano invariati.
2. **Ogni fetch guardato.** Con `esecutore` passato, ogni lettura della probe
   passa da `esecutore.esegui(url)` → `fetch_guardato` (host guard/SSRF,
   redirect verso host non autorizzato bloccati) + `PoliticaFetch` (budget +
   rate-limit + backoff). Nessuna lettura raw fuori dalla politica.
3. **Costo probe contato a parte.** Le metriche per-run separano i fetch di
   probe mappa (`probe_fetch`, `probe_domini`) dai fetch di risoluzione servizi:
   due voci di costo distinte.
4. **Scrittura solo su `mappa-connettore/`, mai `storico.db`.** La mappa valida
   si persiste con l'`_in_cache` atomico esistente. Nessun ramo tocca
   `storico.db`.
5. **Fallimento/budget probe → miss onesto.** Se `esegui` ritorna
   `consentito=False` (budget dominio esaurito) o la probe erra, il comune è
   **fallito/miss onesto**: niente mappa vuota speculativa persistita, **niente
   risoluzioni servizi speculative**. La risoluzione parte **solo dopo** una
   mappa valida.

**Adapter di lettura.** `_sonda_mappa` internamente usa `sonda.risposta(url)`
(→ risposta con `.status_code`/`.text`/`.headers`/`.json()`) in più helper
(`_tipi_disponibili`, `_totale_rest`, `_categorie`, home…). Si introduce un
lettore con un metodo unico `leggi(url) -> RispostaLike | None` (None =
interrogato ma muto/irraggiungibile), che **solleva** su budget esaurito. Due
impl: `_LettoreSonda` (avvolge `_Sonda`, default retro-compatibile) e
`_LettoreEsecutore` (avvolge `EsecutoreFetch`, converte `EsitoFetch` →
`RispostaLike`; `consentito=False` → eccezione budget). `_sonda_mappa` guida il
lettore, non più `_Sonda` diretto.

Scartata la mappa **sintetica** dal registro (`dominio`+`piattaforma`):
accoppierebbe Step 2 a ciò che legge `_discovery_target`, fragile all'evoluzione
del connettore. La probe reale guardata è onesta e riusa il pipeline esistente.

## Matrice test net-free (gate pre-rete)

Tutti con fake iniettati (fetcher/executor/registry o cache pre-popolata), zero
rete — come i test Step 1 che monkeypatchano `_seam_servizi`.

| # | Simulazione | Setup | Asserzione |
|---|---|---|---|
| 1 | **cache hit** | `service_cache` pre-popolata fresca per una key | `res.from_cache=True`; fetcher **mai** chiamato; nessuna nuova scrittura |
| 2 | **successo live** | fake fetcher: 1 candidato che conferma la key | `res.from_cache=False`; `service_cache.salva` chiamato 1 volta; reference coerente |
| 3 | **NOT_FOUND** | fake fetcher: 0 candidati confermabili | `res is None`; **nessuna** scrittura cache; conteggio `miss` |
| 4 | **EMPTY** | mappa con `servizi.tot=0` / `_discovery_target=None` | connettore → NOT_SUPPORTED/NOT_FOUND; `res is None`; nessuna cache; non è errore |
| 5 | **budget esaurito** | fake executor che segnala budget dopo N fetch | run si ferma; exit **5**; metriche riflettono il parziale; nessuna cache corrotta |
| 6 | **interruzione + ripresa** | run parziale (metà lotto) poi re-run | i comuni fatti tornano `from_cache` (0 fetch); il run completa i mancanti; `storico.db` intatto |

### Matrice test net-free — seam probe mappa guardata

Test dedicati al nuovo seam `mappa_connettore(..., esecutore=...)`, tutti con
executor/lettore fake, zero rete.

| # | Simulazione | Setup | Asserzione |
|---|---|---|---|
| P1 | **cache hit senza rete** | mappa fresca su disco | ritorna dalla cache; executor **mai** chiamato |
| P2 | **cache miss + probe guardata** | nessuna cache, fake executor OK | ogni fetch passa da `esegui`; mappa costruita + scritta |
| P3 | **redirect/host non autorizzato** | fake executor che simula host-guard block | probe non segue l'host; comune = miss; nessuna mappa persistita |
| P4 | **budget esaurito** | fake executor `consentito=False` | probe segnala budget; comune = miss onesto; **nessuna** risoluzione servizi; nessuna mappa vuota scritta |
| P5 | **scrittura atomica mappa** | probe OK | scrittura via `.tmp`+`replace()`; nessun file `.tmp` residuo |
| P6 | **risoluzione solo dopo mappa valida** | probe fallisce vs probe OK | con probe fallita: 0 chiamate al resolver; con probe OK: risoluzione tentata |

## Ordine di implementazione

1. **Seam probe guardata**: `mappa_connettore(..., esecutore=None)` +
   `_sonda_mappa(..., esecutore=None)` + lettore (`_LettoreSonda` /
   `_LettoreEsecutore`) + eccezione budget. Chiamanti esistenti invariati.
2. Costante lista-pinnata + gate `--execute` + gate ⊆ campione.
3. Loop reale in `_run_service_catalog` (probe mappa guardata → 5 key →
   classifica); risoluzione **solo dopo** mappa valida.
4. Scrittore metriche atomico per-comune + schema (costo probe separato).
5. Rilevazione budget → exit 5; aggregazione errori per-comune → exit 4.
6. Test net-free: seam probe P1→P6, poi sweep 1→6.
7. **Gate**: suite verde → poi (e solo poi) il comando reale sul campione,
   con verifica dei risultati prima di qualunque fan-out.
