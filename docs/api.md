# API TreasureIQ

Base URL in sviluppo: `http://localhost:8010`. Dal browser non si usa mai
direttamente: il front-end chiama percorsi relativi (`/api/…`) sulla propria
origine e Next li inoltra al container dell'API — vedi `rewrites` in
`web/next.config.mjs`.

**Swagger interattivo:** `http://localhost:8010/docs` — le rotte sono raggruppate
in quattro famiglie (Cittadino, Censimento nazionale, Qualità dei dati, Sistema),
perché hanno garanzie diverse e conviene sapere quale si sta guardando.
Schema grezzo: `GET /openapi.json`.

**Collection Bruno:** `bruno/TreasureIQ/`. Apri la cartella in
[Bruno](https://usebruno.com), scegli l'ambiente `locale` e parti da
*Cittadino → Sessione*: le altre richieste del gruppo hanno bisogno della
sessione aperta, ed è il motivo per cui ha `seq: 1`.

Questo documento spiega **cosa significano** le risposte, che è la parte che uno
schema non dice.

---

## Le due regole che spiegano quasi tutto

**Un campo vuoto è una misura, non un buco da riempire.** Ogni `null` in queste
risposte vuol dire «il comune non l'ha pubblicato» oppure «non l'abbiamo
misurato», mai «zero». Un `telefono: null` va reso come assenza dichiarata, non
sostituito con un centralino plausibile.

**Il binario cambia la forma della risposta, non solo il contenuto.** `kind`
vale `agevolazione` o `informazione` (D-19). Sul binario informativo non
esistono verdetto, criteri e SPID: non sono `null`, proprio non ci sono nel
tipo. Sul binario delle agevolazioni non esiste `info`. Un client che prova a
leggere i campi dell'altro binario ha sbagliato binario.

---

## Chat

### `POST /api/chat`

Il cuore del sistema. Una domanda in italiano, una risposta strutturata.

```json
{
  "message": "quando ritirano il vetro?",
  "comune_istat": "058003",
  "history": ["sono di Albano"]
}
```

| Campo | Note |
|---|---|
| `message` | La frase del cittadino, così com'è. |
| `comune_istat` | Il comune **scelto da una lista**, non dedotto. Quando c'è, non si guarda nient'altro. |
| `history` | Solo i messaggi precedenti del *cittadino*, mai le nostre risposte: una risposta che diventa input della successiva è un cortocircuito. |
| `filtri_override` | Facoltativo. Lista di `{ "azione": "rimuovi", "chiave": "<FiltroChiave>" }`: il cittadino toglie un filtro che gli abbiamo letto ma non è suo. `chiave` deve stare nell'enum `FiltroChiave` (dieci valori, vedi sotto) — una chiave fuori enum è un `422` automatico di Pydantic, non un errore applicativo da gestire a mano. |

Risposta (campi principali):

| Campo | Significato |
|---|---|
| `reply` | La frase di apertura, e nient'altro. Tutto il resto è nei campi tipizzati: la UI non deve estrarre dati dal testo. |
| `kind` | `agevolazione` \| `informazione`. Decide quale metà della risposta è popolata. |
| `matches[]` | Solo su `agevolazione`. Ogni voce ha `verdict`, `criteria[]` e `headline`. |
| `info` | Solo su `informazione`. Documento, ufficio, prove, azioni. `null` altrove. |
| `data_gap` | `not_published` \| `none_found` \| `comune_sconosciuto` \| `null`. |
| `access_mode` | Il gradino a cui la risposta è stata composta: `M2_prosa_api`, `M4_connettore`, `M6_web_aperto`… |
| `citizen_effort` | Quante azioni restano **al cittadino** dopo la risposta. Un conteggio, mai una stima, e non va mai sommato a `cost`. |
| `cost` | Quanto è costato a *noi* recuperare quel dato. Risponde a una domanda diversa da `citizen_effort`. |
| `connettore` | Presente su un comune **fuori copertura** che espone comunque un connettore leggibile: `{indirizzabile, uffici, rest_base}`. Dice per quale strada lo *raggiungeremmo*, non cosa spetta. `null` sui comuni coperti (già letti) o su chi non espone nulla. |
| `numeri_utili` | I recapiti URP: telefoni, email, PEC. **Due fonti distinte, mai da confondere.** Su un comune **coperto** vengono dallo store — la scansione già salvata, `letto_il` è `scansionato_il`, il momento vero della scansione, mai un `now()` al volo. Su un comune **fuori copertura** vengono letti dal vivo in quella richiesta — `letto_il` è davvero adesso, perché il portale è stato letto ora. Marcati `non verificato` per costruzione in entrambi i casi: nessun numero è "verificato", è quello che il portale espone. `null` se non c'è nulla da mostrare. |
| `comuni_ambigui[]` | Quando il nome nel messaggio combacia con più comuni omonimi: `[{nome, provincia, codice_istat}]` da rendere come schede cliccabili. La scelta è del cittadino, non nostra. Vuoto quando il comune è univoco o già scelto. |
| `filtri[]` | I filtri civici **riconosciuti in questo turno** (`chat/filtri.py::riconosci_filtri`), già proiettati dal backend — non include le chiavi appena tolte con `filtri_override` nella stessa richiesta. Ogni voce è un `FiltroOut`: `chiave` (`FiltroChiave`), `valore`, `span` (dove nel testo, `null` se il filtro non viene dal testo di questo turno), `sorgente`, `negato` (`true` se il cittadino ha negato quel filtro, es. «non sono disabile»). È la fonte dei chip di provenienza rimovibili nel pannello «cosa abbiamo capito» del web: ogni chip che il cittadino toglie va in `filtri_override` al giro successivo. |

### `criteria[].state`, sul binario agevolazioni

| Stato | Vuol dire |
|---|---|
| `met` | Il requisito è soddisfatto. |
| `not_met` | Non è soddisfatto. |
| `unknown_source` | **Il comune non l'ha pubblicato.** Non è un sì e non è un no: è una lacuna nei dati, e va mostrata come tale. |
| `unknown_profile` | Manca un dato del cittadino, che può fornirlo. |

Il verdetto viene da confronti espliciti sui campi (`match/engine.py`). Nessun
modello linguistico partecipa a questa decisione (D-01).

### `info`, sul binario informativo

| Campo | Significato |
|---|---|
| `document` | La pagina del comune: titolo verbatim, URL, descrizione, data di lettura. |
| `office` | Ufficio competente. Ogni campo è nullable per conto suo. |
| `stato` | `ufficiale` \| `parziale` \| `non_verificato` \| `non_pubblicato`. Provenienza e completezza, mai un diritto. |
| `letto_dal_vivo` | `true` solo se il portale è stato letto **durante questa richiesta**. Un dato letto al volo e uno verificato non devono avere lo stesso aspetto. |
| `prove[]` | Le righe di «cosa sappiamo dalla fonte», già composte: `confermato` \| `parziale` \| `mancante`. Le assenze sono righe, non righe che mancano. |
| `azioni[]` | I passi successivi: `testo`, `dettaglio`, `url`, `tipo`, `etichetta`. |
| `web_results[]` | Pagine trovate con una ricerca, `non_verificato: true` per costruzione. **Non sono una fonte**: sono un suggerimento da confermare. |

### `POST /api/approfondimento`

`{ "topic": "rifiuti" }` — il costo di recupero dettagliato per un argomento già
risposto. Riusa il topic invece di riclassificare, così resta deterministico.

### `POST /api/contatti-urp`

`{ "comune_istat": "110003" }` (o dal cookie di sessione) — i recapiti URP di un
comune **fuori copertura**, letti dal vivo su richiesta esplicita. Di un comune
che non leggiamo non possiamo dire cosa spetta, ma possiamo dire a chi chiedere.
La risposta torna marcata `non_verificato`: è ciò che il portale espone adesso,
non un dato che abbiamo controllato. La guardia sui numeri vale qui come altrove.

---

## Sessione e profilo

| Rotta | Cosa fa |
|---|---|
| `POST /api/session` | Apre una sessione con un profilo **simulato**. Nessuna credenziale viene verificata, nessun codice fiscale viene letto. Cookie `HttpOnly`, 8 ore. |
| `DELETE /api/session` | Chiude e dimentica tutta la sessione. |
| `POST /api/session/dimentica` | Dimentica **un campo solo** del profilo (`{ "campo": "comune_istat" }`). Il cittadino può correggere ciò che abbiamo dedotto senza ripartire da capo — sesso, età, comune, disabilità nel nucleo sono tutti scordabili uno per uno. |
| `GET /api/me` | Il profilo in sessione, o 401. |
| `GET /api/opportunities` | Le opportunità del comune del profilo, già valutate. `?include_ineligible=true` tiene anche i «no» — un no con una ragione è una risposta. |

---

## Comuni

| Rotta | Cosa fa |
|---|---|
| `GET /api/comuni?q=Castro` | Cerca fra i 7.896 comuni italiani. Fra due omonimi restituisce entrambi: la scelta è del cittadino, non nostra. |
| `GET /api/comune-nearby?lat=&lon=` | Il comune più vicino a una coordinata. Serve al pulsante «usa la mia posizione», che resta sempre facoltativo. |
| `GET /api/comune/{codice_istat}` | La scheda di un comune: aderenza AgID, catalogo servizi/uffici, recapiti e orari, così come l'ultima scansione li ha registrati. Se non esiste ancora uno scan, ne parte uno adesso — il timestamp mostrato resta sempre quello reale della scansione, mai un `now()` composto lì per lì. Comune ignoto → 404. |

---

## Misura (la parte che questo progetto esiste per fare)

| Rotta | Cosa fa |
|---|---|
| `GET /api/readiness` | La pagella 0–100 di ogni comune censito. |
| `GET /api/readiness/{codice_istat}` | La pagella di uno, con le dimensioni e i **rimedi**: cosa dovrebbe fare quel comune. |
| `GET /api/recovery` · `/{codice_istat}` | Quanto è costato recuperare i dati, per record e in aggregato. |
| `GET /api/integration` | Come si arriva a ciascun ente: connettore, modalità di accesso, diagnosi. |
| `GET /api/costo` | Il costo d'integrazione in forma aggregata. |
| `GET /api/panoramica` | Il quadro d'insieme per la pagina pubblica. |
| `GET /api/storico?codice_istat=` | Come si è mossa nel tempo la misura di un comune. |
| `GET /api/stats` · `/api/status` · `/api/health` | Conteggi, stato delle fonti, liveness. |

### Segnalazioni

`GET`/`POST /api/segnalazioni` — un cittadino può segnalare che su un comune
manca qualcosa. Non è un modulo di reclamo: è il modo in cui una lacuna
misurata diventa un numero accanto al nome di quel comune.

---

## Censimento nazionale

Lo sguardo d'insieme sui portali comunali: non «cosa spetta a te», ma «quanti
comuni sappiamo leggere e con quale piattaforma». Vuoto finché nessuno sweep è
stato registrato — un checkout fresco disegna un censimento vuoto, non un errore.

| Rotta | Cosa fa |
|---|---|
| `GET /api/censimento` | L'ultimo rilevamento nazionale: piattaforme, fornitori, sezioni mancanti, vincoli. |
| `GET /api/censimento/comune/{codice_istat}` | La piattaforma e l'aderenza AgID misurate per un comune, o `null` se mai spazzolato. |
| `GET /api/connettori` | Il catalogo delle **sonde**: cosa sappiamo leggere, piattaforma per piattaforma (`livello`: `catalogo` \| `modello` \| `firma`). Costruito dal codice, non da una tabella a mano: una piattaforma che perde la sua declinazione sparisce da qui lo stesso giorno. |

### Cascata servizi (comune fuori copertura, portale a modello AgID)

Quando la chat mostra il badge connettore, sotto compare una cascata a tre
livelli letta **adesso** dal portale: categorie → servizi → anteprima. Non è un
verdetto (D-01): è il catalogo del comune «citato come fonte».

| Rotta | Cosa fa |
|---|---|
| `GET /api/mappa-connettore/{codice_istat}` | La mappa di capacità del portale: catalogo servizi + le 15 categorie AgID (con `id`/`slug` per il drill) + uffici. `null` se il comune non è noto. Cache 30 giorni. |
| `GET /api/mappa-connettore/{codice_istat}/categoria/{term_id}` | I servizi di una categoria, come titolo + link alla scheda. Lista vuota se la categoria non ha (più) servizi. |
| `GET /api/mappa-connettore/{codice_istat}/scheda?url=<url>` | L'anteprima di un servizio, letta dalla sua pagina (descrizione, a chi è rivolto), con l'`url` per aprirla intera. L'`url` **deve** stare sul portale di quel comune (guardia host, niente proxy arbitrario), altrimenti `null`. Fonte citata, non verdetto. |

---

## Cosa NON c'è, e non per dimenticanza

- **Nessuna rotta che restituisca un diritto.** La risposta più forte che questa
  API dà è «nessun requisito pubblicato ti esclude», con l'elenco di quelli che
  il comune non ha pubblicato.
- **Nessuna scrittura verso i portali dei comuni.** Si legge e basta.
- **Nessun endpoint che accetti testo libero da rendere all'utente.** Il testo
  che torna al cittadino è composto da campi tipizzati (D-24).
