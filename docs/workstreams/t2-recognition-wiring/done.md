# T2 — done / handoff

Stato al 2026-08-21. Branch `perf/accumula-filtri-cache-intent-rust`, mai su main.

## Fatto (A + B) — chiude P1 #1 sui path di produzione

| Passo | Cosa | Commit |
|---|---|---|
| Adapter | `catalog/recognition_adapter.firma_da_registro` + `test_recognition_adapter.py` | `ef2f5dc` |
| A | `confirmation._confirm_one` classifica AT via registry | `ef2f5dc` |
| B | `connettore.leggi_connettore` dispatch BASE via registry | `a2a2c9f` |

L'adapter mappa `RecognitionMatch | None` → `Firma` legacy: enum via
`Piattaforma(platform_id)`, `prova` sintetizzata dalla prima `FingerprintEvidence`
con `matched=True`, miss (`None`) → `Firma(IGNOTA, None)`. Registry costruito una
volta a modulo. `classifica_risposta` intatto (il registry lo avvolge via bridge).

**Review Codex `fa80e09..HEAD`: APPROVATO**, nessuna correzione richiesta. Unica
nota non-bloccante chiusa: manca(va) un test dell'envelope AT intero prodotto da
`_confirm_one` dopo il cambio adapter. Aggiunto `tests/test_catalog_confirmation.py`
(5 test, registry reale, solo il fetch stubbato): envelope riconosciuto+atteso-OK,
drift piattaforma (`platform_changed` → REDISCOVER), miss (`provider_not_recognized`
→ MANUAL_REVIEW), entrypoint irraggiungibile, e un `confirm_inventory` end-to-end
che scrive e rilegge il check da disco.

Suite Docker: **1152 passed**, 6 skipped, 3 failed (i 3 PDF pre-esistenti in
`test_wp_pages_caratterizzazione`, non correlati, limite OCR/size dell'ambiente).

## Gate 0 rispettato

L'adapter **rifiuta `Surface.SERVICE_PORTAL`** con `ValueError`: gli ID SP nativi
`municipium_portalegen`/`filodiretto` non sono membri di `Piattaforma`, e un
degrado silenzioso a IGNOTA perderebbe l'identità del portale. Test dedicato:
`test_service_portal_is_refused_not_degraded_to_ignota`.

## Trappola registrata — ciclo di import

`catalog/__init__` importa `connettore` (via `adapters.base.EsitoConnettore`).
Un import `treasureiq.catalog.*` in cima a `connettore.py` crea un ciclo
(`EsitoConnettore` non ancora definito → ImportError). Fix: import locale dentro
la funzione di dispatch. Conseguenza per i test: patchare
`recognition_adapter.firma_da_registro` (modulo sorgente), non
`connettore_mod.firma_da_registro`.

## Non fatto — per un workstream successivo

- **C1**: `scopri_pagina_at` (censimento) NON cablato. Ingestion/diagnostica dove
  `firme_scattate` conta; il registry non produce `scattate`. Resto onesto.
- **SP wiring**: bloccato. Sblocco = estendere il vocabolario SP (aggiungere gli
  ID SP a `Piattaforma` e ai consumer) **oppure** un adapter SP che restituisca
  il contratto catalogo senza passare per `Firma`/`Piattaforma`.
- **Review Codex** del range `fa80e09..HEAD`.
