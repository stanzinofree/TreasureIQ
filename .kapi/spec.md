# SPEC — dialogo-naturale (ciclo 12)

```
TASK: dialogo-naturale
ONE-LINE: TIQ smette di sparare risposte-stampino; dialoga — riconosce il testo, chiede follow-up umani, accumula profilo/filtri turno-per-turno. Tutto deterministico, guardrail intatti.
```

## PROBLEM (reale, non dichiarato)
Oggi ogni messaggio → una risposta secca. Pertinente, ben fatta, ma **canned**: template statici (`respond.py:3343-3347`), zero senso di conversazione. L'utente scrive, partono azioni automatiche di base, ma TIQ non *interagisce*. Manca il dialogo: leggere il testo per arricchire contesto e raffinare filtri parlando, non rispondere-e-basta.

## SCOPE (in)
- **Dialogo multi-turno**: TIQ accumula il profilo/filtri tra un turno e l'altro (non one-shot).
- **Follow-up umani (slot-filling deterministico)**:
  - «ho figli» senza numero → chiedi *quanti*
  - figli → rileva presenza *minorenni* (rilevante agevolazioni)
  - disabilità: chiedi «il disabile è minorenne?» **solo se** disabilità dichiarata
  - comune ambiguo → l'intermezzo esiste (`_quale_comune` respond.py:2451), va reso *umano* (non lista secca)
- **Aggiunta/rimozione filtri dialogando** — SOLO da dichiarazione esplicita del cittadino.
- **Riscrittura messaggio fuori-copertura** (priorità dolore #1) — meno stampino, più umano, resta onesto.
- **Variazione frasi/tono** sul layer di confezionamento testo (oggi tutto stringhe statiche).
- **Script demo video** — costruito in questo ciclo come acceptance bar.

## NON-GOALS (out)
- **Grafica / UX-UI dei risultati** → ciclo separato dopo (deciso col committente).
- **LLM che genera le risposte/intermezzi** → sviluppo futuro, va in doc (modello conversazionale piccolo per soli intermezzi + guardrail nostri). Ora NO.
- Toccare l'intent LLM Ollama esistente (`intent.py:extract_intent`) — resta com'è salvo necessità emersa in plan.
- Nuovi filtri inferiti / guessing al posto del cittadino.
- Riconoscimento comune deterministico (`risolvi_comune`) — non è il problema, non si tocca.

## CONSTRAINTS
- Stack: FastAPI (`api/treasureiq/chat/`) + Next/React (`web/components/`). Deterministico, no nuove dipendenze LLM per l'output.
- Crediti = vincolo progetto: subagent su Haiku/Sonnet, mai Opus.
- `source_typed` / tracciabilità intatta. Verbalizzatore MAI sui numeri (memoria: corrompe le cifre).
- Video-safe: prevedibile, riproducibile in demo.
- Non committare su main; commit = decisione committente.

## DECISIONS
- **D-01** — Approccio **A "vestito bene"**: deterministico più fluido ora; LLM conversazionale = sviluppo futuro documentato. NO LLM nell'output di questo ciclo.
- **D-02** — Scope ciclo = **assi 1+2 fusi** (naturalezza = dialogo). Asse-1 "riconoscimento input separato" NON esiste: collassa nel dialogo. Grafica (asse-3) = ciclo separato.
- **D-03** — **Aggiunta filtro SOLO da dichiarazione esplicita** del cittadino, mai per inferenza. Preserva l'asimmetria anti-guessing di `FiltroOverride` (rimozione libera, aggiunta vincolata all'esplicito).
- **D-04** — **Max una domanda di follow-up per turno, mai bloccante**: TIQ dà comunque il meglio che ha e *offre* di raffinare. No interrogatori (rischio video-flop).
- **D-05** — **Fuori-copertura onesto**: riscrittura del tono, mai inventare copertura/dati.
- **D-06** — **Acceptance = script demo** costruito insieme in questo ciclo; il ciclo è "fatto" quando quelle interazioni suonano umane.

## DISCRETION (l'esecutore decide entro questi confini)
- Forma esatta delle frasi variate / template ricchi (registro, sinonimi) — purché deterministico.
- Come rendere "umano" l'intermezzo comune (chip + frase) senza rompere `needs_clarification`.
- Struttura interna della macchina a stati slot-filling, purché rispetti D-03/D-04.
- Set esatto di frasi del demo script (proposto, poi validato dal committente).

## DEFERRED
- Modello conversazionale piccolo per gli intermezzi (sviluppo futuro, va in doc).
- Grafica/UX-UI risultati (ciclo separato).
- Eventuale rework dell'intent LLM Ollama.

## RISKS (da premortem / red-team)
- **R-01 stato multi-turno** — oggi `/api/chat` costruisce risposta per-messaggio; `profilo_capito` esiste lato stato ma va verificato che regga l'accumulo turno-per-turno. **Prima cosa che plan deve verificare** (potrebbe essere cablaggio non banale).
- **R-02 troppo chiacchierone** — loop di follow-up → 4 domande prima di dare qualcosa → video flop. Mitigato da D-04.
- **R-03 collisione guardrail filtri** — aggiunta-da-dialogo vs asimmetria anti-guessing. Mitigato da D-03 (solo esplicito).
- **R-04 numeri/verdetto** — qualsiasi variazione testo che sfiori cifre/verdetti le corrompe. Guardrail: confezionamento tocca SOLO il testo di cornice, mai i numeri (memoria: verbalizzatore-corrompe-cifre).
- **R-05 disabilità doppio punto** — memoria: gli slot disabilità si cablano in DUE punti (`_profilo_capito` + `extract_intent`). La logica «disabile minorenne solo se disabilità» va cablata in entrambi.
```
