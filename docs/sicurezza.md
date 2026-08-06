# Sicurezza e limiti d'uso

*Scritto sul codice del 5 agosto 2026. Ogni voce dice cosa c'è **oggi**: le
lacune sono elencate come lacune, non nascoste fra le mitigazioni.*

TreasureIQ ha tre superfici di rischio, e sono molto diverse fra loro:

1. cosa può fare **qualcuno contro di noi** — abuso dell'API;
2. cosa possiamo fare **noi contro terzi** — settemila portali pubblici che non
   ci hanno chiesto niente;
3. cosa possiamo fare **contro un cittadino** — dati sensibili e risposte
   sbagliate su diritti veri.

La terza è la più seria, ed è quella di cui si parla di meno.

---

## 1 · Abuso dell'API

### Cosa c'è oggi

**CORS ristretto per configurazione.** Le origini ammesse arrivano da variabile
d'ambiente; in sviluppo valgono solo `localhost:3000` e `127.0.0.1:3000`.

**Sessione in cookie firmato**, non in database. Il profilo del cittadino vive in
un cookie `HttpOnly`, `SameSite=Lax`, con firma `URLSafeSerializer` e scadenza a
8 ore. Ne parliamo di nuovo al punto 3, perché è anche una scelta di privacy.

**Nessun endpoint di scrittura pubblico.** Le rotte che modificano dati —
ingestione, censimento, riclassificazione — sono comandi da riga, non rotte HTTP.
La superficie esposta è in sola lettura, tranne l'apertura di sessione.

### Le lacune, dichiarate

**Nessun limite di frequenza.** È la lacuna più costosa, e non per il carico:
`POST /api/chat` invoca un modello, quindi ogni richiesta ha un **costo in
denaro**. Chiunque conosca l'URL può trasformare quel costo in un problema.

> *Da fare prima di qualunque esposizione pubblica:* limite per sessione e per
> IP sulle rotte che invocano il modello (`/api/chat`, `/api/approfondimento`),
> con soglia bassa — l'uso legittimo è conversazionale, poche richieste al
> minuto. Le rotte di sola lettura sul censimento possono avere soglie più
> larghe: servono dati già calcolati.

**Segreto di firma con valore di default.** `TREASUREIQ_SECRET` ha un default
esplicito e non segreto, dichiarato tale in un commento. Va bene per la demo;
in produzione un segreto noto significa **sessioni falsificabili**, cioè un
profilo scelto dall'attaccante.

> *Da fare:* rifiutare l'avvio se `TREASUREIQ_SECRET` è rimasto al default e
> l'ambiente non è di sviluppo. Un default comodo che non fallisce rumorosamente
> è un default che finisce in produzione.

**Cookie senza flag `Secure`.** Corretto su `http://localhost`; sbagliato appena
c'è un dominio vero.

---

## 2 · Cortesia verso i portali comunali

Interroghiamo settemila amministrazioni che non ci hanno chiesto niente. La
misura di quanto siamo invadenti è pubblica e va tenuta bassa.

### Cosa c'è oggi

**User-Agent che si dichiara**, con l'URL del repository: chi legge i propri log
può capire chi siamo e scriverci.

**Le richieste sono contate e pubblicate.** `EsitoCensimento.richieste` finisce
nel risultato: chiunque rifaccia la misura sa quanto è costata al portale
dall'altra parte. Un censimento nazionale sono **34.229 richieste su 7.896
host** — meno di quattro a testa.

**Ripresa invece di ripetizione.** `--riprendi` salta chi ha già risposto oggi,
`--solo-ignoti` rilegge solo i non riconosciuti, e il salvataggio a blocchi da
200 fa sì che un guasto non costringa a ribussare a tutti. È una difesa loro
prima che nostra.

**Nessuna elusione.** Non aggiriamo blocchi, non ruotiamo indirizzi, non
imitiamo browser. Un portale che ci rifiuta resta registrato come non misurato.

### Le lacune, dichiarate

**`robots.txt` non viene letto.** Le richieste sono poche e mirate a pagine
pubbliche, ma è una regola che una PA può legittimamente porre e che oggi non
guardiamo.

> *Da fare:* leggere e rispettare `robots.txt` per l'acquisizione, registrando
> l'esito — un comune che ci esclude è un dato del censimento, non un ostacolo
> da aggirare.

**Concorrenza globale, non per host.** Oggi otto richieste in volo verso otto
server diversi: innocuo. Diventa dannoso appena leggeremo le singole schede, dove
un comune con 138 servizi le prenderebbe tutte in raffica.

> *Da fare:* limite per host prima di qualunque lettura per scheda. È il primo
> punto di [evoluzione.md](evoluzione.md).

---

## 3 · Il cittadino

### I dati che tocchiamo sono sensibili

ISEE, disabilità, figli minori. La disabilità è **dato relativo alla salute**:
categoria particolare ai sensi dell'art. 9 GDPR, non un campo come gli altri.

### La scelta che protegge di più

**Non esiste un archivio di profili.** Il profilo vive nel cookie firmato del
cittadino, non in una tabella: non c'è un database di ISEE italiani da violare,
perché non l'abbiamo mai costruito.

È una proprietà architetturale, non una policy — e va difesa come tale: la prima
richiesta di «salviamo i profili per migliorare il servizio» la fa sparire.

### Le regole che valgono sulle risposte

**Un requisito compare solo se è scritto in un documento pubblicato**, citato
verbatim. Se la citazione non si ritrova nella fonte, il requisito cade.

**Il modello non decide.** Capisce la domanda e verbalizza un verdetto già
preso; le soglie le confronta codice deterministico, e le cifre arrivano dai
campi, non dal testo generato. Il motivo è documentato e misurato: il
verbalizzatore corrompe le cifre in modo riproducibile, quindi serve una guardia
sui numeri, non un prompt migliore.

**Dove la fonte tace, la risposta dice che tace.** Un'assenza taciuta è
indistinguibile da una ricerca che nessuno ha fatto.

### Iniezione di istruzioni via contenuti di terzi

La sonda live e la ricerca web portano nel sistema **testo scritto da altri**.
Una pagina comunale compromessa potrebbe contenere istruzioni rivolte al
modello.

L'architettura limita il danno per costruzione: il modello riceve testo solo in
due punti — classificazione dell'intento verso uno **schema chiuso**, e
verbalizzazione di un verdetto **già deciso**. Non ha strumenti da invocare, non
decide esiti, non produce le cifre.

Il danno residuo possibile è **la forma** di una risposta, non il suo contenuto
normativo. Va detto perché è reale, non perché sia catastrofico.

> *Da fare:* trattare esplicitamente i contenuti di terzi come dati e non come
> istruzioni anche nei prompt di verbalizzazione, e registrare la provenienza di
> ogni frammento che entra nel contesto.

---

## 4 · Pubblicare i nomi dei fornitori

Il censimento mette il nome di aziende reali accanto a un punteggio. È
un'esposizione reputazionale, e va trattata con la stessa serietà di un dato
personale.

Le regole che ci siamo dati, e che il codice fa rispettare:

**Ogni classificazione porta la prova.** `piattaforma_prova` conserva verbatim la
stringa che l'ha decisa: un enum senza prova è un'opinione con una faccia seria.

**Nessun nome dedotto.** `HGATE` e `PageObject` prendono il nome dall'header e
dalla rotta osservati, non dall'azienda che sospettiamo ci stia dietro. Mettere
in tabella il nome di un'impresa per inferenza è un'accusa, non una
classificazione.

**Colpa assegnata correttamente.** `assente` è una scelta del fornitore, `vuoto`
una del comune. Sommarli darebbe la colpa a chi non ce l'ha, e la distinzione è
scritta accanto al numero, non in una nota a piè di pagina.

**Base di misura sempre visibile.** Aderenze calcolate su denominatori diversi
non finiscono nella stessa classifica: a denominatore unico il fornitore più
conforme d'Italia risultava ultimo.

---

## Elenco delle cose da fare, in ordine

| | Cosa | Perché prima |
|---|---|---|
| 1 | Limite di frequenza per host in acquisizione | è l'unico punto in cui possiamo danneggiare terzi |
| 2 | Limite di frequenza sulle rotte che invocano il modello | costo in denaro esposto a chiunque |
| 3 | Avvio rifiutato se il segreto è al default | sessioni falsificabili in produzione |
| 4 | Cookie `Secure` fuori da localhost | banale, e dimenticabile |
| 5 | `robots.txt` rispettato e registrato | è una regola che possono porre |
| 6 | Provenienza dei frammenti nel contesto del modello | rende ispezionabile l'iniezione |

Le prime quattro sono giornate, non settimane. Nessuna richiede l'architettura
di [evoluzione.md](evoluzione.md).
