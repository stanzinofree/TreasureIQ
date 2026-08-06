# SPEC — chat-polish-freeze (ciclo 2)

    run_id:      chat-polish-freeze
    opened:      2026-08-06
    deadline:    2026-08-14 23:59 (T-8)
    predecessor: chat-first-mvp (spec preservato in spec.mvp1.md.bak)
    branch:      feat/chat-first-mvp — 67 commit avanti su main (e23ca3e)

---

## Goal

Congelare il sistema in uno stato **girabile a video**, poi girare il video ≤3 min
(metà del punteggio, ancora inesistente). Il freeze include un blocco di migliorie
chat/UX + tre fix di sistema che rendono la consegna valutabile e onesta.

Il video racconta **due metà**: il caso del singolo cittadino (chat, eleggibilità,
"il comune non l'ha pubblicato") **e** la scala nazionale (censimento ~249 comuni,
connettore per modello AgID). Un ponte in-chat unisce le due metà.

## Scope

**Dentro il freeze:**
- Chat/UX: avvio-a-un-tap · ponte-scala-in-chat · fix motore NLP · filtri
  selezionati/deselezionabili · contesto chat multi-turno.
- Sistema: merge su `main` + riproducibilità da clone pulito · taratura
  freschezza/DRS per servizi permanenti.
- Deliverable: video ≤3 min + form di consegna.

**Fuori (DEFERRED):** vedi sezione.

---

## DECISIONS

- **D-40** Freeze = i cinque item chat/UX + due fix di sistema (merge/riproducibilità,
  freschezza/DRS). "Gerarchia scheda risposta" e "nessuna modifica" scartate dal
  cittadino. Confine duro: nessuna feature nuova oltre questi.

- **D-41** Il video mostra caso singolo **+** scala nazionale. La scala usa dati già
  misurati (censimento, `piattaforma_prova`, aderenza per fornitore). **Nessuna nuova
  misurazione** per il video: si racconta ciò che esiste.

- **D-42** **Sequenza gated dalla girabilità.** Ordine: (1) merge su main +
  `docker compose up --build` pulito da clone fresco → la consegna deve essere
  clonabile-ed-eseguibile; (2) le migliorie chat/UX che il video richiede;
  (3) freschezza/DRS; (4) video girato ~Aug 10–12, buffer fino Aug 14. Il codice
  si **congela ~Aug 11**: dopo, solo fix bloccanti. Nessun refactor tardo.

- **D-43** **Avvio a un tap.** Empty-state della chat con chip cliccabili: le 4 persone
  (Luigi · Giada · Stefania · Mirella) ciascuna con la propria domanda pronta. Un tap
  carica persona + invia la domanda. Riusa `PRESETS`/`AccessoSimulato`/`profili-demo`.
  Il demo parte senza digitare profili né domande → fluido a video, mostra i 4 casi in
  sequenza.

- **D-44** **Ponte alla scala nazionale in chat.** Dopo una risposta *comunale*, una
  riga sola: "questo comune usa la piattaforma X (aderenza N) — vedi com'è messa
  l'Italia →" che porta a `/analytics`. Unico gesto che cuce le due metà del video
  senza cambio-pagina a freddo. Dati dal censimento, non ricalcolati.

- **D-45** **Filtri profilo selezionati e deselezionabili.** `profilo_capito` (età,
  comune, topic/interessi) reso come chip visibili che il cittadino può **togliere**
  quando abbiamo dedotto male, correggendoci a vista. Vive in `web/lib/profilo.tsx` +
  `ProfiloNoto.tsx`/`Pannello.tsx`. La provenienza (`dichiarato`/`geolocalizzazione`/
  `accesso`) è già tracciata e resta visibile.

- **D-46** **Togliere un dato dedotto non falsa mai il verdetto.** Rimuovere un campo
  del profilo lo riporta a `unknown_profile` → verdetto degrada a UNKNOWN, **mai** si
  ribalta in NOT_MET (spirito R-9). Il motore già ha None-guards per profilo mancante.

- **D-47** **Fix motore NLP.** `chat/intent.py` + `respond.py`: migliorare la
  comprensione del topic e onorare il **contesto multi-turno** (la history è già
  passata da `send()` a `/api/chat`; l'engine deve usarla — follow-up risolti contro
  comune/topic del turno precedente senza richiederli di nuovo). Il topic resta
  **corroborato dalle parole**, mai dedotto dal solo modello (memoria
  topic-modello-serve-riscontro). `test_intent_guardie.py` resta verde.

- **D-48** **Taratura freschezza/DRS.** Un servizio permanente (scuolabus) non va
  penalizzato dal punteggio di freschezza come un bando scaduto. La freschezza pesa
  solo dove ha senso (misure con scadenza), non sui servizi stabili.

- **D-49** **Subagent solo su modelli economici** (Haiku/Sonnet), mai Opus. I crediti
  sono un vincolo del progetto (memoria subagent-modelli-economici).

- **D-50** La guardia sui numeri nel verbalizzatore resta: le cifre non passano dal
  modello (D-24 del ciclo 1 vale ancora).

## DISCRETION (l'arm decide, entro il goal)

- Copy esatto dei chip di avvio e della riga-ponte.
- Interazione filtro: solo-rimozione vs toggle-ripristino (parti dalla rimozione).
- Quante persone in empty-state (4 se stanno, altrimenti griglia compatta).
- Se il ponte-scala mostra il numero di aderenza inline o solo il link.

## DEFERRED (non questo ciclo)

- Gerarchia visiva della scheda risposta (scartata dal cittadino).
- Connettori CKAN/HTML oltre l'attuale MyPortal/AgID.
- Secondo/terzo comune oltre a quelli già caricati.
- Invio reale della segnalazione (resta genera-non-invia, D-25 ciclo 1).

## RISKS

- **R-V (massimo) — video tardivo.** 8 giorni, over-scope mangia il tempo di ripresa.
  Mitigazione: gate di girabilità (D-42), freeze codice ~Aug 11, video è priorità 0.

- **R-M — merge su main regredisce.** 67 commit; il clone fresco deve fare
  `docker compose up --build` pulito. Mitigazione: verifica da directory fresca
  prima di dichiarare fatto; porta 8010≠8000 (OrbStack), ingest non-riproducibile
  (memoria ingest-non-riproducibile) → niente A/B end-to-end come prova.

- **R-N — i fix NLP destabilizzano.** Cambi a intent.py possono regredire le guardie.
  Mitigazione: `test_intent_guardie.py` verde è acceptance, non opzionale.

- **R-F — deselezione corrompe il verdetto.** Coperto da D-46; è anche acceptance.

- **R-P — freschezza mal-tarata nasconde uno stale vero.** Non spegnere la freschezza,
  ridimensionarla solo sui servizi permanenti; un bando scaduto resta penalizzato.

## ACCEPTANCE (testabile)

1. **Clone pulito gira.** Da directory fresca su `main`: `docker compose up --build`
   porta su chat funzionante (API 8010, web) senza passi manuali non documentati.
2. **main aggiornato.** `main` contiene il lavoro chat-first (branch merged o PR).
3. **Avvio a un tap.** Empty-state mostra le 4 persone; un tap carica profilo + invia
   la domanda; compare la risposta senza altra digitazione.
4. **Ponte-scala.** Dopo una risposta comunale appare la riga verso `/analytics` con la
   piattaforma del comune; il link porta alla pagina scala.
5. **Filtri deselezionabili.** I campi dedotti (età/comune/topic) sono chip rimovibili;
   rimuoverne uno aggiorna il profilo visibile.
6. **Deselezione sicura.** Rimosso un campo, il verdetto relativo diventa UNKNOWN, mai
   NOT_MET. Prova: caso con criterio `met` → rimuovi il campo → criterio a
   `unknown_profile`.
7. **Contesto multi-turno.** Un follow-up ("e per mia madre?") risolve contro comune/
   topic del turno precedente senza richiedere di nuovo il comune.
8. **Guardie NLP verdi.** `test_intent_guardie.py` passa; nessuna regressione sui
   test topic esistenti.
9. **Freschezza tarata.** Un servizio permanente d'esempio non risulta "scaduto/stale";
   un bando scaduto resta penalizzato. Prova numerica sullo snapshot committato.
10. **Video ≤3 min** girato, che mostra caso singolo + scala, entro il buffer.

---

## Note di stato (ancoraggio, verificato Aug 6)

    Chat maturo (web/components/Chat.tsx, 1064 righe): due rail AGEVOLAZIONE/
    INFORMAZIONE, Seal per verdetto, CostStrip, EffortCaption, coverage, geoloc
    con residenza≠posizione, comune esplicito (no allucinazione).
    profilo_capito già calcolato e usato per registra(); i "filtri visibili"
    esistono come concetto, D-45 li rende rimovibili.
    NLP: api/treasureiq/chat/{intent,respond}.py; motore match/engine.py con
    None-guards; test_intent_guardie.py presente.
    Censimento: dati scala già misurati (piattaforma_prova, aderenza fornitore).
