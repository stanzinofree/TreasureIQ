# TreasureIQ — copione demo, 3 minuti

Aggiornato: 4 agosto 2026.

Video da registrare in due tracce separate: **schermo muto** prima, **voce**
dopo. Parlare mentre si clicca costringe a rifare tutta la ripresa a ogni
inciampo, e queste risposte impiegano una ventina di secondi ciascuna.

Durata bersaglio **3:00**. Le battute sotto stanno in circa 420 parole, che a
un ritmo parlato normale — non da telegiornale — fanno tre minuti con le pause
dentro. Se sfori, il primo taglio è lo scenario D.

---

## Prima di premere REC

```bash
make scalda-cache COMUNI='Ciampino Camposampiero Trento'
docker compose up -d
```

Senza cache calda la sonda si prende sei secondi di rete in diretta, davanti
alla camera. Con la cache, la stessa identica lettura arriva subito: non cambia
di una virgola cosa risponde il sistema, sposta solo l'attesa fuori dal video.

Tre cose da sapere, che è meglio scoprire adesso che al montaggio:

- **Il topic non è deterministico.** La stessa domanda può passare per due
  strade diverse a due run di distanza. Gira due o tre take per scenario e tieni
  il migliore.
- **Ogni risposta impiega ~20 secondi.** Nel montaggio quel vuoto si taglia, o
  si riempie con la voce: è anzi il momento giusto per dire *perché* stiamo
  interrogando un portale invece di un database.
- **Comune scelto a mano**, mai per geolocalizzazione: il pulsante «oppure
  dimmi il comune di interesse» dà una ripresa ripetibile, la posizione no.

---

## La tesi, in una riga

Non serve un modello che sappia tutto: serve un sistema che sappia **da dove
viene ogni riga** che mostra, e che non riempia i buchi.

---

## A — Il comune coperto · 0:00–0:40

**Comune:** Albano Laziale · **Domanda:** `quando ritirano il vetro?`

**Voce (0:00–0:12), sulla schermata iniziale**

> Un cittadino cerca un'informazione del suo comune. Oggi la trova aprendo il
> sito, se sa dove guardare. TreasureIQ legge quei portali al posto suo — e
> quando risponde, dice sempre da dove viene quello che dice.

**Voce (0:12–0:40), mentre arriva la scheda**

> Questa è una pagina ufficiale del Comune di Albano Laziale. Il titolo è il
> suo, non l'abbiamo riscritto. Sotto, tre righe: cosa sappiamo dalla fonte,
> cosa manca, e cosa il cittadino può fare adesso. Nessuna percentuale di
> affidabilità: sarebbe una misura finta.

**Fermare l'immagine su:** i due bolli in alto, *Fonte ufficiale* e
*Informazioni parziali*. Sono separati apposta — una fonte può essere ufficiale
e incompleta insieme.

---

## B — La domanda fuori catalogo · 0:40–1:20

**Comune:** Albano Laziale · **Domanda:** `quali sono gli orari dell'ufficio tributi?`

Il momento più importante del video. È qui che si vede la differenza fra questo
e un chatbot.

**Voce (0:40–1:05)**

> Ora chiedo una cosa che il catalogo di Albano non copre: l'ufficio tributi.
> Un modello linguistico, davanti a una domanda fuori catalogo, non risponde
> mai «non lo so»: sceglie la categoria più vicina che esiste. Chiedendo i
> tributi rispondeva con l'anagrafe — una pagina giusta, sotto la domanda
> sbagliata.

**Voce (1:05–1:20)**

> Adesso l'etichetta del modello vale solo se le parole del cittadino la
> reggono davvero. E quando manca il dato preciso, la scheda lo dichiara:
> «gli orari dell'ufficio tributi non risultano pubblicati — quelli qui sotto
> sono dell'URP».

**Fermare l'immagine su:** la riga con il pallino vuoto, quella dell'assenza
dichiarata.

---

## C — Il comune non coperto, letto adesso · 1:20–2:05

**Comune:** Camposampiero (PD) · **Domanda:** `quali sono gli orari dell'anagrafe?`

**Voce (1:20–1:45)**

> Camposampiero non è fra i comuni di cui abbiamo i dati. Invece di rifiutare,
> il sistema va a leggere il suo portale mentre il cittadino aspetta. Questi
> orari sono quelli scritti sulla pagina del comune, riportati alla lettera:
> non li abbiamo riscritti, non li abbiamo interpretati.

**Voce (1:45–2:05)**

> E il bollo dice esattamente cosa sono: letti ora, non verificati, non
> conservati. Un dato letto al volo e un dato verificato non devono avere lo
> stesso aspetto.

**Fermare l'immagine su:** il blocco *Orari di apertura*, con il «Giovedì:
chiuso» — è la prova che stiamo riportando, non ricostruendo.

---

## D — Quando nemmeno il portale si lascia leggere · 2:05–2:40

**Comune:** Ciampino (RM) · **Domanda:** `mi dici i numeri dell'ufficio anagrafe?`

**Voce (2:05–2:25)**

> Ciampino la sua pagina URP la pubblica. Ma non espone i propri uffici in una
> forma che una macchina possa leggere, quindi noi non riusciamo a prenderla.
> Fino a ieri qui il sistema si fermava e diceva: cercala a mano sul sito.

**Voce (2:25–2:40)**

> Adesso cerca lui, e marca quello che trova: pagine trovate sul web, non
> lette da noi, da confermare con l'URP prima di fidarsene. Trovata non è
> letta, e resta scritto nella scheda.

**Fermare l'immagine su:** i bolli *Ricerca web · Non verificato* e la riga
«vanno confermate con l'URP prima di fidarsene».

---

## Chiusura · 2:40–3:00

**Voce**

> Ciampino la pagina la pubblica. Siamo noi che non sappiamo leggerla, perché
> non esiste uno standard che ce lo permetta. TreasureIQ misura esattamente
> questo: quanto costa, oggi, arrivare a un dato che è già pubblico.

Ultimo fotogramma: la pagina **Qualità dei dati**, che è il conto di quel costo
comune per comune.

---

## Riserve, se avanza tempo o se un take va male

**Gli omonimi.** `Castro` — esistono Castro (BG) e Castro (LE). Il sistema non
sceglie: chiede. Fra due comuni con lo stesso nome, indovinare è il modo più
veloce di dare a qualcuno le regole di qualcun altro.

**Il comune riconosciuto ma non coperto.** `Roma` — nome risolto, dati non
nostri. Dice cosa sa e cosa non sa, senza spacciare l'uno per l'altro.

---

## Cosa NON promettere, a voce, per nessun motivo

- Che TreasureIQ «sa» se hai diritto a qualcosa. Confronta i requisiti
  pubblicati con quello che dichiari, e mostra il conto — il verdetto non lo
  decide un modello (D-01).
- Che i dati coprano l'Italia. Sono cinque comuni censiti e 7.896 riconosciuti
  per nome: sono due numeri diversi e vanno detti come due numeri diversi.
- Che la ricerca web sia una fonte. È un suggerimento marcato, da confermare.
