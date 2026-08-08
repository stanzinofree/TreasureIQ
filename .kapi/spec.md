# spec — ciclo 7 · bandi-live-agid

Motore bandi **live, on-demand**: dato un comune coperto da AgID REST e un intent "bandi",
estrae i bandi con **criteri di eleggibilità strutturati**, riusando l'estrattore LLM e lo
schema già esistenti, con **cache TTL** e **data di verifica visibile**. Fuori copertura →
esito onesto + advocacy, nessuno scraping su misura. Coerente col north-star: se i dati non
sono aperti, lo diciamo e invitiamo ad aprirli.

## Contesto (fatti scout, ciclo 6)
- Copertura AgID REST ≈ **16%** dei comuni (61/401, `data/censimento-t0.json`); l'84% è
  solo-html. Il tier "api_uffici" misura gli uffici: il CPT bandi/trasparenza è un sottoinsieme.
- Riusabile as-is: `RequirementsExtractor` (`extract/llm.py:64`, prompt già bando-specifico,
  `isee_min`), schema `Opportunity`/`Requirements`/`Source` (`schema.py`), pipeline PDF
  `pypdf` + audit skip (`wp_pages.py:430-548`), pattern sonda timeout-bounded (`sonda_live.py`).
- Già esistente ma povero: `bandi_criteri()` REST (`mappa_connettore.py:754`) → solo elenco
  (titolo/url/data/anteprima verbatim), niente criteri strutturati, niente PDF.
- Store scrivibile = `data-live/` (`LIVE_DIR`); `data/` è `:ro`.

## DECISIONI
- **D-01** Trigger **live/on-demand** a query-time (cittadino chiede bandi in chat), non batch.
  Riusa il pattern sonda; nessun pre-ingest nazionale.
- **D-02** Copertura = comuni coperti da uno di **due gradini REST**, in ordine:
  (1) **CPT bandi/trasparenza AgID** (`amm-trasparente`), oppure
  (2) **`wp/v2/pages`** REST — la stessa scoperta con cui l'ingest già ingerisce i bandi di Albano
  (`wp_pages.py`). Emendato dopo scout ciclo 7: il CPT AgID stretto copre **≈0%** (0/61
  `api_uffici`, 0/385 raggiungibili); il gradino `pages` è dove i bandi vivono davvero nei
  portali WordPress comunali (Albano + set demo). Nessuno dei due REST → esito onesto "non
  coperto dai dati aperti" + invito apertura (advocacy, riusa ChiediApertura/segnalazioni).
  **Lo scraper arbitrario resta Tier 3 deferred** — i due gradini sono entrambi REST, non scrape.
- **D-03** Estrazione = riusa `RequirementsExtractor`. Input = dettaglio bando REST + eventuale
  PDF allegato (via `pypdf`). LLM = **Ollama** di default (crediti); nessun nuovo provider.
- **D-04** Schema = riusa `Opportunity`+`Requirements`+`Source`. Nessun nuovo modello dati per
  il bando arricchito. Il tipo `Bando` REST resta per l'anteprima; l'arricchito è `Opportunity`.
- **D-05** **Cache** su `data-live/` (LIVE_DIR, scrivibile, gitignorato), chiave deterministica
  per comune+bando. Prima query paga (scan+PDF+LLM), riuso entro TTL. Cap di dimensione.
- **D-06** **Freschezza onesta**: al cittadino si mostra "verificato il <data>"; scaduto il TTL
  si ri-scansiona. Se il bando ha una **scadenza**, è mostrata. TTL corto (discrezione: 6–12h).
- **D-07** **Number-guard**: gli importi/ISEE mostrati sono **verbatim dalla fonte**, mai
  riformulati dal modello (il verbalizzatore corrompe le cifre). `source_typed`/guardia numeri.
- **D-08** **PDF budget**: riusa i limiti esistenti (`MAX_PDFS_PER_PAGE`, `MAX_PDF_BYTES`) +
  audit skip (illeggibile vs non tentato). Nessun download illimitato.
- **D-09** Nessuna PII, nessun invio esterno. Coerente con feedback/segnalazioni.

## ACCEPTANCE
- A1 Comune coperto (CPT AgID bandi **oppure** `wp/v2/pages` con bandi) + intent bandi → ≥1
  bando con `Requirements` strutturati; se coperto ma senza bandi pubblicati → "nessun bando
  pubblicato" onesto (non un errore).
- A2 Comune senza né CPT né `wp/v2/pages` utile → esito "non coperto dai dati aperti" + invito
  apertura; **zero** tentativi di scrape arbitrario (Tier 3).
- A3 Seconda query entro TTL non rilancia LLM/PDF (nessuna nuova chiamata provider,
  verificabile); scaduto il TTL → ri-scan.
- A4 Al cittadino compare la data di verifica; se presente, la scadenza del bando.
- A5 Number-guard: un importo/ISEE noto nella fonte compare identico in output (il modello
  non lo altera).
- A6 PDF budget rispettato; skip audati.
- A7 Cache in `data-live/`, gitignorata, mai committata; cap dimensione rispettato.
- A8 Nessuna regressione: chat/servizi/segnalazioni/feedback intatti.
- A9 LLM = Ollama di default; Anthropic solo fallback esplicito, mai forzato (crediti).

## RISKS (5 lenti)
- **R-1 (blind spot, CONFERMATO in scout)** Il CPT AgID stretto copre ≈0% (0/61, 0/385): la
  card bandi del ciclo 6 era mock. Il valore reale sta nel gradino `wp/v2/pages`. Presidio:
  D-02 a due gradini, **copertura misurata per comune in scan** (non promessa), e advocacy onesta
  quando nessun gradino trova bandi (A1, A2). Misura del gradino `pages` sul set demo = prima
  azione verificabile del plan, non scoperta post-execute.
- **R-2 (devil's advocate)** Cache che serve un bando **scaduto** = danno (cittadino perde la
  scadenza). Presidio: TTL corto + data visibile + scadenza mostrata (D-06, A4).
- **R-3 (number corruption)** Il modello corrompe ISEE/importi. Presidio: source_typed/guardia
  (D-07, A5).
- **R-4 (inverted)** "E se NON facessimo il live?" Il solo Tier 1 (enrich batch) copre già il
  16%; il valore del live+cache è la **freschezza**, non la copertura. Tenerlo magro: se i
  bandi non cambiano spesso, il live è oro fuso. Il TTL e il gate misurano se serve.
- **R-5 (team/ops)** Reproducibilità: l'ingest non è riproducibile; il motore live introduce
  stato in `data-live` (invalidazione, dimensione). Presidio: TTL + chiave deterministica +
  cap dimensione cache (D-05).

## DISCRETION (arm decide)
- Forma esatta della chiave cache e TTL numerico (default 6–12h).
- Come si aggancia al chat retrieval: nuovo intent "bandi" o estensione dell'esistente.
- Se arricchire `bandi_criteri()` in place o costruire un modulo `bandi_live` che lo avvolge.

## DEFERRED (non in questo ciclo)
- Tier 3: scraper portali arbitrari solo-html, adapters per famiglia di CMS.
- Invio delle richieste di apertura dati da parte nostra (SMTP, D-07 ciclo 6).
- Batch pre-ingest nazionale dei bandi.
