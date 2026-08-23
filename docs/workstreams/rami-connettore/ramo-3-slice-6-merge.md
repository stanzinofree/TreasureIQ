# Ramo 3 — Slice 6: merge controllato `ServiceReference` (Base) ↔ `SourceInventory.service_portals` (SP)

**Stato:** **IMPLEMENTATO** (v2). Contratto `sp_*` + cache v3, `merge_service_portals()` puro, wiring read-time in `_risposta_modulistica`, `sp_*` nel record del `DataBatch`. 47 golden + 89 test di regressione verdi; smoke Albano = identità (pagina CIE solo `INFORMATION`, nessun `AUTHENTICATED_ONLINE`). Manca ancora il comune con link SP esplicito per esercitare l'arricchimento reale (§7.10).
**Branch:** `feat/ramo3-sp-increment1`
**Dipende da:** Slice 5 (chat wiring del resolver, `feat/ramo3-sp-increment1`), Slice 5.2 (routing/evidence/timestamp, commit `5604072`).

---

## §0 — Scopo

Il connettore **Base** (WP/AgID, Slice 4) risolve una `ServiceKey` in una
`ServiceReference` con opzioni di accesso:

- `INFORMATION` — la pagina del servizio;
- `DOWNLOAD` — il modulo scaricabile (già ripulito dal boilerplate, Slice 5.2);
- `AUTHENTICATED_ONLINE` — un accesso online autenticato **solo se la pagina del
  servizio lo collega esplicitamente** (`service_page.py`, evidenza per-link).

In parallelo, la **discovery SP** persiste in `SourceInventory.service_portals`
gli entrypoint dei portali telematici del comune (`ServicePortalCandidate`:
url, ruolo, `platform_id`, `provider_hint`, `authentication`, `capabilities`,
`fingerprint`, `recognition_status`).

**Slice 6** arricchisce l'opzione `AUTHENTICATED_ONLINE` di una
`ServiceReference` con la **provenienza SP verificata** (piattaforma, ruolo,
metodi di autenticazione, fingerprint) **solo quando esiste un'associazione
verificabile** tra i due lati. La provenienza SP è tipizzata **sull'opzione**
stessa (`ServiceAccessOption` esteso con tre campi opzionali, §3.1), così viaggia
nel `DataBatch` e resta disponibile a UI e backoffice — non un oggetto a lato.

Slice 6 **non** tocca `INFORMATION`/`DOWNLOAD`, **non** crea opzioni da un
candidato SP non referenziato, **non** scrive in cache.

---

## §1 — La regola centrale

1. Il servizio è identificato dal **connettore Base**. La `ServiceReference` e
   le sue opzioni nascono lì; l'SP non può creare, rinominare o sostituire un
   servizio.
2. Il portale SP viene **agganciato a un'opzione solo se esiste
   un'associazione verificabile** (§2). Nessun aggancio per sola vicinanza di
   comune, piattaforma o categoria.
3. Un portale **generico** — ruolo `PERSONAL_AREA`, «Area personale», o
   candidato senza legame con questo servizio — **non viene mai associato
   automaticamente**.
4. L'opzione autenticata **conserva URL, piattaforma, ruolo e provenienza**: il
   merge arricchisce i campi mancanti, non riscrive quelli presenti né cambia
   l'URL che il comune ha messo sulla pagina del servizio.
5. **Nessun merge trasforma un candidato SP generico nel modulo richiesto.** Il
   merge agisce esclusivamente su opzioni `AUTHENTICATED_ONLINE`; `DOWNLOAD` e
   `INFORMATION` restano intatte.
6. Il merge è **read-time** e **non altera la reference cacheata**: senza una
   nuova risoluzione (Slice 3), la cache resta Base-only.

---

## §2 — Definizione di «associazione verificabile»

L'unica associazione ammessa in v1 è **evidenza per-link**:

> Esiste un'opzione Base `O` con `mode == AUTHENTICATED_ONLINE` il cui URL
> **corrisponde** all'`url` di un `ServicePortalCandidate` (o a un
> `entrypoint` di un `ServicePortalGroup`) dello stesso `source_id`.

Questa è la garanzia più forte disponibile: l'opzione autenticata Base esiste
**solo** perché la pagina del servizio la collegava (`service_page.py`,
evidenza contestuale). Se quell'URL è anche un entrypoint SP censito, allora è
il **comune stesso** ad aver legato quel servizio a quel portale — non noi.

**Normalizzazione del confronto URL** (deterministica, senza rete):
- schema-insensitive (`http`/`https`), `www.`-insensitive, trailing-slash
  insensitive;
- confronto base su **host + path**.

**Disambiguazione query string** (host+path uguali, query diverse):
- se l'URL Base **contiene** la query → **confronto esatto** (host+path+query):
  associa solo il candidato con la stessa query;
- se l'URL Base **non contiene** query e i candidati con quell'host+path sono
  **più di uno** → **nessun match** (ambiguo, mai risolto in automatico);
- se l'URL Base non contiene query e il candidato è **uno solo** → match su
  host+path;
- **mai** scegliere il primo candidato. L'ambiguità è un non-match, non una
  scelta.

**Escluso da v1** (proposto come tier B, vedi §6, **decisione richiesta**):
associazione per sola `capability` dichiarata dal `ServicePortalGroup` senza un
link sulla pagina. Più debole dell'evidenza per-link; tenuta fuori finché non
c'è una regola di mappatura `capability → ServiceKey` altrettanto
deterministica.

---

## §3 — Cosa produce il merge

Funzione pura, senza I/O:

```
merge_service_portals(
    *,
    source_id: str,
    reference: ServiceReference,
    inventory: SourceInventory | None,
) -> ServiceReference
```

`source_id` è **esplicito nella firma** (G7): `ServiceReference` non lo contiene
e non va dedotto analizzando `service_id`. Il gate è:

```
if inventory is None or inventory.source_id != source_id:
    return reference
```

- `inventory is None`, `source_id` non combaciante, o
  `service_portals`/`service_portal_groups` vuoti → ritorna `reference`
  **invariata** (identità).
- Per ogni opzione `O` con `mode == AUTHENTICATED_ONLINE`:
  - cerca un candidato/gruppo SP `C` con URL corrispondente (§2);
  - se `C` esiste → **arricchisce** `O` (copia nuova, campi mancanti riempiti):
    - `provider` ← `C.provider_hint` se `O.provider` è `None`;
    - `authentication` ← unione ordinata di `O.authentication` e
      `C.authentication` (nessun metodo inventato: solo quelli dichiarati da un
      lato o dall'altro);
    - `sp_platform_id` ← `C.platform_id`, `sp_role` ← `C.role`,
      `sp_fingerprint` ← `C.fingerprint` (provenienza tipizzata, §3.1);
    - `mode`, `url`, `requires_authentication`, `official` **invariati**: Base
      vince sull'URL (è quello che il comune ha pubblicato) e sul `mode` — un
      `AUTHENTICATED_ONLINE` resta tale, mai promosso a `DOWNLOAD`;
  - se `C` non esiste → `O` resta **identica** (opzione autenticata Base pura).
- Opzioni `INFORMATION`/`DOWNLOAD` → **mai toccate**, mai riordinate.
- Nessuna opzione **nuova** viene creata da un candidato SP non referenziato.

Il merge è **idempotente** (rieseguirlo su una reference già arricchita non
cambia nulla) e **deterministico** (stesso input → stesso output, ordine delle
opzioni preservato).

### §3.1 — Dove vive la provenienza SP — DECISO: (a) provenienza tipizzata sull'opzione

La provenienza SP è un **dato del contratto di accesso**, non di sola
presentazione: serve a UI, `DataBatch`, backoffice e analisi dei connettori.
Deve quindi viaggiare **dentro** l'opzione, non a lato.

`ServiceAccessOption` è esteso con tre campi opzionali:

```python
sp_platform_id: str | None = None
sp_role: ServicePortalRole | None = None
sp_fingerprint: str | None = None
```

Default `None`, retro-compatibili: un'opzione Base pura (nessun aggancio SP) li
lascia a `None`. Il merge li popola **solo** sull'opzione arricchita (§3).

**Cache schema.** Il merge resta read-time e **non** scrive la reference
arricchita nella cache Base-only: le cache continuano a contenere opzioni Base
valide con i tre campi a `None`, quindi il bump **non è tecnicamente
obbligatorio**. Per coerenza con la politica «ogni cambio di shape → bump»,
si porta comunque `SERVICE_CACHE_SCHEMA_VERSION` a **3** (accettato): una
reference v2 letta da un lettore v3 resta valida perché i campi sono opzionali.

**Perché non (b).** `merge_service_portals()` restituisce una
`ServiceReference`, ma `InfoAnswer.service` è un oggetto separato: portando la
provenienza lì, non viaggerebbe più nel `DataBatch` e la funzione non avrebbe un
output strutturato per restituirla. Scartata.

---

## §4 — Seam / punto di innesto

Il merge si colloca **tra il resolver e il builder del batch**, dentro il
handler `_risposta_modulistica` (Slice 5):

```
resolve_service_with_meta(...) -> ResolvedService            # Base, cache-first (Slice 3)
inventory = _inventory_from_live(source_id)                  # SP, read-only
reference2 = merge_service_portals(                          # Slice 6, read-time
    source_id=source_id, reference=resolved.reference, inventory=inventory,
)
service_reference_batch(ResolvedService(reference=reference2, ...), request)
```

- Il **resolver** (`service_resolver.py`) e la **cache** (`service_cache.py`)
  restano Base-only: il merge è a valle, non entra nel write-through (regola 6).
- Il loader inventory è quello già esistente (`_inventory_from_live`), in
  sola lettura; un inventory assente non è un errore (merge = identità).
- Nessun fetch aggiuntivo: si legge l'inventory già persistito, non si sonda
  l'SP live in questo passo.

---

## §5 — Guardie

- **G1 — solo AUTHENTICATED_ONLINE.** Il merge non ispeziona né modifica
  `INFORMATION`/`DOWNLOAD`. Un candidato SP non può diventare un modulo (regola 5).
- **G2 — solo evidenza per-link.** Nessun aggancio senza corrispondenza URL
  Base↔SP. Un `service_portals` non referenziato da nessuna opzione Base è
  ignorato del tutto (nessuna opzione nuova).
- **G3 — URL Base immutabile.** Il merge non cambia mai `O.url`: l'URL
  pubblicato dal comune vince; l'SP fornisce solo metadati mancanti.
- **G4 — nessun metodo di auth inventato.** `authentication` è unione di
  insiemi dichiarati; se entrambi i lati sono vuoti resta vuoto (nessun SPID
  di default).
- **G5 — read-time, no write.** Il merge non chiama `service_cache.salva`. La
  reference cacheata è invariata finché non c'è una nuova risoluzione.
- **G6 — identità su inventory assente/vuoto.** `None`/vuoto → reference
  invariata, byte-identica.
- **G7 — stesso `source_id`.** `source_id` è un **parametro esplicito** della
  firma, mai dedotto da `service_id`. `inventory is None or
  inventory.source_id != source_id` → identità, mai merge incrociato.

---

## §6 — Decisioni (chiuse)

- **D-S6-1 — tier di associazione → DECISO: solo evidenza per-link (v1).** Il
  tier B (capability `ServicePortalGroup` → `ServiceKey`) è **fuori v1**: la sola
  capability SP non basta ad associare un portale a una `ServiceKey`. Eventuale
  sotto-slice futura con mappatura capability deterministica.
- **D-S6-2 — provenienza SP → DECISO: (a) tipizzata sull'opzione.** Tre campi
  opzionali su `ServiceAccessOption` (§3.1); `SERVICE_CACHE_SCHEMA_VERSION` a 3
  per coerenza di politica (non obbligatorio, i campi sono opzionali).
- **D-S6-3 — «Area personale» linkata dalla pagina → DECISO: associazione
  esplicita ammessa.** Se la pagina del servizio contiene **realmente** il link
  e l'URL coincide con un candidato SP (`role=PERSONAL_AREA`):
  - **si può** associare (è esplicita, non automatica: c'è l'evidenza per-link);
  - si conserva `sp_role=PERSONAL_AREA`;
  - **non** si trasforma in modulo;
  - **non** si promuove a `DOWNLOAD` (il `mode` resta `AUTHENTICATED_ONLINE`);
  - l'autenticazione resta quella dichiarata, senza aggiunte.

  Non viola la regola 3 (che vieta l'associazione **automatica** di un portale
  generico): qui l'associazione è portata dall'evidenza per-link della pagina.

---

## §7 — Test previsti (golden, senza rete)

1. **Associazione per-link → arricchimento.** Base con `AUTHENTICATED_ONLINE`
   verso `https://portale.x/cie`; inventory con `ServicePortalCandidate` stesso
   URL → opzione arricchita (platform/role/auth), URL invariato.
2. **URL match con normalizzazione.** Stesso servizio con `www.`/trailing-slash
   diversi → associazione riconosciuta.
2bis. **Query string.** (i) Base con query + candidato stessa query → match
   esatto; Base con query + candidato senza → no match. (ii) Base senza query,
   **due** candidati stesso host+path → **nessun match** (ambiguo, mai il
   primo). (iii) Base senza query, **un** candidato → match host+path.
3. **Candidato SP non referenziato → ignorato.** Inventory con un portale che
   nessuna opzione Base linka → reference invariata, nessuna opzione nuova.
4. **Portale generico non automatico.** `PERSONAL_AREA` **senza** link dalla
   pagina → mai associato (regola 3).
4bis. **Area personale linkata esplicitamente** (D-S6-3). La pagina linka un
   `PERSONAL_AREA` e l'URL coincide con un candidato SP → opzione arricchita:
   `sp_role=PERSONAL_AREA`, `mode` resta `AUTHENTICATED_ONLINE` (mai `DOWNLOAD`),
   `authentication` invariata.
5. **DOWNLOAD/INFORMATION intatte.** Presenza di candidati SP non altera le
   opzioni non-autenticate (regola 5, G1).
6. **URL Base immutabile.** L'URL dell'opzione autenticata non cambia dopo il
   merge (G3).
7. **Nessun metodo inventato.** Entrambi i lati senza `authentication` → resta
   vuoto (G4).
8. **Identità su inventory assente/vuoto** (G6), **su `source_id` non
   combaciante** (G7), e **idempotenza** (doppio merge = singolo).
9. **Read-time, no write.** Il merge non tocca il file di cache (G5): mtime/
   contenuto invariati.
10. **Smoke reale Albano.** `modulo carta d'identità`: oggi la pagina CIE ha
    solo `INFORMATION` (nessun `AUTHENTICATED_ONLINE`) → il merge è identità
    (nessun portale associato). Serve un comune la cui pagina servizio linki
    davvero il portale telematico per esercitare il ramo di arricchimento —
    **da individuare nella flotta** (candidato onesto, non forzato).

---

## §8 — Fuori scope

- Sondaggio SP **live** in questo passo (si legge solo l'inventory persistito).
- Login/compilazione: TIQ indica la porta, non entra (D-R3-5/6). Invariato.
- Fallback SP quando il Base non trova (D-S5-2): resta miss onesto/URP, il merge
  non lo tocca.
- Associazione per capability (tier B) finché D-S6-1 non la apre.
```
```
