# Copione della demo — e lista di collaudo

Aggiornato: 4 agosto 2026. Ogni comune, ogni citazione e ogni esito atteso qui
sotto sono stati verificati quel giorno contro i portali veri. Non c'è niente
di inventato a titolo di esempio.

I portali però cambiano da soli. **Rifai `make scalda-cache` il giorno della
demo** e ricontrolla almeno gli scenari 1, 2 e 5.

Gli scenari sono numerati apposta: quando qualcosa non va, dimmi il numero e
cosa hai visto invece.

---

## Preparazione

```bash
docker compose up -d
make scalda-cache COMUNI="Camposampiero 'Arquata Scrivia' 'Torre Annunziata' Trento Milano Bitetto"
make stato-dati
```

**Perché scaldare la cache.** La prima domanda su un comune mai sondato legge
il portale in diretta: due, sei secondi di attesa davanti al pubblico.
Sondandolo prima, l'esito sta in `data-live/` e la risposta è istantanea.

Se te lo chiedono, la risposta è che **non è un trucco**: la cache contiene
esattamente la lettura che il sistema avrebbe fatto sul momento, dalla stessa
fonte, con la stessa citazione. Sposta l'attesa, non cambia la risposta. Per
mostrarlo davvero a freddo basta saltare il comando.

---

## La riga da cui parte tutto

> TreasureIQ non insegue i dati dei comuni italiani. Misura quanto costa
> leggerli, comune per comune, e li legge dove costa poco. Dove costa troppo
> non inventa: lo dice, e chiede al comune di pubblicarli.

---

# Scenari

## 1 — Comune coperto: il dato curato

**Fai:** scegli **Albano Laziale** dal campo comune · chiedi «*quali sono gli
orari dell'ufficio anagrafe?*»

**Deve succedere:** risponde dal seed, con documento e contatti dell'URP.
Nessuna etichetta «letto ora», e **compare** la striscia dei costi di recupero.

**Guarda:** che non ci sia l'etichetta blu. Questo è il caso normale, serve
solo come metro di paragone. Dura dieci secondi.

---

## 2 — Comune mai visto, portale leggibile: la lettura dal vivo

**Il momento che vende il progetto.** Fai scegliere il comune al pubblico fra
quelli della tabella più sotto, o usa Camposampiero che è il più pulito.

**Fai:** scegli **Camposampiero** · chiedi «*quali sono gli orari dell'ufficio
anagrafe?*»

**Deve succedere:** etichetta blu **LETTO ORA** in cima, poi la citazione:

> Lunedì 09:00 - 12:30 | Martedì 09:00 - 12:30 | Mercoledì 09:00 - 12:30 e
> 15:00 - 18:00 | **Giovedì: chiuso** | Venerdì 09:00 - 12:30 | Sabato 09:00 - 12:00

**Cosa dire mentre appare:** questo comune non è nei nostri dati, non l'abbiamo
mai ingerito, non esiste nessuno snapshot. Il sistema l'ha riconosciuto fra i
7.896 italiani, è andato sul portale **del comune stesso** — non su Google — e
ha riportato alla lettera quello che ci ha trovato.

**Il dettaglio da far notare:** «Giovedì: chiuso». Non è un orario copiato a
metà: è la settimana intera com'è scritta, chiusure comprese.

**Guarda che NON ci siano:** la riga «nessun risultato pubblicato dal comune»
e la striscia dei costi. Su una risposta live parlerebbero dei nostri dati,
cioè di un altro comune.

---

## 3 — Comune mai visto, portale non leggibile: il rifiuto onesto

**Fai:** scegli **Trento** · chiedi «*orari dell'ufficio anagrafe*»

**Deve succedere:**

> Trento ha un portale, ma non espone i propri uffici in una forma che si
> possa leggere da qui: per sapere l'orario bisogna aprire il sito e cercarlo
> a mano. È il motivo per cui questo comune non è ancora fra quelli che
> copriamo.

**Cosa dire:** è il caso più importante dei tre. Non inventa, non ripiega su
un altro comune, non mostra link a caso. Dice cosa ha guardato, cosa non ha
trovato e perché. Un buco dichiarato è un risultato; un buco riempito con una
risposta plausibile è un danno.

---

## 4 — Due comuni con lo stesso nome

**Fai:** scrivi **Castro** nel campo comune, senza sceglierne uno

**Deve succedere:** la tendina mostra **Castro (BG · Lombardia)** e **Castro
(LE · Puglia)** come due voci distinte.

**Cosa dire:** prima si tirava a indovinare, e metà di quei cittadini avrebbe
ricevuto le informazioni dell'altra metà. Ora si sceglie, e quello che il
sistema riceve è un codice ISTAT: niente omonimi, niente grafie diverse, e
nessun modo per un modello di inventarlo.

---

## 5 — Roma: riconosciuta, ma senza portale

**Fai:** scrivi **Roma** e scegli la voce «Roma»

**Deve succedere:** nella tendina la voce porta l'etichetta `portale
sconosciuto`. Alla domanda risponde:

> Roma esiste e lo riconosco (RM, codice 058091), ma nell'indice delle
> pubbliche amministrazioni non risulta l'indirizzo del suo portale, quindi
> non ho un posto dove andare a leggere. **È un buco nostro, non suo.**

**Perché succede:** IPA registra il comune come «Roma Capitale», non «Comune
di Roma», e il filtro che impedisce a una Comunità Montana di regalare il
proprio sito al comune che la ospita esclude anche lei. È uno dei 29 comuni
senza sito su 7.896.

**Cosa dire se te lo contestano:** preferiamo un buco dichiarato a
un'eccezione cablata. È la stessa regola che applichiamo ai dati dei cittadini,
e vale anche quando fa fare brutta figura a noi.

---

## 6 — Un nome che non è un comune

**Fai:** scrivi **Vattelapesca** (o un refuso qualunque)

**Deve succedere:**

> Nessun comune italiano si chiama così. L'elenco è quello ufficiale ISTAT,
> quindi non è un comune che ci manca: controlla il nome, oppure potrebbe
> essere una frazione.

**Il punto:** zero risultati **non** vuol dire «comune non coperto». L'elenco
è completo per costruzione, quindi può voler dire una cosa sola.

---

## 7 — Le agevolazioni restano fuori dal gradino 2

**Fai:** scegli **Camposampiero** · chiedi «*c'è un aiuto per la mensa
scolastica?*»

**Deve succedere:** zero risultati, e questa risposta:

> Di Camposampiero non abbiamo ancora letto i dati, quindi non posso dirti
> cosa ti spetta: le soglie e i requisiti li stabilisce il tuo comune, e
> quelli di un altro comune non valgono per te. Posso però dirti cosa pubblica
> il tuo, se mi chiedi di un ufficio o di un documento.

**Cosa dire:** il gradino 2 vale solo per le informazioni. Un dato letto al
volo non entra mai in un giudizio su cosa ti spetta — sarebbe D-01 aggirato
per comodità. È una scelta, non un limite tecnico.

**Perché questo scenario esiste.** Fino a poche ore fa questa domanda
restituiva **tre agevolazioni di Albano** a chi aveva appena dichiarato di
vivere a Camposampiero: il rail delle agevolazioni caricava sempre i record del
comune coperto. Non era una risposta imprecisa, erano le regole di qualcun
altro — e il sistema sapeva già di non essere lì. Se lo vedi tornare, è la
regressione più grave possibile in questa demo.

---

# I comuni da usare

## Funzionano — gradino 2

| Comune | Ufficio letto | Citazione |
|---|---|---|
| **Camposampiero** (PD) | Anagrafe, Stato civile, Elettorale… | settimana intera, «Giovedì: chiuso» compreso |
| **Arquata Scrivia** (AL) | Anagrafe, Stato Civile ed Elettorale | «lunedì pomeriggio 15.00–17.30, da martedì a venerdì 9.00–12.00, sabato 9.00–11.30» |
| **Villanova di Camposampiero** (PD) | Anagrafe, Stato civile, Elettorale | doppia fascia per giorno (CIE / altre pratiche), chiusa con `[…]` |
| **Torre Annunziata** (NA) | Ufficio URP Portierato | orari lunghi, due sedi |
| **Bitetto** (BA) | U.R.P. | solo il giovedì pomeriggio |

**Protagonista: Camposampiero.** Secondo: Arquata Scrivia.

**Villanova** è ottimo se vuoi mostrare il `[…]`: la settimana non ci sta nella
citazione e il sistema **dichiara** di averla accorciata invece di lasciar
credere che l'orario finisca lì.

## Non funzionano — vanno mostrati lo stesso

| Comune | Cosa succede | Perché è interessante |
|---|---|---|
| **Trento** | `solo_html` | Capoluogo di provincia autonoma, portale su misura |
| **Milano** | `solo_html` | Seconda città d'Italia |
| **Roma** | riconosciuta, senza portale | vedi scenario 5 |

**Questa tabella è metà della demo.** I comuni grandi non funzionano, i piccoli
sì: è l'opposto di quello che si aspettano tutti, e ha una spiegazione precisa.
I comuni piccoli hanno adottato il modello standard AGID, in molti casi con i
soldi del PNRR, perché non avevano un portale storico da difendere. Roma e
Milano se lo sono costruito su misura, prima, e ognuno è un caso a sé.

---

# Il T0

Da `data/censimento-t0.json`. Campione di 401 comuni stratificato per regione,
seme 2026, rifacibile identico con `make censimento N=400`.

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

## Se attaccano il numero

L'obiezione giusta è una sola: *«il 4% misura solo i comuni che avete potuto
sondare per via strutturata»*. È vera, è scritta nel file sotto
`limite_dichiarato`, e si risponde così:

> Esatto. L'asse B lo tentiamo solo dove l'asse A è riuscito, quindi quel 4,2%
> dice cosa è raggiungibile per via strutturata, non cosa è pubblicato. Il
> numero che non dipende da questa scelta è lo zero: nessuno dei comuni che
> siamo riusciti a leggere ha un campo tipizzato per gli orari.

Ammettere il limite prima che te lo trovino è più forte che difendere il
numero grande.

---

# Limiti che conosco già

Non serve segnalarmeli — questi li so. Segnalami tutto il resto.

- **La tendina copre il campo domanda** mentre è aperta. È il comportamento
  normale di un menu a discesa, ma se clicchi la domanda con la lista aperta
  colpisci una riga.
- **Il campo «Comune» scorre via** insieme ai messaggi: dopo qualche turno non
  si vede più quale comune è attivo.
- **Torre Annunziata** unisce in una citazione gli orari di due sedi diverse.
  Leggibile, ma confuso: tienilo in secondo piano.
- **Bitetto** cattura solo il giovedì pomeriggio, perché la pagina spezza la
  settimana in celle separate. Se lo mostri, dillo tu prima che lo noti
  qualcun altro.
- **Nessun test automatico** sul frontend. I 44 test coprono l'estrazione
  della prova e il riconoscimento del comune, tutti lato API.

---

# Come diventa copertura (la domanda «ha futuro?»)

```
make stato-dati                          → chi è stato chiesto e non è coperto
make promuovi COMUNE='Camposampiero'     → prepara la voce enti.json, misurata
                                         → la controlli e la committi
                                         → parte l'ingestione, il comune è coperto
```

`promuovi` **non scrive niente**: stampa la pratica e si ferma. Promuovere un
comune è una decisione umana, e il modo di accesso che trascrive è quello
misurato, non uno scelto a mano.

Il punto da fare: non serve un connettore per comune. Ce ne sono due, uno per
piattaforma, e aggiungere un comune che gira su una piattaforma nota è una riga
di configurazione. Il censimento dice quali piattaforme ricorrono abbastanza da
meritarne uno nuovo.

---

# Cosa NON promettere

- **Non promettere copertura nazionale.** Copriamo 5 comuni e ne sappiamo
  misurare 7.896. Sono due cose diverse e vanno dette diverse.
- **Non chiamare «verificato» ciò che è letto dal vivo.** È verbatim dalla
  fonte, non è verificato da noi, e l'etichetta lo dice.
- **Non usare il gradino 2 per le agevolazioni** (scenario 7).

---

# Quando testi, segnami

Per ogni scenario che non va: **il numero**, cosa hai scritto, cosa ti aspettavi
e cosa hai visto. Se è un comune diverso da quelli in tabella, dimmi anche
quale — così controllo se è il comune o è il codice.
