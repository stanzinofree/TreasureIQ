# spec — ciclo 10 · connettore-municipium + contratto-connettore

## PROBLEM
Municipium (Maggioli) è la 2ª piattaforma per diffusione (1.009 comuni, 12,8%).
Oggi TIQ la **rileva** (`piattaforma.py`: `Piattaforma.MUNICIPIUM`, regex
`municipiumapp.it|\bmunicipium\b`) ma **non la legge**: `mappa_connettore.py`
legge solo `wp-json` WordPress. Un comune Municipium (es. Pomezia) cade sul
gradino web e risponde «NIENTE DI PUBBLICATO» — falso negativo su 1.009 comuni,
perché il portale i dati li pubblica, con un altro schema di URL.

In più: ogni connettore (WP, Halley, Municipium, AgID-servizi) oggi estrae cose
diverse in modo ad-hoc. Manca un **contratto comune** che, a ogni scansione,
tiri fuori le stesse tre superfici e le **persista** come base per la risposta
diretta al cittadino (la live diventa refresh, non unica fonte).

## SCOPING (deciso col committente — «copertura piena»)
Ciclo 10 costruisce il **contratto connettore condiviso** + la **1ª implementazione
completa (Municipium)** + la **persistenza base**. Le tre superfici per scansione:
1. **Aree amministrative** — l'indice degli uffici.
2. **Uffici + recapiti** — la rubrica, letta ORA, campo per campo, onesta dove manca.
3. **Amministrazione trasparente** — bandi attivi, **presenza PDF** (flag), analisi
   PDF **on-demand** («vuoi che li analizzi?»), non automatica.
La base persistita alimenta la risposta diretta e le scansioni periodiche la rinfrescano.

## SCOUTING REALE (3 comuni Municipium, tutto HTML statico sul dominio proprio, 0 JS)
- `api.municipiumapp.it/api/v3/...` → **503 Apache** a client HTTP (WAF/app-gated).
  Scartato: non serve. Tenant id `5370` (Pomezia) dal path S3 — non serve.
- Contenuti sul **dominio proprio**: `/it/page/{slug|id}`, `/it/organizational_unit/{slug}`
  (alias IT `/it/unita_organizzative/{slug}`), `/it/public_documents/{slug}`, `/it/sitemap`.
- **Discovery uffici OMOGENEA via sitemap** — `/it/sitemap` (HTTP 200 su tutti) elenca i
  link canonici `/it/organizational_unit/{slug}`: **Pomezia 115, Fiumicino 80, Riccione 133**.
  Ingresso universale, nessuno slug/id per-comune. (Errore misura corretto: grep sull'alias
  IT `unita_organizzative` dà 0 → usare il path EN `organizational_unit`.)
  La pagina `aree-amministrative[-N]` (anch'essa in sitemap) = fallback secondario.
- **Follow 301**: Riccione redirige `organizational_unit/{slug}` → `unita_organizzative/{slug}`
  (200). Il client deve seguire i 301, ma solo se restano sullo stesso host (guardia SSRF).
- **Per-ufficio pubblicato, disomogeneo** (recapiti in HTML statico):
  - Pomezia `servizio-tributi-31081` → tel diretto `06 83997842`, email/PEC ufficio,
    orari sportello. **Ricco.** · `servizi-demografici` (anagrafe) → solo centralino ente. **Scarno.**
  - Fiumicino `area-servizi-al-cittadino…` → tel `06 65210…`. · Riccione affari-generali →
    tel `0541 608232` + PEC. Leggi ciò che c'è, onesto campo-per-campo dove manca.
- **Amministrazione trasparente / PDF fattibili in statico**: la sitemap Pomezia linka
  `amministrazione-trasparente`; le pagine `/it/public_documents/{slug}` servono raccolte
  documentali con **PDF diretti** (14 su una pagina). → AT+PDF raggiungibili senza headless.
  **Maturità:** l'indice BANDI ATTIVI esatto (schema/URL) è meno provato degli uffici →
  **da scoutare in plan** (fable HEAD); degrado onesto se non trovato su un comune (D-02b).

## GENERALITÀ — 3 comuni Municipium testati
Discovery via sitemap + reading per-ufficio **generalizzano su 3 comuni** (Pomezia,
Fiumicino, Riccione). AT/PDF confermati raggiungibili in statico su Pomezia; indice
bandi da provare su ≥2 comuni in plan/review prima di dichiararlo coperto.

## DECISIONS
- **D-01 — Lettura sul dominio proprio, mai da `api.municipiumapp.it`** (host 503 fuori).
- **D-02 — Discovery uffici dalla SITEMAP.** `/it/sitemap` → link `organizational_unit/{slug}`.
  Ingresso universale (verificato 3 comuni). `aree-amministrative[-N]` = fallback secondario.
  Nessuno slug/id hardcoded. Nessun ufficio da alcun segnale → degrada onesto (D-02b).
- **D-02b — Degrado onesto.** Municipium noto ma discovery vuota → scheda `letto_ora` coi
  soli canali ente (IPA + eventuale centralino), stato «piattaforma nota, rubrica non esposta
  qui». MAI crash, MAI «NIENTE DI PUBBLICATO» generico.
- **D-03 — Scheda LETTO ORA** che sostituisce il falso «NIENTE DI PUBBLICATO». `source_typed` per riga.
- **D-04 — Rubrica uffici per-ufficio.** Per ogni ufficio: nome, URL, recapiti pubblicati
  (tel diretto, email/PEC, orari) letti verbatim. Match domanda→ufficio con sinonimi
  (anagrafe→servizi-demografici); ambiguo/non trovato → si chiede o si elenca, non si indovina.
- **D-05 — Onesto campo-per-campo.** Campo per-ufficio solo se pubblicato. Manca → «il comune
  non l'ha pubblicato per questo ufficio». MAI dedurre recapito per-ufficio dal centralino ente.
- **D-06 — Confini diretto-vs-web invariati.** Municipium = fonte diretta letta ora, non web.
  Web resta ultimo gradino solo se neanche la sitemap Municipium è raggiungibile.
- **D-07 — Number-guard.** Nessun recapito/orario/importo passa da un LLM: parsing HTML
  deterministico, cifre verbatim dalla pagina.
- **D-08 — Cortesia + guardia host + follow-301.** Host ristretto al dominio del comune
  (no SSRF), budget richieste, timeout, cache TTL con esito volatile se ambiguo (L-5 ciclo 7).
  Segue i 301 solo se restano sullo stesso host.
- **D-09 — CONTRATTO CONNETTORE condiviso.** Interfaccia comune che una scansione produce:
  `{ aree_amministrative[], uffici[ {nome, url, recapiti, orari, source_typed} ],
     amministrazione_trasparente{ bandi_attivi[], pdf_presenti(flag), indice_url } }`.
  Municipium ne è la 1ª implementazione piena; il seam è pensato perché WP/Halley/AgID lo
  implementino poi senza rework. HEAD in plan decide dove vive il contratto (nuovo modulo
  vs estensione `mappa_connettore.py`) e la firma esatta.
- **D-10 — Persistenza base + refresh.** Ogni scansione persiste il risultato del contratto
  in uno store per-comune (chiave ISTAT), come la base che serve alla risposta diretta.
  La live rinfresca la base; le scansioni periodiche la tengono calda. Onestà su freschezza:
  ogni riga porta `source_typed` + timestamp; ambiguo non si cachea (L-5). Non si spaccia
  cache vecchia per «letto ora».
- **D-11 — Amministrazione trasparente: bandi + PDF, analisi on-demand.** Il connettore
  elenca i **bandi attivi** trovati nell'indice AT (verbatim), segnala **presenza PDF** come
  flag, e offre l'analisi PDF **su richiesta** del cittadino — mai analisi automatica di massa
  (costo/crediti). Estrazione criteri PDF riusa la pipeline `extract/corpus` (ciclo 7).
  Number-guard D-07 anche qui: importi/scadenze verbatim, mai da LLM.

## DISCRETION (lasciato all'execute)
- Punto d'innesto nel percorso comune-non-censito (dove oggi gira scrape scheda/contatti +
  `_numeri_utili_al_volo`), keyed su `piattaforma == MUNICIPIUM`.
- Forma parser sitemap/HTML; forma esatta store di persistenza (riusa store bandi/alberatura esistente?).
- Quali canali ente promuovere in scheda oltre centralino/PEC.

## DEFERRED
- **Contratto implementato per WP/Halley/AgID** (Municipium è la 1ª impl; gli altri seguono a valle).
- **Host API `api.municipiumapp.it`** (503) → mai.
- **Analisi PDF automatica di massa** → sempre on-demand (crediti).
- Normalizzazione strutturata orari/scadenze oltre il verbatim → se serve.

## RISKS (critical pass 5 lenti, proporzionale)
- **Blind spot:** i canali «ente» dall'HTML potrebbero già venire da IPA → valore marginale
  se ci fermassimo lì. Il valore vero: togliere il falso «NIENTE», elenco uffici, AT/bandi,
  base persistita, assenza onesta per-ufficio.
- **Devil's advocate:** «è solo Pomezia» → discovery validata su 3 comuni; AT bandi da validare
  su ≥2 in plan/review prima di dichiarare copertura.
- **Inverted (cosa NON fare):** non inventare recapiti/bandi, non leggere dall'host 503, non
  marcare `verificato` ciò che è `letto_ora`, non spacciare cache per fresco, non cachare l'ambiguo,
  non analizzare PDF senza richiesta.
- **Premortem:** sitemap/indice AT cambia schema o assente → degrada a «piattaforma nota, non
  leggibile qui» (onesto), non crash né bugia. Scope pieno a 6 giorni dal video → AT è la parte
  meno provata: se in execute l'indice bandi non regge su ≥2 comuni, si spedisce con AT in
  degrado onesto e uffici+base pieni (il video non dipende dai bandi Municipium).
- **Red team:** link sitemap a host esterni → guardia host (D-08), no SSRF; sitemap enorme
  (1–3.5MB) → limite parsing/byte; PDF grandi → analisi solo on-demand, budget.

## ACCEPTANCE
- **A1** Comune Municipium riconosciuto non censito (Pomezia, ISTAT 058085) → risposta
  `letto_ora`, NON più «NIENTE DI PUBBLICATO».
- **A2** Discovery via `/it/sitemap` → ≥1 `/it/organizational_unit/{slug}` letto, URL sul
  dominio del comune (301 seguiti).
- **A3a** «ufficio tributi Pomezia» → tel diretto `06 83997842` + email/PEC + orari, verbatim, `letto_ora`.
- **A3b** «anagrafe Pomezia» (→ `servizi-demografici`) → ufficio riconosciuto, esito onesto
  «solo centralino», nessun numero ente spacciato per diretto.
- **A4** `source_typed` corretto per ogni riga; nessun testo di risposta generato da LLM.
- **A5** Guardia host: link sitemap/redirect fuori dominio ignorati (no SSRF).
- **A6** Discovery via sitemap validata su ≥2 comuni oltre Pomezia (Fiumicino 80, Riccione 133);
  regge o degrada onesto (D-02b), mai crash.
- **A7** Comune non-Municipium invariato (nessuna regressione).
- **A8** Suite pytest verde + tsc/build se toccato il web.
- **A9 (contratto)** Il connettore Municipium restituisce l'oggetto contratto D-09
  (`aree_amministrative` + `uffici` + `amministrazione_trasparente`); la firma è documentata e
  riusabile (non Municipium-specific).
- **A10 (persistenza)** Una scansione persiste la base per-comune (chiave ISTAT); una seconda
  richiesta risponde dalla base con `source_typed`+timestamp corretti; la live rinfresca senza
  spacciare cache per «letto ora».
- **A11 (AT/bandi/PDF)** Per ≥1 comune: elenco bandi attivi (verbatim) O degrado onesto se
  l'indice non regge; **flag presenza PDF** corretto; analisi PDF eseguita **solo su richiesta**,
  importi/scadenze verbatim (number-guard).
