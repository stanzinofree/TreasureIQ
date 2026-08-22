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
