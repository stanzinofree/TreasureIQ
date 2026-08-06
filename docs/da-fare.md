# Da fare

*Stato al 6 agosto 2026. Scadenza hackathon: 14 agosto — otto giorni.*

Ordinato per **quanto pesa sul cittadino**, non per quanto è comodo farlo. Ogni
voce dice cosa è rotto, perché, e quanto costa: senza quello una lista di
compiti è solo una lista di desideri.

---

## Rotto adesso

### 1 · La ricerca web restituisce zero, sempre

SearXNG gira e non indicizza niente: `site:comune.roncaro.pv.it bandi` → 0,
`roncaro bandi mezzi pubblici` → 0. Il terzo gradino della scala D-32 **non
funziona**, e non da ieri.

Conseguenza misurata sulla matrice: su 30 combinazioni «comune senza
connettore» la ricerca live non è mai partita.

**Non ripararlo: sostituirlo.** Sappiamo l'indirizzo del sito di ogni comune
italiano (7.888 su 7.896, da IPA) e sappiamo su quale piattaforma gira. Un
motore di ricerca è un modo indiretto e fragile di arrivare a una pagina di cui
**abbiamo già l'URL**.

Al suo posto, due gradini:

- piattaforma con lettore di catalogo (WordPress, MyPortal, PeopleWeb) →
  elencare i servizi che corrispondono al tema, letti adesso;
- altrimenti → aprire la home e agganciare i collegamenti il cui testo
  corrisponde alle parole della domanda.

Coerente con la dottrina già scritta in `sonda_live.py`: *«non è un link
trovato da un motore di ricerca: è la fonte, citata»*.

*Su degoog:* stessa classe di fragilità di SearXNG — entrambi fanno da tramite
verso motori che non controlliamo. Cambiare proxy sposta il problema di
qualche mese. Se un giorno servisse una ricerca generica (bandi statali), un
contratto vero (Brave, già previsto nelle variabili d'ambiente) è più onesto di
un proxy che fa scraping.

### 2 · La risposta si ripete e si contraddice

La premessa nuova («non ho ancora letto i dati del Comune di X») e il testo
preesistente («di questo comune non abbiamo ancora letto i dati…») dicono la
stessa cosa due volte con parole diverse, nella stessa risposta. Vanno unite in
una frase sola.

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

### 6 · Il pannello dei filtri mostra solo tre cose

`Profilo` (in `web/lib/profilo.tsx`) ha `eta`, `comune`, `interessi`. L'API
restituisce anche **nucleo familiare, figli minori, ISEE, disabilità** e la
pagina non può mostrarli perché il tipo non li prevede.

### 7 · Lettura live: manca il gradino del catalogo

Oggi il ripiego per un comune non coperto è solo la ricerca (rotta). Per i
comuni su piattaforme che sappiamo leggere il ripiego giusto è **leggerne il
catalogo adesso** — WordPress, MyPortal e PeopleWeb hanno già il lettore.

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
| **Municipium** (Maggioli) | 1.009 | solo firma | 3–5 gg |
| **HGATE** | 957 | rotte già mappate, manca la scheda | 2–3 gg |
| **AgendaSmart** | 401 | rotta `/agenda-smart` verificata | 2–3 gg |
| **OpenPA** | 364 | nome noto, rotte da mappare | 2–3 gg |
| MyPortal (completare) | 155 | già a livello modello | 0,5 gg |

Sommati: **2.886 comuni** — il 36,5% d'Italia — passerebbero da «non copro» a
una risposta vera, per una quindicina di giornate.

Restano **800 comuni non riconosciuti** (10,1%), ora in gruppi da 40–70: ogni
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
