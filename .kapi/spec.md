# SPEC — registro-comuni-schede (ciclo 14)

## TASK
`registro-comuni-schede` — registro locale dei comuni (logo + metadata + snapshot servizi + change-detection, zero-leak) che alimenta una card comune curata, + un giro di polish sulle schede chat. Prima del video (~14 ago).

## GOAL
Dare alla card comune un'identità curata (logo/glifo + nome + numeri utili) senza fetch esterno a runtime, costruendo un registro comuni locale che salva logo, metadata e snapshot servizi e rileva quando un comune cambia tra due scansioni. In parallelo ripulire il rumore delle schede chat (spaziatura, debug, bandi, web results, feedback).

## SCOPE (in)
- **Connettore eGov/EGS** (nuovo, data layer): riconoscimento della famiglia piattaforma dal pattern URL `EG0/EGS*.HBL?en=eg###` (es. Marino `en=eg176`: servizi `EGSCHTST.HBL?...&MESSA=PUBBLICA`, mappa `EGSMISTMSIT.HBL?...&FUNZ=1`) + scraping di servizi/mappa/AT. Segue il contratto connettore esistente D-09 (`connettore.py`: `AmministrazioneTrasparente`, `SchedaServizio`, …), come Municipium/Halley. Sblocca Marino con dati reali.
- **Registro comuni** (nuovo data layer): store locale per-comune — logo (asset/base64), nome, istat, dominio, **famiglia piattaforma + endpoint reali (amministrazione/servizi/mappa/AT)**, timestamp ultima scansione, snapshot servizi (mappa connettore), storia scansioni per diff. **Change-detection**: rileva quando dati/servizi stabili di un comune cambiano tra due query. Zero fetch live esterno al render.
- **Card comune curata**: logo dal registro (fallback monogramma/glifo civico neutro + nome se assente) + nome + numeri utili.
- **Fix spaziatura ProfiloNoto "sto usando"**: padding sinistra, testo non attaccato ai bordi, bordo destro staccato dal divisorio chat.
- **Togli tag debug**: codice ISTAT via dall'UI (info di debug). Il segnale di riconoscimento comune può restare, ma senza il codice.
- **Bandi collapsed**: primo bando + "+N altri" expander inline.
- **Web results in fondo**: "Pagine trovate sul web / non verificato" in fondo alla card, dopo il verificato; restano visibili.
- **Feedback in header**: da sempre-visibile nel flusso → bottone piccolo nell'header.

## NON-GOALS (out)
- Servizi → sidebar sinistra (= ciclo 15, deciso "polish prima").
- Feedback prompt ogni-N-messaggi (deciso: solo header).
- Web results come bottone-collapse (deciso: in fondo, sempre visibili).
- Favicon/logo live-fetch a runtime (privacy) — logo solo dal registro locale.
- Logo che finge lo stemma ufficiale — solo logo reale salvato o glifo neutro.

## CONSTRAINTS
- Stack: Next 15 / React 19 (frontend); FastAPI/Python (backend); store registro locale (JSON vs SQLite → plan). Docker, web senza bind-mount → rebuild obbligatorio ([[container-non-monta-sorgente-api]]).
- **Privacy-preserving**: zero fetch esterno al render; logo servito da asset locale/base64.
- Determinismo TIQ mantenuto.
- **Degrado onesto**: comune senza logo → glifo+nome; comune che non trova nulla (Marino) → card + numeri + vuoto onesto, mai guscio rotto ([[fonte-nuova-niente-da-recuperare]]).
- WCAG AA, tema light unico, stile civico giapponese esistente, riuso token/primitive ciclo 13.
- No dep/font/palette nuova per la parte UI.
- 4-5 giorni al video: polish visibile = must-have (Onda 1). Registro + connettore eGov degradano onestamente; nessuno dei due può affondare il video.
- **Connettore eGov**: scraping server-side (fetch backend, non al render), determinismo TIQ tenuto. Non fetch dal browser del cittadino. Segue contratto D-09 (`connettore.py`), come Municipium/Halley.

## DECISIONS
- D-01 Registro locale self-hosted, zero fetch live (privacy + determinismo).
- D-02 Logo reale dal registro; fallback nome + glifo civico neutro (mai stemma finto).
- D-03 Registro "pieno" (scelta utente, nonostante R-01): logo + metadata + snapshot servizi + change-detection tra scansioni.
- D-04 Servizi restano in chat in questo ciclo (spostamento sidebar = ciclo 15).
- D-05 Web results in fondo alla card, sempre visibili (non collapse).
- D-06 Feedback = bottone header (non prompt periodico).
- D-07 Bandi collapsed: primo + "+N altri".
- D-08 Togliere il codice ISTAT dall'UI (debug); non necessariamente tutto il chip riconoscimento.
- D-09 Riuso token/primitive ciclo 13; **assorbire i token nelle regole componente o alzare la specificità**, mai aggiungere bolt-on cieco ([[globals-css-bolt-on-cascade]]).
- D-10 **Connettore eGov/EGS in-scope con scraping reale** (scelta utente, R-01 esplode): riconosci famiglia `EGS*.HBL?en=eg###`, salva endpoint nel registro, **e estrai davvero i dati** (servizi/mappa/AT). Implementa contro il contratto D-09 esistente. Marino = dati reali. Degrado se scraping non chiude: endpoint salvati + link mostrati, mai guscio rotto.
- D-11 **Logo one-shot alla scansione** (scelta utente, scioglie ex-DEFERRED): il backend cattura `og:image`/favicon UNA volta durante la scansione (non al render → privacy tenuta), riusa la guardia SSRF post-redirect + size-cap dello stesso connettore. Salva `logo_b64` nel registro. Fallback glifo/monogramma civico se assente/fetch fallisce (D-02). Nessun fetch logo al render.

## DISCRETION (plan/execute decidono)
- Formato store registro: JSON file vs SQLite (verificare se un DB esiste già lato backend).
- UX del segnale "il comune è cambiato": minimale (badge/nota), non invasiva.
- Meccanismo glifo/monogramma: iniziale vs icona civica.

## DEFERRED
- Servizi → sidebar sinistra (ciclo 15).
- Connettore eGov: comuni EGS oltre Marino (una firma-famiglia + Marino verificato ora; roll-out ampio dopo il video).
- Enrichment logo avanzato (crop/normalizzazione/CDN). Il logo-fetch one-shot base è ora in-scope (D-11).
- F4/F5 cascade ProfiloNoto residui (se non chiusi dal fix spaziatura).

## RISKS
- **R-01 (CRITICA) Slittamento video**: 3 thread grossi — connettore eGov nuovo (scraping) + registro pieno + polish — in 4-5gg. Mitigazione OBBLIGATORIA nel plan, sequenza a onde con degrado indipendente per onda:
  - Onda 1 **POLISH** (must-have video, spedisce da solo): spaziatura ProfiloNoto, via ISTAT, bandi collapsed, web in fondo, feedback header. Se il resto salta, il video ha già le schede pulite.
  - Onda 2 **REGISTRO + card comune**: logo/metadata/snapshot; degrada a snapshot-senza-UI-diff.
  - Onda 3 **CONNETTORE eGov** (rischio massimo, ULTIMO): scraping EGS. Degrada a "endpoint riconosciuti+salvati+link" se lo scraping non chiude — Marino resta onesto, non rotto.
  Nessuna onda a valle può bloccare un'onda a monte già pronta.
- R-02 Cascade bolt-on CSS ricorrente (ciclo 13): il polish tocca le stesse card → assorbire token, non aggiungere bolt-on cieco.
- R-03 Change-detection senza storia: registro parte vuoto, diff ha senso dalla 2ª scansione. Onestà: "prima scansione, niente da confrontare".
- R-04 Ingestione non riproducibile ([[ingest-non-riproducibile]]): il set-pagine cambia a ogni run → il diff rischia falsi "cambiato" da rumore d'ingestione. Change-detection sui dati STABILI (servizi/logo/contatti), non sul set-pagine volatile.
- R-05 Tensione di scope esplicita: "registro pieno" confligge col "polish prima" scelto poco prima. Tenuta a vista, non risolta a favore di uno solo.

## ACCEPTANCE (demo-script, costruito nel ciclo)
1. Card comune: logo (o glifo+nome) + numeri utili. **Marino → dati reali estratti dal connettore eGov** (servizi/mappa/AT dagli endpoint `EGS*.HBL?en=eg176`). Se lo scraping degrada: endpoint riconosciuti + link + vuoto onesto, mai guscio rotto.
2. ProfiloNoto "sto usando": spaziatura sinistra corretta, testo staccato dai bordi, bordo destro non attaccato al divisorio.
3. Nessun codice ISTAT visibile nell'UI.
4. Molti bandi → primo + "+N altri", espande inline.
5. Web results in fondo alla card, dopo il verificato.
6. Feedback raggiungibile da bottone header, non più fisso nel flusso.
7. Registro: 2ª query sullo stesso comune usa logo/metadata dal registro (no fetch) e registra la scansione; se un dato stabile cambia, il registro lo rileva; prima scansione → "niente da confrontare".
