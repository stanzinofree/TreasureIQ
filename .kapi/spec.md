# SPEC — ciclo 16: due piattaforme per comune (BASE + Amministrazione Trasparente)

slug: due-piattaforme-sweep

## PROBLEM
Oggi lo sweep riconosce UNA piattaforma per comune (la BASE del portale, first-match
in `firma_da_risposta`). Ma l'Amministrazione Trasparente (AT) è quasi sempre un
vendor DIVERSO (Barletta: BASE=Publisys SIAMO, AT=ISWEB), ed è lì che vivono i
bandi — il cuore di TIQ. Senza riconoscere l'AT come piattaforma a sé, ogni comune
è un caso a mano per l'ingestion bandi, e non c'è evidenza di quale connettore serve.
Inoltre il first-match cieco nasconde le collisioni fra firme e non ri-classifica i
già-etichettati quando aggiungi una firma nuova.

## GOAL
Al primo sweep un comune esce con DUE piattaforme riconosciute — BASE (chat rapida:
orari/uffici/servizi) e AT (ingestion + ricerca BANDI) — via una BATTERIA di firme
(prova-tutte + punteggio, non first-match). Struttura chiusa/pulita ora, estensibile
e veritiera dopo. Popola: scheda comune, logiche di interrogazione chat, storico
sweep, analytics.

## IN SCOPE
- Riconoscimento BASE riscritto come **batteria a punteggio**: prova tutte le firme,
  sceglie il vincitore per score, conserva i runner-up come diagnostica.
- Riconoscimento **AT** con la stessa batteria, applicata alla pagina AT scoperta.
- **Discovery URL AT** best-effort: link "Amministrazione trasparente" nel footer AgID
  + probe percorsi/subdomini noti (`trasparenza.<dominio>`, `<dominio>/zf` Halley,
  `/amministrazione-trasparente`). Se non trovata → `piattaforma_at = NON_TROVATA`.
- Firme AT per le famiglie note: ISWEB, Halley trasparenza (/zf), WP AT-plugin,
  Publisys/ISWEB. + le 6 BASE già mappate preservate.
- **Schema** `portale_snapshot`: colonne nuove additive (piattaforma_at,
  piattaforma_at_prova, at_url, firme_scattate diagnostiche).
- **Re-sweep nazionale ORA** con la batteria (scelta committente D-04): i numeri
  analytics si aggiornano; le cifre hardcoded in `site/vetrina.html` vanno
  ri-verificate/aggiornate prima del video.
- **Superfici**: scheda comune mostra due connettori ("portale X · trasparenza Y");
  logica chat sa quale connettore userebbe (BASE per orari/uffici/servizi, AT per
  bandi); analytics sottosezione "Piattaforme trasparenza" (GROUP BY piattaforma_at).
- **Demo bandi ISWEB (Barletta)** end-to-end via open-data (`/pagina48` atti di
  concessione) — brief SEPARABILE, cuttable se la deadline stringe.

## CONSTRAINTS
- Stack: Python (api/treasureiq), SQLite storico.db (versionato), Next/React (web).
- Video hackathon 14 ago = priorità dura (oggi 11 ago).
- Riuso: `firma_da_risposta` come motore firma; host-guard post-redirect (SSRF) come
  in `_logo_one_shot`/`_scarica_logo`; `classificato_da='riclassificazione'` già
  distinto da `evoluzione()`.
- Non rompere connettori/test esistenti (test_piattaforma, test_egov, test_registro,
  test_connettore_contratto).
- Delega subagent su Sonnet/Fable, mai Opus (crediti).
- Mai commit su main: branch + PR.

## DECISIONS
- **D-01** Riconoscimento = BATTERIA a punteggio (prova-tutte, vincitore per score,
  runner-up conservati), sostituisce il first-match. [committente: "Sostituisce"]
- **D-02** DUE piattaforme per comune: `piattaforma` (BASE) + `piattaforma_at` (AT),
  entrambe dalla batteria; AT girata sulla pagina AT scoperta.
- **D-03** Discovery AT best-effort (footer AgID + subdomini/percorsi noti); niente
  trovato → `NON_TROVATA` (dato onesto, non buco). Host-guard riusato.
- **D-04** Re-sweep nazionale ORA, pre-video; numeri analytics aggiornati; cifre
  `vetrina.html` ri-verificate. [committente: "No, ri-classifica subito"]
- **D-05** Schema additivo su `portale_snapshot` (ALTER/migrazione): piattaforma_at,
  piattaforma_at_prova, at_url, firme_scattate. `_COLONNE_PORTALE` esteso.
- **D-06** Superfici: card due-connettori + chat connector-aware + analytics
  sottosezione AT (GROUP BY piattaforma_at).
- **D-07** Demo bandi ISWEB Barletta (open-data) come brief separabile/cuttable.
- **D-08** Batteria non deve regredire i vendor BASE già noti: firme specialiste per
  6 famiglie BASE + famiglie AT; i test esistenti aggiornati alle nuove aspettative.

## DISCRETION (l'implementatore decide)
- Nomi esatti colonne, formula di score, struttura interna della batteria.
- Come la chat sceglie il connettore (routing base-vs-AT per intento).
- Formato della diagnostica `firme_scattate` (stringa / JSON).
- Ordine/soglia delle sonde di discovery AT.

## DEFERRED (non ora)
- Connettori-bandi completi per TUTTE le famiglie AT (ora solo demo ISWEB).
- Scheduler auto-resweep.
- Coda lunga vendor rari.

## NON-GOALS
- Non estraiamo bandi per ogni famiglia AT in questo ciclo.
- Non cambiamo la lettura del modello AgID BASE.
- Nessun nuovo standard imposto ai comuni.

## RISKS
- **R-01** Re-sweep nazionale sposta i numeri della vetrina (94,2%, tabella
  piattaforme, 7896…). MITIG: dopo il re-sweep, aggiornare le cifre hardcoded in
  `site/vetrina.html` e ri-verificarle contro ogni claim del video. [accettato D-04]
- **R-02** Discovery AT falsi-URL / SSRF. MITIG: riuso host-guard post-redirect;
  `NON_TROVATA` invece di indovinare.
- **R-03** Batteria che sostituisce first-match cambia aspettative dei test
  (test_piattaforma/test_egov). MITIG: aggiornare fixture; assert su vincitore+score.
- **R-04** Migrazione schema su storico.db versionato: righe vecchie senza colonne
  nuove. MITIG: ALTER additivo con default NULL; INSERT OR REPLACE già presente.
- **R-05** Riproducibilità sweep (memoria ingest-non-riproducibile): il conteggio
  SIAMO è variato 37 vs 22 fra run per flakiness. MITIG: retry nelle sonde; lo score
  è deterministico dato l'HTML, la variabilità è di rete non di logica.
- **R-06** Demo bandi ISWEB slitta sotto deadline. MITIG: D-07 brief separabile,
  cuttable senza rompere il resto.

## CONTEXT (scoperte a monte, non ipotesi)
- Publisys SIAMO = 6º vendor BASE (Barletta): API facade `/kapi/api/sito/*`, envelope
  `{"error":false,"results":[...]}`. AT su ISWEB (`trasparenza.<dominio>`), bandi con
  export Open Data su `/pagina48_atti-di-concessione`.
- Firma SIAMO pulita: `env.js` con `siamo.publisys.it` (definitiva) o `configurazione`
  che torna l'envelope JSON (path fisso, no assunzione base). Il bare-200 su
  `configurazione` = falso positivo (soft-404 HTML, es. Halley Ancarano).
- Conteggio SIAMO nazionale = **25 comuni** confermati (firma `env.js` con `siamo.publisys.it`,
  retry x3 su 7867 siti). Concentrati al Sud (hits 6000→3, 7000→25: coda ISTAT PZ/BA/…).
  Lista in scratchpad `siamo_confirmed.tsv`. È il 6º vendor BASE reale, non un one-off Barletta.
