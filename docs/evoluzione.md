# Cosa costruire dopo l'MVP

*Dimensionato sui numeri misurati il 12 agosto 2026, non su un'architettura di
riferimento. Ogni scelta scartata porta la condizione che la rimetterebbe in
gioco: così la decisione si può rivedere con un dato invece che con un'opinione.*

---

## I numeri da cui parte il dimensionamento

| | |
|---|---|
| Richieste per un censimento nazionale | 34.229, ~4 per comune |
| Durata | ~90 minuti, 8 richieste in parallelo |
| Righe prodotte per rilevazione | 7.896 |
| Righe dopo un anno di rilevazioni quotidiane | ~2,9 milioni |
| Oggetti seminati nel catalogo (uffici, servizi, rami AT), letti da disco invece che live | 57.603 |
| PDF stimati, alla quota misurata del 10% | ~5.700, ~3 GB |

Sono numeri piccoli. Il rischio del sistema **non è il volume**: è la cortesia
verso settemila server pubblici, e la tracciabilità di come abbiamo misurato.

---

## Le tre cose da costruire

### 1 · Limite di frequenza per host

Oggi la concorrenza è **globale**: otto richieste in volo, di norma verso otto
server diversi. Regge finché chiediamo quattro cose a comune.

Smette di reggere appena leggiamo le singole schede: Anzola dell'Emilia ne
pubblica 138, e senza un limite per host quel comune si prenderebbe 138
richieste in raffica.

È l'unico punto in cui il sistema, oggi, **può fare un danno vero a qualcuno**.
Per questo è il primo.

*Forma:* un semaforo per host nel client HTTP, con distanza minima fra due
richieste allo stesso portale. Poche decine di righe.

### 2 · Registro delle esecuzioni

Quale rilevazione è girata, quando, con quale versione del codice, su quali
comuni, con quale definizione di aderenza.

È il problema che ci ha morso davvero: in una sola giornata la definizione di
aderenza è cambiata quattro volte — denominatori, base di misura, campi letti —
e per un po' le pagine hanno mostrato una **stratigrafia** invece di un dataset.
Ogni numero era difendibile; messi insieme non erano una misura.

`classificato_da` è nato come surrogato di questo registro. Va promosso a
struttura: una tabella di corse, e ogni riga di misura che punta alla sua.

*Forma:* tabella `rilevazione` con id, avvio, fine, versione, ambito, e una
chiave esterna dalle righe di misura.

### 3 · Uno scheduler piccolo

Cron più una tabella di lavori con lock. Il lock non è teorico: due censimenti
contemporanei sullo stesso SQLite sono un problema reale.

La ripresa la sappiamo già fare — `--riprendi` salta chi ha già risposto oggi,
`--solo-ignoti` rilegge solo i non riconosciuti, `--solo-misurabili` rimisura chi
sappiamo leggere, e il salvataggio a blocchi da 200 fa sì che un'interruzione
costi al massimo l'ultimo blocco.

*Forma:* ~200 righe. Non è un sistema, è la disciplina che manca.

**Cosa c'è oggi, e cosa manca ancora — la distinzione va tenuta netta.** Una
scansione comunale è "stantia" oltre 6 giorni (`GIORNI_STANTIA`, D-S6 in
`scansioni.py`). Il refresh oggi è **reattivo**: parte in background quando una
ricerca tocca un comune con una scansione vecchia (refresh-on-search), più
un'utilità a riga di comando (`--sonda`/`--invecchia`) manuale, usata per
scaldare la demo. È deciso esplicitamente (D-S10) che **nessuno scheduler gira
nel sistema attuale** — quelle utility sono comandi da lanciare, non un job che
si sveglia da solo.

Lo scheduler descritto qui sopra è il pezzo **mancante**: un processo
**proattivo** che rinfresca le scansioni scadute per conto suo, senza
aspettare che un cittadino faccia la domanda che le fa scattare. È lavoro
futuro, non un refactor del refresh-on-search — le due cose convivono anche a
scheduler acceso: il refresh-on-search resta lo short-circuit per il comune
che qualcuno sta chiedendo *adesso*, lo scheduler tiene fresco il resto.

---

## Le tre cose scartate, e cosa le rimetterebbe in gioco

### Coda di messaggi (Kafka o simili)

**Scartata.** Serve a flussi ad alta frequenza con più consumatori e replay. Qui
c'è un lavoro batch su una lista finita, una volta al giorno o alla settimana.
Porterebbe topic da gestire, consumer lag da sorvegliare e un cluster da tenere
in piedi per 34.000 richieste giornaliere. Una tabella di lavori fa lo stesso al
centesimo del costo operativo.

> **Condizione che la rimette in gioco:** estrazione dai PDF su scala. È l'unico
> carico genuinamente CPU-bound del progetto — migliaia di documenti, molto
> peggio con l'OCR — e lì una coda con worker in un linguaggio compilato ha
> senso. **Soglia:** quando la quota di requisiti che vivono in un allegato
> illeggibile supera il **10% dei servizi letti**. È già calcolabile con i dati
> che registriamo.

### Object storage per i PDF

**Scartato.** Conservando il **testo estratto** invece dei binari, il nazionale
sta sotto il gigabyte. Il PDF originale resta citabile per URL e riscaricabile.
Archiviare i binari ci renderebbe un mirror di documenti pubblici altrui — con
domande su diritti e conservazione — senza migliorare di niente la risposta al
cittadino.

> **Condizione:** se una fonte comincia a rimuovere documenti che avevamo citato,
> e la citazione verbatim non è più verificabile. Allora conservare l'originale
> smette di essere accumulo e diventa **prova**. **Soglia:** oltre l'1% di
> citazioni che non si ritrovano più alla fonte.

### Database server (PostgreSQL)

**Scartato per ora.** SQLite in modalità WAL regge letture concorrenti e questi
volumi con margine. E la migrazione costa poco *proprio perché* lo store sta
dietro il modulo `storico`: finché nessuno scrive SQL fuori da lì, cambiare
motore è un pomeriggio.

> **Condizione:** scritture concorrenti da più processi — cioè quando lo
> scheduler avrà più di un lavoratore che scrive — oppure query analitiche su
> più anni che diventano lente. **Soglia:** oltre 10 milioni di righe, o un
> secondo di latenza sulla pagina analytics.

---

## Il lavoro sui connettori

È l'unica voce che scala con **il numero di piattaforme**, non di comuni. Le
stime e la copertura per fornitore stanno in [connettori.md](connettori.md).

Il criterio con cui allocare l'effort è esplicito, e non è la curiosità:

```
comuni del fornitore  ×  aderenza mancante
```

pesato sui cittadini, quando avremo la popolazione ISTAT — oggi è l'unico campo
progettato e mai riempito.

---

## Cosa non è architettura ed è più urgente di tutto

Tre buchi noti, in ordine di quanto pesano sul cittadino:

**La popolazione ISTAT.** Senza, ogni frase dice «il X% dei comuni» invece di
«il X% dei cittadini». Il campo esiste già in tabella, si riempie con un `UPDATE`
sul codice ISTAT, e non tocca la rete.

**844 comuni non riconosciuti** (10,7%). Restano in gruppi da 40–70, non più
famiglie da mille. Ogni firma nuova vale ora decine di comuni, non centinaia.

**155 comuni MyPortal leggibili in JSON e non ancora letti.** Sono il caso
migliore che abbiamo — campi tipizzati, API pulita, codice IPA ricavabile
dall'anagrafe — e sono ancora fermi al conteggio.
