# Connettori: copertura, effort, priorità

*Numeri del censimento del 5 agosto 2026, su 7.896 comuni italiani.*

---

## Tre livelli di lettura, non due

Un comune non è «coperto o no». Le cose che sappiamo fare sono tre, e valgono
diversamente per chi fa la domanda:

| Livello | Cosa sappiamo | Cosa ne ricava il cittadino |
|---|---|---|
| **firma** | riconosciamo la piattaforma | niente direttamente — ma sappiamo contarla, e sappiamo a chi chiedere conto |
| **catalogo** | quanti servizi pubblica, e quanto è fresco l'ultimo | sappiamo dirgli se il suo comune pubblica poco |
| **modello** | leggiamo le schede: a chi è rivolto, cosa serve, entro quando | una risposta vera alla sua domanda |

Solo il terzo livello serve la chat. Gli altri due servono la misura — che è
l'altra metà del progetto.

---

## Cosa si legge diretto via REST, cosa resta scrape

Per un comune a modello AgID il portale espone, via REST, più degli uffici già
sondati: il catalogo **servizi** — Custom Post Type `servizi` — e la sua
tassonomia **`categorie_servizio`**, le 15 categorie standard del modello.
Saperlo in anticipo serve a tre cose a costo zero-runtime: instradare diretto
invece che verso la ricerca web quando un cittadino chiede «come faccio X»,
proporre le categorie come chip a cascata, e usare la lista servizi come coda
di ingestion di domani — ogni scheda porta la sua modulistica.

Il confine fra REST e scrape è misurato comune per comune, non assunto:

| Superficie | Via | Condizione |
|---|---|---|
| `servizi` | REST | CPT `servizi`, sempre presente sui comuni a modello AgID sondati |
| `amministrazione trasparente` (bandi/agevolazioni) | REST **quando il tema lo espone** | il CPT `amm-trasparente` compare in `/wp-json/wp/v2/types`; su Figline c'è, una nota precedente che lo dava scrape-only era sbagliata |
| `contatti URP` | scrape | mai visto come CPT REST sui comuni sondati finora, nonostante candidati come `punti_di_contatto` esistano nel vocabolario del tema |

L'aderenza AgID di un comune (vedi [architettura.md](architettura.md)) si
calcola su una checklist **fissa di 4 superfici** — servizi, uffici,
trasparenza, contatti — lette dagli stessi campi già sondati dalla mappa del
connettore: nessuna rilettura del portale, nessun input digitato a mano. La
via scrape esiste come ripiego ma non incrementa mai il numero di superfici
"esposte": è una via di lettura, non una copertura.

---

## Stato per piattaforma

| Piattaforma | Comuni | Quota | Livello | Servizi letti | Regioni |
|---|---|---|---|---|---|
| **PeopleWeb** (Siscom) | 1.124 | 14,2% | modello | 31.039 | 18 |
| **Municipium** (Maggioli) | 1.009 | 12,8% | firma | — | 20 |
| **HGATE** | 957 | 12,1% | firma | — | 15 |
| *non riconosciuta* | 800 | 10,1% | — | — | 19 |
| WordPress generico | 724 | 9,2% | firma | — | 19 |
| **WordPress Design Comuni** | 715 | 9,1% | modello | 19.302 | 18 |
| **ComWeb** (ePublic) | 502 | 6,4% | modello | — | 9 |
| **AgendaSmart** | 401 | 5,1% | firma | — | 17 |
| **OpenPA** | 364 | 4,6% | firma | — | 16 |
| *non misurata* | 291 | 3,7% | — | — | 20 |
| Magnolia CMS | 171 | 2,2% | firma | — | 12 |
| **Regione FVG** | 168 | 2,1% | firma | — | 1 |
| Drupal | 154 | 2,0% | firma | — | 12 |
| **Regione Veneto** | 85 | 1,1% | modello | 3.151 | 1 |
| **Rete Civica Lepida** | 70 | 0,9% | modello | 4.111 | 1 |

**Leggiamo le schede su 2.496 comuni** — il 31,6% d'Italia — per **57.603
servizi contati**.

---

## Dove conviene mettere l'effort

Il criterio non è la curiosità né la simpatia per una tecnologia:

```
comuni del fornitore  ×  quanto sale il livello di lettura
```

### Prima fascia — mille comuni a colpo

**Municipium (1.009 comuni, 20 regioni).** Il secondo fornitore d'Italia, oggi
solo riconosciuto. È anche il più *nazionale* di tutti: presente in tutte e venti
le regioni. Serve capire come espone i servizi.
*Stima: 3–5 giornate*, se la struttura è simile agli altri.

**HGATE (957 comuni, 15 regioni).** Rotte già mappate e verificate su comuni di
province diverse — `EGSCHTST.HBL` per i servizi, `EGSCHTST24.HBL` per gli uffici,
`EGSMISTMSIT.HBL` per la mappa del sito. Il codice ente `en=` si ricava dalla
home, che scarichiamo già: **scoperta a costo zero**.
Manca solo la rotta della scheda singola.
*Stima: 2–3 giornate.*

### Seconda fascia — già quasi fatto

**MyPortal: Veneto e Lepida (155 comuni).** Già a livello modello, e sono il
**caso migliore del censimento**: API JSON, campi tipizzati, codice IPA ricavabile
dall'anagrafe nazionale. Manca solo far girare la misura su tutti invece che sui
comuni di prova.
*Stima: mezza giornata.* È il miglior rapporto fra lavoro e risultato di tutta
la tabella.

**AgendaSmart (401 comuni, 17 regioni).** Rotta `/agenda-smart` verificata su
otto comuni di cinque regioni. Fornitore ignoto, piattaforma Laravel.
*Stima: 2–3 giornate.*

**OpenPA (364 comuni).** Nome noto, rotte da mappare.
*Stima: 2–3 giornate.*

### Terza fascia — costa più di quanto rende

**WordPress generico (724 comuni).** Hanno l'API REST ma non il vocabolario dei
servizi: ogni installazione organizza i contenuti a modo suo. Non è un
connettore, sono settecento connettori.

**Regione FVG (168 comuni).** Applicazione Angular senza contenuto nell'HTML e
senza API trovabile staticamente. Servirebbe la cattura di rete di un portale, la
stessa cosa che ha sbloccato MyPortal.

**Gli 800 non riconosciuti.** Ora in gruppi da 40–70, non più famiglie da mille.
Ogni firma nuova vale decine di comuni.

---

## Cosa cambia per la chat di TIQ

Oggi la chat risponde bene sui comuni ingeriti e dice onestamente di non sapere
sugli altri. Ogni fornitore che sale a livello **modello** cambia quella frase
per un pezzo d'Italia:

| Se saliamo su… | Comuni che passano da «non copro» a una risposta vera |
|---|---|
| Municipium | 1.009 |
| HGATE | 957 |
| AgendaSmart | 401 |
| OpenPA | 364 |
| MyPortal completo | 155 |

Sommati: **2.886 comuni**, il 36,5% d'Italia, per una quindicina di giornate di
lavoro. Nessun'altra voce del progetto ha questo rapporto.

---

## Perché non è «un connettore per prodotto»

Il lettore è **uno** — il modello di contenuto AgID — e i fornitori sono
*declinazioni* che cambiano solo nella forma: quale livello di intestazione,
quale prefisso di campo, quali alias.

Le stime qui sopra sono giornate per **scrivere una declinazione e verificarla su
comuni veri**, non per costruire sei sistemi. La differenza si vede nel codice:
il lettore dei campi tipizzati serve sia i box CMB2 di WordPress sia i `sys_*` di
MyPortal, perché entrambi fanno la stessa cosa — nominano i campi come le sezioni
del modello.

---

## Manutenzione: quanto costa tenerli in vita

I portali cambiano senza avvisare, quindi una scoperta scade dopo **7 giorni** e
va rifatta.

L'allarme però c'è già: `impronta_declinazione` è un hash della forma su cui il
lettore si aggancia, e sostituisce il numero di versione che nessun fornitore
pubblica. Quando si muove su molti comuni dello stesso fornitore la stessa notte,
quel fornitore ha cambiato template e **lo sappiamo prima che se ne accorga un
cittadino**.

Quanto è stabile ciascuno, misurato:

| Fornitore | Impronte distinte | Lettura |
|---|---|---|
| WordPress Design Comuni | 4 su 671 comuni | template molto uniforme |
| Regione Veneto | 7 su 74 | uniforme |
| PeopleWeb | 8 su 541 | uniforme, per un prodotto commerciale |
| Rete Civica Lepida | 11 su 66 | deployment divergenti |
| ComWeb | 12 su 502 | i più divergenti fra loro |

**Il costo di manutenzione non scala col numero di comuni: scala col numero di
piattaforme, e con quanto ciascuna è disomogenea.** ComWeb con 12 impronte su 502
comuni costerà più di PeopleWeb con 8 su 1.124.
