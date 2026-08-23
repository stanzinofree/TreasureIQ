# Issue (nota tecnica): 3 failure PDF/OCR in `test_wp_pages_caratterizzazione`

**Stato:** ✅ CHIUSA — 2026-08-23. Suite completamente verde: **1534 passed, 6 skipped, 0 failed**, PARITY 35/35.
**Registrata:** 2026-08-23, alla chiusura del blocker seam-guard (M3) e al merge di ComWeb nell'integrazione.
**Non bloccava:** né il fix M3 (`mappa_connettore`), né il connettore ComWeb (Ramo 3 #2). Entrambi review-clean e mergiati.
**Bloccava:** dichiarare `make test` completamente verde → niente merge su `main` finché aperta. **Ora chiusa.**

## Soluzione applicata (triage confermato: sovrapposizione semantica in `corpus.py`)

Radice reale: `FULL_OCR` ("serve OCR") veniva conflato con "PDF illeggibile"
(`_skip(..., illegible=True)`), forzando `L3_illeggibile` su documenti validi ma
con OCR non ancora eseguito.

Fix in due parti, come da triage:

1. **Produzione** — `FULL_OCR` non incrementa più `illegible_count`. Introdotto
   uno stato dedicato **"OCR rinviato/non misurato"** (`ocr_deferred_count`),
   restituito separatamente da `collect_pdf_segments`. Un PDF che richiede OCR
   resta `L1_manuale` ("non ancora letto"), mai `L3` ("illeggibile"). File:
   `extract/corpus.py` (nuovo conteggio + `_skip(..., ocr_deferred=True)`),
   più i 3 chiamanti aggiornati alla firma a 5 valori (`ingest/wp_pages.py`,
   `api.py`, `bandi_live.py`). `L3` resta riservato alla vera illeggibilità
   (INVALID / parse-fail / zero testo estraibile).

2. **Test** — `test_wp_pages_caratterizzazione` ora inietta un **inspector
   deterministico** (`_DeterministicPdfInspector`) via nuovo parametro
   `WPPagesConnector(pdf_inspector=...)`: `%PDF` → TEXT_BASED/NATIVE_TEXT (apre
   via pypdf), altrimenti INVALID. Budget/segmenti/ladder non dipendono più
   dall'euristica/versione del pacchetto PDF Inspector installato. Nessuna
   fixture modificata; `FULL_OCR` non trattato indiscriminatamente come "PDF
   aperto" (la distinzione testo-estratto vs OCR-da-eseguire è preservata).

   La nuova semantica è bloccata da:
   `test_corpus_pdf_inspection::test_corpus_routes_scanned_pdf_to_ocr_before_pypdf`
   (ora asserisce `illegible == 0`, `ocr_deferred == 1`).

Nota: l'asserzione su `illegible.pdf` è passata da "parsing fallito" (pypdf) a
"ispezione fallita / Not a PDF" — i byte plain-text vengono ora respinti al gate
d'ispezione uno stadio prima, restando comunque skip illeggibile audito.

---

### Cronistoria (analisi originale, mantenuta per tracciabilità)

## I test rossi

Tutti in `api/tests/test_wp_pages_caratterizzazione.py`, stessa radice:

| Test | Atteso | Ottenuto |
|---|---|---|
| `test_recovery_level_and_notes` | `RecoveryLevel.L1_MANUALE` | `L3_ILLEGGIBILE` |
| `test_pdf_budget_and_audit_trail` | budget/audit con un PDF aperto | fallisce (nessun PDF aperto) |
| `test_corpus_truncation_and_segment_boundaries` | segmenti dal corpo PDF | fallisce (nessun corpo estratto) |

## Radice unica

Il fixture "buono" `good.pdf` non viene più aperto: l'ispettore lo instrada su
`InspectionRoute.FULL_OCR`, e `corpus.py` tratta quella rotta come **illeggibile**.

`api/treasureiq/extract/corpus.py:186-199`:

```python
if inspection.route is InspectionRoute.FULL_OCR:
    plan = build_ocr_plan(absolute_url, inspection)
    reason = (
        "ispezione PDF: OCR richiesto prima dell'estrazione"
        ...
    )
    _skip(..., reason, illegible=True)   # <-- FULL_OCR contato come illeggibile
    continue
```

Log riprodotto durante lo sweep dei fixture:

```
skipping PDF .../good.pdf: ispezione PDF: OCR richiesto prima dell'estrazione
skipping PDF .../oversized.pdf: 2102152 byte, oltre il limite di 2097152 byte
skipping PDF .../illegible.pdf: inspection failed: Not a PDF: file appears to be plain text
```

Con i tre PDF skippati e **nessuno** genuinamente aperto, la ladder D-16 scende a
`L3_illeggibile` (rung riservato a "ogni PDF linkato ha fallito l'apertura") invece
di `L1_manuale`; a cascata falliscono anche budget/audit e truncation/segment, che
presuppongono un corpo PDF estratto.

## Ipotesi (da verificare in triage)

1. **Drift del fixture** `good.pdf`: il byte-content del fixture ora corrisponde a un
   PDF che `inspect_pdf_bytes` classifica come solo-immagine → `FULL_OCR`. Da quando?
   Il fixture andrebbe rigenerato come PDF con testo estraibile senza OCR.
2. **Drift dell'ispettore** `inspect_pdf_bytes` / soglia OCR: la logica di routing è
   cambiata e ora manda in OCR ciò che prima apriva direttamente.
3. **Semantica `illegible=True` su `FULL_OCR`**: un PDF che *richiede* OCR è davvero
   "illeggibile" ai fini della ladder? Se OCR è un percorso previsto (non un fallimento),
   forse la ladder non dovrebbe scendere a L3 per un rinvio a OCR — ma questo è un
   cambio di contratto D-16, non una fix di fixture. Decidere prima di toccare.

## Criterio di chiusura

`make test` senza questi 3 failure (e senza regressioni), con la scelta esplicita tra
"rigenera fixture" (ipotesi 1/2) e "rivedi ladder per FULL_OCR" (ipotesi 3) motivata a doc.

## Fuori scope di questa slice

Boundary estrazione PDF/OCR (`treasureiq.extract.corpus`), non la strangler seam né
la discovery servizi. Preesistente sul ramo integrazione (falliva identico prima di M3).
