# T2 SP — done / handoff

Stato al 2026-08-21. Branch `perf/accumula-filtri-cache-intent-rust`, mai su main.
Piano: `planning.md` (confirmation-only, approvato). Locale per review Codex.

## Fatto — chiude la metà SP di P1 #1 sul path di produzione

| Passo | Cosa | Commit |
|---|---|---|
| Piano | `planning.md` — registry SP native-only, seam separata, confirmation-only | `af1cbd1` |
| Impl | seam + registry SP + cablaggio `_confirm_one` + test | `d306b46` |

- `recognition_bridge.build_service_portal_registry()` — registry coi **soli
  plugin SP nativi** (`municipium_portalegen`, `filodiretto`), **niente bridge**:
  su SP il bridge è cieco a filodiretto e rivendica l'id BASE `municipium` su una
  pagina portalegen senza l'asset. Native-only tiene ogni id BASE fuori da SP.
- `recognition_adapter.riconosci_service_portal()` → `RiconoscimentoSP` — seam
  che ritorna l'id nativo come stringa, **mai `Firma`**. Riconoscimento
  **indipendente** dall'atteso: passarlo come `hint` al registry filtrerebbe via
  il plugin del vendor reale e il drift non sarebbe mai visibile. `firma_da_registro`
  resta BASE/AT-only e continua a rifiutare SP (Gate 0 intatto).
- `confirmation._confirm_one` ramo SERVICE_PORTAL (additivo): match → identità
  nativa + drift (`platform_changed` → REDISCOVER); miss → comportamento di oggi
  (trust `provider_hint` + liveness), mai declassamento.

Suite Docker: **1166 passed**, 6 skipped, 3 failed (i 3 PDF pre-esistenti).

## Guardrail verificati (test)

- pagina Municipium con solo `container-municipium-agid`, **senza** asset
  portalegen → `None`, **non** `municipium` (il bridge-BASE non contamina SP);
- portalegen reale → `municipium_portalegen` 0,995; filodiretto reale (anche con
  rotta nell'entrypoint URL) → `filodiretto`; HTML generico → `None`;
- `_confirm_one` SP: match+combacia → OK/KEEP; drift → `platform_changed`/
  REDISCOVER; miss → envelope di oggi invariato; `confirm_inventory` e2e scrive
  `check/service_portal/<id>-0.json` con `platform` nativo.

## Non fatto — follow-up

- **Discovery-time stamping** di `ServicePortalCandidate.platform_id` /
  `fingerprint` / `recognition_status` (i campi esistono, mai popolati): richiede
  fetch-per-candidato in `discover_service_portal_candidates` (oggi fetch-free).
  Rimandato per scelta.
- **C1** (`scopri_pagina_at`) resta fuori, come da T2 A+B.
