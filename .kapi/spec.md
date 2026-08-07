# SPEC — Scheda-comune + aderenza connettore (MVP video)

Ciclo 5 · task: `scenario-cards-freeze` · brainstorm 2026-08-07

## GOAL
Standardizzare i flussi/card della chat per il video con una cornice onesta,
uguale sui casi Figline/Benevento/Perugia: «quanto riesco a vedere · come farlo
aprire di più · dimmi come vado». Cuore: **aderenza al connettore** (numero reale,
calcolato dai probe) + **scheda-comune** ricca dentro TIQ + **2 form** (apertura
dati, feedback). Motore di retrieval CONGELATO: si aggiunge uno strato di
persistenza+presentazione attorno, non dentro il matching.

## CONTESTO
- Oggi gli scan sono LIVE per-richiesta; il censimento è snapshot una-tantum.
  Nessuna persistenza dello scan, nessun timestamp «ultimo scan».
- Dottrina esistente (respond.py:219/1263, api.py:779): VIETATE le percentuali
  inventate in chat («affidabilità %» = numero con l'aria di precisione). Ogni
  cifra mostrata deve avere denominatore reale e provenienza visibile.
- Sonda già disponibile: `mappa_connettore` → servizi-REST (esposto+rest_base+
  categorie), uffici (unità organizzative), `contatti_via`, `amministrazione_
  trasparente_via`, bandi. Basta per calcolare l'aderenza AgID senza nuovi scan.
- `readiness.score_comune` (0-100, 5 dim) esiste ma è sui RECORD INGERITI →
  non uniforme sui 3 casi (Figline/Benevento non ingeriti). NON è l'aderenza.

## DECISIONS
- **D-01** (ereditata): nessun verdetto di eleggibilità da letture live. La
  scheda-comune e le card sono NAVIGAZIONE, non responso.
- **D-B7** (ereditata): il modello non tocca/genera cifre. Ogni numero della
  scheda è estratto verbatim dai probe.
- **D-S1 — Aderenza = superfici AgID machine-readable esposte via REST /
  superfici definite.** Lo scrape NON conta verso l'aderenza (è ripiego nostro,
  prova del buco del comune). Misura l'apertura vera, premia la conformità.
- **D-S2 — Solo il connettore AgID emette una % calcolata.** WP-Custom (solo
  HTML) → tier «solo HTML, dettaglio non ancora mappato», NIENTE %. Sconosciuto
  → stato «non ancora sondato», nessun numero. Mai una cifra su connettori senza
  reader.
- **D-S3 — «% del pubblicato letto» / «copertura ricerca» = MORTA.** Denominatore
  (totale pubblicato dal comune) inconoscibile → sarebbe numero inventato. Non si
  mostra. L'apertura si dice SOLO come aderenza-connettore (D-S1).
- **D-S4 — Provenienza visibile su ogni numero.** «servizi via API: 103», «ultimo
  scan: 7 ago», «aderenza AgID 80% = 4/5 superfici». Nessuna cifra nuda.
- **D-S5 — Store di scansione persistente** (prerequisito): record per-comune con
  timestamp + cache (servizi/aderenza/contatti/orari/logo). Serve sia al refresh
  sia alla scheda con «ultimo scan».
- **D-S6 — Refresh-on-search:** comune riconosciuto, scan >6 giorni → parte il
  refresh, indicatore «sto aggiornando · attendi o vedi gli attuali?». Se scan
  fresco → serve la cache.
- **D-S7 — Form esterni, non TIQ-hosted.** Apertura-dati e feedback = link esterni
  (Google Form o simile), `target=_blank rel=noopener`. Nessuna PII su di noi per
  l'MVP. URL placeholder finché non forniti.
- **D-S8 — Logo/asset SOLO dal portale del comune** (stesso host della sonda,
  guardia SSRF già copre). Mai CDN terzi. Degrado muto se assente (come
  numeri_utili): niente logo, niente errore. Il logo esposto è esso stesso indice
  di apertura.
- **D-S9 — Freeze retrieval:** pesi/matching/scala NON si toccano in questo ciclo.
  Calibrazione pesi = workstream separato, fuori spec.

## DISCRETION (arm decide, entro le decisioni)
- Composizione esatta della checklist AgID (4-6 superfici): almeno servizi-REST,
  uffici-REST, trasparenza-REST, contatti-REST; bandi-REST se già cablato.
- Forma dello store (file JSON per-comune vs sqlite): scegliere il più semplice
  che regge timestamp + cache; niente nuova dipendenza pesante.
- UI della scheda-comune (layout), purché stile «civico giapponese» esistente,
  no Inter/gradient/emoji, numeri con provenienza.
- Lock/concorrenza refresh: accettabile doppia-scansione occasionale per l'MVP
  (no lock complesso) purché non rompa nulla.
- Soglia demo: per mostrare il refresh dal vivo, forzare stale un comune (seed
  timestamp indietro). Onesto se trasparente.

## DEFERRED (progettato, non costruito per il video)
- **Job batch schedulato ogni 5 min** (rotazione: primi X con scan >6gg, poi gli
  altri). Invisibile in demo, infra pesante (scheduler+lock+politeness), contro il
  freeze. Design registrato qui, build post-video.
- Reader connettore WP-Custom (scrape indice servizi HTML — es. Pergine /Servizi).
- Re-scan automatico dei comuni non toccati dal refresh-on-search.

## RISKS
- **8 giorni al video, scope ampio** (scheda-page + store + refresh + aderenza +
  logo + 2 form). Mitigazione: linea di taglio — se il tempo stringe cade PRIMA il
  refresh-on-search (la scheda regge con «ultimo scan: adesso», live). Minimo
  irrinunciabile: aderenza% + scheda + form.
- **Aderenza scambiata per giudizio.** Copy deve dire «apertura del portale», non
  «qualità del servizio». Separata da readiness (dati ingeriti) — assi diversi.
- **Logo 404/timeout** → deve degradare muto, mai bloccare la scheda.
- **Cache fresca in demo** → refresh non scatta senza forzare stale (vedi
  DISCRETION).

## ACCEPTANCE
1. Aderenza AgID calcolata dai probe (mai digitata) su checklist 4 superfici
   (servizi/uffici/trasparenza/contatti REST). Dato reale sondato 2026-08-07:
   Figline 3/4=75% (servizi+uffici+trasparenza REST, contatti scrape),
   Benevento 2/4=50%, Perugia 2/4=50% (servizi+uffici REST, trasparenza+contatti
   scrape). `punti_di_contatto` REST assente su tutti e 3 = gap reale mostrato,
   non nascosto (aggancio card apertura-dati). Numero = esposte/definite, con
   provenienza. `amm-trasparente` E' REST ed e' discriminante (Figline sì, altri no).
2. Connettore non-AgID → tier/stato, MAI una %.
3. «% del pubblicato letto» non appare da nessuna parte.
4. Store di scansione persiste timestamp + cache per-comune; «ultimo scan: <data>»
   reale nella scheda e nella sidebar.
5. Refresh-on-search: scan >6gg → refresh + indicatore «attendi/attuali»; scan
   fresco → cache servita senza refresh.
6. Scheda-comune dentro TIQ: connettore, aderenza, ultimo scan, servizi esposti,
   contatti ufficiali (da scansione), orari uffici, ISTAT, link pagina ufficiale,
   logo (se disponibile, muto se no). Linkata dalla sidebar dati.
7. 2 form esterni (apertura dati dentro la scheda-comune; feedback su ogni chat),
   link `target=_blank rel=noopener`.
8. Ogni numero mostrato ha provenienza visibile; nessuna cifra nuda o inventata.
9. Retrieval invariato: nessuna modifica a pesi/matching/scala. Suite verde.
10. Job batch NON costruito (solo progettato in DEFERRED).
