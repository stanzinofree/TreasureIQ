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
