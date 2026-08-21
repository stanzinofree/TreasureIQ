# T2 — Cablare `build_recognition_registry()` in produzione

**Obiettivo:** i 3 caller che oggi chiamano diretto `classifica_risposta` /
`firma_da_risposta` per SELEZIONARE il connettore o classificare una superficie
passano a `build_recognition_registry().recognize(...)`. Così i 7 plugin nativi +
la soppressione Passo C diventano il path di riconoscimento reale, non infra
inerte (chiude P1 #1 della review Codex `ce3bc6c..1e7a569`).

**Non-obiettivo:** NON toccare `classifica_risposta`. Resta il classificatore
condiviso (24 caller); il registry lo avvolge via il bridge, non lo sostituisce.
Gli altri consumatori di `classifica_risposta` (raffinazione WordPress,
`impronta_grezza`, i runner interni a `piattaforma.py`) restano invariati.

## Gate 0 — vocabolario SP prima dell'adapter

La forma legacy `Firma` può rappresentare solo valori dell'enum
`ingest.piattaforma.Piattaforma`. I plugin nativi SP già attivi restituiscono
invece `municipium_portalegen` e `filodiretto`, che non sono membri dell'enum.
Un adapter generico BASE/AT/SP che facesse soltanto
`Piattaforma(match.result.platform_id)` trasformerebbe quei riconoscimenti in
`IGNOTA`, perdendo l'identità del portale senza errore.

Decisione T2: il primo adapter e il primo wiring coprono **solo BASE e AT**.
Il wiring del surface `SERVICE_PORTAL` resta bloccato fino a una decisione
esplicita su uno dei due contratti compatibili:

1. aggiungere gli ID SP al vocabolario condiviso e ai relativi consumer; oppure
2. introdurre un adapter SP che restituisca il contratto catalogo
   `platform_id` senza convertirlo in `Firma`/`Piattaforma`.

Non è accettabile usare `try/except ValueError → IGNOTA` come comportamento
normale per SP: quello è un fallback di difesa per dati corrotti o plugin
malformati, non una politica di compatibilità.

---

## Vincolo di forma (il cuore del lavoro)

Legacy e registry hanno contratti diversi. L'adapter deve fare da ponte:

| | Legacy | Registry |
|---|---|---|
| ritorno | `ClassificaFirme(vincitore: Firma, scattate: list[FirmaScattata])` | `RecognitionMatch \| None` |
| piattaforma | `Firma.piattaforma` → `Piattaforma` (enum) | `match.result.platform_id` → `str` (== `Piattaforma.value`) o `None` |
| prova | `Firma.prova` → `str \| None` (prosa umana) | nessuna; c'è `result.evidence` (tuple `FingerprintEvidence`) + `result.fingerprint` |
| runner-up | `scattate` → `list[FirmaScattata]` (diagnostica) | nessun equivalente |
| miss | `Firma(Piattaforma.IGNOTA, None)` | `None` (score ≤ 0 → None, fix `fa80e09`) |

Tre perdite di fedeltà da gestire ESPLICITAMENTE:
1. **enum ↔ str**: `Piattaforma(platform_id)` ricostruisce l'enum; `None` →
   `Piattaforma.IGNOTA`. Su BASE/AT ogni `platform_id` emesso (bridge + nativi)
   è un valore valido di `Piattaforma`; il `try/except ValueError → IGNOTA` è
   rete difensiva su dati corrotti, non politica di compat (per SP vedi Gate 0,
   dove il surface è rifiutato a monte, non convertito).
2. **prova**: il nativo non produce `prova`. Sintetizzarla dall'evidence vincente
   (es. `descrizione` della prima `FingerprintEvidence` con `matched=True`, o
   `key: observed`). Degrada per le 5 famiglie migrate; accettabile perché
   `prova` è diagnostica, MA va sintetizzata, non lasciata `None`.
3. **scattate**: nessun equivalente nel registry. Vedi call site C (unico che la
   usa) per la decisione.

### includi_at è implicito nella surface — NON passarlo all'adapter
`includi_at=False` (BASE, escludi famiglia AT) vs `includi_at=True` (AT) oggi è
un flag esplicito. Nel registry è codificato nella **surface**:
`ORDINARY_DATA` = BASE, `TRANSPARENCY` = AT, `SERVICE_PORTAL` = SP.
**PRIMA di scrivere l'adapter, Codex verifica** in `recognition_bridge.py` che
`LegacyRecognitionBridge(Surface.ORDINARY_DATA)` chiami internamente
`classifica_risposta(..., includi_at=False)` e `Surface.TRANSPARENCY` con
`includi_at=True`. Se la mappatura non è quella, l'adapter la deve forzare o il
BASE lascerebbe vincere una piattaforma AT-only (il bug che il commento a
`connettore.py:397` previene).

---

## Passo 1 — Adapter (nuovo modulo)

`api/treasureiq/catalog/recognition_adapter.py`. Vive in `catalog`: può importare
il registry e (per la mappatura enum) `Piattaforma` da `ingest.piattaforma`.
NON è un plugin → il confine plugin non lo tocca. In T2 v1 accetta soltanto
`Surface.ORDINARY_DATA` e `Surface.TRANSPARENCY`; per
`Surface.SERVICE_PORTAL` deve fallire esplicitamente con un errore di contratto
finché il Gate 0 non viene chiuso. Costruisce l'osservazione una volta e la
riusa.

API proposta (forma legacy in uscita, così i caller cambiano al minimo):

```python
def firma_da_registro(
    *, headers: dict[str, str], html: str, surface: Surface,
    source_id: str, entrypoint_url: str,
    expected_platform: str | None = None,
) -> Firma:
    """Rimpiazzo drop-in BASE/AT di firma_da_risposta via registry di produzione.
    Miss (None) → Firma(Piattaforma.IGNOTA, None).

    SERVICE_PORTAL non è supportato da questa API finché gli ID SP nativi non
    sono rappresentabili nel vocabolario legacy.
    """
```

Corpo:
1. `obs = RecognitionObservation(source_id, surface, entrypoint_url, http_status=200, headers=headers, body=html, expected_platform=expected_platform)`.
2. `match = _REGISTRY.recognize(obs)` dove `_REGISTRY = build_recognition_registry()` costruito **una volta a modulo** (il build registra 7 plugin + 4 bridge; non rifarlo per chiamata).
3. `if match is None: return Firma(Piattaforma.IGNOTA, None)`.
4. `piatt = Piattaforma(match.result.platform_id)` (gestire `platform_id is None` → IGNOTA, benché con `fa80e09` un match non-None abbia sempre platform_id; difendere comunque).
5. `prova = _prova_da_evidence(match.result)`.
6. `return Firma(piatt, prova)`.

Aggiungere `_prova_da_evidence(result) -> str | None`: prima evidence
`matched=True` → `f"{e.key}: {e.observed}"` o `e.description`; nessuna → `None`.

**Test adapter** (colma la lacuna «`RecognitionMatch` senza copertura»):
`api/tests/test_recognition_adapter.py` — per BASE e AT: match noto
→ enum giusto + prova non vuota; miss → `Firma(IGNOTA, None)`; parità enum col
vecchio `firma_da_risposta` sulle famiglie NON migrate; e sulle migrate il
`platform_id` viene dal nativo (già coperto lato registry, qui asserire il ponte
enum). Aggiungere un test esplicito che SERVICE_PORTAL venga rifiutato dal
contratto legacy, senza degradare a `IGNOTA`. Usare il DB di test read-only,
nessuna rete (i plugin sono offline).

---

## Passo 2 — Cablare i 3 call site (uno per commit, con test verdi in mezzo)

### A — `catalog/confirmation.py:64` (AT) — il più facile, fare per primo
Oggi:
```python
found = classifica_risposta(headers=dict(headers), html=html, includi_at=True).vincitore
platform = found.piattaforma.value
```
Usa solo `.piattaforma.value` (str). Sostituire con:
```python
found = firma_da_registro(
    headers=dict(headers), html=html, surface=Surface.TRANSPARENCY,
    source_id=source_id, entrypoint_url=url,
)
platform = found.piattaforma.value
```
`source_id` e `url` sono già in scope in `_confirm_one`. Il ramo SP (else) non
tocca il classificatore — invariato. Rischio: minimo, la superficie AT è già
coperta dai nativi urbi/jcitygov/wp_amm_trasp con parità verificata.

### B — `connettore.py:399` (BASE) — dispatch del connettore, alto blast radius
Oggi `firma_da_risposta(..., includi_at=False)` e poi dispatch su
`firma.piattaforma == Piattaforma.MUNICIPIUM / EGOV / PEOPLEWEB`. Sostituire con
`firma_da_registro(..., surface=Surface.ORDINARY_DATA, source_id=codice_istat,
entrypoint_url=base)`. Il dispatch resta identico (confronta enum).
**Perché è sicuro:** MUNICIPIUM/EGOV/PEOPLEWEB NON sono in `_RETIRED_TO_NATIVE`
→ il bridge li serve ancora, `Piattaforma(platform_id)` li ricostruisce. I nativi
SP portalegen/filodiretto sono surface SERVICE_PORTAL → non interferiscono col
BASE. **Da verificare:** che `Piattaforma.value` per ognuno dei tre sia
esattamente il `platform_id` che il bridge emette (`municipium`, `egov`,
`peopleweb`); scrivere un test di dispatch che lo prova su fixture reali prima di
cambiare la riga. `firma_da_risposta` ha **12 caller** — cambiare SOLO questa
riga (la selezione connettore), lasciare gli altri 11 su `firma_da_risposta`.

### C — `ingest/censimento.py:632` `scopri_pagina_at` (AT) — la scattate qui
Unico sito che usa `esito.scattate` (→ `EsitoDiscoveryAT.firme_scattate`, campo
diagnostico) e `esito.vincitore.prova`. **Problema architetturale:** `censimento`
è ingestion, importa `ingest.piattaforma` direttamente; il registry di produzione
avvolge lo stesso `classifica_risposta` via bridge, ma il nativo non produce
`scattate`.

**DECISIONE PRESA — C1. NON cablare questo sito.** `scopri_pagina_at` resta sul
`classifica_risposta` diretto. Motivo: è ingestion/diagnostica, non «selezione
del connettore in produzione» nel senso della review Codex; il ramo che il
cittadino vede (dispatch connettore = B, conferma = A) è cablato, e
`scopri_pagina_at` serve la mappatura AT di censimento dove `scattate` conta.
Cablarlo qui degraderebbe `scattate`→sintetica senza guadagno di correttezza, e
toccherebbe **7 caller** (connettore, inventory_discovery, censimento).
**Azione Codex:** NON modificare `scopri_pagina_at`. Documentare in
`t1-baseline-e-scala.md` come «resto onesto», non buco. P1 #1 si chiude sui path
di produzione A+B; C è fuori scope per progetto.

---

## Passo 3 — Regressione + memoria
- Suite Docker completa (immagine `sha256:67fe2f7a…`, sorgente montata,
  `-e PYTHONPATH=/src`). Baseline attesa: 1143 passed (3 PDF pre-esistenti).
- Aggiornare `t1-baseline-e-scala.md`: P1 #1 chiuso (o parzialmente, se C1),
  elencare cosa è cablato (A+B) e cosa resta diretto (C, con motivo).
- Commit separati A / B / C(+adapter col primo), trailer co-author. Branch
  `perf/accumula-filtri-cache-intent-rust`, MAI su main (freeze).

## Ordine di esecuzione (C1 — C fuori scope)
1. Chiudere Gate 0 nel documento/contratto; fino ad allora adapter + test
   adapter coprono solo BASE/AT → verde.
2. Call site A (confirmation) → suite → commit.
3. Test dispatch BASE su fixture reali → call site B (connettore) → suite → commit.
4. `scopri_pagina_at` (C) — **NON toccare**. Solo nota in memoria.
5. Decidere e cablare SP in un workstream successivo, dopo il vocabolario.
6. Review Codex del nuovo range (`fa80e09..HEAD`).

## Rischi
- **`Piattaforma(platform_id)` con valore ignoto** → `ValueError` in produzione.
  Difendere l'adapter con `try/except ValueError → IGNOTA` + log **solo su
  BASE/AT, come rete su dati corrotti**; MAI come compat SP (vedi Gate 0: SP è
  rifiutato a monte, non degradato). Su BASE/AT ogni ID nativo/bridge è un
  membro valido dell'enum, quindi il ramo scatta solo su output davvero corrotto.
- **Surface→includi_at nel bridge non allineata** → BASE lascia vincere AT-only.
  Verifica obbligatoria in Passo 1.
- **Un nativo più stretto del bridge su una variante reale** (già annotato in
  Passo C) → falso negativo. Il gate resta: miss → None → manual review, non
  verdetto stantìo. Onesto, non silenzioso.
