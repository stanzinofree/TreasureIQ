# Roadmap

> **Nota v1:** il framing aggiornato e il piano operativo corrente sono in
> [piano-v1.md](piano-v1.md). TIQ non è pensato per confrontare o classificare
> i comuni: deve rendere ricercabili le informazioni pubbliche ovunque, usando
> connettori come ponte temporaneo verso uno standard aperto della PA. Questo
> documento conserva la roadmap precedente e va letto come storico/contesto
> finché non verrà riallineato punto per punto.

*Se l'hackathon va bene e TIQ vince, questa è la strada. Nessuna data: le date
mentono quando il progetto è di uno solo. Qui c'è **l'ordine**, e la ragione
dell'ordine — quanto ogni fronte avvicina TIQ a essere il punto d'ingresso unico
del cittadino.*

---

## Il criterio

Quattro fronti. Nessuno è un impegno di calendario: sono le direzioni che TIQ
seguirebbe se il progetto continua oltre l'MVP. Vengono prima quelli che
restituiscono di più — più comuni leggibili, o risposte più utili — per lo
stesso lavoro. Il dettaglio operativo di ciascuno vive in
[da-fare.md](da-fare.md); qui c'è la strategia.

## 1 · Irrobustire il riconoscimento delle piattaforme

Tutto parte dalla firma: se TIQ non riconosce su che piattaforma gira un comune,
non sa quale connettore usare. Oggi riconosce la maggior parte del panorama, ma
i pattern sono fragili in due punti.

- **Drift dei template.** Un fornitore aggiorna il tema e la firma si sposta su
  molti comuni la stessa notte: il connettore scritto sul vecchio non calza più.
  Serve rendere le impronte più resistenti alla variazione cosmetica e trattare
  il movimento improvviso dell'impronta come **allarme**, non come rumore.
- **La coda lunga dei «grigi».** Restano gruppi da 40–70 comuni su firme non
  ancora scritte. Ogni firma nuova ora vale decine di comuni, non più centinaia,
  ma è proprio da qui che si sceglie il prossimo connettore: la barra più alta
  fra i grigi in Analytics è il lavoro che sblocca di più.

Obiettivo: meno comuni «non dichiarati», e firme che non si rompono al primo
restyle.

## 2 · Connettori più profondi e un substrato di query più solido

Riconoscere una piattaforma non basta: bisogna **leggerla bene**.

- **Leggere il modello dove oggi c'è solo la firma.** Diverse famiglie
  (Municipium, eGov/hgate, OpenPA) hanno un connettore che estrae servizi e
  uffici ma di cui lo sweep **non calcola ancora l'aderenza** al modello AgID.
  Portarle a misura piena arricchisce la tabella dei fornitori e rende onesto il
  confronto. → [connettori.md](connettori.md)
- **Ingestione guidata dallo sweep.** Oggi `ingest/` gira a comando su un
  set-pagine non riproducibile. Il passo è renderla **pilotata dal censimento**
  — la piattaforma rilevata sceglie il connettore — con un corpus riproducibile
  e la stessa change-detection che il registro già ha. → [architettura.md](architettura.md)
- **Query live robuste verso i siti.** Il proof-of-concept sui bandi di gara
  Halley (landing trasparenza → sezione legacy → elenco con titolo, CIG, link)
  dimostra che la navigazione live regge anche su portali lenti e legacy. Va
  generalizzata ad altri vendor, sempre dietro la guardia SSRF per-hop.
- **Per i portali illeggibili, chiedere apertura.** Una fetta di comuni — i
  portali in Angular/JS renderizzati lato client, come i 168 di Regione FVG —
  non espone nessuna API leggibile staticamente: costa più reverse-engineering
  di quanto renda. Qui la mossa giusta non è tecnica ma **civica**: chiedere
  all'ente di esporre un endpoint pubblico dei propri contenuti. Un Comune che
  pubblica già i dati per legge non ha ragione di nasconderli dietro un
  rendering che nemmeno un motore di ricerca legge.
- **Standardizzare il connettore in capability, non in un monolite.** Oggi ogni
  vendor è una funzione sola che produce tutto in un colpo; la chat, che spesso
  vuole *una* cosa (l'orario di quell'ufficio, il logo), non può chiederla senza
  ri-scansionare. La direzione è un contratto a **verbi discreti** — `elenca_uffici`,
  `retrieve_ufficio`, `scan_logo`, `scan_mappa_sito`, `scopri_at` — con la stessa
  sequenza da entrambi i lati chat↔connettore, e il retrieve customizzato *dentro*
  il connettore (dove sta il logo lo sa il vendor, non la chat). Confine dati
  pulito = confine di linguaggio: un connettore potrà essere un binario Rust/Go
  che emette lo stesso `EsitoConnettore` dove lo scraping rende meglio fuori da
  Python. → dettaglio in [da-fare.md](da-fare.md)

## 3 · Una chat che risponde come una persona informata

Oggi «è aperto oggi l'ufficio anagrafe di Albano Laziale?» ottiene gli orari. Il
passo successivo è la risposta che darebbe un impiegato onesto: incrociare
l'orario con il **contesto del giorno**, dichiarare l'incertezza invece di
fingere certezza, e portare sempre il recapito per verificare.

Esempio del comportamento a cui puntiamo:

> Oggi è **15 agosto**, festa nazionale in Italia. Ho letto gli orari
> dell'anagrafe dalla sua pagina e ho controllato gli avvisi del Comune, ma
> **non ho trovato conferme** sulla chiusura o apertura dell'ufficio in questo
> giorno. Conviene chiamare il **numero XXXX** riportato sulla pagina
> dell'ufficio, oppure l'**URP al numero yyyy** preso dal sito.

Cosa serve dietro:

- incrociare l'orario con il calendario (festività nazionali) e con le **news di
  chiusura** pubblicate dal Comune;
- una risposta **probabilistica e onesta** — «buona probabilità», non certezza
  falsa — quando la fonte non conferma;
- **sempre un recapito** (numero dell'ufficio dalla sua pagina, URP come
  fallback) per chiudere il dubbio con una telefonata.

Il verdetto resta deterministico (§ *Il motore di risposta* in
[architettura.md](architettura.md)); è la **verbalizzazione** a diventare più
naturale, non il dato a diventare più disinvolto.

## 4 · Bandi e requisiti: ricerca e risposte migliori

Il terzo motivo per cui un cittadino apre il sito del Comune, dopo servizi e
uffici, sono **bandi e diritti**.

- **Ricerca bandi più forte.** La cascata di gradini (`cpt` → `pages` →
  `alberatura`, incluso il portale Halley dei concorsi) copre i casi principali,
  ma la scoperta va estesa: più vendor con estrattore reale, filtri per **tema e
  scadenza** più precisi, e la distinzione netta fra «nessun bando» e «non so
  leggere questo portale». → [connettori.md](connettori.md)
- **Requisiti leggibili.** Il campo «a chi è rivolto / condizioni di accesso»
  esiste, ed è vuoto sul 94% dei comuni interrogabili. Dove è compilato, la
  domanda «ho i requisiti?» diventa **deterministica**: si confrontano i filtri
  del cittadino con i vincoli pubblicati, senza interpretazione. Più requisiti
  esposti in campi tipizzati significa meno margine per l'ambiguità — ed è la
  ragione per cui, a valle, TIQ caldeggia lo standard di esposizione.

---

## Oltre l'MVP · Da prototipo validato a sistema

*I quattro fronti sopra fanno crescere TIQ in larghezza — più comuni, risposte
più utili. Questo capitolo è un'altra cosa: **la maturazione**. L'MVP è servito
a una cosa sola, e l'ha fatta: dimostrare che l'idea regge e ha potenziale. La
strada dopo la vittoria non aggiunge feature, **irrobustisce le fondamenta** —
stabilità, applicabilità, riproducibilità, con un occhio a performance,
standardizzazione e a un'evoluzione che non rompa gli schemi e i contratti a
ogni passo. È il salto da prototipo che convince a sistema di cui ci si fida.*

Il principio unico: **ogni cucitura del sistema è un contratto tipizzato,
attraversato da funzioni pure, con la provenienza sempre in chiaro.** Vale per
la chat come per i connettori. Due cantieri, stessa dottrina.

### Il motore chat come pipeline standardizzata

Oggi l'estrazione di profilo, intento e filtri vive intrecciata nel codice di
risposta, con cinture e casi speciali che si sono accumulati. La direzione è un
flusso lineare e ispezionabile — l'utente scrive, un analizzatore (funzione,
microservizio o binario Rust/Go) normalizza e torna filtri canonici, un motore
di ricerca li consuma e compone la risposta:

```
CHAT → NORMALIZZAZIONE → [profilo · intento · filtri] → VALIDATOR
     → FILTRI CANONICI → RETRIEVAL → VERDETTO → UI
```

Ogni slot estratto porta la sua prova — non solo «niente figli», ma *perché* lo
sappiamo: `{ field, value, confidence, source, matched }`, con la confidenza
**derivata dalla provenienza, mai emessa dal modello**. Questo dà due cose
insieme: filtri più precisi (segmentare l'intento sul settore giusto) e un
audit civico — TIQ sa sempre spiegare *da dove* viene una sua convinzione.

Sei rework compongono il cantiere — registro schemi condiviso, profilo come
reducer event-sourced, validator che riconcilia i conflitti, retrieval come
router di capability, muro netto fra verdetto e verbalizzazione, e un replay
harness che rigioca l'intera pipeline sui casi reali. Il dettaglio operativo e
l'ordine (il registro schemi apre la strada; reducer e replay comprano più
stabilità subito) sono in [da-fare.md](da-fare.md).

### L'accesso: mobile-first, fino a un'app dedicata

Un cittadino apre il sito del Comune dal telefono, in coda a uno sportello o
sul bus — non dalla scrivania. L'MVP è nato responsive ma pensato desktop; il
passo di maturità è **rifare la UX mobile-first**, il pollice come unità di
misura: la chat che riempie lo schermo, la scheda civica che scorre, i recapiti
a un tocco per chiamare. E dove il mobile web non basta — notifiche di scadenza
di un bando, il profilo che persiste, l'accesso SPID nativo — la strada è uno
**spin-off in app dedicata**, con lo stesso `api` dietro: il confine chat↔API
già pulito rende l'app un altro client, non una riscrittura.

### Perché è questa la strada, e non altre feature

- **Determinismo.** Un flusso a stadi puri si testa stadio per stadio e si
  rigioca uguale a sé stesso; la famiglia di bug di stato — un follow-up che si
  porta dietro il comune sbagliato — sparisce alla radice invece di essere
  rincorsa caso per caso.
- **Riproducibilità.** Ogni bug diventa una fixture nel replay harness; una
  regressione si vede prima di arrivare in chat, non dopo.
- **Standardizzazione e sostenibilità.** Schemi e contratti congelati in un solo
  posto significano che un connettore o un analizzatore possono essere riscritti
  — anche in un altro linguaggio, dove lo scraping o le performance lo ripagano —
  senza rompere il resto: il confine dati **è** il confine di linguaggio, e un
  conformance test difende quel confine come già fa l'oracolo di parità dello
  scorer intent (35/35).
- **Professionalità.** È la differenza fra un prototipo che dimostra e un sistema
  di cui un ente si fida: contratti espliciti, provenienza tracciata, verdetto
  separato dalla verbalizzazione.

Blast radius alto e trasversale: si procede col metodo già rodato sui
connettori — contratto congelato, test di parità sul comportamento attuale, un
pezzo alla volta. Nessun big-bang.

---

## Cosa non faremo, e perché

**Coda di messaggi, object storage, database server.** Un censimento nazionale
sono decine di migliaia di richieste in un'ora e mezza su una lista finita: un
lavoro batch, non un flusso. Le condizioni misurabili che rimetterebbero in
gioco ciascuna scelta sono scritte in [evoluzione.md](evoluzione.md) — così la
decisione si rivede con un dato invece che con un'opinione.

**Un motore di ricerca nostro.** SearXNG e le sue alternative fanno da tramite
verso motori che non controlliamo: cambiarne uno sposta il problema di qualche
mese. Il gradino di ricerca oggi è Brave **ancorato al dominio** del comune
(`site:comune.x.it …`): un contratto vero, non un proxy che fa scraping, e usato
solo per un comune di cui conosciamo già l'indirizzo — non per cercare
l'indirizzo. La scala reale è: record ingerito → mappa diretta del comune →
Brave `site:`. Ollama resta confinato all'intento, mai al verdetto.

**Inseguire l'ultimo 10% dei portali non riconosciuti a colpi di scraping.**
Sono comuni in gruppi da 40–70: ogni firma nuova rende, ma sotto una certa
soglia il tempo rende di più altrove — o, meglio, si chiede apertura invece di
inseguire la chiusura (fronte 1 e 2).

---

## Come verificare che una direzione regga

Rieseguire la matrice: `python api/tests/matrice/matrice.py`.

Novanta combinazioni — nove comuni su tre livelli di copertura, cinque domande,
due profili — contro l'API vera. È lo strumento che ha trovato la ricerca morta,
il bando del Lazio offerto in Sicilia e l'anagrafe a zero, e nessuno dei tre si
vedeva leggendo il codice. Ogni fronte è «finito» quando la matrice lo conferma,
non quando il codice sembra giusto.
