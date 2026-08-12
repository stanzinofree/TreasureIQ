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

### I bandi: leggi-prima, poi tre gradini in cascata, e il portale Halley

`bandi_live.py` non si ferma al CPT: prova tre gradini REST in ordine e
tiene il primo che copre — `cpt` (`amm-trasparente` via `wp-json/wp/v2/`),
`pages` (le sei parole chiave su `wp/v2/pages`, quando manca il CPT), e
**`alberatura`** (ciclo 8, sempre tentato — anche quando `cpt`/`pages` hanno
già risposto ma a zero bandi, perché un WordPress "silenzioso" non è la
stessa cosa di un comune non coperto).

Prima di sondare, però, ogni gradino **legge cosa è già catalogato** da uno
sweep precedente — zero rete se il catalogo è caldo, sonda solo se manca,
è incompleto o è scaduto (ciclo 18a, «discovery leggi-prima»). La regola è
sempre la stessa: *catalogo per instradare, cascata come ripiego, mai
verifica anticipata* — ricontrollare dal vivo un dato già catalogato
rifarebbe esattamente la sonda che si voleva evitare.

- **`alberatura`** parte da `registro.endpoints.at` (la pagina Amministrazione
  Trasparente già trovata da uno sweep) invece di ripartire dalla home del
  Comune: un solo fetch sull'URL catalogato, contro la catena originale
  (`_rami_wp` poi `_rami_html`) che può costarne fino a 4-5. I rami scoperti
  finiscono in una cache dedicata, `LIVE_DIR/alberatura/{istat}/rami.json`
  (14 giorni), così un miss bandi successivo (che scade ogni 8 ore) non
  ri-scopre i rami ogni volta. Se `endpoints.at` manca o il registro è muto,
  la catena originale resta il ripiego — invariata.
- **`cpt`** legge prima `mappa-connettore/{istat}.json`: se è calda e dice
  `amministrazione_trasparente_via == "REST"`, il `rest_base` della
  tassonomia bandi è già stato misurato da uno sweep precedente e non serve
  ripetere il probe `/wp-json/wp/v2/taxonomies`. Se la cache è assente,
  fredda, o il comune ha `via == "scrape"` (niente REST AT), si sonda come
  prima.
- Il **dispatch** legge `registro.piattaforma_at`: se è catalogata e non più
  vecchia di 14 giorni, seleziona quali dei tre gradini tentare invece di
  provarli alla cieca; se il dato manca, non è mai stato scritto, o è
  scaduto, si torna alla cascata cieca (tutti e tre). Onesto: **oggi le due
  voci catalogate (`wp_amm_trasp`, `halley_trasparenza`) autorizzano
  comunque tutti e tre i gradini** — nessun caso reale prova ancora che uno
  dei due possa saltarne uno senza perdere una fonte (Benevento, per
  esempio, ha i bandi WP su `pages` e i concorsi veri su `alberatura`:
  tagliare un gradino da quella voce perderebbe l'uno o l'altro). Il
  dispatch è quindi infrastruttura pronta, non ancora un taglio di fetch in
  produzione — lo diventa quando un resweep futuro giustificherà una voce
  ridotta.

Nessuna di queste letture salta la guardia SSRF (`fetch_guardato`, un host
atteso per hop): un URL letto dal catalogo si valida come uno letto dal vivo.
E se il catalogo è illeggibile o corrotto, si tratta come assente — mai
come un dato di cui fidarsi ciecamente.

Il gradino `alberatura` riconosce due vendor con estrattore reale: WordPress
e **Halley**, il portale dei concorsi pubblici *veri* — spesso su un
sottodominio separato dal sito istituzionale (`/zf/index.php/…/concorsi/in-corso`,
scoperto in `api/treasureiq/alberatura.py`). Le pagine Halley dichiarano
charset ISO-8859-1/windows-1252, mai UTF-8: decodificate esplicitamente,
altrimenti gli accenti si corrompono («mobilità» → «mobilitÃ »). Titolo e
data di scadenza sono letti verbatim dalla tabella del listing, mai
generati dal modello.

---

## Stato per piattaforma

| Piattaforma | Comuni | Quota | Livello | Servizi letti | Regioni |
|---|---|---|---|---|---|
| **PeopleWeb** (Siscom) | 1.124 | 14,2% | modello | 31.039 | 18 |
| **Municipium** (Maggioli) | 1.009 | 12,8% | firma* | — | 20 |
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

*Municipium (firma\*): non ha un CPT `servizi` da contare — il livello
"firma/catalogo/modello" di questa tabella è tarato sul modello AgID, che
Municipium non usa. Ha però un connettore proprio, consegnato al ciclo 10
(D-09): vedi il paragrafo Municipium più sotto per cosa legge davvero oggi.

---

## Dove conviene mettere l'effort

Il criterio non è la curiosità né la simpatia per una tecnologia:

```
comuni del fornitore  ×  quanto sale il livello di lettura
```

### Prima fascia — mille comuni a colpo

**Municipium (1.009 comuni, 20 regioni).** Il secondo fornitore d'Italia, il più
*nazionale* di tutti (presente in tutte e venti le regioni). Non usa il modello
a CPT AgID: ha un connettore proprio, consegnato al ciclo 10 (contratto D-09,
`api/treasureiq/municipium.py` + `municipium_at.py`) — **parziale**, non
"firma" pura, ma non ancora al livello **modello** di questa tabella.

Cosa legge oggi, verificato sul codice: la discovery uffici parte da
`{sito}/it/sitemap` (l'host applicativo `api.municipiumapp.it` risponde 503,
va bypassato — `municipium.py:126`), da cui estrae i link
`organizational_unit`/`unita_organizzative` e, in fallback, la pagina
`aree-amministrative` (`municipium.py:113-168`). Ogni ufficio è letto
verbatim (telefono/email/PEC/orari dalla sola sezione «Contatti», mai da un
modello — `municipium.py:188-217`), ma **spesso la pagina non pubblica
recapiti**: `source_typed` è vero solo quando ne trova almeno uno
(`municipium.py:262`). L'indice di Amministrazione Trasparente/bandi è
delegato a un modulo B3 (`municipium_at.py`) che legge SOLO i link già
estratti dalla sitemap, mai un secondo fetch di discovery — onesto **2 comuni
su 3** testati dal vivo: Fiumicino sì (30+ pagine-bando individuali, nessun
indice unico), Pomezia no (la trasparenza vive su un dominio terzo,
`pomezia.trasparenza-valutazione-merito.it`, scartato dalla guardia
anti-SSRF perché non è il dominio del comune).
*Stima residua: portarlo nel censimento e stimare l'estensione ai restanti
comuni Municipium* — oggi verificato solo su Pomezia e Fiumicino.

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
