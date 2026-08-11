# Roadmap

*Scritta il 6 agosto 2026, aggiornata il 9 agosto 2026. Da rivedere
all'inizio della prossima sessione: è una proposta di sequenza, non un
impegno.*

Il dettaglio di ogni voce — cosa è rotto, perché, quanto costa — sta in
[da-fare.md](da-fare.md). Qui c'è solo **l'ordine**, e la ragione dell'ordine.

---

## Il vincolo che decide tutto

**Otto giorni alla scadenza**, e la consegna non è il codice: è il **video**.
È l'unica cosa che nessun altro può fare al posto nostro, e l'unica che, se
manca, rende inutile tutto il resto.

Quindi la roadmap si legge al contrario: si parte da cosa deve essere vero
davanti a una telecamera, e si toglie tutto ciò che non lo serve.

---

## Fase 1 · Rendere vera la demo (2 giorni)

Cose che si vedono in tre minuti di video e che oggi sono rotte.

**La ricerca live che non trova mai niente.** La risposta promette «ho cercato
adesso sul sito del comune» e sotto non c'è nulla. Sostituire il gradino web
con la lettura diretta: sappiamo l'URL di 7.888 comuni e su quale piattaforma
girano. → *da-fare § 1*

**La risposta che si ripete.** Due frasi diverse dicono la stessa cosa nella
stessa risposta. → *§ 2*

**Il rail informativo a zero.** «Dove sta l'anagrafe» non risponde nemmeno sui
comuni ingeriti, e per un video è la domanda più naturale che esista. → *§ 3*

**Genzano e Marino registrati senza dati.** Rispondono come coperti e non
trovano niente: in una dimostrazione dal vivo è il difetto peggiore, perché
sembra che il motore non funzioni. → *§ 4*

## Fase 2 · Allargare quello che si può mostrare (1 giorno)

**FATTO** — il ciclo nlp-filtri: `filtri.py` deterministico (10
`FiltroChiave`, span-obbligatorio dal testo, Ollama non riempie più nessuno
slot) e i chip in `ChipFiltri.tsx`/`ProfiloNoto.tsx` sul rail. Chiudeva anche
*da-fare § 6* (il pannello mostrava solo tre campi di profilo).

**I 155 comuni MyPortal**, già leggibili in JSON: mezza giornata, il miglior
rapporto fra lavoro e risultato della lista. → *§ 8*

**Ingerire altri comuni** su WordPress Design Comuni: tre secondi e zero
chiamate al modello ciascuno. La lista dei leggibili è in
[connettori.md](connettori.md).

**La popolazione ISTAT**, per poter dire «il 46% dei cittadini» invece di «il
12% dei comuni». Un `UPDATE`, nessuna richiesta di rete. → *§ 9*

## Fase 3 · La consegna (2 giorni)

**Il video.** Il copione esiste già in `demo/copione-10min.md` e va rifatto
sui numeri nuovi.

**Il pitch.** Numeri, coerenza e storia ci sono: il censimento nazionale, il
94% dei campi vuoti, le tre regioni che hanno risolto il problema una volta
sola.

**La pagina `/developer`** — una sola, scritta a mano: com'è fatto, quanto è
vero, e cosa abbiamo deciso di **non** fare con le soglie che lo
rimetterebbero in discussione. Quest'ultima parte è la più rara e la più
convincente davanti a un giudice tecnico.

## Fase 4 · Prima di qualunque esposizione pubblica

**Limite di frequenza per host** in acquisizione: l'unico punto in cui
possiamo danneggiare terzi. **Cookie `Secure`** fuori da localhost.
**`robots.txt`** letto e registrato. → *sicurezza.md*

---

## Dopo l'hackathon, se il progetto continua

In ordine di quanto restituiscono:

1. **I connettori** — Municipium (1.009 comuni) è passato da "solo firma" a
   **parziale/consegnato** al ciclo 10 (uffici letti dal sito, bandi onesti
   su 2 comuni su 3 testati): resta HGATE (957), AgendaSmart (401), OpenPA
   (364). Sommati con MyPortal: **2.886 comuni**, il 36,5% d'Italia, per una
   quindicina di giornate. Nessun'altra voce ha questo rapporto. →
   [connettori.md](connettori.md)
2. **Il registro delle esecuzioni** — è il problema che ci ha morso davvero:
   in una giornata la definizione di aderenza è cambiata quattro volte e le
   pagine hanno mostrato una stratigrafia invece di un dataset.
3. **Un registro unico dei comuni**, al posto dei tre che oggi devono
   concordare a mano.
4. **Lo scheduler** e il resto dell'architettura post-MVP, dimensionati sui
   numeri misurati. → [evoluzione.md](evoluzione.md)
5. **Un motore di ingestione** vero. Oggi `ingest/` è uno scheletro
   (`Connector`, `FetchStats`, readiness) che gira a comando su un set-pagine
   non riproducibile. Il passo è renderlo **guidato dallo sweep** — la
   piattaforma rilevata sceglie il connettore — con un corpus riproducibile e
   la stessa change-detection che il registro già ha. Resta un atto **distinto**
   dallo sweep, non fuso in esso (perché, in [architettura.md](architettura.md)).

---

## La direzione del prodotto

Quattro fronti, in ordine di quanto avvicinano TIQ a essere il punto d'ingresso
unico del cittadino. Nessuno è un impegno di data: sono le direzioni che
seguirebbe, se il progetto continua.

**1 · Più comuni, anche chiedendo apertura.** Il grosso della copertura resta
lavoro di connettori (→ [connettori.md](connettori.md)). Ma una fetta di comuni
— i portali in Angular/JS renderizzati lato client, come i 168 di Regione FVG —
non espone nessuna API leggibile staticamente: costa più reverse-engineering di
quanto renda. Per questi la mossa giusta non è tecnica ma **civica**: chiedere
all'ente di **aprire un endpoint pubblico** dei propri contenuti. Un Comune che
pubblica già i dati per legge non ha ragione di nasconderli dietro un rendering
che nemmeno un motore di ricerca legge.

**2 · Una chat che risponde come una persona informata.** Oggi «è aperto oggi
l'ufficio anagrafe?» ottiene gli orari. Il passo successivo è la risposta che
darebbe un impiegato onesto: **«Sì, questi sono gli orari — ma chiama per
sicurezza»**. Significa incrociare l'orario con il giorno, dichiarare
l'incertezza invece di fingere certezza, e portare sempre il recapito per
verificare. Il verdetto resta deterministico (§ *Il motore di risposta* in
[architettura.md](architettura.md)); è la **verbalizzazione** a diventare più
naturale, non il dato a diventare più disinvolto.

**3 · Ricerca bandi più forte.** I tre gradini in cascada (`cpt` → `pages` →
`alberatura`, incluso il portale Halley dei concorsi) coprono i casi principali,
ma la scoperta va estesa: più vendor con estrattore reale, filtri per tema e
scadenza più precisi, e la distinzione netta fra «nessun bando» e «non so
leggere questo portale». → [connettori.md](connettori.md)

**4 · Le news del Comune, con uno standard da chiedere.** Dopo servizi e bandi,
il terzo contenuto che un cittadino cerca sono gli **avvisi**: chiusure,
scadenze, allerte. Oggi ogni Comune li pubblica a modo suo. La strada
sostenibile non è scrapare mille layout diversi ma **chiedere agli enti di
esporre un feed RSS/Atom** — uno standard che esiste da vent'anni, gratis da
produrre, e che renderebbe le news leggibili senza un connettore per template.
Come per il fronte 1, la leva è chiedere apertura, non inseguire la chiusura.

---

## Cosa non faremo, e perché

**Coda di messaggi, object storage, database server.** Un censimento
nazionale sono 34.229 richieste in novanta minuti su una lista finita: un
lavoro batch, non un flusso. Le condizioni misurabili che rimetterebbero in
gioco ciascuna scelta sono scritte in [evoluzione.md](evoluzione.md) — così
la decisione si rivede con un dato invece che con un'opinione.

**Un motore di ricerca nostro.** SearXNG e le sue alternative fanno da tramite
verso motori che non controlliamo: cambiarne uno sposta il problema di qualche
mese, e infatti SearXNG è fuori dalla scala (D-59). Il terzo gradino oggi è
Brave con ricerca **ancorata al dominio** del comune (`site:comune.x.it …`,
D-58): un contratto vero, non un proxy che fa scraping, e usato solo per un
comune di cui conosciamo già l'indirizzo — non per cercare l'indirizzo. La
scala reale è: record ingerito → mappa diretta del comune → Brave `site:`.
Ollama resta confinato all'intento, mai al verdetto (D-01).

**Coprire l'ultimo 10% dei portali non riconosciuti.** Sono 800 comuni in
gruppi da 40–70: ogni firma nuova ora vale decine di comuni, non più
centinaia. Il tempo rende di più altrove.

---

## Come verificare che una fase sia finita

Rieseguire la matrice: `python api/tests/matrice/matrice.py`.

Novanta combinazioni — nove comuni su tre livelli di copertura, cinque
domande, due profili — contro l'API vera. È lo strumento che ha trovato la
ricerca morta, il bando del Lazio offerto in Sicilia e l'anagrafe a zero, e
nessuno dei tre si vedeva leggendo il codice.
