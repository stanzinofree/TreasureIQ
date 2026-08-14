# Da fare

*Stato al 6 agosto 2026, aggiornato il 9 agosto 2026. Scadenza hackathon: 14
agosto.*

Ordinato per **quanto pesa sul cittadino**, non per quanto è comodo farlo. Ogni
voce dice cosa è rotto, perché, e quanto costa: senza quello una lista di
compiti è solo una lista di desideri.

---

## Rotto adesso

### 1 · ~~La ricerca web restituisce zero, sempre~~ — RISOLTO

SearXNG girava e non indicizzava niente: il terzo gradino della scala D-32 era
morto. **Sostituito, non riparato** (D-58/D-59): SearXNG è fuori dalla scala, il
gradino 3 ora è **Brave con ricerca ancorata al dominio** (`_cerca_sul_web(f"site:{host} {query}")`,
`respond.py`) — un contratto vero, non un proxy che fa scraping, e usato solo
per un comune di cui conosciamo già l'indirizzo. La chiave vive in `.secrets`
(via `env_file`), non nel codice.

Verificato dal vivo: Bisceglie (fuori copertura) → pagine reali da
`comune.bisceglie.bt.it`, tutte marcate `non verificato`. Coerente con la
dottrina in `sonda_live.py`: *«non è un link trovato da un motore di ricerca:
è la fonte, citata»*.

Resta aperto **il gradino del catalogo** (vedi #7): per le piattaforme che
sappiamo leggere, prima di Brave dovremmo elencare i servizi letti adesso.

### 2 · ~~La risposta si ripete e si contraddice~~ — RISOLTO

La premessa nuova e la coda preesistente dicevano la stessa cosa due volte, e
peggio: la coda dava un dead-end («non sono riuscito a collegare… rivolgiti
all'URP») anche quando la ricerca live aveva trovato pagine. Fix in
`build_chat_answer`: se `web_results` sono presenti e la coda non è una domanda,
si tiene solo la premessa. Una risposta, non due che si contraddicono.

### 2b · ~~Il ciclo nlp-filtri~~ — RISOLTO

I filtri del profilo (nucleo familiare, figli minori, disabilità, ISEE,
età/anziano, employment status, comune, tema) sono ora estratti da
`filtri.py`, modulo **deterministico**: 10 `FiltroChiave`, ognuno con
`span` obbligatorio nel testo (nessun filtro senza la prova testuale che
l'ha prodotto), sorgente tracciata (`testo`/`profilo`/`override_client`).
Ollama resta confinato all'intento — non riempie più nessuno slot di
filtro. Chip sul rail in `ChipFiltri.tsx`. Chiudeva anche *§ 6* qui sopra.

### 3 · Il rail informativo dà zero anche sui comuni ingeriti

Nella matrice, «dove sta l'ufficio anagrafe e quando è aperto» restituisce 0
risultati **anche su Albano, Benevento, Lucca** — dove i dati ci sono. Né
documenti né uffici. Da capire se è il recupero o la composizione.

### 4 · Tre registri che devono concordare a mano

Perché un comune compaia servono voci in `SOURCES` (ingestione), `enti.json`
(misura) e `COMUNI` in `api.py` (API). Se ne manca una, i record esistono su
disco e sono **invisibili ovunque**.

Non è teorico: è già successo con Ariccia (quindici record fantasma, c'è il
commento nel codice), è successo di nuovo ieri con quattro comuni, e **Genzano
di Roma e Marino sono in questo stato adesso** — registrati, senza seed,
rispondono come coperti e non trovano niente.

*Rimedio:* un registro solo, derivato dai file in `data/seed/`.

### 5 · L'instradamento del modello varia fra chiamate

«ci sono bandi per i mezzi pubblici» a volte è classificata `agevolazione` e a
volte `informazione`, a parità di frase. Il record viene comunque mostrato, ma
sul rail informativo perde i criteri confrontati.

---

## Incompleto

### 6 · ~~Il pannello dei filtri mostra solo tre cose~~ — RISOLTO

`Profilo` (`web/lib/profilo.tsx:59-80`) ora ha anche `disabilita`,
`nucleoFamiliare`, `disabilitaNucleo`, `figliMinori` — e `dimenticaFatto`
(`profilo.tsx:110-119`) sa dimenticare ciascuno di questi campi, non solo i
tre originali. `ChipFiltri.tsx` mostra tutti e 10 i `FiltroChiave` (incluso
ISEE) come chip sul rail del turno di chat; `ProfiloNoto.tsx` mostra quelli
persistiti nel profilo. L'ISEE resta un filtro di turno, non un campo salvato
in `Profilo` — coerente con `filtri.py`, che lo estrae ma non lo marca come
dato da ricordare fra un messaggio e l'altro.

### 7 · Lettura live: manca il gradino del catalogo

Oggi il ripiego per un comune non coperto è solo la ricerca (Brave `site:`).
Per i comuni su piattaforme che sappiamo leggere il ripiego giusto è **leggerne
il catalogo adesso** — WordPress, MyPortal e PeopleWeb hanno già il lettore.

*Fondamenta pronte:* `api/treasureiq/mappa_connettore.py` misura al volo servizi
e 15 categorie standard del modello AgID (cache 30g). Manca il cablaggio in
chat: chip a cascata sul rail informativo (categoria → servizio) prima di Brave.
Attenzione: il catalogo AgID espone i **servizi amministrativi**, non i bandi
(quelli vivono in amministrazione-trasparente → restano ricerca web). Vince sul
rail informazione, non su quello agevolazioni.

### 8 · 155 comuni MyPortal leggibili e non letti

Veneto e Rete Civica Lepida: API JSON, campi tipizzati, codice IPA ricavabile
dall'anagrafe. È il **miglior rapporto fra lavoro e risultato** di tutta la
lista — mezza giornata.

### 9 · La popolazione ISTAT

Il campo esiste in tabella ed è vuoto. Senza, ogni frase dice «il X% dei
comuni» invece di «il X% dei cittadini». Si riempie con un `UPDATE` sul codice
ISTAT, nessuna richiesta di rete.

### 10 · 19 comuni PeopleWeb su 35 senza scheda

L'indice non aggancia sempre. È un limite nostro, contato come tale
(`nota_misura`), non come inadempienza del fornitore.

### 11 · L'ufficio nominato non aggancia lo store che ce l'ha

Sintomo (Bisceglie, 110003, WordPress AgID): il cittadino chiede la
**viabilità**, la chat non la trova e ripiega sui contatti dell'anagrafe —
mentre lo snapshot connettore contiene eccome `Sicurezza e Viabilità` (e la
sua ripartizione). Non è un buco dati: è **estrazione + match** dell'ufficio.

Due difetti a monte, verificati:

- **`_ufficio_chiesto` (`respond.py`) riconosce solo `ufficio <parola>`.**
  Il regex `uffici[oi]\s+…([parola])` fallisce su `viabilità`, `servizio
  viabilità`, `sportello viabilità`, e su `ufficio sicurezza e viabilità`
  cattura solo `sicurezza`. Senza un ufficio estratto, il ramo connettore non
  parte → ripiego URP. *Allargamento:* accettare `servizio|settore|sportello|
  ripartizione|assessorato` oltre `ufficio`, e catturare nomi multi-parola,
  non il primo token.
- **La card "URP" non è l'URP.** `orari-urp/{istat}.json` cachea l'ufficio
  *rappresentativo* scelto dal censimento (`ufficio_scelto`), che qui è
  l'Anagrafe. Copy da correggere: se non è l'URP, dire «recapiti dell'ufficio
  Anagrafe», non spacciarlo per URP.

Il match a valle (`_ufficio_connettore_pertinente`) è già corretto: quando due
uffici combaciano (ripartizione + servizio) li propone come **scelta**.

#### PIANIFICATO — modulo NLP-uffici, mini-piano Livello A

Riframe: scegliere l'ufficio **non** è vocabolario aperto. Il set uffici del
comune è **noto** (lo store connettore di Bisceglie ne elenca 53). È
**retrieval del messaggio contro una lista nota** — stessa forma di comune
(lista ISTAT) e topic (tassonomia): entrambi già deterministici.

Livello A (deterministico, riusa il crate scorer):

1. **Sorgente ufficio = store, non regex.** Carica i nomi ufficio da
   `UfficioConnettore.nome` dello store del comune; normalizza (casefold,
   accenti, `servizio/settore/sportello/ripartizione/assessorato` come rumore
   di testa, non come trigger obbligatorio).
2. **Scorer riusabile.** Stessa macchina del crate intent (keyword→peso per
   token, confine di parola, argmax con margine), ma i "topic" sono i nomi
   ufficio caricati a runtime dallo store — non la tassonomia fissa. Un
   `score_ufficio(msg, uffici) -> (slug|None, secondi)` foglia, testabile,
   portabile 1:1 in Rust come `tiq_intent`.
3. **Trigger largo.** Sul rail informazione tenta *sempre* il match ufficio,
   non solo dietro la parola letterale «ufficio». `_ufficio_chiesto` resta
   come scorciatoia, ma non è più l'unica porta.
4. **Pareggio = scelta, non indovinello.** Margine sotto soglia o due nomi a
   pari peso (ripartizione + servizio) → `_ufficio_connettore_pertinente` già
   propone la scelta al cittadino (comportamento corretto, invariato).
5. **Golden condivisi.** `cases-uffici.json` per-comune (frase→slug atteso,
   `null`=ambiguo/assente), oracolo per Python e per l'eventuale port Rust —
   stesso schema di `cases.json`.
6. **Fix copy URP** (indipendente, 1 riga): se `ufficio_scelto` ≠ URP, la card
   dice «recapiti dell'ufficio X», non «URP».

Fuori scope L1, misurato dopo: **embeddings** solo sul residuo dove le parole
non si sovrappongono (`buche in strada`→`Viabilità`, `dove pago il bollo`→
`Tributi`) — ranking della lista nota, non generazione. **Mai** LLM sul «tono»
per scegliere l'ufficio: l'ufficio lo decidono i sostantivi, non il sentiment,
e affidarlo al modello reintroduce l'allucinazione che la cintura esiste per
evitare. Il contesto-chat (ereditare ufficio/comune dai turni) è già in
`_eredita_dal_contesto`, da estendere all'ufficio.

---

## Connettori: dove l'effort rende di più

Criterio: `comuni del fornitore × quanto sale il livello di lettura`.

| Fornitore | Comuni | Stato | Stima |
|---|---|---|---|
| **Municipium** (Maggioli) | 1.010 | parziale — consegnato ciclo 10 (uffici + AT onesta 2/3) | da stimare oltre i 2 comuni verificati |
| **HGATE** | 956 | rotte già mappate, manca la scheda | 2–3 gg |
| **AgendaSmart** | 377 | rotta `/agenda-smart` verificata | 2–3 gg |
| **OpenPA** | 363 | nome noto, rotte da mappare | 2–3 gg |
| MyPortal (completare) | 155 | già a livello modello | 0,5 gg |

Sommati: **2.886 comuni** — il 36,5% d'Italia — passerebbero da «non copro» a
una risposta vera, per una quindicina di giornate.

Restano **844 comuni non riconosciuti** (10,7%), ora in gruppi da 40–70: ogni
firma nuova vale decine di comuni, non più centinaia.

---

## Sicurezza — prima di qualunque esposizione pubblica

Fatte ieri: limite di frequenza sulle rotte che invocano il modello, avvio
rifiutato col segreto di prova fuori da sviluppo.

Restano, in ordine:

1. **Limite di frequenza per host** in acquisizione — è l'unico punto in cui
   possiamo danneggiare terzi, e diventa concreto appena leggeremo le singole
   schede (un comune con 138 servizi le prenderebbe tutte in raffica).
2. **Cookie `Secure`** fuori da localhost.
3. **`robots.txt`** letto e rispettato, con l'esito registrato: un comune che
   ci esclude è un dato del censimento, non un ostacolo da aggirare.
4. **Provenienza dei frammenti** che entrano nel contesto del modello.

---

## Architettura post-MVP

Dettagli e soglie in [evoluzione.md](evoluzione.md). In sintesi: costruire
limite per host, registro delle esecuzioni, scheduler piccolo. Non costruire
coda di messaggi, object storage, database server — con le condizioni
misurabili che li rimetterebbero in gioco.

### VALUTAZIONE — standardizzare i connettori (contratto verbi + capability)

Oggi un connettore è **una funzione monolitica** (`leggi_<vendor>(comune,
sonda) -> EsitoConnettore`): produce tutto in un colpo — piattaforma, uffici,
AT, logo. Va bene per lo sweep batch, male per la chat, che spesso vuole *una*
cosa (l'orario di *quel* ufficio, il logo) e oggi non può chiederla senza
ri-scansionare tutto. Il caso Bisceglie (uffici §11) e il post-MVP «connettore
target singolo» sono due sintomi dello stesso limite.

Direzione (da valutare, non ancora pianificata):

1. **Contratto a capability, non monolite.** Scomporre il connettore in verbi
   discreti con firma stabile, ognuno indipendente e cachabile:
   `scopri_piattaforma`, `elenca_uffici`, `retrieve_ufficio(target)`,
   `scan_logo`, `scan_mappa_sito`, `scopri_at`. La chat chiama il verbo che le
   serve; lo sweep li chiama tutti. `EsitoConnettore` resta il tipo di ritorno
   aggregato, ma composto da pezzi che esistono anche da soli.
2. **Sequenza pulita chat↔connettore.** Un'unica tabella verbo→metodo, gli
   stessi nomi da entrambi i lati, così non si rincorrono più helper sparsi in
   `respond.py` (`_office_da_ufficio_nominato`, `_ufficio_connettore_pertinente`,
   sonde live) che oggi reimplementano pezzi di retrieve fuori dal connettore.
3. **Retrieve customizzato *dentro* il connettore.** Ogni capability vive nel
   connettore del vendor (logo dove sta il logo — cfr. eGov `/header.html`,
   Municipium CDN; uffici dall'indice `unita_organizzativa`; mappa dalla
   sitemap). La chat non conosce le stranezze del portale: chiede `scan_logo`,
   il connettore sa dove guardare.
4. **Confine dati = confine di linguaggio.** Se il contratto è un confine JSON
   pulito (già lo è: `EsitoConnettore` è un modello serializzabile), un
   connettore può essere un **binario/servizio Rust o Go** che emette lo stesso
   JSON — utile dove lo scraping rende meglio fuori da Python (portali lenti,
   parsing pesante, concorrenza). Confine per sottoprocesso/IPC, non PyO3:
   lo scraping è I/O-bound e va isolato, non embeddato in-process. Precedente:
   lo scorer intent è già uscito da Python via crate ([[intent]] sprint).

Costo/rischio: tocca `connettore.py` (D-09/D-10) e tutti i vendor
(comweb/egov/openweb/municipium/wordpress_agid/openpa) + i punti chat che oggi
scavano da soli. Blast radius alto → dietro test di parità sullo store attuale
(stesso `EsitoConnettore` prima/dopo), un vendor alla volta. Prerequisito
naturale del modulo NLP-uffici §11 (che vuole `elenca_uffici`/`retrieve_ufficio`
come capability pulite).

### VALUTAZIONE — il motore chat come pipeline a contratti tipizzati

Il filo: **ogni cucitura = contratto tipizzato + provenienza + funzione pura**.
Il flusso obiettivo è lineare e ispezionabile:

```
CHAT → NORMALIZZAZIONE ─┬─ PROFILE extractor ─┐
                        ├─ INTENT detector   ─┼─ VALIDATOR → FILTRI CANONICI → RETRIEVAL → VERDETTO → UI
                        └─ QUERY-FILTER extr. ─┘
```

Ogni slot estratto porta la sua prova, non solo il valore:

```json
{ "field": "children", "value": false, "confidence": 1.0,
  "source": "explicit_user_statement", "matched": "non ho figli" }
```

**Guardia dura:** `confidence` è **derivata dalla source, non emessa dal
modello** — `explicit_user_statement`=1.0, `marker`=0.9, `inferred`≤0.7,
`model_topic`=0.6 (soglia scorer). Se il numero lo spara il modello si
riapre l'allucinazione che scorer + cintura esistono per chiudere. La
provenienza dà anche l'audit civico: «perché pensi non abbia figli?» →
«hai scritto 'non ho figli'» = fiducia, ed è storia da demo.

Sei rework, ordinati per rapporto valore/rischio:

1. **Registro schemi = confine di linguaggio (prerequisito economico).** Un
   solo posto per gli schemi (JSON Schema → genera tipi Python *e* Rust/Go).
   L'analizzatore in Rust/Go regge **solo** se il contratto è congelato e ogni
   impl passa lo stesso **conformance test** — identico all'oracolo parità
   dello scorer (`cases.json`, 35/35). Senza, «riscrivo in Rust» = due verità
   che divergono. Sblocca 2–6.
2. **Profilo cittadino = reducer event-sourced, non mutazione sparsa.** Oggi il
   profilo si accumula tra i turni con cinture (R-8/R-9), override, reset — ed è
   la classe di bug ricorrente (leak Albano al cambio comune, reset override su
   nuova conversazione, `comune_hint`). Ogni turno emette **eventi tipizzati**
   (`slot_asserito`, `slot_ritrattato`, `comune_cambiato`); un reducer puro li
   ripiega. «cambio comune» diventa un evento, non un caso speciale sparso in
   `respond.py`. Deterministico, replayabile — uccide la famiglia bug di stato.
3. **Validator = riconciliatore di conflitti (il crux).** Non valida solo la
   forma: **riconcilia**. Turno 1 «non ho figli» (1.0), turno 5 «mia figlia» →
   conflitto. Regola deterministica: provenienza più forte + più recente vince,
   il conflitto resta *tracciato*, non silenziato. Qui la provenienza paga.
4. **Retrieval = router di capability tipizzate (gemello dei connettori).** Il
   motore di ricerca riceve i filtri canonici e sceglie la query; ogni
   capability **dichiara i filtri che consuma e l'evidenza che produce**.
   «quale query per questo intent» = lookup, non `if/elif`. Stessa dottrina
   capability dei connettori (sezione sopra).
5. **Verdetto vs verbalizzazione, muro netto.** Retrieval torna evidenza
   tipizzata con slot; il verbalizzatore rende **solo** template su slot, non
   vede mai la cifra grezza da riformattare. La corruzione cifre non può
   accadere per costruzione, non per guardia. Roadmap §3 ci si appoggia.
6. **Replay harness first-class (la rete che rende sicura la riscrittura).**
   Unificare `matrice.py` (90 combo), `cases.json`, suite e2e in un harness che
   registra sessioni reali anonimizzate come fixture e **rigioca l'intera
   pipeline deterministicamente**. Ogni bug → una fixture. È ciò che rende
   non-suicida cambiare motore: l'harness dice se la pipeline è ancora verde.

Priorità: **1** (prerequisito), poi **2** e **6** comprano più stabilità subito
(la classe bug di stato, e la rete per riscrivere in sicurezza). 3–5 seguono il
disegno del flusso. Blast radius alto e trasversale → stesso metodo dei
connettori: contratto congelato, conformance test, un pezzo alla volta.

---

## Prodotto e consegna

| | Cosa | Perché |
|---|---|---|
| **1** | **Il video** | è la consegna, ed è l'unica cosa che nessun altro può fare al posto nostro |
| 2 | Il pitch | numeri e coerenza ci sono già |
| 3 | Pagina `/developer` | una sola, scritta a mano: com'è fatto, quanto è vero, cosa abbiamo deciso di **non** fare |
| 4 | Ingerire altri comuni | 3 secondi e zero chiamate al modello ciascuno; la lista dei leggibili è in `docs/connettori.md` |

---

## Come si è arrivati a questa lista

Non da un'ispezione: da una **matrice di 90 combinazioni** — 9 comuni su tre
livelli di copertura × 5 domande × 2 profili — eseguita contro l'API vera. È
lo strumento che ha trovato la ricerca morta, il bando del Lazio offerto in
Sicilia e l'anagrafe a zero.

Vale la pena tenerla e rieseguirla dopo ogni cambio: sta in
`scratchpad/matrice.py` e va spostata nel repository.
