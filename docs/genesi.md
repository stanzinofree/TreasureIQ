# TIQ — Genesi e motivazioni

*Perché questo progetto esiste, cosa ha misurato l'MVP e dove vuole arrivare.
Scritto il 12 agosto 2026.*

---

## Genesi

Ogni tanto capita di dover cercare gli orari di un ufficio del comune, di
capire come richiedere un certificato e a chi rivolgersi, o di sapere se ci
sono bandi a cui si ha diritto. Oggi è sicuramente più facile rispetto a
qualche anno fa, ma è ancora a un livello insoddisfacente vista l'era
tecnologica che affrontiamo e le potenzialità di interconnessione della rete
pubblica che abbiamo.

Si viene rediretti da un portale all'altro (quando va bene), oppure si finisce
su un 404 o su un sito che non risponde più perché il webserver è in errore. È
in questo scenario che ho cominciato a coltivare l'idea di fare scraping con un
linguaggio comune per facilitare le richieste: quello che sul comune A sta
sotto «Servizi» e sul comune B sotto «Uffici», sotto TIQ è in una chat.

TIQ non è la soluzione: è un apriscatole, un motore di apertura verso le realtà
locali affinché si adotti tutti lo stesso schema di esposizione dei dati, a
favore della standardizzazione e della consultazione da parte del cittadino.

Il problema che TIQ vuole risolvere è visto con un occhio da reverse
engineering. Ogni realtà adotta una piattaforma con un proprio metodo di
esposizione. A T0, TIQ scrive quanti più connettori possibile per leggere e
uniformare queste informazioni; col tempo, e con un utilizzo sempre più
diffuso, potrebbe aiutare a caldeggiare uno standard di esposizione — come sta
cercando di fare AgID — ma orientato a **centralizzare la consultazione**. Il
problema non sono i fornitori che costruiscono le loro piattaforme per offrire i
contenuti: il problema è che non c'è una spinta comune a far lavorare quei
produttori su uno schema condiviso di esposizione dei dati, per creare un vero
standard.

## MVP

Questa prima versione è andata al di là delle mie aspettative. Ho costruito un
primo livello di *sweeping* che indicizza tutti i comuni partendo dalla lista
ufficiale fornita dallo Stato, cercando di uniformare le informazioni raccolte
per dare a TIQ una base di comprensione della geografia e dell'esposizione dei
servizi. Da qui sono nate due serie di connettori:

- **Connettore dei siti Base** — le piattaforme che ospitano il sito del comune
  e ne forniscono l'infrastruttura.
- **Connettore dell'Amministrazione Trasparente (AT)** — la sezione della
  trasparenza, inclusa la parte dei bandi.

Un comune, di regola, ha **due** piattaforme distinte: quella del portale
principale e quella della trasparenza, spesso di fornitori diversi. TIQ le
riconosce separatamente.

Non ci siamo spinti fino all'analisi dei PDF (con l'eccezione del mio comune,
Albano Laziale, come esperimento): ci siamo fermati all'**interrogazione web**.
Al momento interessa valutare le potenzialità e dare modo di vedere con mano
l'utilità di poter cercare da una chat tutte le informazioni, confrontarle con i
filtri che imposto io e capire subito se ho o no i requisiti di adesione. E qui
si torna allo standard di pubblicazione: se i requisiti fossero sempre esposti
in campi blindati, la query sarebbe deterministica e non ci sarebbe margine di
interpretazione.

## Cosa ha misurato, in numeri

Tutti i numeri sono misurati, mai stimati; dove non abbiamo potuto guardare, la
casella resta vuota. Il dettaglio, aggiornato a ogni censimento, sta nella
pagina **Analytics** dell'applicazione.

- **7.896 comuni censiti** — l'intera lista ufficiale, non un campione.
- **57.770 servizi** contati nei cataloghi esposti.
- **Due piattaforme per comune** riconosciute separatamente: portale base e
  amministrazione trasparente.
- **94% dei comuni** con campo dei requisiti previsto lo lascia **vuoto**: la
  domanda «chi ne ha diritto?» ha un posto dove stare, e quel posto è deserto.
  Non è un'accusa generalizzata — dove la piattaforma non prevede nemmeno il
  campo lo diciamo a parte, perché quei comuni non potrebbero pubblicare i
  requisiti neanche volendo.

Su questi comuni «letti da un connettore» TIQ sa già estrarre uffici, servizi e
amministrazione trasparente. Come esperimento di livello successivo, per la
famiglia di portali più diffusa nella trasparenza abbiamo dimostrato la **query
live ai bandi di gara** — titolo, CIG, link alla scheda — fermandoci prima
dell'analisi dei PDF: la prova che la catena regge, non ancora il servizio.

## Dove vuole arrivare

Il fine non è che TIQ legga per sempre l'illeggibile. È che leggerlo diventi
**inutile**, perché i dati sono esposti in modo uniforme e verificabile alla
fonte. Ogni connettore che scriviamo è, allo stesso tempo, la misura di quanto
manca a quello standard: la lista dei fornitori ancora «grigi» nel censimento è
esattamente la lista del lavoro che resta.

TIQ è un apriscatole. Serve finché la scatola è chiusa.
L'obiettivo di TIQ è che quello che oggi vogliamo fare noi come privati e come iniziativa di un singolo venga perseguita dallo stato e diventi una piattaforma centralizzata o comunque venga caldeggiata come strada di riferimento per le trasparenze dei comuni.
