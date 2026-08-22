# Rewrite pulito: Source Engine — piano

Stato al 2026-08-22. Branch `refactor/source-engine` (da `perf/accumula-...`, HEAD
`81abfd0`). `main` **congelato** finché l'utente non lo dichiara stabile: qui si
lavora, mai push/merge su main. Baseline verde bloccata: suite Docker **1167
passed**, 6 skipped, 3 failed (i 3 PDF pre-esistenti). Àncora reversibilità.

Strategia: **strangler incrementale**. Nuovo core accanto al vecchio, migrazione
seam per seam, ogni fase verde e reversibile. Niente big-bang su repo consegnato.
Validato da doppia review Fable (analisi stato + inventario pulizia).

---

## 1. Obiettivo end-state — invarianti verificabili

Il rewrite è finito quando **tutte** queste sono vere e coperte da test:

- **I1 — Plugin recognition = 1 file + 1 riga.** Aggiungere un riconoscimento
  BASE/AT/SP tocca solo `plugins/recognition/<surface>/<nuovo>.py` + una riga nel
  builder del registry. Zero altri file. *Guard test:* nessun modulo di produzione
  importa `classifica_risposta`/`firma_da_risposta`/`scopri_pagina_at` fuori dal
  bridge/adapter.
- **I2 — Connettore isolato.** Scrivere/cambiare un connettore non tocca il codice
  comune dell'engine né gli altri connettori. Lo sweep non richiede modifiche al
  core quando cambia un connettore.
- **I3 — Contratto chat→connettore universale.** La chat chiede servizi con un
  contratto unico e standardizzato, invariante al numero/tipo di connettori. Un
  nuovo connettore non cambia le firme che la chat consuma.
- **I4 — Sweep sicuro.** Lanciabile senza mettere mani al codice: `--dry-run` non
  scrive mai `data-live`; esito uniforme (`CheckResult`); retry/backoff/rate-limit;
  stato per superficie+entrypoint; nessuna mutazione dati senza guardia.
- **I5 — Aderenza reale per comune.** Lo sweep registra un livello di aderenza al
  connettore per (comune, superficie), così il sistema sa quando un comune è
  **DIFFORME/drifted** — non un flag WP-only, ma tutte le famiglie.
- **I6 — Niente dati fissi in produzione.** Nessun fallback comune hardcoded
  (Albano/Ciampino), nessun seed MVP nel path di produzione, nessuna cache runtime
  versionata come fixture. Solo dati di riferimento nazionali + output sweep.

---

## 2. Stato reale (correzioni all'analisi Codex)

Codex sostanzialmente accurato (13/15). Tre correzioni registrate:

1. Fix SP recognition **committata** (`81abfd0`), non nel working tree.
2. La confirmation SP **già persiste** l'identità nativa versionata nel check
   envelope (`confirmation.py:98-108`): la "SP recognition attiva" è già parziale.
3. Il vocabolario stato/azione/outcome **esiste già** (`catalog/checks.py`:
   `CheckResult`/`CheckStatus`/`RecognitionAction`); manca l'adozione worker-wide.

Doppio binario reale oggi: `censimento`/`inventory_discovery` chiamano il
classificatore legacy diretto; `connettore`/`confirmation` passano dal registry.

---

## 3. Inventario di pulizia

### 3A. Comuni statici / dati fissi (→ I6)

| File:riga | Cosa | Azione |
|---|---|---|
| `chat/respond.py:128-129` | `DEFAULT_COMUNE_ISTAT="058003"` / `="Albano Laziale"` (fallback centrale, usato a 442/1647/3427-3436/4261) | **REMOVE** |
| `chat/respond.py:1227` | alias `"058003": (("albano",),)` | MIGRATE → registro |
| `chat/respond.py:3925` | testo "URP del Comune di Albano Laziale" | REMOVE |
| `api.py:143-146` · `ingest/__main__.py:40-48` | seed hardcoded 058003→albano | MIGRATE → data-driven |
| `stats.py:114-129` | centroidi hardcoded Albano/Fonte Nuova | MIGRATE → `data/comuni-istat.json` |
| `chat/intent.py:13,39,72,379,557` | tassonomia + prompt "Albano seed" | MIGRATE comune-agnostic (prereq I3) |
| `ingest/wp_pages.py` | connettore "for Albano's WordPress" (per-comune) | MIGRATE → plugin famiglia WP |
| `extract/spike.py` | tool spike one-off MVP su Albano | **REMOVE** |
| `ingest/popola_cache.py:36` | `DEFAULT_COMUNI=("Albano","Fonte Nuova")` | VERIFICA (tool morto?) |
| `readiness.py`, `match/engine.py`, `wp_comuni.py` | Albano nei docstring come misura | KEEP (evidenza) |

Dati versionati:
- `data-live/connettore/` = 4075 JSON runtime, **9 versionati** in git (snapshot demo
  congelati) → **de-versionare i 9**; dir resta cache non tracciata.
- `data/seed/*.json` (9 file MVP) caricati da `api.py:146` → MIGRATE a fixture, via
  dal path produzione.
- `data/extraction-cache/`, `data/websearch-cache/` (22 file) → de-versionare.
- `data/storico.db` → **KEEP** (decisione committente, non riaprire).
- `data/comuni-istat.json`, `ipa-recapiti.json`, `enti.json`, `censimento-t0.json` → KEEP.

### 3B. Matrice call-site recognition (→ I1)

5 call-site legacy diretti, 3 moduli. Piccola: strangolabile in un passo.

| Call-site | Chiama | Superficie | Azione |
|---|---|---|---|
| `connettore.py:499` | `scopri_pagina_at` | retrieval AT inline | MIGRATE → seam |
| `censimento.py:1071` | `firma_da_risposta` | sweep BASE | MIGRATE (adapter drop-in) |
| `censimento.py:1086` | `scopri_pagina_at` | sweep discovery AT | MIGRATE |
| `inventory_discovery.py:57,60` | `classifica_risposta`+`scopri_pagina_at` | discovery (codice nuovo che bypassa il registry!) | MIGRATE (priorità) |
| `censimento.py:599-632` | def `scopri_pagina_at` (usa `classifica_risposta`) | impl legacy | → corpo wildcard plugin, poi REMOVE |
| `piattaforma.py:424,622` | def `classifica_risposta`/`firma_da_risposta` | motore firme v1 | KEEP dietro il bridge |

`classifica_risposta` NON si cancella (classificatore condiviso): resta avvolto dal
bridge (`recognition_bridge.py:73-97`).

### 3C. Documenti

REMOVE: `docs/architettura.md` (12 ago, pre-catalog), `docs/da-fare.md` (todo
consegnato). MERGE in un doc motore unico: `roadmap.md`, `evoluzione.md`,
`connettori.md`. VERIFICA post-rewrite: `flusso-chat.md`, `sicurezza.md`,
`motore-dati.html`. KEEP: `api.md`, `piano-v1.md`, `framework-plugin-riconoscimenti.md`,
`architettura-flussi-discovery-sp.md`, `genesi.md`, workstreams attivi.

### 3D. Moduli da strangolare

- **`chat/respond.py` — 4516 righe, 6 responsabilità fuse.** Da estrarre per primo
  il layer connettore (resp. 5 lettura connettore/catalog + 6 composizione+DTO,
  ~1500 righe): è il contratto chat→connettore (I3).
- **`ingest/censimento.py` — 1834 righe.** recognition BASE + discovery AT + misura
  aderenza (WP-only) + estrazione uffici/orari + promozione piattaforma.
- **`connettore.py` — 585 righe.** dispatch+refresh + store triplo + discovery AT
  inline. Gating `_esito_vuoto:136` = predicato cieco già morso → derivare dal
  contratto, non enumerare.
- Duplicato: `scopri_pagina_at` in censimento chiamato da 3 superfici, zero registry.

### 3E. Aderenza — cosa c'è, cosa manca (→ I5)

Esiste in 3 pezzi scollegati:
1. Misura: `censimento.py:826 _aderenza` + `:946 _aderenza_wp` — **WP-only**.
2. Persistenza: `storico.py:109` colonna `aderenza`, `:614 aderenza_fornitori`.
3. Motore nuovo: `checks.py:32-38` `completeness/recognition/coverage_score` +
   `fingerprint`; `confirmation.py` drift-check → `platform_changed`;
   `drift.py DriftKind` con `PLATFORM_CHANGED`/`CONNECTOR_DEGRADED`.

Manca:
- `coverage_score` hardcoded 1.0 (`confirmation.py:123`); `recognition_score`
  binario 1.0/0.0 sul path legacy → non sono misure.
- Nessuno stato **DIFFORME** in `CheckStatus`; i `DriftEvent` non confluiscono nel
  `CheckResult`.
- Aderenza censimento (per-modello, WP-only) e score catalog (per-fingerprint) non
  si parlano → serve un campo unico per (comune, connettore) che fonda
  recognition + coverage misurata + drift, per **tutte** le famiglie.

---

## 4. Fasi (ognuna con exit-gate verde)

### Fase 0 — Pulizia base + freeze contratti (rischio ~nullo) ✅ in corso
- [x] Push `perf/...` → origin; branch `refactor/source-engine`; baseline lock 1167.
- [x] Doc "stato reale" (questo file) + matrice call-site + inventario.
- REMOVE tool morti: `extract/spike.py`, archivia `popola_cache.py`.
- REMOVE/MERGE doc obsoleti (3C).
- De-versionare i 9 JSON congelati + cache in `data/` (3A).
- **Exit-gate:** suite verde a 1167; niente più cache runtime tracciata; docs snelli.

### Fase 1 — Seam unico recognition (uccide ripple, → I1)
- Characterization test su ognuno dei 5 call-site (fissa comportamento attuale).
- Migra i 5 al seam `recognition_adapter` (`firma_da_registro`/`riconosci_service_portal`).
- Guard test I1 (nessun import legacy diretto in produzione).
- **Exit-gate:** suite verde; nuovo plugin = file + 1 riga dimostrato con un plugin
  di prova aggiunto e rimosso senza toccare altro.

### Fase 2 — Sweep sicuro + aderenza (→ I4, I5)
- Worker consuma `CheckResult`/`RecognitionAction` end-to-end.
- `--dry-run` (mai scrive `data-live`) + guardia mutazione dati.
- Stato per superficie+entrypoint (`EndpointState`), transizione calcolata dal core.
- retry/backoff/rate-limit per dominio + budget.
- Aderenza unificata: `_aderenza` oltre WP, `coverage_score` misurato (non 1.0),
  stato DIFFORME in `CheckStatus`, `DriftEvent`→`CheckResult`, campo unico
  (comune, connettore).
- **Exit-gate:** sweep su comune fixture → transizioni asserite + zero write non
  protette + aderenza calcolata per famiglia non-WP.

### Fase 3 — Contratto chat→connettore universale (→ I2, I3)
- Estrai da `respond.py` il layer connettore (resp. 5+6) dietro `SourceConnector`
  Protocol + `DataRequest`/`DataBatch` uniformi.
- Esecutore SP: `service_portal_request` → connettore (oggi zero chiamanti).
- Capability catalog minimo: superficie→entrypoint→piattaforma→capability→access_mode.
- `chat/intent.py` comune-agnostic.
- **Exit-gate:** e2e chat (suite PR #22) verde; aggiungere un connettore fittizio
  non cambia nessuna firma consumata dalla chat.

### Fase 4 — Freeze stato pulito → poi CHAT
- Re-review Codex+Fable; doc motore unico; tag baseline pulita.
- Rimozione definitiva del path legacy strangolato.
- **Exit-gate:** tutte le invarianti I1-I6 coperte da test. Da qui: lavoro CHAT.

---

## 5. Fuori scope (nord, non progetto ora)

Source Intelligence Engine monolitico big-bang; SP retrieval live multi-vendor
completo; PDF/OCR engine; admin dashboard; merge su main. Restano direzione futura.
