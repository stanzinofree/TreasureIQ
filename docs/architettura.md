# Architettura di TreasureIQ

*Stato al 9 agosto 2026. Ogni cifra in questo documento è misurata, non stimata:
dove non abbiamo misurato, il documento lo dice.*

---

## Il malinteso da togliere subito

TreasureIQ sembra un sistema solo e sono **due**, con confini diversi e costi
diversi.

| | Cosa fa | Quando gira | Rete mentre un cittadino aspetta |
|---|---|---|---|
| **Acquisizione** | legge i portali comunali e ne normalizza i contenuti | offline, su comando | no |
| **Risposta** | cerca dentro lo snapshot già acquisito e decide un verdetto | a ogni domanda | no |

Il motore che risponde in chat **non interroga i dati aperti**: cerca in ciò che
l'acquisizione ha già scaricato e verificato. È la ragione per cui una risposta
arriva in tempi da conversazione e non da crawler.

L'unica eccezione è confinata e dichiarata: la **sonda live** (`sonda_live.py`),
che per un comune fuori copertura legge il portale in quel momento — solo sul
rail informativo, mai per decidere se qualcuno ha diritto a qualcosa.

La sonda segue una scala fissa, dal certo al probabile: **record già ingerito →
mappa diretta del portale del comune → ricerca Brave ancorata al dominio**
(`site:comune.x.it …`, D-58). SearXNG è fuori (D-59): un proxy verso motori che
non controlliamo è più fragile di un contratto vero, usato per giunta su pagine
di cui conosciamo già l'indirizzo. Ogni pagina così raggiunta torna marcata
`non verificato`: è la fonte citata, non un verdetto.

---

## Dimensioni reali

| | |
|---|---|
| Righe di codice Python (`api/treasureiq`) | 21.838 su 46 moduli |
| Righe di codice TypeScript/TSX (`web`) | 10.577 |
| Test | 481, tutti verdi, su 27 file |
| Comuni censiti | 7.896 — tutti i comuni italiani |
| Richieste per un censimento completo | 34.229, circa 4 per comune |
| Durata di un censimento completo | ~90 minuti con 8 richieste in parallelo |
| Servizi comunali contati | 57.603 |
| Piattaforme riconosciute | 20 |
| Modello linguistico (`chat/filtri.py`) | spaCy `it_core_news_lg` 3.8.0, ~500MB — scaricato nel Dockerfile, non fissato in `requirements.txt`; se assente il riconoscimento filtri degrada a una cue-list |

---

## Il motore di acquisizione

### Connettori

Un connettore per **piattaforma sorgente**, con un'interfaccia sola:
`Connector.fetch()`. Ogni connettore dichiara la propria `transport_quality` —
un'API tipizzata vale più di uno scrape HTML — e **misura quanta struttura ha
recuperato** invece di limitarsi a recuperarla.

Quella misura non è telemetria interna: finisce nel punteggio pubblico di
leggibilità, quindi deve restare onesta anche quando è poco lusinghiera.

Due connettori leggono fuori dal modello AgID, sul dominio proprio del comune:

- **Municipium** (`municipium.py`, `municipium_at.py`) — non c'è un'API host
  comune (risponde 503): la scoperta parte da `{dominio}/it/sitemap`, che
  elenca gli uffici e, quando c'è, l'Amministrazione Trasparente. Copertura
  onesta a due terzi: sitemap e uffici sì, AT solo quando il comune la
  pubblica nello stesso formato.
- **Halley** (`alberatura.py`) — i concorsi pubblici veri spesso non vivono
  nel WordPress del comune ma in un portale Halley separato, sotto `/zf/`.
  Le pagine dichiarano ISO-8859-1/windows-1252: un decode UTF-8 a forza
  corromperebbe i caratteri accentati, quindi il connettore decodifica col
  charset dichiarato (ripiego a ISO-8859-1 se assente).

`bandi_live.py` mette in fila tre gradini REST, dal certo al meno probabile,
e si ferma al primo che risponde:

1. **`cpt`** — un custom post type dedicato ai bandi, dove il portale lo espone.
2. **`pages`** — le stesse sei parole chiave di ricerca cercate su
   `wp/v2/pages`, per i comuni WordPress "semplici" senza CPT (es. Albano).
3. **`alberatura`** — il portale Halley `/zf/`, tentato solo quando i primi due
   non coprono il comune.

Un comune che non risponde a nessuno dei tre resta `non_coperto`, dichiarato
come tale — mai un elenco vuoto spacciato per «nessun bando».

### Il modello AgID come interfaccia

La scoperta che ha riorganizzato tutto: **l'interfaccia da leggere non è il CMS,
è il modello di contenuto AgID**. La scheda servizio di PeopleWeb espone
`A chi è rivolto`, `Come fare`, `Cosa serve`, `Tempi e scadenze` — le stesse
identiche voci che il tema WordPress Design Comuni tiene in campi tipizzati, e
che il modello PNRR del Veneto nomina in inglese (`pnrr_what_is_needed`).

Quindi si scrive **un lettore del modello**, con una *declinazione* per
fornitore, invece di sei connettori per sei prodotti. Le declinazioni
differiscono solo nella forma: quale livello di intestazione, quale prefisso di
campo, quali alias di etichetta.

### Cosa il lettore produce

Per ogni scheda letta:

- **aderenza** — quanta parte del modello quel portale espone davvero;
- **sezioni dichiarate** e **compilate** — la differenza fra ciò che il fornitore
  ha previsto e ciò che il comune ha riempito. Distinguibile **solo** dove i
  campi sono tipizzati;
- **impronta della declinazione** — un hash della forma strutturale, che
  sostituisce il numero di versione che nessun fornitore pubblica;
- **stato dei vincoli** — se il campo che dice *chi ha diritto* esiste, e se
  qualcuno l'ha riempito.

### L'aderenza è una misura del fornitore, non del comune

L'aderenza dice quante sezioni del modello AgID quel portale espone davvero —
`A chi è rivolto`, `Come fare`, `Cosa serve`, `Tempi e scadenze`. È una misura
del **fornitore prima che del comune**, ed è la ragione per cui vale la pena
calcolarla: dice a chi va chiesto conto, perché è il fornitore ad aver scelto
la declinazione — chi con `<h4>`, chi con `<h3>`, chi solo per metà — non il
comune che quella declinazione l'ha subita.

Va letta **come media su più comuni, mai su una pagina sola**: sotto `/servizi`
vivono anche pagine informative che il modello non ce l'hanno per disegno, e
misurare quelle fa sembrare inadempiente chi non lo è. Sul campo, ComWeb
misurato su una pagina sbagliata dava **0,10**; su ventitré comuni dà **0,70**.
Stesso fornitore, stesso codice: solo il denominatore era sbagliato.

L'impronta accompagna l'aderenza come sostituto del numero di versione che
nessun fornitore pubblica: finché regge, la declinazione è quella; quando
cambia — di solito sulla stessa notte, su tutti i comuni di quel fornitore —
sappiamo cosa sta per rompersi, prima che se ne accorga un cittadino.

---

## Il censimento nazionale

Una sonda deterministica misura ogni comune italiano su tre assi.

**Asse A — indirizzabilità.** Il portale risponde? Espone un'API degli uffici?

**Asse B — recuperabilità.** Gli orari di sportello si trovano, e in che forma?

**Asse C — piattaforma.** Che software gira sotto, con la **prova verbatim** che
l'ha deciso: un header, un meta tag, un percorso di asset.

### Come si scoprono le piattaforme

Non si elencano in anticipo: **si raggruppano gli sconosciuti**. Metà dei comuni
italiani non espone né `meta generator` né header di prodotto, quindi la sonda
registra per ognuno un'**impronta grezza** — nome del server, estensioni delle
rotte, prime directory degli asset — e i fornitori emergono da un `GROUP BY`
sullo storico.

Due regole imparate a caro prezzo:

- **Un `generator` sconosciuto va conservato verbatim, mai scartato.** È così
  che è emerso ComWeb, che si dichiara in chiaro e finiva fra gli anonimi.
- **Raggruppare per impronta esatta spacca le famiglie.** La versione di nginx e
  i nomi dei cookie cambiano fra deployment: raggruppando su quelli, Municipium —
  1.009 comuni, il 12,8% d'Italia — appariva come decine di gruppi da cinque.

---

## Lo store

Un solo file SQLite, `data/storico.db`, con due tabelle e una regola comune:
**una riga per soggetto per giorno, mai sovrascritta fra giorni diversi**.

| Tabella | Cosa registra |
|---|---|
| `costo_snapshot` | quanto ci è costato leggere i comuni che ingeriamo |
| `portale_snapshot` | la misura di **tutti** i portali italiani, ingeriti o no |

Sono separate di proposito: un comune compare nel censimento anni prima che
qualcuno gli scriva un connettore, e confondere «misurato» con «ingerito»
trasformerebbe una mappa del paese in un rapporto sul nostro arretrato.

### Provenienza

Ogni riga dice **chi l'ha decisa**: `classificato_da` vale `sonda` quando l'ha
misurata la sonda, `riclassificazione` quando l'ha dedotta una regola applicata
dopo, leggendo l'impronta già salvata.

Serve a proteggere la metrica che vale di più. Riclassificare vecchie righe con
regole nuove fa sembrare che un comune sia *migrato* da `ignota` a `hgate`
quando sul suo portale non è cambiato niente — è cambiata la nostra ignoranza.
`evoluzione(da, a)` scarta quei cambi, così le migrazioni vere restano visibili
e le nostre revisioni no.

---

## Il motore di risposta

Sette passi, di cui **cinque deterministici**.

1. **Intento** *(modello)* — il testo libero diventa uno schema chiuso: forma
   della domanda, argomento, indizio di comune. Da qui non escono più slot
   anagrafici (ciclo 11, D-01): il modello classifica topic/kind/comune_hint
   e nient'altro (`chat/intent.py:473-477`). Mai prosa, mai un verdetto.
2. **Filtri** *(deterministico)* — gli slot anagrafici (comune, disabilità
   propria o nel nucleo, figli minori, età, ISEE, tipo di nucleo, condizione
   lavorativa, tema) non li deduce più il modello linguistico: li riconosce
   `chat/filtri.py::riconosci_filtri` per pattern e lemmi spaCy
   (`it_core_news_lg`), un filtro alla volta, ciascuno con lo **span verbatim**
   che lo giustifica. Nessuno span, nessun filtro: è la regola che uccide
   l'allucinazione. Riconosce anche la negazione («non sono disabile»)
   segmentando le clausole del testo. Senza il modello spaCy (scaricato nel
   Dockerfile, non fissato in `requirements.txt`) degrada a una cue-list di
   frasi fisse — più debole, ma dichiarata, mai muta.
3. **Guardie** *(deterministiche)* — il comune nominato deve comparire nelle
   parole del cittadino; il ruolo deve essere dichiarato; gli argomenti
   informativi per natura non possono diventare agevolazioni. Scartano ciò che
   il modello ha aggiunto di suo.
4. **Recupero** *(deterministico)* — 21 argomenti, 68 chiavi, confronto a
   confine di parola: `tari` non prende `tariffa`, `tributi` non prende
   `contributi`.
5. **Pertinenza** *(deterministica)* — le chiavi devono comparire sia nella
   domanda sia nel titolo, oppure i due devono condividere una parola piena.
   Fuori dal conteggio le parole generiche e il nome del comune.
6. **Verdetto** *(deterministico)* — 7 criteri confrontati con `Decimal`, tre
   valori logici, quattro esiti. Nessun modello tocca questo passo.
7. **Verbalizzazione** *(modello)* — mette in italiano un verdetto già preso. Le
   cifre e le citazioni arrivano dai campi strutturati, non dal testo generato.

Il confine è quello: **il modello capisce la domanda, non stabilisce l'esito.**

---

## Confini che il codice fa rispettare

**Nessuna rete mentre un cittadino aspetta**, tranne la sonda live per i comuni
fuori copertura, sul solo rail informativo, con esito in cache separata e
scrivibile — `data/` è montata in sola lettura apposta.

**Un requisito compare solo se esiste nel documento**, citato verbatim. Se la
citazione non si ritrova nella fonte, il requisito cade.

**Un campo non misurato resta vuoto, mai zero.** Su un grafico zero e
sconosciuto hanno lo stesso aspetto e significato opposto.

**Le due basi di misura dell'aderenza non si sommano.** Leggendo HTML si misura
sul modello intero; leggendo campi tipizzati sui soli box che l'API espone. A
denominatore unico il fornitore più conforme d'Italia risultava ultimo.

---

## Cosa non c'è, e perché

**Nessuna coda di messaggi.** Un censimento nazionale è 34.229 richieste in 90
minuti su una lista finita: un lavoro batch, non un flusso.

**Nessun object storage.** Conservando il testo estratto invece dei binari, il
nazionale sta sotto il gigabyte, e il PDF originale resta citabile per URL.

**Nessun database server.** SQLite in modalità WAL regge questi volumi, e lo
store sta dietro un modulo solo: cambiare motore, quando servirà, è un
pomeriggio.

Le condizioni misurabili che rimetterebbero in gioco ciascuna di queste scelte
sono in [evoluzione.md](evoluzione.md).
