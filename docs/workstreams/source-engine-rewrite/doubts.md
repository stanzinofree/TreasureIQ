# Rewrite Source Engine — dubbi, corner case, come superati

Stato al 2026-08-22. Branch `refactor/source-engine`. Documento richiesto
esplicitamente: *"scrivi tutto quello che trovi come dubbio e come lo superi,
analizza bene corner case e problemi architetturali che abbiamo già affrontato"*.
Da leggere prima della review Codex insieme a `planning.md`.

Legenda esito: **RISOLTO** (deciso e implementato) · **DEFERRED** (deciso di
rimandare alla review con proposta) · **APERTO** (serve decisione).

---

## 1. `scattate` perso migrando `scopri_pagina_at` — DEFERRED (C1)

**Dubbio.** `scopri_pagina_at` (censimento.py:599-632) fa tre cose fuse:
discovery (trova il link AT), recognition (riga 632, via `classifica_risposta`)
e **diagnostica `.scattate`** — la lista di TUTTE le firme scattate, non solo la
vincitrice. Il seam `firma_da_registro` ritorna solo il vincitore (`Firma`), non
l'insieme delle firme scattate. Migrare alla cieca perderebbe la diagnostica.

**Perché conta.** `.scattate` è l'unico punto dove oggi si vede *quali altre
piattaforme erano vicine* — segnale grezzo di aderenza/ambiguità. Buttarlo
contraddice l'invariante I5 (aderenza reale), non la serve.

**Come superato (proposta per la review, non eseguita).** Estendere il seam,
non il chiamante: aggiungere al risultato del registry un campo opzionale
`scattate: tuple[FirmaScattata, ...]` (o un `RecognitionTrace`) popolato dal
bridge/adapter quando disponibile, `()` per i plugin nativi che non lo
espongono. Così `scopri_pagina_at` migra senza perdere diagnostica e I5 guadagna
la sorgente giusta. **Non toccato in questo giro**: 3 chiamanti
(`connettore.py:499`, `censimento.py:1086`, `inventory_discovery.py`), è un
cambio di firma del seam → decisione architetturale, va in review.

---

## 2. Interplay `da_impronta` a censimento:1071 — RISOLTO

**Dubbio.** `_impronta` dopo il riconoscimento BASE ha un fallback statistico
region-aware `da_impronta(impronta=grezza, regione=...)` che scatta quando la
firma è IGNOTA. Il seam **non replica** questo fallback.

**Come superato.** M2 migra SOLO la chiamata di recognition a
`firma_da_registro`; il blocco `da_impronta` sotto resta **invariato**. Ordine
preservato: seam prima, statistico dopo su IGNOTA. La preservazione è coperta
dal test C richiesto al subagent (branch fallback ancora presente).

---

## 3. Cambio del testo `prova` per comuni WP/comweb — RISOLTO (atteso)

**Dubbio.** Il plugin BASE nativo produce `evidence` diverso dal
classificatore legacy → cambia il testo `prova` salvato nell'output del
censimento per i comuni wordpress_agid/comweb.

**Come superato.** È l'effetto voluto (T2): stessa piattaforma (l'enum non
cambia, il nativo rispecchia lo score del bridge), evidence più ricco. Non è una
regressione: la piattaforma riconosciuta è identica. Segnalato qui perché un
diff sull'output censimento lo mostrerà e non deve allarmare la review.

---

## 4. Ciclo di import censimento→adapter→bridge→plugin — RISOLTO

**Dubbio.** `catalog/__init__` importa `connettore`; importare `catalog.*` in
cima a `censimento`/`connettore` crea un ciclo all'import del modulo (trappola
già morsa, vedi memoria `container-non-monta-sorgente-api` e affini).

**Come superato.** M2 usa **import locale** dentro `_impronta`
(`from treasureiq.catalog.recognition_adapter import firma_da_registro`), non in
testa al modulo. M1 (`inventory_discovery`) è codice nuovo a valle del ciclo →
import in testa sicuro. Confermato: suite verde.

---

## 5. De-versionare `data/seed/` e cache runtime — DEFERRED

**Dubbio.** Il piano I6 vuole togliere dati fissi. Ma `compose.yml:7` +
`.gitignore` mostrano che `data/seed/` e `data/extraction-cache/` sono
versionati **di proposito** (la demo/vetrina ci dipende).

**Come superato.** Regola: *quando ciò che trovo contraddice come è stato
descritto, lo segnalo invece di procedere*. NON de-versionato in questo giro.
Va deciso in review con l'utente: separare "fixture demo" (restano) da "cache
runtime versionata per sbaglio" (via) richiede conferma su cosa la vetrina
carica davvero. Rischio se sbagliato: demo/Pages rotta.

---

## 6. Potatura docs che alimentano la vetrina — DEFERRED

**Dubbio.** Il piano 3C vuole rimuovere/mergere `architettura.md`,
`connettori.md`, `evoluzione.md`, `roadmap.md`. Ma `site/build.py:36-40` li usa
come pagine di navigazione del sito vetrina e i docs si linkano tra loro.

**Come superato.** NON rimossi. Rimuoverli rompe la build della vetrina
(memoria `sito-vetrina-e-deploy`). Va fatto insieme all'aggiornamento di
`build.py`, in un passo dedicato con verifica del build del sito — non come
pulizia cieca. In review.

---

## 7. `classifica_risposta` è condiviso (5 chiamanti) — RISOLTO (vincolo)

**Dubbio.** Tentazione di cancellare il classificatore legacy.

**Come superato.** NON si cancella: resta avvolto dal bridge
(`recognition_bridge.py:73-97`) che è la sorgente di riconoscimento per le
famiglie non ancora native. Il guard test I1 (delegato) lo mette nero su
bianco: gli unici import legittimi di `classifica_risposta`/`firma_da_risposta`
sono bridge/adapter + il sito di definizione `piattaforma.py`.

---

## 8. `DEFAULT_COMUNE_ISTAT` Albano — DEFERRED

**Dubbio.** I6 vuole via i fallback comune hardcoded (Albano `respond.py:128`,
usato in 5 punti). È nel path della CHAT, non del motore sweep.

**Come superato.** Fuori dallo scope di questo giro (Fase 0/1 = motore
recognition, non chat). Toccare respond.py ora rischia la chat senza rete di
caratterizzazione sul flusso. Rinviato a Fase 3 (contratto chat→connettore) con
test e2e (PR #22) come rete. Registrato in `planning.md` §3A.

---

## 9. `source_id` = URL invece di ISTAT in `_impronta` — RISOLTO (review P2)

**Dubbio (Codex, review `11954a9`).** M2 passava `source_id=str(resp.url)` a
`firma_da_registro`. Il contratto `RecognitionObservation.source_id` è
l'identità *stabile* della fonte (codice ISTAT), non l'URL osservato. Oggi non
rompe nulla (nessun plugin legge `source_id`) ma è violazione di contratto:
provenance incoerente, risultato non correlabile al comune, divergenza tra
discovery/censimento/confirmation.

**Come superato.** Aggiunto param `codice_istat: str | None` a `_impronta`,
propagato dal chiamante `censisci_comune` (dove l'ISTAT è già in scope);
`source_id = codice_istat or str(resp.url)` — l'URL resta solo `entrypoint_url`,
fallback all'URL solo se l'ISTAT non è propagato. Test focalizzato
`test_impronta_passa_codice_istat_come_source_id` cattura i kwarg passati al
seam. Coerente ora con discovery/confirmation che già usano l'ISTAT.

---

## 10. `--dry-run` e il refresh legacy — RISOLTO (scelta di design, Fase 2A)

**Dubbio.** `--dry-run` deve garantire "zero scrittura su `data-live`". I path
catalog (discovery/confirmation) sono guardabili con un flag `dry_run` che salta
la write finale. Ma il **refresh** non passa dal catalog: costruisce un argv e
delega a `sweep_main` (CLI legaco) che scrive lo storico. Aggiungere un dry-run
lì significherebbe threadare il flag dentro tutto il path legacy — blast radius
alto, contro "senza rompere nulla".

**Come superato.** Sotto `dry_run`, il ramo refresh **si rifiuta**: logga un
warning e ritorna un exit code dedicato senza chiamare `sweep_main`. Meglio
rifiutare esplicitamente che simulare a metà o mutare in silenzio. `--dry-run`
copre oggi discovery e confirmation (i due path del motore nuovo); il refresh
legacy resterà coperto quando sarà strangolato in Fase 2D/3. Test
`test_run_batch_refresh_dry_run_rifiuta_e_non_chiama_sweep_main` fissa che
`sweep_main` non viene mai invocato.

**Correzione review (Codex `6f0acee..dd0a56b`).** Prima il rifiuto ritornava
`0`, indistinguibile da "eseguito con successo". Introdotta la costante
`EXIT_REFRESH_SKIPPED = 2` (0=ok, 1=errori, 2=rifiutato); `run()` la propaga e
ferma il ciclo. Stesso giro: (a) fallback di `TREASUREIQ_SWEEP_MODE` invalida
messo su `refresh` — coincide col log "uso refresh", prima impostava
`confirmation` per sbaglio; (b) `--aderenza` ora si aggancia con
`if config.aderenza:` sul path refresh (l'unico che raggiunge quel punto) — la
guardia `config.mode == "discovery"` era morta, discovery ritorna prima.

---

## 11. `coverage_score` finto 1.0 vs onesto None — RISOLTO (Fase 2B)

**Dubbio.** Il piano vuole `coverage_score` *misurato*, non hardcoded 1.0
(`confirmation.py`). Ma la confirmation non interroga il connettore: verifica
solo che l'entrypoint noto sia vivo e riconosciuto. Non ha modo di misurare
"quanta parte del contratto dati/capability è presente". Mettere una misura
inventata sarebbe peggio del problema.

**Come superato.** `coverage_score = None` (non misurata) invece di 1.0. È il
valore onesto per questa superficie; la copertura reale la calcolerà il path
refresh/connettore (slice futura, dove i dati si scaricano davvero). Verificato
che i consumer reggono None: `admin_app._bucket(None)` → "unknown". Il segnale di
aderenza che la confirmation *sì* produce è `recognition_score` + il nuovo stato
**DIFFORME** (drift della piattaforma), non una copertura fittizia.

**DIFFORME vs MANUAL_REVIEW.** Prima il drift (piattaforma cambiata) e il
non-riconosciuto collassavano entrambi su MANUAL_REVIEW. Ora sono stati distinti:
DIFFORME = riconosciuto ma difforme dal contratto persistito (l'utente voleva
"so quando un comune è difforme"); MANUAL_REVIEW = provider non riconosciuto.

---

## 12. `_aderenza` "WP-only" era stale + dove fondere — RISOLTO (Fase 2C)

**Dubbio.** Il planning §3E chiamava la misura di aderenza "WP-only" e chiedeva
"`_aderenza` oltre WP + campo unico (comune, connettore)". Ma leggendo il codice:
`censimento._aderenza` **dispatcha già** WP → `_aderenza_wp`, MyPortal (Lepida,
Veneto) → `_myportal`, PeopleWeb/ComWeb → scheda HTML via `_ROTTE_SERVIZI`.
Cinque famiglie, non una. Il "WP-only" era una descrizione invecchiata.

**Il buco reale.** Non è "misurare oltre WP" (già fatto per 5 famiglie), è che
il path **catalog** (`CheckResult`) non ha *nessuna* copertura e non esiste un
verdetto unico per (comune, connettore) che fonda recognition + coverage + drift.

**Come superato (scelta utente: "fusione in catalog").** Nuovo
`catalog/aderenza.py`: `fondi_aderenza` è una funzione **pura** che opera sul
`CheckResult` uniforme — quindi vale per tutte le famiglie senza sapere nulla di
WordPress/MyPortal — e ci innesta una copertura misurata opzionale. La misura la
continua a produrre chi la sa fare (il censimento); qui si fonde, non si misura,
per non violare "confirmation = solo liveness" e non accoppiare catalog→censimento
con fetch nuovi. `coverage_da_misura` è il ponte esplicito dalla forma dict del
censimento. Il verdetto è onesto: `None` (non uno zero) quando non riconosciuto,
difforme, o copertura non misurata.

**Non ancora agganciato a un path vivo.** Il modulo è core nuovo *accanto* al
vecchio (strangler): testato in isolamento, si aggancerà quando il refresh sarà
strangolato (2D/Fase 3). Scelta deliberata per tenere il gate verde e reversibile.

**Correzione review (Codex, 2 rilievi contrattuali).** (a) `connettore` non deve
prendere il valore dalla piattaforma: `connector_id` è il motore/plugin
(`entrypoint_confirmation`, `filodiretto_sp`) e serve stabile per admin e
versionamento, `identity["platform"]` è la piattaforma riconosciuta
(`wordpress_agid`, `comweb`). Collassarli rendeva ambigua la chiave e aggregava
connettori diversi. Fix: `connettore = check.connector_id` **sempre**, nuovo
campo separato `piattaforma`. (b) La regola "recognition sblocca la coverage"
non era davvero applicata: bastava uno stato non-pessimo, ma un `OK` con
`recognition_score=None` (possibile per `SOURCE_IDENTITY`) sbloccava il verdetto.
Fix: `riconosciuto = recognition_score is not None and recognition_score > 0`.
+2 test (`test_ok_senza_recognition_score_non_sblocca_il_verdetto`, campo
`piattaforma`); drift-test ora con recognition positivo così è il drift a
azzerare, non l'assenza di riconoscimento.

---

## 13. Wiring 2D-iii: nuovi artefatti in `data-live` + RMW stato — RISOLTO (Fase 2D)

**Dubbio.** Agganciare `EndpointState` e `fondi_aderenza` al path confirmation
aggiunge due nuovi alberi scritti in `data-live` (`stato/<surface>/` e
`aderenza/<surface>/`) e introduce un read-modify-write dello stato (leggi il
precedente → transisci → riscrivi). Rischi: (a) violare l'invariante I4
(dry-run non deve scrivere); (b) corsa se due sweep toccano lo stesso endpoint.

**Come superato.** (a) Tutto il blocco `_registra_stato_e_aderenza` sta dentro
lo stesso `if not dry_run` del `_write_check`: e2e `test_dry_run_non_scrive_
stato_ne_aderenza` prova che nessuno dei tre alberi nasce sotto dry-run. La
scrittura è atomica (tmp + `replace`), come già `_write_check`. (b) La corsa non
si materializza oggi: `run()` non sovrappone due sweep (ciclo batch→pausa,
memoria `keep sweep worker alive`) e la confirmation è per-comune sequenziale.
Se in Fase 3 lo sweep diventasse concorrente per-endpoint servirà un lock per
`(source_id, surface, entrypoint)` — annotato, non anticipato.

---

## 14. Review 2D: identità stato + politica non agganciata — RISOLTO (Fase 2D-iv/v)

Due blocking dalla review Codex `b6738a0..80c051c`.

**(iv) Identità dell'endpoint.** Il path `stato/<surface>/<id><suffix>.json`
indicizza solo `(surface, source_id, suffix)`, ma l'identità dichiarata include
`entrypoint_url`. Se l'URL AT cambiava, o cambiava l'ordine dei portali SP, il
vecchio file veniva riusato e `transiziona()` sommava i contatori del vecchio
endpoint al check del nuovo. **Fix:** `_stato_precedente` confronta
l'`entrypoint_url` persistito e ritorna `None` se non combacia → lo stato
riparte da zero. Scelta URL-compare (non hash-nel-path): risolve il mescolamento
sia per l'AT sia per il riordino SP; il costo è che due SP che si scambiano
posizione perdono entrambi la storia (raro, e comunque meglio di contatori
sporchi). Lettura dello stato spostata a monte del check. Test:
`test_confirm_url_cambiato_reinizializza_stato`.

**(v) PoliticaFetch non agganciata.** `PoliticaFetch`/`LimitatoreDominio`/
`BudgetDominio` erano core isolati: backoff/rate-limit/budget senza effetto
reale. **Fix:** `catalog/fetch_runtime.py::EsecutoreFetch` media ogni fetch —
`decidi() → (rifiuta se budget esaurito) → dormi l'attesa → fetch_guardato() →
registra()`. Il backoff è alimentato dai `fallimenti_consecutivi` dello stato
persistito, letto prima del fetch. Orologio e sleep iniettabili (test
deterministici). `confirm_inventory` accetta un `esecutore` opzionale (None =
path storico diretto, per i test unitari); `sweep_worker` ne costruisce **uno
per lotto** (budget/rate-limit sono per dominio: vanno condivisi fra i comuni
del lotto per non martellare un host SaaS comune a molti). Un rifiuto per budget
→ `_confirm_one` ritorna `None` → endpoint saltato, nessun check scritto
(diverso da irraggiungibile = UNAVAILABLE). Knob via env
(`TREASUREIQ_FETCH_INTERVALLO_DOMINIO_S`, `_BUDGET_DOMINIO`, `_BACKOFF_BASE_S`,
`_BACKOFF_CAP_S`). Test: `test_catalog_fetch_runtime.py` +
`test_budget_esaurito_salta_endpoint_niente_scritture` +
`test_backoff_alimentato_da_stato_persistito`.

**(vi) Discovery fuori dalla politica** (re-review). L'`EsecutoreFetch` era
costruito solo nel ramo confirmation: la discovery periodica
(`discover_source_inventory → fetch_guardato`) faceva fetch senza rate-limit né
budget → l'argine anti-flooding copriva solo metà del motore. **Fix:**
`discover_source_inventory` accetta un `esecutore` opzionale e vi instrada il suo
UNICO fetch di rete (la home BASE); `scopri_pagina_at` e i candidati SP lavorano
sull'HTML già scaricato, non fanno rete (verificato: nessun `fetch_guardato` in
`service_discovery.py` né dentro `scopri_pagina_at`). `sweep_worker` costruisce
l'esecutore con un helper condiviso `_nuovo_esecutore(config)` e lo passa sia a
discovery sia a confirmation (un esecutore per lotto). Budget esaurito → discovery
ritorna `None` senza scrivere inventario. Limite noto: la home BASE non ha uno
stato persistito (quello vive per AT/SP), quindi il backoff sul fetch di
discovery parte da 0 — rate-limit e budget restano gli argini attivi. Il refresh
legacy resta fuori (path da strangolare, già dichiarato). Test in
`test_catalog_inventory_discovery.py`: routing + budget-skip.

**Non bloccanti dalla review, ancora aperti (annotati):** check/stato/aderenza
scritti atomici singolarmente ma non transazionali insieme (un errore intermedio
può lasciare i tre alberi disallineati); RMW dello stato non protetto da lock
(vedi §13.b: non si materializza con lo sweep sequenziale attuale); possibile
starvation degli endpoint oltre il budget se l'ordine di visita è sempre fisso.
Tutti rilevanti solo con sweep concorrente / lotti saturi in Fase 3.

**Copertura None nel record aderenza.** Il verdetto persistito dalla confirmation
ha `coverage_score=None`/`verdetto=None` per costruzione: la confirmation misura
liveness, non copertura (vedi §11). Il record resta utile (status, drift,
recognition, fingerprint, stato endpoint); la copertura la riempirà il path
refresh/connettore quando sarà strangolato.

---

## Corner case verificati (non bloccanti)

- **`source_id`/`final_url` in scope** in `discover_source_inventory` prima
  della chiamata M1: verificato, drop-in pulito.
- **`Firma.piattaforma`** esiste e `.value` è la stringa attesa da
  `update_source_inventory`: verificato, downstream invariato.
- **Suite reversibilità**: 1167 passed bloccata come àncora prima e dopo ogni
  edit. I 3 fail PDF sono pre-esistenti (`test_wp_pages_caratterizzazione.py`),
  non toccati.
- **`extract/spike.py`**: rimosso; zero import reali (grep). Due docstring che lo
  citavano ripuntate a `.kapi/spike-d07.md` (llm.py, wp_pages.py).

---

## Sintesi per la review

Eseguito in autonomia solo il sottoinsieme **sicuro e reversibile**: M1+M2
(migrazione BASE al seam, drop-in), rimozione spike morto, doc di piano/dubbi.
Rinviato alla review tutto ciò che è **cambio di firma del seam** (C1/scattate),
**accoppiato alla demo/vetrina** (dati, docs) o **nel path chat** (Albano,
intent) — perché sono decisioni architetturali o hanno blast radius fuori dal
motore, e la consegna è *"senza rompere nulla"*.

---

## §15 — 3C-bis+ter: la flotta copre TUTTO il rail office (commit db7f056)

**Scoperta che blocca 3D letterale.** Implementando 3D pieno ho verificato che il
rail office `_risposta_da_connettore` è condiviso da OGNI piattaforma il cui
reader riempie `esito.uffici`, non solo dalle 3 famiglie flotta. Dal dispatch
`connettore.py:261-288` i reader che producono `uffici`: municipium, comweb,
peopleweb (flotta ✅), wp_design/wordpress_generico/comunibootstrapitalia
(wordpress_agid ✅), **openweb** (`openweb.py:400`), **openpa** (`openpa.py:384`),
**egov/hgate** (`egov.py:420-430`, entrambi via `leggi_egov`). Le ultime tre
famiglie NON avevano connettore v1 → rimuovere il read v0 e gating su batch
MEDIATED le avrebbe fatte cadere su web scrape: **il cittadino perde la card
uffici** su piattaforme già consegnate. Non è churn isomorfo, è regressione.

**Decisione committente (AskUserQuestion):** «Prima i connettori v1 mancanti, poi
taglio v0». Fatto in questa fetta.

**Cosa contiene la fetta.** 8 unità leaf nuove (openweb/openpa/egov/hgate ×
base/trasparenza), stessa `_projection` pura, stesso gate MEDIATED-se-record,
versionate 1.0.0 indipendenti. Registrate prima del WebScrape wildcard;
`FLOTTA_PLATFORMS` esteso a 7 piattaforme. egov+hgate in UN package (stessa
vendor family, stesso reader `leggi_egov`) ma con 4 classi leaf distinte per
onorare l'invariante «una unità per (piattaforma × superficie)».

**Semplificazione rispetto al piano.** Il piano ipotizzava per eGov «nuova
proiezione su `aree_amministrative`». Verificato che è SBAGLIATO per il rail
office: eGov riempie `esito.uffici` come gli altri (`_leggi_uffici_egov`), quindi
è la stessa `FlottaBaseConnettore`. `aree_amministrative` è un concetto di
display sull'esito di acquisizione, NON parte del rail office → nessuna superficie
nuova serve. hgate coperto perché il batch usa `esito.piattaforma` come
platform_id ("hgate") e un comune hgate risolverebbe altrimenti WebScrape.

**Dubbi aperti / da guardare in review:**
- **D-15a Trasparenza openweb/openpa/egov/hgate.** Ho aggiunto anche le unità
  `.trasparenza` (non solo `.base`) perché l'adapter flotta gate è a livello
  piattaforma: con la piattaforma in `FLOTTA_PLATFORMS` l'adapter rivendica anche
  TRANSPARENCY, e senza unità trasparenza la risoluzione connettore cadrebbe su
  WebScrape (adapter=flotta/MEDIATED ma connector=web_scrape = incoerenza). Le
  4 famiglie popolano davvero `amministrazione_trasparente`, quindi la proiezione
  è reale, non un guscio. Se si preferisse gating per-superficie nell'adapter,
  è un refactor a parte.
- **D-15b URBI/halley/jcitygov.** Restano fuori: NON hanno reader office nel
  dispatch → `esito.uffici` sempre vuoto per loro → v0 già ritorna None → nessuna
  regressione quando 3D taglierà v0. Verificato via dispatch (else → `precedente`).
- **D-15c Sprawl.** 8 file quasi-identici (leaf di 3 righe). È il prezzo
  dell'invariante «unità versionata indipendente». Se si accetta un solo modulo
  per famiglia con più classi (come ho fatto per egov/hgate) si può compattare
  openweb/openpa, ma ho preferito coerenza col pattern esistente municipium/
  comweb/peopleweb (un package per piattaforma).

**Gate.** Suite piena: 1269 passed, 6 skipped, 3 fail PDF pre-esistenti
(`test_wp_pages_caratterizzazione.py`, non toccati). Test parità+risoluzione
estesi a tutte e 7 le piattaforme (58 nei 3 file catalog).

**Prossima fetta 3D** ora sbloccata senza regressione: ogni piattaforma del rail
office risolve un batch MEDIATED, quindi si può riscrivere `_risposta_da_connettore`
per decidere sulla DataBatch e rimuovere il read v0 `esito.uffici`.

---

## §16 — 3D pieno: la scheda ufficio si decide sulla DataBatch (commit segue)

**Cosa cambia.** `_risposta_da_connettore` non legge più `esito.uffici` diretto:
la lettura uffici su cui DECIDE arriva ora attraverso il contratto v1
(`_batch_offices_decisione` → `CatalogRuntime().execute`). Gate: batch assente o
`access_mode != MEDIATED` → `None` (ripiego web, invariato). Gli uffici si
ricostruiscono con `UfficioConnettore.model_validate(record)` dai record del
batch e la selezione/render esistente gira invariata. `access_mode` emesso =
`offices_batch.access_mode.value` = `"mediated"` (vocabolario catalog), non più
la stringa M-ladder `M4_connettore`.

**Perché è sicuro (parità).** Per flotta/wordpress la proiezione legge
`esito.uffici`, quindi `access_mode MEDIATED ⇔ record presenti ⇔ esito.uffici
non vuoto`: il gate batch coincide col vecchio `if not esito.uffici`. Con
3C-bis+ter ogni piattaforma del rail office (municipium/comweb/peopleweb/openweb/
openpa/egov/hgate + wordpress) risolve un connettore MEDIATO → nessuna
regressione. URBI/halley/jcitygov non hanno reader office → `esito.uffici`
sempre vuoto → il ramo non li serviva prima e non li serve ora.

**Tre trappole gestite.**
1. **Troncamento.** La batch decisione usa `RequestLimits(max_records=10_000)`
   (model_copy dopo la costruzione, qualunque sia la fonte della richiesta),
   NON il cap 100 della telemetria: l'organigramma completo, come nel rail v0.
2. **Mappa cache-miss.** `_da_cache` che manca non fa più sparire la scheda:
   sintetizzo una `MappaConnettore` minima (`codice_istat`+`nome`+`sondato_il`,
   `sito=None`) — il connettore flotta legge solo `mappa.codice_istat`.
3. **Display vs decisione.** Il dump di display (`esito_connettore=esito_mostrato`)
   resta esito-based: conserva `amministrazione_trasparente`/`aree_amministrative`
   (non proiettati nel batch office). La DECISIONE è batch, il DISPLAY è
   l'artefatto di acquisizione. Onesto e senza perdita di campi.

**Vocabolario access_mode — chi flippa e chi NO.**
- FLIP (6 assert → `CatalogAccessMode.MEDIATED.value`): SOLO la scheda ufficio
  decisa dal connettore, in `test_innesto_connettore.py` (3 assert + docstring).
- NON flippato (correzione al piano): `test_ricerca_live.py` 185/200/217 NON sono
  la scheda ufficio — sono answer di **ripiego web** con `leggi_connettore=None`,
  che ereditano il label M-ladder `M4_connettore` dall'**ente** (Ciampino ente
  M4). 3D non tocca quel path → restano `AccessMode.M4_CONNETTORE.value`. Il piano
  li elencava per errore come «answer asserts» del connettore.
- NON flippato: `respond.py` ~2520 (answer `not_published`, no office/dump) resta
  `M4_CONNETTORE` — non è deciso sul batch; e `test_e2e_chat_live.py:131`
  classifica proprio quell'answer, quindi resta invariato. L'answer ufficio
  (mediated) passa per i rami `UFFICIO`/`ELENCO` (office/esito_connettore
  presenti), mai per la scala access_mode.

**Dubbi aperti.**
- **D-16a Doppia esecuzione offices.** La batch decisione (limite alto) e la
  telemetria `_data_batches_da_connettore` (cap 100) eseguono entrambe offices.
  La telemetria è inerte (non serializzata al client) → l'ho lasciata intatta
  per blast radius minimo. Si potrebbe far coincidere `selected_data_batch` con
  la batch decisione, ma è ottimizzazione su codice inerte: rinviata.
- **D-16b Gate e2e non eseguibile qui.** `test_e2e_chat_live.py` (TREASUREIQ_E2E=1)
  è uno strumento live: scrive in LIVE_DIR (`/live`, read-only nel container di
  test) e fa rete verso comuni+LLM. Non è un gate CI in questo harness. La
  classificazione del ramo connettore nell'e2e dipende da office/esito_connettore
  (preservati), NON da access_mode → 3D non ne cambia i verdetti. Va rieseguito
  a demo-time. Suite offline piena: 1269 passed, 3 fail PDF pre-esist.

---

## §17 — 3E esecutore SERVICE_PORTAL (additivo, 0 chiamanti chat)

**Cosa.** Cablato il seam mancante per la surface SERVICE_PORTAL: un
`service_portal_request` ora risolve davvero via `CatalogRuntime`. Due pezzi:
- `catalog/service_portal_connector.py` → `ServicePortalConnettore`
  (name "service_portal"): `supports` = `surface is SERVICE_PORTAL`; `retrieve`
  carica la `SourceInventory` persistita (`LIVE_DIR/inventario/{id}.json`),
  matcha il `service_id` (= URL del candidato, unica chiave stabile: i candidati
  non hanno id proprio) e proietta UN record-puntatore senza credenziali
  (url, label, role, auth accettate, capabilities, provider, source_url).
- `catalog/adapters/service_portal.py` → `ServicePortalAdapter`: manifest
  `("*",)` × (SERVICE_PORTAL, "authenticated_service", INDIRECT), fa da GATE per
  `CatalogRuntime.execute` (che costruisce il batch dal `ConnectorResult`, non
  chiama `adapter.read`; `read` c'è per parità e non inventa record).

**access_mode = INDIRECT (scelta).** TIQ indica il portale ufficiale ma NON
autentica e NON media i dati dietro login: né MEDIATED (implicherebbe recupero
mediato) né DIRECT. INDIRECT = puntatore onesto. `requires_authentication=True`
e limitation esplicita "l'autenticazione resta al cittadino".

**Miss onesto.** Inventario assente o `service_id` non tra i portali confermati
→ `NOT_FOUND`, `records=()`, nessuna URL indovinata.

**Trappola risolta (fallback wildcard).** Sia `web_scrape` sia SP hanno
`platforms=("*",)`. `AdapterRegistry.fallback_requests_for` ritorna il PRIMO
adapter wildcard: registrando SP PRIMA di web_scrape, l'ignoto ripiegava su
`authenticated_service` (rotto `test_fallback_requests_are_explicit_for_unknown_platform`).
Fix: SP registrato DOPO web_scrape → web_scrape resta l'unica rotta di scrape
fallback; `resolve` per SERVICE_PORTAL è comunque indipendente dall'ordine
(web_scrape non rivendica quella surface). Pinnato da
`test_service_portal_is_never_a_scrape_fallback`. Vincolo d'ordine annotato nel
commento di `adapters/defaults.py`.

**Nessuna collisione.** web_scrape connector `supports` solo
{services,offices,contacts,transparency} → non intercetta SERVICE_PORTAL; il
connettore SP è quindi order-free nel registry connettori.

**Fuori scope (invariato, §5).** Nessun retrieval live multi-vendor, nessun
login, nessun fetch di rete: SP legge solo l'inventario già scoperto. Il
wiring chat (recognition sceglie il `service_id`, la chat chiama l'esecutore) è
il passo successivo, deliberatamente 0 chiamanti in 3E.

**Dubbi aperti.**
- **D-17a service_id = URL.** Chiave stabile ma fragile se il portale cambia
  URL; alla riscansione l'inventario si aggiorna, il vecchio id non matcha più
  (→ NOT_FOUND corretto, non un puntatore stantìo). Un id sintetico stabile
  (hash host+role) è possibile ma richiede persistere l'id nel candidato: rimandato.
- **D-17b freshness da updated_at.** Il batch porta `retrieved_at=inventory.updated_at`
  con status FRESH; la valutazione vs policy età non è fatta qui (come per gli
  altri connettori). Onesto perché il batch espone updated_at a valle.
- **D-17c capability singola.** Solo "authenticated_service". appointment/
  online_service come capability distinte si aggiungono al manifest quando il
  wiring chat le distinguerà.

**Gate.** Suite offline 1277 passed, 6 skipped, 3 fail PDF pre-esist.
