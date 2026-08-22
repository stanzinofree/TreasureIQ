# Motore unico — architettura di arrivo

Stato: **Fase 4 chiusa**. Baseline pulita al tag `baseline-source-engine-v1`
(questo commit). Documento di riferimento del motore dopo lo strangler: com'è fatto,
quali invarianti lo tengono, quale test presidia ciascuna. Non è un piano — il
piano è `planning.md`; qui c'è l'end-state.

Suite offline al tag: **1282 passed, 6 skipped, 3 fail PDF/OCR pre-esistenti**
(baseline documentata, non regressione).

---

## 1. La forma del motore

Un solo motore, tre stadi in fila, nessun path v0 parallelo sopravvissuto:

```
riconoscimento  →  connettore (per piattaforma × superficie)  →  contratto chat
   (plugin)          (flotta, isolati)                            (CatalogRuntime)
```

- **Riconoscimento.** Un plugin per (superficie, prodotto):
  `plugins/recognition/<surface>/<nome>.py` + una riga di registro. Le firme
  legacy (`classifica_risposta`/`firma_da_risposta`/`scopri_pagina_at`) vivono
  solo dietro il bridge/adapter, mai in produzione diretta.
- **Connettore.** Ogni piattaforma è un'isola sotto `catalog/flotta/<piattaforma>/`.
  Condivide solo il contratto (`_base`, `_projection`, `catalog.contracts`), mai
  un fratello. L'unico modulo che li conosce tutti è l'aggregatore
  `flotta/__init__.py` (`flotta_connectors()`).
- **Contratto chat.** La chat non tocca `esito.uffici`: chiede dati via
  `DataRequest`/`DataBatch` a `CatalogRuntime`, che risolve connettore+adapter,
  applica il gating d'accesso (`AccessMode`) e la freschezza. La telemetria v1
  (`data_batches`/`query_plan`/`selected_data_batch`) è prodotta a ogni turno —
  seam di migrazione, ancora non letta da `ChatOut` (scelta, non codice morto).

Confine onesto diretto-vs-web: dove il connettore legge davvero il dato
strutturato serve `MEDIATED`/`DIRECT`; dove non c'è, `INDIRECT` punta al portale
(mai un verdetto inventato), `UNAVAILABLE` dice «non servito».

---

## 2. Invarianti → test

| Inv | Cosa garantisce | Presidio |
|-----|-----------------|----------|
| **I1** | Riconoscimento = 1 file + 1 riga; nessun import legacy fuori dal bridge | `test_recognition_seam_guard.py` (contenimento AST). Parte «diff 1-file+1-riga» = gate di review, non unit test. Parità plugin↔bridge: `test_catalog_recognition_bridge.py`, `test_recognition_adapter.py`, i `test_plugin_*_recognition.py` |
| **I2** | Connettore isolato: cambiarne uno non tocca né il core né altri connettori | `test_i2_connector_isolation.py` (2 archi AST: nessun import fratello; il core non importa connettori concreti). Dispatch per-piattaforma: `test_catalog_connector_registry.py`, `test_catalog_flotta.py` |
| **I3** | Contratto universale chat→connettore via DataRequest/DataBatch/CatalogRuntime | `test_chat_catalog_route.py`, `test_catalog_runtime.py`, `test_catalog_planner.py`, `test_catalog_contracts.py`, `test_catalog_data_contracts.py`, `test_catalog_service_portal_executor.py`, `test_chat_recognition_contract.py` |
| **I4** | Sweep sicuro: `--dry-run` non scrive mai, `CheckResult` uniforme, retry/backoff/rate-limit, stato per superficie+entrypoint | `test_sweep_dry_run.py` (dry-run-non-scrive con controprova su discovery/refresh/confirmation), `test_catalog_confirmation_wiring.py` (stato+budget+backoff), `test_catalog_endpoint_state.py`, `test_catalog_fetch_policy.py`, `test_sweep_worker.py` |
| **I5** | Aderenza reale per (comune, superficie), anche famiglie non-WP | `test_catalog_aderenza.py`, `test_catalog_sweep_bridge.py`, `test_catalog_sweep_import.py`, `test_catalog_drift.py`, `test_catalog_service_discovery.py` |
| **I6** | Nessun dato fisso in produzione: nessun ripiego hardcoded su un comune | `test_i6_no_hardcoded_comune.py` (tripwire AST: vieta `x or DEFAULT_COMUNE_*` e `== DEFAULT_COMUNE_*`, non la costante) |

### Nota I6 — cosa NON vieta

`DEFAULT_COMUNE_ISTAT`/`DEFAULT_COMUNE_NOME` esistono ancora: sono l'identità del
comune demo (Albano). Leciti: la definizione, e il `return DEFAULT_COMUNE_ISTAT,
DEFAULT_COMUNE_NOME` di `_resolve_comune` quando il cittadino **nomina** Albano
(risoluzione identità, non sostituzione). Vietate le due forme di ripiego. I tre
siti rimossi in Fase 4:

1. `_risposta_bandi` — niente `or DEFAULT`; senza comune si chiede.
2. gate `_build_informazione_answer` — sostituito da filtro di proprietà
   `_appartiene_all_ente`: un `COMUNALE` combacia solo se
   `source.ente_codice_istat == ente.codice_istat`; NAZIONALE/REGIONALE valgono
   per tutti (regione già filtrata a monte).
3. handler `/chat` agevolazione — input a vuoto ⇒ `records=[]`, non Albano.

---

## 3. Cosa resta fuori

- **Merge su main**: fuori scopo (`planning.md` §5). La baseline vive su
  `refactor/source-engine`, congelata al tag.
- **Wiring chat → service_id → executor SP**: il seam SERVICE_PORTAL è cablato e
  testato (`test_catalog_service_portal_executor.py`) ma senza chiamante in chat.
  È il prossimo lavoro (CHAT), non parte del motore-di-arrivo.
- **I1 «diff 1-file+1-riga»**: proprietà di processo, presidiata dalla review, non
  da un test (una metrica di diff-size sarebbe fragile).

Dettaglio decisionale e corner case: `doubts.md` (§18 pulizia, §19 exit-gate).
