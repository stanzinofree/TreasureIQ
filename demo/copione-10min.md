# TreasureIQ — copione demo, 10 minuti

Aggiornato: 4 agosto 2026. Per la versione corta vedi `copione.md`.

Dieci blocchi. Ogni blocco ha **AZIONE** (cosa registrare) e **VOCE** (il testo da
incollare in ElevenLabs, verbatim, senza indicazioni di regia dentro).

Circa 1.380 parole totali: a ritmo parlato normale fanno dieci minuti con le
pause. ElevenLabs tende ad andare più svelto di una persona — se esce corto,
allunga le pause al montaggio invece di aggiungere testo.

---

## Prima di premere REC

```bash
make scalda-cache COMUNI='Ciampino Camposampiero Trento Castro'
docker compose up -d
```

- Finestra a **1440×900**, zoom browser **110%**: le card sono dense, e a 100%
  in un video compresso le etichette in mono diventano illeggibili.
- Comune scelto **a mano**, mai per geolocalizzazione: la posizione non dà una
  ripresa ripetibile.
- Ogni risposta impiega ~20 secondi. Registra l'attesa e tagliala dopo: la voce
  ci va sopra comodamente, ed è il momento migliore per spiegare cosa sta
  succedendo sotto.
- **Il topic non è deterministico.** Due o tre take per blocco, tieni il buono.

---

## 1 · Il problema · 0:00–0:50

**AZIONE** — Schermata iniziale ferma. Scorri lentamente fino al campo domanda.

**VOCE**

> Ogni comune italiano pubblica i propri servizi sul proprio sito. Gli orari
> degli uffici, i contributi per i libri di testo, il calendario della raccolta
> differenziata: sono dati pubblici, e sono già online.
>
> Il problema non è che manchino. Il problema è che per trovarli bisogna sapere
> dove guardare, su quale sito, sotto quale voce di menu. Chi ha più bisogno di
> quei servizi è spesso chi ha meno strumenti per cercarli.
>
> TreasureIQ legge quei portali al posto del cittadino. Ma la parte importante
> non è che risponde: è che dice sempre da dove viene ogni riga che mostra, e
> quando non lo sa lo dichiara invece di riempire il buco.

---

## 2 · Il comune coperto · 0:50–2:00

**AZIONE** — «oppure dimmi il comune di interesse» → **Albano Laziale** →
`quando ritirano il vetro?` → attendi la scheda → fermati sui due bolli in alto.

**VOCE**

> Cominciamo dal caso facile. Albano Laziale è uno dei comuni di cui abbiamo
> letto il catalogo: quarantadue servizi, presi dal sito ufficiale.
>
> La risposta non è un paragrafo di prosa. È una scheda, e ogni parte ha un
> mestiere preciso. In alto due bolli: fonte ufficiale, informazioni parziali.
> Sono separati apposta, perché una fonte può essere ufficiale e incompleta
> nello stesso momento — e appiattire le due cose in un giudizio solo è il modo
> più elegante di mentire.
>
> Poi il servizio, con il titolo esatto che usa il comune. Non l'abbiamo
> riscritto: riformularlo significherebbe interpretarlo.
>
> Sotto, tre blocchi. Cosa sappiamo dalla fonte. Cosa puoi fare adesso. E
> l'ufficio competente, con i recapiti veri e gli orari.
>
> Quello che non troverete da nessuna parte è una percentuale di affidabilità.
> Un numero del genere avrebbe l'aria di una misura senza esserlo.

---

## 3 · La domanda fuori catalogo · 2:00–3:10

**AZIONE** — Stesso comune → `quali sono gli orari dell'ufficio tributi?` →
fermati sulla riga con il pallino vuoto, quella dell'assenza dichiarata.

**VOCE**

> Adesso il caso interessante. Chiedo una cosa che il catalogo di Albano copre
> male: l'ufficio tributi.
>
> Qui c'è un problema che riguarda qualunque sistema costruito su un modello
> linguistico. Un modello, davanti a una domanda che non rientra in nessuna
> delle categorie che conosce, non risponde mai «nessuna categoria». Sceglie la
> più vicina che esiste. Chiedendo dell'ufficio tributi, questo sistema
> rispondeva con l'iscrizione all'anagrafe: una pagina perfettamente corretta,
> messa sotto una domanda che non era la sua.
>
> Non è un dettaglio estetico. Per un cittadino, un dato giusto al posto della
> risposta che cercava è peggio di un rifiuto: se ne va convinto di aver
> ottenuto quello che chiedeva.
>
> Adesso l'etichetta che sceglie il modello vale solo se le parole del cittadino
> la reggono davvero, e la pagina deve parlare di quello. E dove il dato preciso
> manca, la scheda lo dichiara: gli orari dell'ufficio tributi non risultano
> pubblicati — quelli qui sotto sono dell'URP.
>
> Dichiarare un'assenza è una risposta. Nasconderla no.

---

## 4 · Il profilo, e il verdetto che non decide il modello · 3:10–4:30

**AZIONE** — «Accedi con SPID/CIE (simulazione)» → mostra le quattro tessere →
scegli **Giulia Bianchi** → torna in chat → `ci sono contributi per i libri di
testo?` → fermati sui criteri della scheda.

**VOCE**

> In un servizio vero, a questo punto saremmo su SPID o su CIE, e TreasureIQ
> riceverebbe indietro soltanto i dati che servono a rispondere. Qui non viene
> verificata nessuna credenziale e niente lascia il computer: quattro profili
> finti, con nomi che si leggono come inventati.
>
> Scelgo Giulia: trentotto anni, ISEE dodicimila, nucleo di tre persone.
>
> Ora la domanda cambia natura. Non chiedo più un'informazione, chiedo se ho
> diritto a qualcosa. E qui il progetto ha una regola che non negozia: il
> verdetto non lo decide il modello.
>
> Il modello capisce la domanda e basta. Poi un motore deterministico confronta
> i requisiti pubblicati dal comune con i dati del profilo, criterio per
> criterio, e mostra il conto.
>
> Guardate cosa risponde: nessun requisito ti esclude, ma sei criteri non sono
> verificabili. E li elenca: ISEE, età, nucleo familiare, figli minori,
> disabilità, condizione lavorativa. Il comune non li ha pubblicati, quindi non
> sappiamo se ti riguardano.
>
> Quella riga è il cuore del progetto. Un requisito che il comune non ha
> pubblicato non è un requisito soddisfatto, e non è nemmeno un requisito
> mancato: è un buco nei dati. Un sistema che volesse fare bella figura lo
> ignorerebbe e direbbe «sì, ne hai diritto». Questo lo conta e lo mostra.

---

## 5 · Il comune non coperto, letto adesso · 4:30–5:45

**AZIONE** — «Dimentica» il comune → **Camposampiero (PD)** →
`quali sono gli orari dell'anagrafe?` → fermati sul blocco orari, sul «Giovedì:
chiuso».

**VOCE**

> Camposampiero, provincia di Padova. Non è fra i comuni di cui abbiamo letto il
> catalogo, e sono a più di cinquecento chilometri da Albano.
>
> Invece di rispondere che non lo copriamo, il sistema va a leggere il portale
> di Camposampiero mentre il cittadino aspetta. Sono i sei secondi che avete
> visto passare.
>
> Questi orari sono quelli scritti sulla pagina del comune, riportati alla
> lettera. Non li abbiamo riscritti, non li abbiamo ordinati, non li abbiamo
> interpretati. Guardate il giovedì: chiuso. Se avessimo ricostruito un orario
> «tipico», quel giovedì sarebbe sparito, e qualcuno si sarebbe presentato
> davanti a una porta chiusa.
>
> E il bollo dice esattamente cosa sono questi dati: letti ora, non verificati,
> non conservati. Un dato letto al volo e un dato verificato non devono avere lo
> stesso aspetto, altrimenti tanto vale non distinguerli.

---

## 6 · Quando nemmeno il portale si lascia leggere · 5:45–7:00

**AZIONE** — **Ciampino (RM)** → `mi dici i numeri dell'ufficio anagrafe?` →
fermati sui bolli «ricerca web · non verificato» e sulla riga dell'URP.

**VOCE**

> Ciampino. Il portale c'è, risponde, e la pagina dell'URP la pubblica: se la
> cercate a mano la trovate in due secondi.
>
> Ma non espone i propri uffici in una forma che una macchina possa leggere.
> Non è colpa di Ciampino: è che non esiste uno standard che glielo imponga, e
> ogni comune pubblica come può.
>
> Fino a ieri il sistema si fermava qui e diceva al cittadino: cercala a mano
> sul sito. Vero, e inutile.
>
> Adesso cerca lui. E marca con precisione quello che trova: pagine trovate sul
> web, non lette da noi, da confermare con l'URP prima di fidarsene. Trovata non
> è letta, e la differenza resta scritta nella scheda invece di sfumare nel
> testo.
>
> Questo è il terzo gradino, e sta apposta dopo gli altri due: prima il dato
> verificato, poi il portale letto alla lettera, e solo alla fine la ricerca.
> Mai al contrario.

---

## 7 · Quando la risposta giusta è una domanda · 7:00–7:45

**AZIONE** — «Esci e dimentica» → «oppure dimmi il comune di interesse» →
scrivi `Castro` → mostra le tre voci proposte.

**VOCE**

> Un ultimo caso, breve. Castro.
>
> In Italia ci sono due comuni che si chiamano Castro: uno in provincia di
> Bergamo, uno in provincia di Lecce. Novecento chilometri di distanza, e regole
> diverse su tutto. E per non farsi mancare niente c'è pure Castro dei Volsci,
> in provincia di Frosinone.
>
> Il sistema non ne sceglie uno. Li mette in fila e chiede quale.
>
> Sembra una cortesia, ed è invece la stessa regola di prima: indovinare, qui,
> significa dare a qualcuno le soglie e i requisiti di qualcun altro con
> l'aspetto di una risposta certa. Fra due omonimi, la risposta giusta è una
> domanda.

---

## 8 · Il conto del recupero · 7:45–8:50

**AZIONE** — Menu → **Qualità dei dati**. Scorri la pagina, fermati sui punteggi
e sui rimedi proposti.

**VOCE**

> Fin qui abbiamo visto un assistente. Ma la cosa che questo progetto misura
> davvero è un'altra, ed è questa pagina.
>
> Per ogni comune censito, quanto costa arrivare ai suoi dati. Se esiste
> un'API o solo pagine HTML. Se i requisiti sono in campi strutturati o in prosa
> libera. Se i record hanno una scadenza, un importo, una descrizione. Se il
> catalogo è finito su dati punto gov punto it, dove un aggregatore può trovarlo.
>
> E accanto a ogni lacuna, il rimedio: cosa dovrebbe fare quel comune per
> chiuderla. Quasi sempre non serve adottare nessuno standard nuovo — il campo
> esiste già nel tema che il comune sta usando, ed è semplicemente vuoto.
>
> Questo è il punto dell'intero progetto. Non stiamo proponendo l'ennesimo
> standard: stiamo misurando quanto costa, oggi, arrivare a un dato che è già
> pubblico.

---

## 9 · Cosa non promettiamo · 8:50–9:30

**AZIONE** — Menu → **Manifesto**. Ferma su un paio di righe.

**VOCE**

> Tre cose che questo sistema non fa, e che vale la pena dire ad alta voce.
>
> Non decide se avete diritto a qualcosa: confronta quello che il comune ha
> pubblicato con quello che dichiarate, e vi mostra il conto. Se il conto non
> torna, ve lo dice.
>
> Non copre l'Italia. Cinque comuni censiti a fondo, e settemilaottocento­
> novantasei riconosciuti per nome. Sono due numeri diversi e vanno detti come
> due numeri diversi.
>
> E non tratta la ricerca sul web come una fonte. È un suggerimento marcato, da
> confermare con l'ufficio.

---

## 10 · Chiusura · 9:30–10:00

**AZIONE** — Torna alla schermata iniziale. Ferma sul titolo.

**VOCE**

> Ciampino la sua pagina la pubblica. Camposampiero pubblica i suoi orari, con
> il giovedì chiuso. Albano pubblica quarantadue servizi.
>
> Nessuno di questi comuni sta nascondendo niente. Siamo noi che non riusciamo a
> leggerli, perché non esiste una forma comune in cui pubblicarli.
>
> Trovare quello che ci spetta non dovrebbe essere una caccia al tesoro. E il
> primo passo non è un'intelligenza artificiale più brava a indovinare: è un
> dato scritto in modo che non ci sia niente da indovinare.

---

## Riserve, se un take va male o avanza tempo

- **Roma** — nome riconosciuto, dati non nostri: dice cosa sa e cosa non sa.
- **Monitoraggio** — lo stato dei sistemi, per mostrare che le fonti sono vive.
- **Segnalazione** — il cittadino può segnalare una lacuna al comune.
- **Come funziona** (`/info`) — il meccanismo per intero, se serve un blocco
  tecnico in più.
