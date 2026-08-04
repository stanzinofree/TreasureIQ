# Copione della demo

Ultimo aggiornamento: 4 agosto 2026. Ogni comune e ogni citazione in questo
file sono stati verificati quel giorno contro i portali veri: niente è
d'esempio. I portali però cambiano, quindi **rifai `make scalda-cache` il
giorno della demo** e ricontrolla che i tre comuni protagonisti rispondano
ancora come scritto qui.

---

## L'idea in una riga

> TreasureIQ non insegue i dati dei comuni italiani. Misura quanto costa
> leggerli, comune per comune, e li legge dove costa poco. Dove costa troppo
> non inventa: lo dice, e chiede al comune di pubblicarli.

---

## Prima di cominciare

```bash
docker compose up -d
make scalda-cache COMUNI="Camposampiero 'Arquata Scrivia' 'Torre Annunziata' Trento Milano"
make stato-dati
```

**Perché scaldare la cache.** La prima domanda su un comune mai sondato va a
leggere il portale in diretta: due, sei secondi di attesa davanti al pubblico.
Sondandolo prima, l'esito sta in `data-live/` e la risposta è istantanea.

Non è un trucco, ed è importante saperlo dire se qualcuno lo chiede: **la
cache contiene esattamente la lettura che il sistema avrebbe fatto sul
momento**, dalla stessa fonte, con la stessa citazione. Sposta l'attesa, non
cambia la risposta. Se preferisci mostrarlo davvero a freddo, salta il
comando: funziona lo stesso, solo più lento.

Per rifare tutto da zero: `make scalda-cache COMUNI="…"` con `--rileggi` non
esiste come flag del Makefile — usa
`docker compose exec api python -m treasureiq.sonda_live --rileggi Camposampiero`.

---

## L'arco: tre gradini, non due

Il punto della demo non è "funziona". È che **il sistema sa dire quale dei tre
casi ha davanti**, e non fa mai finta di essere nel caso migliore.

### Gradino 1 — comune coperto: il dato curato

**Chiedi:** «quali sono gli orari dell'ufficio anagrafe di Albano Laziale?»

Risponde dal seed. Fonte datata, nessuna rete toccata. È il caso normale, e in
demo serve solo come metro di paragone: dura dieci secondi.

### Gradino 2 — comune mai visto, portale leggibile: la lettura dal vivo

**Il momento che vende il progetto.** Fai scegliere il comune al pubblico fra
questi, oppure usa Camposampiero che è il più pulito.

**Chiedi:** «orari dell'ufficio anagrafe di Camposampiero»

Risponde citando la pagina del comune, letta in quel momento:

> Lunedì 09:00 - 12:30 | Martedì 09:00 - 12:30 | Mercoledì 09:00 - 12:30 e
> 15:00 - 18:00 | **Giovedì: chiuso** | Venerdì 09:00 - 12:30 | Sabato 09:00 - 12:00

Il «Giovedì: chiuso» è il dettaglio da far notare: non è un orario copiato a
metà, è la settimana intera com'è scritta sulla pagina, chiusure comprese.

**Cosa dire mentre appare:** questo comune non è nei nostri dati. Non l'abbiamo
mai ingerito, non c'è nessuno snapshot. Il sistema ha riconosciuto il comune
fra i 7.896 italiani, è andato sul portale del comune stesso — non su Google —
e ha riportato alla lettera quello che ci ha trovato. La citazione è verbatim
apposta: potete aprire quella pagina e controllarci.

### Gradino 3 — comune mai visto, portale non leggibile: il rifiuto onesto

**Chiedi:** «orari dell'ufficio anagrafe di Trento»

> Trento ha un portale, ma non espone i propri uffici in una forma che si
> possa leggere da qui: per sapere l'orario bisogna aprire il sito e cercarlo
> a mano. È il motivo per cui questo comune non è ancora fra quelli che
> copriamo.

**Cosa dire:** questo è il caso più importante dei tre. Il sistema non
inventa, non ripiega su un altro comune, non mostra link a caso. Dice cosa ha
guardato, cosa non ha trovato, e perché. Un buco dichiarato è un risultato;
un buco riempito con una risposta plausibile è un danno.

---

## I comuni da usare (verificati il 4 agosto 2026)

### Funzionano — gradino 2

| Comune | Ufficio letto | Citazione |
|---|---|---|
| **Camposampiero** (PD) | «Anagrafe, Stato civile, … URP, Notifiche» | «Lunedì 09:00 - 12:30 \| Martedì 09:00 - 12:30 \| Mercoledì 09:00 - 12:30 e 15:00 - 18:00 \| **Giovedì: chiuso** \| Venerdì 09:00 - 12:30 \| Sabato 09:00 - 12:00» |
| **Arquata Scrivia** (AL) | Anagrafe e Stato Civile | «Orari al Pubblico lunedì pomeriggio dalle 15.00 alle 17.30, da martedì a venerdì dalle 9.00 alle 12.00, sabato dalle 9.00 alle 11.30» |
| **Torre Annunziata** (NA) | Anagrafe | «dal lunedì al mercoledì: 7:30-18:00 \| giovedì: 7:30-19:00 \| venerdì: 7:00-18:00 …» |
| **Bitetto** (BA) | — | «GIOVEDI \| IL POMERIGGIO: 15.30 alle 17.30» |

**Usa Camposampiero come protagonista.** Arquata è ottimo come secondo.

Bitetto tienilo come esempio di **cattura parziale**: la pagina spezza
l'orario settimanale in celle e il sistema ne riporta una sola. Se lo mostri,
dillo tu prima che lo noti qualcun altro — è coerente col resto del discorso.

Torre Annunziata unisce gli orari di due sedi in una citazione sola: leggibile,
ma meno pulito. Secondo piano.

Ce ne sono altri 12 nel campione: `data/censimento-t0.json`, cerca gli esiti
con `citazione_orari` non nullo.

### Non funzionano — gradino 3, e vanno mostrati

| Comune | Cosa succede | Perché è interessante |
|---|---|---|
| **Trento** | `solo_html` | Capoluogo di provincia autonoma, portale su misura |
| **Milano** | `solo_html` | Seconda città d'Italia |
| **Roma** | non riconosciuto | IPA la registra come «Roma Capitale», non «Comune di Roma» |

**Questa tabella è metà della demo.** I comuni grandi non funzionano, i piccoli
sì: è l'opposto di quello che si aspetta chiunque, e ha una spiegazione
precisa. I comuni piccoli hanno adottato il modello standard AGID, in molti
casi con i soldi del PNRR, perché non avevano un portale storico da difendere.
Roma e Milano se lo sono costruito su misura, prima, e ognuno è un caso a sé.

Su Roma, se qualcuno la prova: il registro pubblico non la chiama «Comune di
Roma», e noi non abbiamo cablato un'eccezione per farla entrare. Preferiamo un
buco dichiarato a un'eccezione nascosta — è la stessa regola che applichiamo ai
dati dei cittadini.

---

## Il T0: il numero che regge

Da `data/censimento-t0.json`, campione di 401 comuni stratificato per regione,
seme 2026, riproducibile con `make censimento N=400`.

| Misura | Risultato |
|---|---|
| Comuni misurati | 385 su 401 (16 portali irraggiungibili) |
| Ti dicono **quali uffici** hanno | **15,8% ±3,6** |
| Ti dicono **quando l'URP è aperto** | **4,2% ±2,0** |
| — in un **campo tipizzato** | **0** |

**La frase da dire:** su quattrocento comuni italiani, presi a caso in tutte le
regioni, **nemmeno uno** pubblica l'orario del proprio URP in un campo che una
macchina possa leggere. I sedici che ce l'hanno lo tengono dentro una pagina,
in prosa, da estrarre.

### Se qualcuno attacca il numero

Lo faranno, e l'obiezione giusta è una sola: *«il 4% misura solo i comuni che
avete potuto sondare per via strutturata»*. È vera, è scritta nel file sotto
`limite_dichiarato`, e la risposta è:

> Esatto. L'asse B lo tentiamo solo dove l'asse A è riuscito, quindi quel 4,2%
> dice cosa è raggiungibile per via strutturata, non cosa è pubblicato. Il
> numero che non dipende da questa scelta è lo zero: nessuno dei comuni che
> siamo riusciti a leggere ha un campo tipizzato per gli orari.

Ammettere il limite prima che te lo trovino è più forte che difendere il
numero grande.

---

## Comandi utili durante la demo

```bash
make stato-dati    # cosa c'è nei dati curati e cosa è stato letto dal vivo
make test          # 22 test, tutti sull'estrazione della prova
make censimento N=50   # rifà una misura piccola dal vivo, se serve mostrarla
```

`make stato-dati` è utile a fine demo: mostra i comuni che qualcuno ha chiesto
e che non copriamo. È il backlog vero — guidato dalla domanda, non da un elenco
deciso a tavolino.

---

## Come diventa copertura (la domanda «ha futuro?»)

Se te la fanno, il percorso è questo e non è teorico:

```
make stato-dati                          → chi è stato chiesto e non è coperto
make promuovi COMUNE='Camposampiero'     → prepara la voce enti.json, misurata
                                         → tu la controlli e la committi
                                         → l'ingestione parte, il comune è coperto
```

`promuovi` **non scrive niente**. Stampa la pratica e si ferma: promuovere un
comune è una decisione umana, e il modo di accesso che trascrive è quello
misurato, non uno scelto a mano.

Il punto da fare: non serve un connettore per comune. Ce ne sono due, uno per
piattaforma, e aggiungere un comune che gira su una piattaforma nota è una riga
di configurazione. Il censimento dice quali piattaforme ricorrono abbastanza da
meritarne uno nuovo.

---

## Cosa NON promettere

- **Non promettere copertura nazionale.** Copriamo 5 comuni e ne sappiamo
  misurare 7.896. Sono due cose diverse e vanno dette diverse.
- **Non chiamare "verificato" ciò che è letto dal vivo.** È verbatim dalla
  fonte, non è verificato da noi, e l'interfaccia lo dice.
- **Non usare il gradino 2 per le agevolazioni.** Vale solo per le
  informazioni: un dato letto al volo non entra mai in un giudizio di
  eleggibilità (D-01, D-32). Se qualcuno chiede «e per il bonus mensa a
  Camposampiero?», la risposta corretta è che non possiamo verificarlo — e va
  detta come una scelta, non come un limite tecnico.
