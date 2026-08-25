# Ramo 3 — Connettore servizi #2: ComWeb

Stato: SPEDITO (23 ago) + VERIFICA AGLIÈ (24 ago, §8) — passi 2-8 completi, smoke
live Alpignano verde, commit isolato; 4 rossi pre-esistenti registrati §5.1
(triage separato). [storico header]
Stato precedente: IMPLEMENTATO (23 ago) — passi 2-6 spediti, net-free verde (71/71 sui test
servizio); resta smoke reale (passo 7) + commit (passo 8)
Branch previsto: `feat/ramo3-sp-increment1` (o dedicato `feat/ramo3-comweb`)
Pilota di riferimento: `WordPressAgidServiceConnector` (Slice 4, commit `8965a2e`).

---

## 0. Perché ComWeb e non Municipium

Il target iniziale era Municipium. Recon dal vivo su Pomezia (058079, Municipium)
lo esclude: la piattaforma **non espone i servizi a granularità `ServiceKey`** in
HTML raggiungibile.

| Livello sondato | Cosa restituisce l'HTML statico |
|---|---|
| `/it/sitemap` | `organizational_unit`, `public_documents`, `news`, `menu` — nessun `/it/servizio/*` |
| `/it/menu/servizi-N` | 43 link `/it/page/{slug}` = le 15 macro-categorie |
| `/it/page/{categoria}` | rimanda ad altre categorie (id numerici), ricorsivo |
| pagina categoria | ancora categorie + marker `municipiumapp` (Angular SPA) |

I dettagli servizio li rende la SPA leggendo da `api.municipiumapp.it`, che è
**503/WAF** lato server (già annotato in `municipium.py:6`). Nessuna superficie
per-servizio da cercare e confermare → il contratto del pilota non è replicabile.
Municipium resta **coda lunga** (dottrina «guarda la piattaforma prima di
riparare»; il vuoto è un esito, non un buco).

**ComWeb** invece è il candidato pulito, verificato su fixture reale
(`api/tests/fixtures/comweb_servizi_alpignano.html`) e su `comweb.py`:

- HTML statico Bootstrap Italia, **niente SPA, niente WAF**;
- indice servizi `{base}/it-it/servizi`;
- categorie a un solo segmento: `/it-it/servizi/{categoria}` (`_RE_AREA_CATEGORIA`);
- **schede servizio individuali** con secondo segmento nested + id numerici e
  hash: `/it-it/servizi/{categoria}/{slug}-{ids}-{hash}` (`comweb.py:20-22`);
- titoli reali nell'anchor: «Agevolazioni Tassa Rifiuti (TARI)», «Addizionale
  Comunale IRPEF», «Accordi Territoriali - Agevolazioni Contrattuali».

Cioè la stessa forma del CPT WordPress (titolo + URL per-servizio,
confermabile), su un trasporto diverso (scrape indice, non REST `?search=`).

---

## 1. Obiettivo

Un secondo connettore servizi per la famiglia ComWeb che, dato un `ServiceKey`
riconosciuto, emette **esattamente un** `ServiceReference` — riusando il
contratto e le seam del pilota, e provando che l'astrazione regge oltre WP/AgID.

Invarianti (dal contratto Slice 4, non cambiano):
- **I-1** Esattamente un candidato confermato, o `NOT_FOUND`. 0/≥2 mai indovinati.
- **I-2** `service_id` costruito da `source_id`, mai dal titolo.
- **I-3** `access_mode = MEDIATED`: TIQ relaia il dato del comune, non è il comune.
- **I-4** Nessun URL inventato, nessun login/cookie; le opzioni vengono solo da
  evidenza sulla pagina servizio.
- **I-5** Host guard: un candidato o un link fuori dall'host ufficiale è scartato.
- **I-6** La conferma passa dal recogniser condiviso `riconosci_service_key`,
  mai da un nearest-neighbour.

---

## 2. Riuso (cosa NON si riscrive)

| Pezzo | Riuso | Nota |
|---|---|---|
| `ServiceKey`, `riconosci_service_key` | 1:1 | Il recogniser gira sui titoli scoperti, identico a WP. |
| `SERVICE_SEARCH_TERM` | 1:1 | Il termine per-key restringe la ricerca; poi conferma il recogniser. |
| `ServiceReference`, `ServiceAccessOption` | 1:1 | Nessun campo nuovo. |
| `service_cache` (v3) | 1:1 | Cache-first, chiave `(source_id, service_key)`. |
| `merge_service_portals` (Slice 6) | 1:1 | Arricchimento SP read-time, puro. |
| `InfoAnswer.service` / `respond.py` | 1:1 | Il resolver è già keyed su `platform_id`: **nessun cambio chat**. |
| `resolve_service[_with_meta]` | 1:1 | Solo registrazione del nuovo connettore, zero logica nuova. |
| `leggi_pagina_servizio` (`service_page.py`) | 1:1 (da verificare) | Estrae link DOWNLOAD/AUTHENTICATED tipizzati; l'HTML ComWeb è Bootstrap Italia — **V-1** conferma il typing sui marker ComWeb. |
| `_base_con_schema`, `_host_senza_www` | 1:1 | Stesse utility host del pilota. |
| `EsecutoreServiceFetcher` / coordinatore | 1:1 | Rate-limit per-dominio condiviso di processo (D-S5). |

---

## 3. Cosa cambia (perimetro della modifica)

Tre punti, chirurgici. Il resto è nuovo file.

### 3.1 Generalizzare `ServiceCandidate.wordpress_id`

Oggi (`service_connectors/base.py:23`):

```python
class ServiceCandidate(_StrictModel):
    wordpress_id: int = Field(gt=0)   # WP-specifico
    title: str = Field(min_length=1)
    url: AnyHttpUrl
```

ComWeb non ha un id WordPress: l'identità stabile è lo **slug + id numerici**
nel path della scheda. Generalizzare a un id nativo di piattaforma, stringa:

```python
class ServiceCandidate(_StrictModel):
    native_id: str = Field(min_length=1)   # WP passa str(id); ComWeb lo slug
    title: str = Field(min_length=1)
    url: AnyHttpUrl
```

`service_id` — costruito nella base condivisa, prefisso per-sottotipo, **mai dal titolo** (I-2):
- WP resta `{source_id}:wp:{native_id}` (il connettore WP passa `str(id)`);
- ComWeb `{source_id}:comweb:{native_id}` (native_id = segmento identificativo
  stabile della scheda: slug + id numerici dell'ultimo segmento path).

> Decisione da confermare (§7 D-1): rinominare `wordpress_id`→`native_id`
> tocca il connettore WP e i suoi test. Alternativa meno invasiva: lasciare
> `ServiceCandidate` a WP e dare a ComWeb un candidato proprio. Preferenza:
> **generalizzare** — un secondo connettore che condivide il tipo *è* la prova
> che l'astrazione regge; due candidati paralleli sarebbero debito.

### 3.2 La seam di fetch: firma neutra, due strategie

Il `ServiceFetcher` (Protocol) resta il solo punto di rete. **Il Protocol non
espone concetti WP** (`rest_base` era WP-specifico): firma neutra, la costruzione
dell'endpoint resta interna all'adapter.

```python
class ServiceFetcher(Protocol):
    def scopri_servizi(
        self, *, base_url: str, term: str, limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        ...
    def leggi_pagina(self, url: str, *, official_host: str) -> str | None:
        ...
```

- **WP** costruisce `{base}/wp-json/wp/v2/{rest_base}?search={term}` **dentro**
  la sua strategia (rest_base non esce dall'adapter).
- **ComWeb** scarica l'indice statico e filtra gli anchor scheda per `term`.

Il connettore chiama solo `scopri_servizi` e non sa se sotto c'è REST o scrape (D-2 = A).

**Split di `EsecutoreServiceFetcher`.** Oggi è WP-specifico: astrarre il Protocol
ma lasciare l'unica impl WP renderebbe il seam finto. Separare in:
- parte **comune** — coordinatore `EsecutoreFetch`, rate-limit per-dominio (D-S5),
  host guard, redirect manuale con re-check host a ogni hop, `leggi_pagina`;
- due **strategie** `scopri_servizi` — `_WpDiscovery` (REST) e `_ComWebDiscovery`
  (scrape indice) — iniettabili, così WP e ComWeb condividono rete+guard ma non la
  logica di scoperta.

**Discovery ComWeb (bounded — drill per-categoria, provato in V-1).**
V-1 ha **falsificato** l'ipotesi "indice-solo": l'indice `/it-it/servizi` di Alpignano
è una **vetrina** (15 categorie, 1 scheda "in evidenza" per categoria, **0 schede
anagrafe**). Le schede complete vivono nella **pagina categoria**
(`/it-it/servizi/anagrafe-e-stato-civile` = 56 schede, tutte le key anagrafiche).
Quindi il drill per-categoria **non è un fallback: è il path primario** (D-3).

Mapping — **costante specifica del connettore** (è un percorso di navigazione, NON
un termine di ricerca: NON riusare `SERVICE_SEARCH_TERM`):

```python
COMWEB_SERVICE_CATEGORY = {
    ServiceKey.CARTA_IDENTITA:   "anagrafe-e-stato-civile",
    ServiceKey.CAMBIO_RESIDENZA: "anagrafe-e-stato-civile",
    ServiceKey.STATO_CIVILE:     "anagrafe-e-stato-civile",
    ServiceKey.ACCESSO_ATTI:     "anagrafe-e-stato-civile",
    ServiceKey.TRIBUTI:          "tributi-finanze-e-contravvenzioni",
}
```

Flusso (nessun URL scheda fabbricato — si **segue** l'anchor realmente trovato):
1. `GET {base}/it-it/servizi` — indice (unico entry-point costruito, come il root
   REST di WP).
2. Tra gli anchor **categoria** presenti sull'indice, scegli quello il cui slug ==
   `COMWEB_SERVICE_CATEGORY[service_key]`. Il mapping **seleziona quale anchor
   seguire**, non costruisce il path.
3. Host guard, **segui** quell'anchor (I-5) → pagina categoria.
4. Raccogli gli anchor **scheda** (`_RE_SCHEDA`) realmente presenti; titolo = testo anchor.
5. Conferma via `riconosci_service_key(titolo)` (I-6); esattamente uno confermato o
   `NOT_FOUND` (I-1).

Vincoli di discovery (tutti obbligatori — dal committente):
- indice principale + **al più UNA** pagina categoria (quella mappata); mai oltre;
- il mapping seleziona la categoria, ma l'**URL si segue** dall'anchor realmente
  trovato — il connettore **non costruisce URL arbitrari** (né categoria né scheda);
- la conferma resta **sempre** sul titolo via `riconosci_service_key` (I-6);
- `limit` massimo di link/pagine **configurabile**, mai illimitato;
- ordine **deterministico** (nessun set-order casuale);
- **nessun** crawler ricorsivo, **nessun** fan-out;
- le **categorie** (un solo segmento) **mai** candidate come servizi;
- accetta **solo** URL che rispettano il pattern scheda `_RE_SCHEDA`;
- candidato valido = **titolo riconosciuto** (I-6) **e** host ufficiale (I-5).

**Caveat ambiguità (V-1, I-1).** Nella categoria anagrafe due key hanno **≥2 schede**:
`carta_identita` (*carta d'identità* + *carta d'identità elettronica CIE*) e
`stato_civile` (*certificati* + *trascrizione atti*). Col recogniser attuale
confermano entrambe → **NOT_FOUND** (I-1, mai indovinare). È il comportamento
corretto: la disambiguazione è **lavoro futuro del recognizer**, non una scelta
implicita del connettore. `cambio_residenza`, `accesso_atti` = 1 scheda netta,
coperte. `tributi` = 16 schede fiscali (TARI/IMU/IRPEF/canone…), nessuna letteralmente
"tributi": copertura dipende dal recogniser, verificare su fixture tributi.

**`_RE_SCHEDA`** (da inchiodare su fixture, V-1) deve gestire:
- URL **relativi e assoluti**;
- **due** segmenti dopo `/it-it/servizi/`;
- identificatore **numerico** nell'ultimo segmento;
- **hash** finale;
- `query` e `fragment` ignorati;
- **rifiuto** delle categorie a un solo segmento (`_RE_AREA_CATEGORIA`);
- **rifiuto** di link esterni o pagine non-servizio.

### 3.3 Il connettore: base condivisa + due sottotipi

Il corpo del pilota (`_confermati`, `_opzioni`, `_esito`, la costruzione del
`ServiceReference`) è piattaforma-agnostico. Estrarlo in un
`_ServiceConnectorBase`; WP e ComWeb diventano sottotipi che differiscono solo in:
- `supports()` (gate di piattaforma);
- il prefisso di `service_id` (`wp` / `comweb`);
- la discovery (delegata alla seam §3.2).

```python
class ComWebServiceConnector(_ServiceConnectorBase):
    name = "comweb_service"; version = "1"
    _PREFISSO = "comweb"
    _PIATTAFORME = frozenset({Piattaforma.COMWEB.value})

    def supports(self, request, *, platform_id) -> bool:
        return (
            request.surface is Surface.ORDINARY_DATA
            and request.capability == CAPABILITY_SERVICES
            and platform_id in self._PIATTAFORME
        )
```

### 3.4 Il gate su `mappa` NON è `servizi.esposto`

Trappola: `AssetServizi.esposto`/`rest_base` sono concetti **WP-REST**, popolati
solo da `/wp-json/wp/v2/types`. Su ComWeb `servizi.esposto` è `False` — il gate
del pilota (`not mappa.servizi.esposto → NOT_SUPPORTED`) escluderebbe ComWeb per
sempre. Il connettore ComWeb gate su:
- `platform_id == Piattaforma.COMWEB.value`, e
- `_base_con_schema(mappa.sito)` non `None`.

Nessuna dipendenza da `servizi.esposto`/`rest_base`.

### 3.5 Registrazione

`default_service_registry` registra anche il nuovo connettore sopra lo stesso
esecutore condiviso; ogni connettore riceve un fetcher con la **propria strategia**
di discovery (§3.2) ma la parte comune (coordinatore, host guard, rate-limit) è una:

```python
comune = EsecutoreServiceFetcher(esecutore)          # rete + guard condivisi
reg.register(WordPressAgidServiceConnector(comune.con(_WpDiscovery())))
reg.register(ComWebServiceConnector(comune.con(_ComWebDiscovery())))
```

Il registry seleziona per `platform_id` (D-R3): un comune ComWeb prende il
connettore ComWeb, un WP/AgID il suo. Nessun conflitto, nessun cambio a `supports`
del pilota.

---

## 4. Test (net-free, come Slice 4)

| Test | Setup | Asserto |
|---|---|---|
| indice = vetrina | stub serve `comweb_servizi_alpignano.html` | anchor categoria estratti; 0 schede anagrafe (V-1) |
| drill categoria | stub serve `comweb_categoria_anagrafe_alpignano.html` | 56 schede nested, categorie escluse |
| conferma singola | stub categoria + `service_key=CAMBIO_RESIDENZA` | 1 `ServiceReference`, `service_id` `…:comweb:{native_id}` |
| ambiguo → NOT_FOUND | `service_key=CARTA_IDENTITA` (2 schede: carta + CIE) | `NOT_FOUND`, nessuna scelta implicita (I-1) |
| mapping tributi | stub serve `comweb_categoria_tributi_alpignano.html` | categoria seguita = `tributi-finanze-e-contravvenzioni` (16 schede) |
| no URL fabbricato | mapping punta a categoria assente dagli anchor indice | `NOT_FOUND`; il connettore non costruisce il path categoria |
| host guard | stub con scheda su host estraneo | scartata (I-5) |
| opzioni da pagina | stub serve una scheda con link modulo/SPID | DOWNLOAD/AUTHENTICATED tipizzati (I-4) |
| gate mappa | `servizi.esposto=False`, `sito` presente | il connettore **procede** (non NOT_SUPPORTED) |
| titolo mai in id | scheda con titolo che *sembra* un id | `service_id` = `…:comweb:{native_id}`, titolo assente (I-2) |
| indice senza match | stub indice senza titolo confermabile | `NOT_FOUND`; **nessuna** ricerca web né fallback SP |
| limite anti fan-out | stub con N ≫ `limit` schede | al più `limit` fetch; nessun crawl ricorsivo |
| regressione WP | stesso caso su connettore WP | **identico** `ServiceReference` di Slice 4, salvo prefisso `service_id` |

Girano nello stage `dev` in Docker (come tutta la suite), fetcher stub → zero rete.

---

## 5. Sequenza di consegna

1. **V-1 recon — FATTO (23 ago).** Indice = vetrina (0 schede anagrafe); pagina
   categoria completa (anagrafe 56, tributi 16). Pattern scheda/categoria inchiodati.
   Fixture catturate: `comweb_categoria_anagrafe_alpignano.html`,
   `comweb_categoria_tributi_alpignano.html` (+ indice preesistente). D-3 chiusa =
   mapping+drill. Resta da confermare in codice che `leggi_pagina_servizio` tipizzi
   i link scheda ComWeb (passo 5).
2. **FATTO.** `ServiceCandidate.wordpress_id → native_id` (§3.1) + connettore WP e test.
3. **FATTO.** Protocol neutro `scopri_servizi` (§3.2) + `_ServiceConnectorBase` estratto
   in `service_connectors/connettore_base.py` (§3.3, `DiscoveryTarget` hook per-famiglia).
4. **FATTO.** Adapter WP rifattorizzato su base/Protocol, **parità** (test WP invariati);
   endpoint REST resta interno al WP (`_discovery_target` compone la collezione).
5. **FATTO.** `ComWebServiceConnector` + `_ComWebDiscovery` bounded in
   `service_connectors/comweb_service.py`; gate su piattaforma+`sito`, **non** su
   `servizi.esposto` (§3.4); `COMWEB_SERVICE_CATEGORY` + `_RE_SCHEDA`/`_RE_CATEGORIA`.
6. **FATTO.** Registrazione (§3.5) + 17 test net-free (`test_comweb_service_connector.py`).
   Servizio verde: 71/71 (WP+esecutore+comweb). *NB: `make test` mostra 4 fallimenti
   **pre-esistenti** sul branch, estranei a Ramo 3-#2 (drift allowlist seam in
   `mappa_connettore.py`; 3 su `test_wp_pages_caratterizzazione` — PDF/recovery).*
7. **FATTO (smoke live 23 ago).** Smoke mirato su Alpignano (`001008`,
   `www.comune.alpignano.to.it`) via **esecutore guardato**, senza sweep e senza
   Brave: due `retrieve()` diretti sul connettore ComWeb.
   - `CAMBIO_RESIDENZA` → **FULFILLED**, `access_mode=MEDIATED`,
     `service_id = 001008:comweb:cambio-residenza-305-59428-1-ed80250a6bea88e349c3d678093f1e4f`,
     `source_url` reale, opzione `INFORMATION`.
   - `TRIBUTI` → **NOT_FOUND** = ambiguità onesta (I-1): 7 schede tributi
     confermano la key (TARI×5, IMU×2); disambiguazione = lavoro futuro recognizer.
   - `CARTA_IDENTITA` → **NOT_FOUND** (carta + CIE, ≥2).
   - Checklist verde: `platform_id==comweb`; `esposto=False` non blocca;
     `service_id` = `istat:comweb:native_id`; una scheda → una reference;
     ambiguità → NOT_FOUND; nessun fallback SP/web (access_mode sempre MEDIATED);
     cache/chat non toccate (solo `register`).
8. **FATTO (commit isolato 23 ago).** Committati **esclusivamente** i 7 file
   modificati + i file nuovi del connettore (comweb_service.py, connettore_base.py,
   test_comweb, 2 fixture categoria) + questo doc. I 4 rossi pre-esistenti (sotto)
   **non** mescolati al commit.

### 5.1 Rossi pre-esistenti sul branch (NON di questa slice)

`make test` sul branch `feat/ramo3-sp-increment1` mostra **4 fallimenti estranei**
a Ramo 3-#2 (git diff conferma: file fuori dalla superficie di questa slice):

| Test | Causa | Superficie |
|------|-------|-----------|
| `test_recognition_seam_guard::test_only_the_allowlisted_files_import_the_legacy_classifier_seam` | drift allowlist: `mappa_connettore.py` importa `firma_da_risposta` fuori allowlist | `mappa_connettore.py` (committato, non mio) |
| `test_wp_pages_caratterizzazione::test_pdf_budget_and_audit_trail` | asserzione PDF budget/audit | corpus/PDF (non mio) |
| `test_wp_pages_caratterizzazione::test_corpus_truncation_and_segment_boundaries` | truncation/segment boundaries | corpus/PDF (non mio) |
| `test_wp_pages_caratterizzazione::test_recovery_level_and_notes` | RecoveryLevel/notes | recovery (non mio) |

**Triage separato:** il seam-guard non blocca questa slice (drift fuori
superficie). Nessuna GitHub issue per ora (niente remoto/triage dedicato): la nota
qui è già tracciata, fuori scope e riproducibile. I 3
`test_wp_pages_caratterizzazione` sono regressioni di branch indipendenti dal
connettore-servizio.

### 5.2 Fix post-review (23 ago)

Due finding dalla review del commit, corretti nello stesso commit slice (amend):

- **P1 — cap applicato prima della conferma (bloccante).** `_ComWebDiscovery._schede`
  troncava a `limit` **prima** che `_confermati` (recognizer, nel connettore) girasse:
  una scheda utile oltre il cap dava un falso NOT_FOUND (rischio su categorie lunghe
  tipo tributi). Fix: il cap è ora **difensivo** (`_CAP_DIFENSIVO_SCHEDE = 2000`,
  guardia memoria contro pagina abnorme), ben sopra ogni categoria reale (anagrafe
  56, tributi 16); la pagina categoria — documento singolo già limitato dal
  transport — è raccolta **intera**, la conferma resta a valle nel connettore.
  Regressione: `test_match_beyond_old_limit_still_resolves` (match a pos. 250, oltre
  il vecchio 200) + `test_discovery_collects_all_schede_on_a_long_page` (250/250).
- **P2 — fixture non whitespace-clean.** Le due fixture categoria sono HTML server
  catturato verbatim con CRLF (come la sorella indice `comweb_servizi_alpignano.html`
  e altre fixture del repo). CRLF **intenzionale** registrato in
  `api/tests/fixtures/.gitattributes` (`comweb_*.html -text -whitespace`):
  `git diff --check` ora tace, fedeltà byte preservata.

Servizio: **74/74** verdi (era 71 + 3 test P1).

#### BLOCKING prima del merge globale (branch→main)

| Campo | Valore |
|-------|--------|
| File coinvolto | `mappa_connettore.py` |
| Test | `test_recognition_seam_guard` |
| Causa | allowlist non aggiornata (import legacy `firma_da_risposta` fuori allowlist) |
| Fix previsto | correggere l'allowlist **oppure** rimuovere l'import legacy |
| Criterio di chiusura | `make test` senza quel failure |

Verifiche obbligatorie prima del commit:
- **V-2 ✓** i test WP restano verdi dopo la generalizzazione del candidato.
- **V-3 ✓** un comune ComWeb con `servizi.esposto=False` risolve comunque
  (`test_gate_proceeds_when_servizi_not_exposed`).
- **V-4 ✓** `service_id` = `{source_id}:comweb:{native_id}`, mai dal titolo
  (`test_service_id_from_path_never_from_title`).
- **V-5 ✓** `respond.py`/resolver/`service_cache`/`merge` **non toccati** (solo la
  `register` in più in `service_registry.py`).

---

## 6. Perimetro (cosa NON si tocca)

- `ServiceKey`, `riconosci_service_key`, `service_cache`, `merge_service_portals`,
  `InfoAnswer.service`, `resolve_service*` — invariati (solo una `register` in più).
- Il connettore Municipium **non** si costruisce ora (§0).
- Nessun cambio al path intent/scorer/Rust (fuori Ramo 3).

---

## 7. Decisioni chiuse (review 23 ago)

- **D-1 → DECISA: generalizzare.** `ServiceCandidate.wordpress_id → native_id`
  (str). WP passa `str(id)`, ComWeb il segmento identificativo stabile. Il
  `service_id` resta esplicito e per-sottotipo (`{source_id}:wp:{native_id}` /
  `{source_id}:comweb:{native_id}`), mai dal titolo.
- **D-2 → DECISA: A, firma neutra.** Protocol `scopri_servizi(*, base_url, term,
  limit)`. Nessun concetto WP (`rest_base`) nel Protocol: la costruzione REST resta
  interna all'adapter WP. `EsecutoreServiceFetcher` **splittato** in parte comune +
  due strategie (§3.2), altrimenti il Protocol sarebbe astratto ma l'impl WP-only.
- **D-3 → DECISA (post V-1): mapping key→categoria, drill primario.** V-1 ha provato
  che l'indice è una vetrina (0 schede anagrafe) e la pagina categoria è completa (56).
  Il mapping vive in una costante **specifica del connettore** `COMWEB_SERVICE_CATEGORY`
  (percorso di navigazione, NON `SERVICE_SEARCH_TERM`), 5 voci → 2 categorie. Il mapping
  sceglie **quale anchor categoria seguire** sull'indice; nessun URL fabbricato; conferma
  sempre sul titolo; carta_identita/stato_civile multi-scheda restano NOT_FOUND
  (disambiguazione = lavoro futuro del recognizer). Vincoli completi in §3.2.
  *Aggiornamento 24 ago (§8.2): su Agliè `stato_civile` è in realtà FULFILLED — la
  categoria ha UNA sola scheda col marker «matrimonio», quindi exactly-1+confirm passa.*

---

## 8. Verifica su seconda fixture reale — Agliè 001001 (24 ago)

Seconda campagna net-free su fixture catturate dal vivo
(`api/tests/fixtures/comweb/aglie_*.html`): indice (9 categorie), categoria
anagrafe (16 card), categoria tributi (9 card). Host ufficiale
`www.comune.aglie.to.it` (canonical nell'HTML); `servizi.comune.aglie.to.it` è
un host **diverso** (servizi online) e cadrebbe sotto host guard.

### 8.1 Forma e numero delle richieste (asserita nei test)

Per **ogni** key: `GET /it-it/servizi` (indice) → `GET
/it-it/servizi/{categoria mappata}` (una sola, quella di
`COMWEB_SERVICE_CATEGORY`) → al più `GET` della singola scheda confermata (per
le opzioni di accesso). Mai un'altra categoria, mai crawl
(`test_aglie_every_key_reads_index_plus_its_one_mapped_category`).

### 8.2 Esito per key (ground truth, non ipotesi)

| ServiceKey | Card che confermano (recogniser sul titolo) | n | Esito | Perché |
|---|---|---|---|---|
| `cambio_residenza` | «Cambio Residenza» | 1 | **FULFILLED** | exactly-1 + confirm; `service_id = 001001:comweb:cambio-residenza-305-22801-1-f8ed…` |
| `accesso_atti` | «Richiedere l'accesso agli atti» | 1 | **FULFILLED** | «Accesso Civico» (istituto diverso) **non** porta marker `accesso [agli] atti` → mai confuso |
| `carta_identita` | «Carta d'Identità Elettronica (CIE)» + «Carta d'identità per minori» | 2 | **NOT_FOUND** | ambiguità onesta (I-1): ≥2 confermate, nessuna scelta implicita |
| `stato_civile` | nessuna (dopo fix recogniser) | 0 | **NOT_FOUND** | «pubblicazione di matrimonio» è un servizio distinto (banns), non più marker di `STATO_CIVILE`; 0 confermate → miss onesto. Vedi caveat sotto |
| `tributi` | «Pagamento Tassa Rifiuti (TARI)» + «Pagare tributi IMU» | 2 | **NOT_FOUND** | key generica by design; IUC/TOSAP/ICP non portano marker |

**Caveat `stato_civile` — RISOLTO (slice recogniser, 24 ago).** La verifica
aveva rilevato un FULFILLED indebito: il vocabolario condiviso includeva
«matrimonio» come marker autonomo di `STATO_CIVILE`, e ad Agliè la sola card
«Richiedere una pubblicazione di matrimonio» (i banns — servizio distinto) lo
confermava. Il marker nudo «matrimonio» è stato **rimosso** da `service_key.py`
(sostituito dalla frase inequivoca «certificato di matrimonio», in parallelo a
nascita/morte): un sotto-servizio specifico non collassa più nella key generica.
Effetto su Agliè: 0 card confermate → **NOT_FOUND onesto** (test
`test_aglie_stato_civile_is_honest_not_found`). La fix è cross-family (usata
identica da WP); golden positivi/negativi in `test_service_key.py`. Nessuna
modifica al connettore ComWeb né a WP: solo il vocabolario condiviso e le
asserzioni dei test che codificavano il bug.

### 8.3 Ambiguità: migliorabile-e-dimostrabile vs miss onesto

- **`carta_identita` → resta miss onesto.** Le due card (CIE + per-minori) non
  offrono una regola dimostrabile dalle card stesse per eleggere la CIE come
  «rilascio canonico»: un tie-break su «qualificatore di platea nel titolo»
  (*per minori*) sarebbe una scelta lessicale arbitraria, non evidenza. **Da
  verificare con altra prova live**: se su più comuni ComWeb la card CIE è
  strutturalmente distinta (es. categoria/metadato dedicato), la preferenza
  diventerebbe dimostrabile.
- **`tributi` → resta miss onesto.** Due card confermano (TARI, IMU): la key è
  un ombrello. L'unico miglioramento vero è **splittare il vocabolario**
  (`ServiceKey` per-tributo) — decisione di contratto condiviso, non un
  tie-break del connettore.
- **`accesso_atti` → già corretto.** La distinzione atti/civico regge da sola:
  i marker (`accesso agli atti`/`accesso atti`) non matchano «Accesso Civico».

### 8.4 Fingerprint ComWeb (primi test su fixture reali)

Il plugin `plugins/recognition/base/comweb.py` (generator meta, definitivo,
score 0.998, `comweb-base-v1`) aveva già una matrice di test **sintetici**
(`test_plugin_comweb_recognition.py`); ora è coperto anche su **HTML reale**:
le tre pagine di Agliè portano `generator: ComWeb - www.epublic.it` (branding
vendor, identico su indice e categorie → fingerprint stabile per-portale), e il
nativo pareggia il bridge legacy anche sulla fixture reale.

**Marcatori NON aggiunti, con prova contraria.** `data-element="service-link"`
è presente nelle fixture ComWeb ma anche in quelle **OpenPA e PeopleWeb** del
repo: le fixture stesse ne falsificano la specificità — non è un marker ComWeb.
L'host `servizi.comune.*` è un pattern di hosting, non una firma della
piattaforma. Nessun marker nuovo nel plugin (che deve anche restare a parità di
score col bridge v1).

### 8.5 Cache/metriche

Invariato rispetto a §2: cache v3 keyed `(source_id, service_key)`, un
FULFILLED di Agliè entra in cache come quello di Alpignano; i NOT_FOUND onesti
non fabbricano riferimenti. Nessun contatore nuovo introdotto da questa
verifica.
