# Workstream T2 — cablaggio registry di riconoscimento

Workstream condiviso tra Codex e Claude per portare in produzione i plugin di
riconoscimento nativi: i caller che oggi chiamano diretto `classifica_risposta`
per SELEZIONARE il connettore passano a `build_recognition_registry()`.

Chiude P1 #1 della review Codex `ce3bc6c..1e7a569` (registry non cablato al
runtime). Prerequisiti già a posto sul branch `perf/accumula-filtri-cache-intent-rust`:
7 plugin nativi attivi + soppressione Passo C (`_RETIRED_TO_NATIVE`) + fix
None-su-miss (`fa80e09`).

## Regola di base

Un agente lavora su un solo call site alla volta. Non modifica il runtime finché
il passo non ha criterio di accettazione (suite verde in mezzo). Commit separati,
mai su `main` (repo freeze), trailer co-author.

## Artefatti

- `planning.md` — piano eseguibile completo (adapter + 3 call site + rischi).
- `done.md` — handoff/stato via via che i passi chiudono.

## Decisione presa

- **C1**: `scopri_pagina_at` (censimento) NON si cabla — è ingestion/diagnostica
  dove `scattate` conta, fuori dal path che il cittadino vede. P1 #1 chiude su
  A (confirmation) + B (connettore).

## Non-obiettivo

NON toccare `classifica_risposta`: resta il classificatore condiviso (24 caller).
Il registry lo avvolge via bridge, non lo sostituisce.
