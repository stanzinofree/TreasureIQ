# Roadmap

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
