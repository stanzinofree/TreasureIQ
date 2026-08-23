# Piano TIQ v1 — dalla sorgente v0 alla lettura aperta della PA

## Decisione di base

Il tag `v0` congela la situazione attuale del progetto e costituisce la
sorgente di partenza per ogni evoluzione successiva.

TIQ non deve confrontare i comuni tra loro. Deve rendere ricercabili e
accessibili le informazioni pubbliche di qualunque ente, usando connettori
specifici solo finché le PA e i fornitori non espongono dati tramite contratti
aperti e uniformi.

La direzione di lungo periodo è quindi:

```text
portali eterogenei → connettori TIQ → modello canonico → API aperte
                                      ↓
                         standard pubblico condiviso
                                      ↓
                     meno connettori, più accesso diretto
```

TIQ è per ora uno strumento interno di lettura e spiegazione tramite chat, non
un provider di API pubbliche. È un ponte operativo verso uno standard aperto,
non un sostituto proprietario del futuro portale statale.

## Principi non negoziabili

1. L'SLM comprende il linguaggio, ma non decide fatti, diritti, fonti o esiti.
2. Il routing applicativo è deterministico e versionato.
3. Ogni dato esposto porta fonte, data di lettura, parser e livello di
   freschezza.
4. `ignoto`, `non trovato`, `non leggibile` e `non pubblicato` sono stati
   distinti.
5. La conversazione mantiene uno stato strutturato; la prosa non è memoria.
6. Un connettore non può inventare dati e non può nascondere i fallimenti.
7. Gli schemi canonici devono poter essere implementati anche fuori da Python.
8. Ogni passaggio rilevante deve essere riproducibile tramite replay e fixture.
9. La risposta finale è composta da dati verificati e template deterministici;
   l'SLM può eventualmente aiutare soltanto nella forma linguistica non
   fattuale.
10. La sicurezza verso i portali pubblici è parte del prodotto: rate limit,
    SSRF, redirect, dimensioni e timeout sono vincoli di primo livello.

## Stato implementazione — baseline corrente

Aggiornato dopo il primo ciclo di lavoro v1:

- `v0`: tag Git creato sul commit di baseline; il codice demo/SPID resta
  congelato e non è stato riutilizzato per la conversazione anonima.
- catalogo backoffice: contratti, snapshot, store append-only, drift e shadow
  run implementati in `api/treasureiq/catalog/`.
- `DataRequest`/`DataBatch`: implementati con access mode, freschezza,
  evidenze, limiti, trasporto e versione del connettore.
- planner: `QueryPlan` e selezione deterministica del batch implementati.
- adapter: seam universale e registry implementati; WordPress-AgID è il primo
  adapter registrato, gli altri restano da portare sul contratto v1.
- PDF: gate `pdf-inspector` implementato prima dell’estrazione `pypdf`;
  scansioni e PDF misti producono un piano OCR esplicito, ma l’engine OCR non
  è ancora attivo.
- conversazione: store SQLite server-side, cookie anonimo first-party da 90
  giorni, endpoint `DELETE /api/conversation` e interfaccia di forget già
  collegati. Il percorso di deploy deve ancora fornire il DB persistente.

Restano da completare: connettori non WordPress, Evidence Store, engine OCR,
replay delle conversazioni e verifica sul deployment TIQ.

## Fase 0 — congelamento e baseline v0

Stato: da registrare con il tag `v0`.

- Conservare il commit corrente come baseline immutabile.
- Registrare branch, commit, dipendenze, variabili di ambiente e compose.
- Eseguire e archiviare la suite attuale e la build frontend.
- Verificare la baseline in locale con OrbStack.
- Verificare il deployment esistente su `https://tiq.middei.info/` senza
  modificarlo.
- Creare una matrice di replay delle conversazioni già coperte dai test.
- Separare nel backlog i bug v0 dalle evoluzioni v1.

Deliverable: `v0`, report di baseline e matrice di regressione.

## Fase 1 — contratti canonici e stato conversazionale

Obiettivo: impedire che chat, connettori e motore decisionale condividano
interpretazioni implicite.

### Persistenza della conversazione

Una conversazione deve poter essere riaperta dopo un refresh e, finché il
cittadino non la dimentica, anche dopo la chiusura del browser. Il contratto
non dipende da SPID, login o dalle sessioni simulate del demo MVP.

Per l'uso anonimo il browser riceve un identificatore opaco, casuale e non
contenente dati personali. Il cookie è first-party, `Secure`, `HttpOnly` e
`SameSite=Lax`, con durata di **90 giorni**, esplicita e documentata. Il server conserva lo
stato associato all'identificatore; il client non è autorevole sul contenuto
della conversazione.

Sono previste due operazioni esplicite:

- `resume`: riapre la conversazione associata al cookie;
- `forget`: invalida immediatamente l'identificatore, elimina lo stato della
  conversazione e rimuove il cookie. Non è una semplice revoca del token.

L'interfaccia deve informare chiaramente dell'uso del cookie e offrire
`Dimentica questa conversazione`. Una futura identità autenticata potrà essere
aggiunta come altro meccanismo di associazione, ma non è un prerequisito del
contratto v1.

SPID simulato, login fittizio, accesso simulato e scenari demo non fanno parte
della progettazione v1. Restano soltanto nella baseline `v0` finché non verrà
deciso esplicitamente di rimuoverli dal codice.

Costruire e versionare:

- `ConversationState`;
- `ConversationEvent`;
- `Intent` e `QueryPlan`;
- `EntityRef` per comune, ente, ufficio, servizio e documento;
- `SlotValue` con valore, origine, evidenza e confidenza;
- `DataRequest` e `DataBatch`;
- `SourceEvidence` e `Freshness`;
- stati distinti per errore, assenza e illeggibilità.

### Contratto iniziale di `ConversationState`

Lo stato canonico contiene solo ciò che serve per interpretare la richiesta e
costruire il piano dati. Non contiene la risposta precedente come memoria
decisionale e non contiene dettagli tecnici del modello.

```json
{
  "conversation_id": "uuid",
  "revision": 12,
  "schema_version": "1",
  "scope": {
    "municipality": {
      "istat": "058003",
      "name": "Albano Laziale",
      "source": "explicit_selection",
      "status": "active"
    }
  },
  "intent": {
    "value": "find_benefit",
    "source": "deterministic_scorer",
    "status": "active"
  },
  "topic": {
    "value": "mensa_scolastica",
    "source": "user_message",
    "evidence": "mensa scolastica",
    "status": "active"
  },
  "beneficiary": {
    "value": "child",
    "source": "explicit_user",
    "status": "active"
  },
  "slots": {
    "children_count": {
      "value": 2,
      "source": "user_message",
      "evidence": "ho due figli",
      "status": "active"
    },
    "isee": {
      "value": null,
      "source": null,
      "evidence": null,
      "status": "unknown"
    }
  },
  "pending": {
    "slot": "isee",
    "question_code": "isee_required",
    "status": "open"
  },
  "last_query_plan_id": null,
  "versions": {
    "intent_rules": "1",
    "slot_rules": "1",
    "state_schema": "1"
  }
}
```

Le sorgenti dei valori sono chiuse e distinguono sempre una proposta del
modello da una dichiarazione dell'utente:

```text
explicit_selection | user_message | pending_answer |
deterministic_scorer | slm_fallback | system_catalog
```

`slm_fallback` può essere accettato soltanto dopo la validazione deterministica
e resta distinguibile dalla selezione esplicita.

### Eventi v1 e reducer

Il reducer applica soltanto questi eventi:

```text
SET_SCOPE | SET_INTENT | SET_TOPIC | SET_BENEFICIARY |
SET_SLOT | REMOVE_SLOT | CORRECT_SLOT |
SET_PENDING_QUESTION | ANSWER_PENDING_QUESTION |
CLEAR_PENDING_QUESTION | RESET_CONTEXT
```

Regole fondamentali:

- la selezione esplicita del comune prevale sul nome riconosciuto nel testo;
- una dichiarazione esplicita del turno corrente prevale sul valore precedente;
- una correzione invalida il valore precedente;
- una negazione rimuove solo ciò che nega;
- una risposta breve viene associata soltanto al `pending` aperto;
- eventi duplicati sono idempotenti;
- una revisione inattesa viene rifiutata;
- nessun evento può scrivere direttamente un verdetto o un risultato dati.

Il reducer deve essere puro e riproducibile:

```text
reduce(state, event) -> new_state
```

```text
stesso stato + stesso evento = stesso nuovo stato
```

### Persistenza separata

La conversazione persistita è composta da tre livelli distinti:

```text
Conversation
  ├── ConversationState       stato corrente proiettato
  ├── ConversationEvent       log strutturato delle transizioni
  └── ConversationMessage     testo originale mostrato all'utente
```

Un evento v1 ha questa forma concettuale:

```json
{
  "event_id": "uuid",
  "conversation_id": "uuid",
  "sequence": 13,
  "type": "SET_SLOT",
  "payload": {
    "slot": "children_count",
    "value": 2,
    "source": "user_message",
    "evidence": "ho due figli"
  },
  "input_message_id": "uuid",
  "rules_version": "1",
  "created_at": "2026-08-20T12:00:00Z"
}
```

Un messaggio conserva il testo necessario alla riapertura della chat e alla
visualizzazione del transcript, ma non viene usato come memoria decisionale:

```json
{
  "message_id": "uuid",
  "conversation_id": "uuid",
  "sequence": 13,
  "role": "user",
  "content": "Ho due figli e cerco la mensa scolastica",
  "created_at": "2026-08-20T12:00:00Z"
}
```

Le risposte dell'assistente possono essere salvate per il transcript, ma non
sono input del reducer e non possono diventare evidenza utente in un turno
successivo.

### `forget` e concorrenza

`forget` deve essere un'operazione transazionale:

1. invalidare il token della conversazione;
2. cancellare `ConversationState`, eventi e messaggi;
3. impedire nuove scritture sul vecchio identificatore;
4. rimuovere il cookie nella risposta HTTP.

Il client invia la `revision` corrente. Se la revisione non coincide con quella
del server, il nuovo turno non viene applicato: il client deve ricaricare lo
stato aggiornato. Questo evita che due schede del browser sovrascrivano il
contesto senza accorgersene.

Le modifiche del contesto devono essere operazioni esplicite: `SET`, `REMOVE`,
`CONFIRM`, `CORRECT`, `REJECT`, `ANSWER_PENDING_SLOT`.

Deliverable: schema registry, reducer puro, replay deterministico e test di
compatibilità con il comportamento v0.

### Contratto di `TurnInterpretation`

`TurnInterpretation` descrive esclusivamente ciò che il sistema ha capito del
messaggio corrente. Non contiene risultati di ricerca, eleggibilità, fonti
scelte o testo di risposta.

Forma concettuale:

```json
{
  "message_id": "uuid",
  "intent": {
    "value": "find_benefit",
    "confidence": 0.94,
    "source": "deterministic_scorer",
    "status": "accepted"
  },
  "entities": [
    {
      "type": "topic",
      "value": "mensa_scolastica",
      "canonical_id": "mensa_scolastica",
      "evidence": "mensa scolastica",
      "source": "user_message",
      "status": "accepted"
    }
  ],
  "claims": [
    {
      "field": "children_count",
      "value": 2,
      "evidence": "ho due figli",
      "source": "user_message",
      "status": "accepted"
    }
  ],
  "operations": [
    {
      "type": "SET_SLOT",
      "field": "children_count",
      "value": 2
    }
  ],
  "ambiguities": [],
  "abstained": false,
  "rules_version": "1",
  "model_version": null
}
```

### Vocabolari chiusi iniziali

Gli intenti v1 devono essere pochi e orientati all'azione richiesta:

```text
SEARCH_INFORMATION
FIND_SERVICE
FIND_BENEFIT
FIND_NOTICE
FIND_OFFICE
FIND_CONTACT
FIND_OPENING_HOURS
FIND_DOCUMENT
VERIFY_REQUIREMENTS
CONTINUE_CONTEXT
CORRECT_CONTEXT
FORGET_CONVERSATION
UNKNOWN
```

Le entità ammesse includono inizialmente:

```text
municipality
institution
service
benefit
notice
office
document
topic
beneficiary
date
```

Gli slot anagrafici o procedurali restano separati dalle entità e vengono
accettati solo quando il testo li supporta. Un numero isolato, per esempio
`"due"`, non è uno slot finché non esiste una domanda `pending` compatibile.

### Regole di validazione

Prima di trasformare l'interpretazione in eventi:

- l'intento deve appartenere al vocabolario chiuso;
- ogni entity deve avere un identificatore canonico oppure diventare
  `ambiguous`;
- ogni claim estratto dal messaggio deve avere uno span/evidenza;
- valori numerici, date e codici devono passare parser deterministici;
- negazioni e correzioni devono diventare operazioni esplicite;
- l'SLM non può emettere direttamente `SET` su valori non presenti nel testo;
- confidenza bassa o conflitto tra candidati produce `abstained=true`;
- `abstained=true` può generare solo una richiesta di chiarimento o nessun
  evento, mai un valore inventato.

Il passaggio successivo è quindi deterministico:

```text
TurnInterpretation → validate → ConversationEvents → reduce
```

## Fase 2 — flusso chat deterministico

Obiettivo: fare dello SLM un interprete controllato, non il motore della chat.

Pipeline target:

```text
messaggio
  → normalizzazione deterministica
  → scorer/regole
  → risoluzione entità
  → SLM solo se ambiguo o non riconosciuto
  → validazione contro schema e testo
  → aggiornamento dello stato
  → QueryPlan
```

Attività:

- portare il backend intent Rust/Python deterministico a default;
- introdurre soglie e margine minimo tra candidati;
- imporre l'astensione del modello;
- vietare slot senza span o senza fonte esplicita;
- eliminare la rilettura libera dell'intera storia;
- passare al modello stato strutturato e ultimo messaggio;
- registrare versione di regole, vocabolario e modello;
- rendere riproducibili le correzioni multi-turno.

Deliverable: chat con stessa decisione a parità di input, stato e versioni,
anche quando Ollama è spento.

## Fase 3 — Query Planner e retrieval federato

Obiettivo: separare definitivamente “cosa chiede l'utente” da “come si legge
una fonte”.

Il planner traduce l'intento in una richiesta dati, per esempio:

```json
{
  "plan": "find_service",
  "scope": {"municipality": "058003"},
  "capabilities": ["services", "offices", "documents"],
  "freshness": "catalog_then_live_if_stale",
  "required_slots": []
}
```

### Contratto di `QueryPlan`

Il piano è un oggetto dati versionato. Non contiene chiamate HTTP, nomi di
moduli Python o URL costruiti dalla chat.

```json
{
  "plan_id": "uuid",
  "conversation_id": "uuid",
  "plan_version": "1",
  "operation": "find_service",
  "scope": {
    "municipality_istat": "058003"
  },
  "requirements": [
    {
      "capability": "services",
      "selection": {
        "topic": "mensa_scolastica"
      },
      "freshness": {
        "policy": "catalog_then_live_if_stale",
        "max_age_seconds": 604800
      },
      "required": true
    },
    {
      "capability": "documents",
      "selection": {
        "relation": "linked_to_service"
      },
      "freshness": {
        "policy": "use_catalog_then_refresh_on_change",
        "max_age_seconds": 2592000
      },
      "required": false
    }
  ],
  "filters": {
    "children_count": 2,
    "isee": null
  },
  "response_mode": "structured_with_evidence",
  "rules_version": "1"
}
```

### Capability v1

Il registry iniziale espone capability, non piattaforme:

```text
institution_profile
services
benefits
public_notices
offices
contacts
opening_hours
documents
forms
application_channels
deadlines
```

Un connettore può dichiarare solo le capability effettivamente verificate.
`services` non implica automaticamente `documents`, e `offices` non implica
automaticamente `opening_hours`.

### Regole del planner

- un intent sconosciuto non produce un piano dati;
- un piano senza comune quando il dato è comunale produce una richiesta di
  chiarimento, non una ricerca sul comune predefinito;
- una capability non dichiarata non viene tentata per supposizione;
- il catalogo viene usato prima della rete;
- il live fetch parte solo per dato assente, scaduto o richiesto esplicitamente;
- ogni requisito del piano deve avere un criterio di successo o di fallimento;
- il piano non può produrre direttamente una risposta finale;
- l'ordine delle capability e dei fallback è stabile e versionato.

### Esiti di esecuzione

Ogni requisito produce uno stato indipendente:

```text
fulfilled       dati recuperati e validati
empty           fonte leggibile, nessun elemento trovato
not_supported   capability non esposta dalla fonte
not_found       endpoint/documento non trovato
stale           dato presente ma oltre la freschezza ammessa
unreadable      fonte raggiunta ma non interpretabile
failed          errore tecnico o rete
```

Questi esiti non vengono compressi in un generico “nessun risultato”. La
risposta deve distinguere, per esempio, tra “non ci sono bandi pubblicati” e
“questo portale non espone una sezione bandi leggibile”.

Il planner non conosce WordPress, Municipium o Halley. Conosce solo capability
canoniche e regole di freschezza.

Deliverable: esecuzione deterministica del piano, cache/catalogo prima della
rete, fallback dichiarati e trace leggibile.

## Fase 4 — SDK universale dei connettori

Obiettivo: trasformare i connettori da funzioni verticali a adapter di
capability.

Separare:

1. transport adapter: HTTP, redirect, retry, rate limit e SSRF;
2. capability detector: cosa espone davvero la fonte;
3. source adapter: conoscenza della piattaforma;
4. canonical normalizer: conversione nel modello comune.

### Modello canonico v1

Ogni record normalizzato usa un involucro comune:

```json
{
  "entity_type": "service",
  "canonical_id": "service:058003:mensa-scolastica",
  "institution_id": "058003",
  "title": "Mensa scolastica",
  "status": "active",
  "data": {},
  "source": {
    "source_id": "comune-058003",
    "url": "https://www.comune.example.it/servizi/mensa",
    "retrieved_at": "2026-08-20T12:00:00Z",
    "adapter": "wordpress_agid",
    "adapter_version": "1.0",
    "raw_hash": "sha256:..."
  },
  "evidence": [],
  "freshness": {
    "status": "fresh",
    "checked_at": "2026-08-20T12:00:00Z"
  }
}
```

Le entità iniziali sono:

```text
Institution
Service
Benefit
Notice
Office
ContactPoint
Document
Procedure
Requirement
Deadline
ApplicationChannel
```

Le relazioni devono essere identificabili e non soltanto espresse nel testo:

```text
Institution → publishes → Service
Service → requires → Requirement
Service → has_document → Document
Notice → concerns → Service
Office → provides → ContactPoint
Procedure → has_deadline → Deadline
Procedure → accepts_via → ApplicationChannel
```

Il normalizzatore non deve fondere automaticamente due record solo perché
hanno lo stesso titolo. La deduplicazione richiede un identificatore sorgente,
una relazione verificata o una regola esplicita e testata.

### Evidenza obbligatoria

Ogni campo che può influenzare una risposta deve poter puntare a una o più
evidenze:

```json
{
  "field": "deadline.date",
  "value": "2026-09-30",
  "quote": "Le domande devono essere presentate entro il 30 settembre 2026",
  "document_url": "https://www.comune.example.it/files/bando.pdf",
  "page": 4,
  "coordinates": null,
  "extraction_method": "native_text",
  "extraction_version": "1",
  "verified": true
}
```

Un valore privo di evidenza non può essere usato per una decisione fattuale.
Può restare nel catalogo come dato non verificato, ma deve essere marcato e
non deve apparire come certezza nella risposta.

### Registry e `SourceManifest`

Il registry associa una fonte conosciuta alle capability verificate, senza
esporre questa scelta al livello chat:

```json
{
  "source_id": "comune-058003",
  "institution_id": "058003",
  "base_url": "https://www.comune.example.it",
  "platform": {
    "family": "wordpress_agid",
    "variant": "design-comuni",
    "fingerprint": "sha256:...",
    "detected_at": "2026-08-20T12:00:00Z"
  },
  "capabilities": {
    "services": {"status": "verified", "adapter": "wordpress_agid"},
    "offices": {"status": "verified", "adapter": "wordpress_agid"},
    "documents": {"status": "unknown", "adapter": null}
  },
  "endpoints": {},
  "last_probe_at": "2026-08-20T12:00:00Z",
  "manifest_version": "1"
}
```

Stati ammessi per una capability:

```text
verified       verificata con una risposta valida
unsupported    verificata come non disponibile
unknown        mai verificata o fingerprint cambiato
stale          verifica scaduta
broken         precedentemente disponibile, ora fallita
```

`unknown` non equivale a `unsupported`: il primo autorizza una discovery
controllata, il secondo evita tentativi inutili finché non cambia la fonte.

### Interfaccia dell’adapter

Il contratto logico è:

```python
class SourceAdapter(Protocol):
    name: str

    def discover(self, source: SourceRef) -> SourceManifest: ...

    def capabilities(
        self, manifest: SourceManifest
    ) -> set[CapabilityResult]: ...

    def query(
        self,
        manifest: SourceManifest,
        request: DataRequest,
    ) -> DataBatch: ...
```

L’adapter può conoscere HTML, REST, encoding, paginazione e struttura del
vendor. Non può conoscere:

- il testo della risposta all’utente;
- il profilo conversazionale;
- le regole di eleggibilità;
- il ranking dei risultati;
- le decisioni del planner.

### Selezione dell’adapter

La selezione è deterministica:

```text
SourceManifest
  → capability richiesta
  → adapter registrati compatibili
  → priorità dichiarata
  → primo adapter con manifest valido
  → esito esplicito se nessuno è disponibile
```

La priorità non è una preferenza arbitraria: deve essere motivata da un
contratto più strutturato o da una fonte più diretta. Per esempio:

```text
REST tipizzato > feed strutturato > HTML semantico > HTML euristico
```

Il registry deve poter eseguire più adapter per la stessa capability solo per
conferma o fallback esplicito, mai per sommare silenziosamente dati duplicati.

Contratto target:

```python
discover(source) -> SourceManifest
capabilities(manifest) -> set[Capability]
query(manifest, request) -> DataBatch
```

Ogni adapter deve avere contract test comuni, fixture reali, fingerprint della
fonte e audit dei record scartati.

Deliverable: registry dei connettori, capability standard e primo adapter
riscritto senza modificare il risultato pubblico v0.

### Transport layer comune

Gli adapter non devono creare client HTTP propri per le funzioni fondamentali.
Usano un transport condiviso che applica sempre le stesse policy:

```text
request
  → URL normalizzata
  → host autorizzato
  → rate limit per host
  → cache policy
  → timeout budget
  → redirect controllato per hop
  → risposta con hash e metadati
```

Il risultato del trasporto è distinto dal dato normalizzato:

```json
{
  "url": "https://www.comune.example.it/api/services",
  "final_url": "https://www.comune.example.it/api/services",
  "status_code": 200,
  "content_type": "application/json",
  "retrieved_at": "2026-08-20T12:00:00Z",
  "body_hash": "sha256:...",
  "from_cache": false,
  "redirects": [],
  "error": null
}
```

Policy obbligatorie:

- allowlist dell'host atteso per la fonte;
- verifica dell'host a ogni redirect;
- blocco di IP privati, loopback, link-local e schemi non HTTP(S);
- limite di dimensione prima e durante il download;
- timeout separati per connessione, lettura e operazione totale;
- distanza minima e concorrenza limitata per host;
- User-Agent identificabile e contatto del progetto;
- retry solo su errori transitori e con backoff;
- nessun retry automatico su 4xx o risposte semanticamente invalide.

La cache non può mascherare lo stato della fonte. Ogni risultato indica se è
stato letto dal vivo o servito da cache, con età e policy applicata. Un
fallimento live non può trasformarsi silenziosamente in un dato fresco.

Il transport layer produce telemetria operativa, ma il catalogo pubblico usa
solo dati verificati: tempi, tentativi e costi interni non diventano fatti sulla
PA.

### Contratto con il motore di chat

Il connettore non restituisce prosa e non decide come rispondere. Restituisce un
`DataBatch` strutturato:

```json
{
  "request_id": "uuid",
  "access_mode": "mediated",
  "surface": "ordinary_data",
  "source_id": "comune-058003",
  "capability": "services",
  "status": "fulfilled",
  "records": [],
  "evidence": [],
  "freshness": {
    "status": "fresh",
    "retrieved_at": "2026-08-20T12:00:00Z"
  },
  "limitations": [],
  "connector": {
    "name": "wordpress_agid",
    "version": "1.0"
  }
}
```

Il motore di chat usa soltanto:

- record canonici;
- evidenze;
- stato di freschezza;
- `access_mode`;
- esito e limitazioni.

Non conosce la sequenza HTTP, il parser HTML, il vendor o le regole di
discovery. Il connettore non conosce il testo della risposta, il profilo
conversazionale o il template di verbalizzazione.

## Fase 5 — pipeline documentale e PDF

Obiettivo: leggere documenti nativi, scansionati e misti senza mandare tutto a
OCR.

Pipeline target:

```text
download sicuro
  → hash e validazione
  → pdf-inspector
  → classificazione per pagina
  → estrazione nativa
  → OCR selettivo
  → segmenti con pagina/coordinate
  → fatti canonici ed evidenze
```

Integrare `pdf-inspector` dietro un adapter versionato, misurando sui PDF reali
di TIQ l'accuratezza di classificazione, l'ordine di lettura, le tabelle e la
percentuale di pagine che richiedono OCR.

Riferimento tecnico: [firecrawl/pdf-inspector](https://github.com/firecrawl/pdf-inspector/tree/main).

### Contratto di ispezione

L'ispezione deve produrre un risultato indipendente dal motore OCR:

```json
{
  "document_hash": "sha256:...",
  "pdf_type": "mixed",
  "confidence": 0.98,
  "page_count": 12,
  "pages_needing_ocr": [7, 8],
  "encoding_warning": false,
  "native_text_available": true,
  "inspector": "pdf-inspector",
  "inspector_version": "0.2.6"
}
```

Valori ammessi per `pdf_type`:

```text
text_based
scanned
image_based
mixed
invalid
unknown
```

### Routing per pagina

```text
PDF
  → validazione e hash
  → classificazione
  → pagine native → estrazione layout-aware
  → pagine immagine/scansione → OCR
  → merge ordinato dei segmenti
  → controllo qualità
```

Il routing non deve inviare a OCR l'intero documento quando solo alcune pagine
sono illeggibili. Ogni segmento risultante conserva:

```text
document_hash
page_number
source_method       native_text | ocr
text
coordinates
confidence
```

### Regole di qualità

- testo vuoto o troppo breve non è automaticamente un PDF senza contenuto;
- encoding danneggiato produce `unreadable` o fallback OCR controllato;
- le tabelle devono mantenere righe, colonne e pagina di origine;
- le pagine OCR devono essere distinguibili da quelle native;
- un requisito estratto deve citare il segmento da cui proviene;
- una citazione non ritrovata nel segmento scarta il valore;
- il fallimento OCR resta visibile nel risultato del connettore;
- lo stesso hash e la stessa versione del parser devono essere riutilizzabili
  senza rieseguire l'estrazione.

### Scelta del motore OCR

`pdf-inspector` non sostituisce l'OCR: decide dove serve e fornisce
un'estrazione nativa strutturata. Il motore OCR sarà un adapter separato, così
potrà essere sostituito o eseguito localmente senza cambiare il contratto PDF.

Prima dell'integrazione definitiva occorre un benchmark su fixture reali TIQ:

```text
PDF nativo | PDF scansionato | PDF misto | tabelle | encoding rotto | moduli
```

Le metriche minime sono: pagine correttamente classificate, testo recuperato,
ordine di lettura, tabelle recuperate, citazioni verificabili, tempo e memoria.

Deliverable: `DocumentVersion`, `EvidenceSpan`, routing OCR per pagina,
fallback `unreadable` e citazioni verificabili.

## Fase 6 — Evidence store e qualità della fonte

Obiettivo: fare di ogni risposta una lettura verificabile, non una sintesi
opaca.

Persistono separatamente:

- fonte e URL;
- versione del documento;
- segmento o pagina;
- fatto estratto;
- citazione;
- parser e versione;
- data di lettura;
- freschezza;
- conflitti tra fonti;
- motivo di eventuale scarto.

### Struttura dell'evidenza

L'evidenza non è soltanto una stringa allegata al record. È un oggetto
referenziabile:

```json
{
  "evidence_id": "uuid",
  "fact_id": "fact:service:058003:mensa:deadline",
  "source_document_id": "doc:sha256:...",
  "source_url": "https://www.comune.example.it/files/bando.pdf",
  "retrieved_at": "2026-08-20T12:00:00Z",
  "location": {
    "page": 4,
    "coordinates": null,
    "section": "Scadenza"
  },
  "quote": "Le domande devono essere presentate entro il 30 settembre 2026",
  "value": "2026-09-30",
  "extraction_method": "native_text",
  "parser_version": "pdf-inspector:0.2.6",
  "verification": "quote_found"
}
```

Un `Fact` può avere più evidenze, anche da fonti diverse. Il sistema non deve
scegliere silenziosamente una fonte in caso di conflitto:

```text
Fact
  ├── Evidence A → deadline 2026-09-30
  └── Evidence B → deadline 2026-10-15
```

Il conflitto diventa uno stato pubblico del dato:

```text
consistent
conflicting
expired
unverified
superseded
```

### Regole di risoluzione

- una fonte più recente non prevale automaticamente se è meno strutturata o
  non verificata;
- un PDF ufficiale collegato alla pagina del bando ha precedenza su una copia
  trovata altrove;
- una modifica della fonte crea una nuova `DocumentVersion`, non sovrascrive
  l'evidenza storica;
- un fatto confliggente non viene trasformato in un singolo valore certo;
- la risposta può usare un fatto solo se lo stato è compatibile con il piano;
- il cittadino deve poter aprire la fonte originale;
- `forget` elimina anche le evidenze private associate alla conversazione, ma
  non cancella il catalogo pubblico condiviso.

### Contratto verso la risposta

Il motore di risposta riceve fatti già risolti o esplicitamente confliggenti:

```json
{
  "field": "deadline",
  "value": "2026-09-30",
  "status": "verified",
  "evidence_ids": ["uuid"],
  "freshness": "fresh"
}
```

Non riceve HTML grezzo, prompt o output libero del modello. La verbalizzazione
può soltanto proiettare il contratto e deve degradare in modo esplicito quando
un fatto è `conflicting`, `expired` o `unverified`.

Deliverable: risposta con evidenze, gestione dei conflitti e invalidazione dei
dati quando cambia l'hash della fonte.

## Fase 7 — misurazione della compatibilità e standard aperto

Obiettivo immediato: rendere visibile quando una PA non espone dati compatibili
con il modello AGID e quando per accedervi serve un connettore troppo custom.
Lo standard aperto è il risultato futuro che TIQ può sostenere con queste
misurazioni, non un'API pubblica che TIQ deve esporre ora.

Per ogni fonte TIQ deve distinguere almeno:

```text
agid_compatibility
  compatible | partial | incompatible | unknown

connector_effort
  standard_rest | known_adapter | custom_adapter |
  heuristic_scrape | unreadable

data_exposure
  typed | semi_structured | free_text | missing | unknown
```

La chat non deve spiegare questo report. La valutazione della fonte è un
processo di backoffice, ripetuto nel tempo, che alimenta il catalogo interno.
L'utente finale riceve soltanto la modalità con cui il dato è stato recuperato.

### Due superfici per ogni comune

Il catalogo deve modellare separatamente le due piattaforme che normalmente
servono un comune:

```text
Comune
  ├── piattaforma dati ordinari
  │     servizi, uffici, contatti, orari, modulistica
  └── piattaforma Amministrazione Trasparente
        bandi, avvisi, concorsi, documenti e pubblicazioni
```

Le due superfici possono appartenere allo stesso fornitore, a fornitori
diversi o a una piattaforma non riconosciuta. Non vanno fuse in un unico
“portale comunale”, perché hanno capability, accessi e livelli di aderenza
diversi.

### Due livelli di misurazione

Il backoffice produce due misure indipendenti:

```text
1. Piattaforma → modello AgID
   Quanto la piattaforma standard espone correttamente il modello?

2. Comune → piattaforma
   Quanto il singolo comune utilizza e compila quella piattaforma?
```

La prima misura riguarda il fornitore e la sua implementazione dello standard;
la seconda riguarda il contenuto effettivamente pubblicato dal comune. Un
comune non deve essere penalizzato per una sezione che la piattaforma non
prevede, e una piattaforma non deve essere considerata conforme solo perché il
comune ha compilato una pagina in testo libero.

### Classificazione dell'accesso per l'utente

La chat espone soltanto la modalità di recupero del dato:

```text
direct       dato letto da fonte standard compatibile AgID
mediated     dato recuperato da un connettore di retrieve noto
indirect     dato trovato tramite scraping web o fonte non strutturata
unavailable  nessun dato leggibile o fonte non raggiungibile
```

Regola operativa:

```text
100% standard AgID e endpoint noto → direct
piattaforma riconosciuta + adapter/retrieve custom → mediated
nessuna piattaforma leggibile + ricerca/scraping → indirect
nessuna lettura possibile → unavailable
```

Questa classificazione non è un giudizio sul comune e non viene spiegata in
chat con un report tecnico. Serve a rendere il risultato trasparente e a
misurare nel backoffice quanto lavoro resta da standardizzare.

### Ciclo di backoffice

```text
censimento periodico
  → riconoscimento delle due piattaforme
  → misura piattaforma/AgID
  → misura comune/piattaforma
  → aggiornamento manifest e capability
  → selezione del connettore
  → catalogo pronto per la chat
```

### Report interno di esposizione

Il report è associato alla fonte e alla rilevazione, non al valore personale del
cittadino. Non è una graduatoria e non produce un punteggio sintetico della PA.

```json
{
  "institution_id": "058003",
  "source_id": "comune-058003",
  "measurement_id": "run-2026-08-20-058003",
  "agid_model": {
    "version": "1",
    "compatibility": "partial",
    "sections": {
      "who_is_it_for": {"status": "present_empty", "exposure": "typed"},
      "what_is_needed": {"status": "present", "exposure": "free_text"},
      "how_to_apply": {"status": "present", "exposure": "typed"},
      "deadlines": {"status": "missing", "exposure": "missing"}
    }
  },
  "connector_effort": {
    "class": "custom_adapter",
    "platform": "example-platform",
    "discovery_steps": 4,
    "requests": 12,
    "custom_rules": 7,
    "fallbacks_used": ["html_heuristic"],
    "maintainability": "high_drift_risk"
  },
  "data_exposure": {
    "services": "semi_structured",
    "offices": "typed",
    "documents": "free_text",
    "notices": "unknown"
  },
  "limitations": [
    "requirements_present_but_not_typed",
    "deadline_not_exposed",
    "custom_scraper_required"
  ],
  "measured_at": "2026-08-20T12:00:00Z",
  "source_evidence": []
}
```

Stati delle sezioni: `absent`, `present_empty`, `present`,
`partially_recovered`, `unreadable`, `unknown`. `present_empty` indica un
problema di compilazione, `absent` un limite dello schema/fonte, `unreadable`
un limite del connettore e `unknown` una verifica ancora da fare.

La chat mostra questo report solo quando è rilevante, con linguaggio semplice.
Il dettaglio tecnico resta nel report interno e nella telemetria del connettore.

Lo standard dovrebbe descrivere almeno:

- servizi;
- uffici e punti di contatto;
- orari;
- bandi e avvisi;
- requisiti;
- documenti;
- scadenze;
- canali di presentazione;
- identificatori dell'ente;
- provenienza e aggiornamento;
- capability e versione dello schema.

Il formato deve essere:

- pubblico;
- versionato;
- documentato con JSON Schema/OpenAPI;
- compatibile con REST;
- estendibile senza rompere i client;
- accompagnato da esempi e contract test;
- pubblicabile direttamente da una PA o da un fornitore.

### Snapshot di backoffice

Il censimento produce due oggetti diversi e non intercambiabili.

`PlatformSnapshot` descrive la famiglia di piattaforma:

```json
{
  "platform_id": "wordpress_agid",
  "surface": "ordinary_data",
  "vendor": "example-vendor",
  "agid_model": {
    "target_version": "1",
    "compatibility": "partial",
    "sections": {
      "services": "typed",
      "offices": "typed",
      "contacts": "semi_structured",
      "opening_hours": "free_text"
    }
  },
  "access_contract": {
    "transport": "rest",
    "endpoints": ["services", "offices"],
    "authentication": "public",
    "pagination": "verified"
  },
  "connector": {
    "adapter": "wordpress_agid",
    "mode": "standard_rest",
    "version": "1.0"
  },
  "fingerprint": "sha256:...",
  "measured_at": "2026-08-20T12:00:00Z"
}
```

`MunicipalityPlatformSnapshot` descrive l'istanza concreta del comune:

```json
{
  "municipality_istat": "058003",
  "surface": "ordinary_data",
  "platform_id": "wordpress_agid",
  "base_url": "https://www.comune.example.it",
  "platform_compatibility": "partial",
  "municipality_adoption": {
    "services": "present",
    "offices": "present",
    "contacts": "present_empty",
    "opening_hours": "missing"
  },
  "access_mode": "direct",
  "capabilities": {
    "services": "verified",
    "offices": "verified",
    "contacts": "verified",
    "opening_hours": "unsupported"
  },
  "capability_access_modes": {
    "services": "direct",
    "offices": "direct",
    "contacts": "mediated"
  },
  "connector": "wordpress_agid",
  "fingerprint": "sha256:...",
  "measured_at": "2026-08-20T12:00:00Z"
}
```

Per la superficie Amministrazione Trasparente si crea un secondo snapshot,
anche quando la piattaforma coincide con quella dei dati ordinari.

Ogni rilevazione conserva lo storico. Un cambio di fingerprint, endpoint,
schema o capability genera un evento di drift:

```text
unchanged | platform_changed | schema_changed | endpoint_changed |
capability_changed | connector_degraded | connector_recovered
```

`capability_access_modes` è la classificazione autorevole per la singola
capability. `access_mode` resta una sintesi compatibile per il livello snapshot
finché tutti i consumer saranno migrati.

La chat usa solo l'ultimo snapshot valido; il backoffice conserva lo storico
per capire quando un connettore ha smesso di essere diretto o ha richiesto
scraping custom.

### Censimento periodico

Il censimento è un processo batch di backoffice, separato dalla richiesta
utente. Per ogni comune esegue due sweep logici:

```text
Sweep ordinary_data
  → identifica piattaforma dati ordinari
  → misura piattaforma/AgID
  → misura comune/piattaforma
  → aggiorna capability e manifest

Sweep transparency
  → identifica piattaforma AT
  → misura piattaforma/AgID per AT
  → misura comune/piattaforma per AT
  → aggiorna capability e manifest
```

Ogni esecuzione è registrata:

```json
{
  "measurement_id": "run-2026-08-20-001",
  "scope": "all_italian_municipalities",
  "started_at": "2026-08-20T01:00:00Z",
  "finished_at": "2026-08-20T02:30:00Z",
  "software_version": "v1-dev",
  "agid_model_version": "1",
  "status": "completed",
  "counts": {
    "municipalities": 7896,
    "ordinary_completed": 7896,
    "transparency_completed": 7896,
    "drifts": 24,
    "failures": 31
  }
}
```

Il salvataggio è incrementale e riprendibile. Un'interruzione non invalida gli
snapshot precedenti e non pubblica risultati parziali come se fossero completi.
Ogni snapshot porta il riferimento alla rilevazione che lo ha prodotto.

Regole operative:

- limite di frequenza per host;
- concorrenza globale e per host separate;
- checkpoint periodici;
- retry solo per errori transitori;
- aggiornamento del manifest solo dopo verifica completa;
- snapshot precedente mantenuto fino alla validazione del nuovo;
- alert su drift improvvisi della stessa piattaforma;
- nessuna scansione duplicata se lo snapshot è ancora fresco.

Il primo scheduler resta intenzionalmente semplice: processo pianificato più
registro delle rilevazioni e lock. Una coda distribuita entrerà in discussione
solo quando l'OCR o l'analisi documentale renderanno il carico realmente
asincrono e separabile.

### Regole di `access_mode`

La modalità appartiene a ogni risultato di capability (`DataBatch`), non è una
proprietà unica e immutabile del comune.

| Modalità | Condizioni |
| --- | --- |
| `direct` | piattaforma riconosciuta, capability verificata, contratto standard REST/feed compatibile AgID e nessuna discovery o euristica custom necessaria per il retrieve |
| `mediated` | piattaforma riconosciuta, ma il retrieve richiede adapter specifico, endpoint proprietari, trasformazioni custom o navigazione controllata |
| `indirect` | piattaforma assente/non riconosciuta, fonte solo HTML libero, ricerca web o scraping euristico |
| `unavailable` | fonte irraggiungibile, capability non esposta, documento illeggibile o nessun percorso autorizzato |

Esempi:

```text
REST AgID con schema verificato
  → direct

Municipium riconosciuto con parser e percorso vendor-specifico
  → mediated

Comune senza piattaforma identificabile, pagina trovata via scraping
  → indirect

AT presente ma non raggiungibile o non interpretabile
  → unavailable
```

La presenza di un adapter non implica automaticamente `mediated`: un adapter
può implementare il contratto standard di una piattaforma e restituire
`direct`. Diventa `mediated` quando deve compensare l'assenza o la deviazione
dal contratto standard.

La modalità è determinata dal backoffice e trasmessa al motore chat come dato
immutabile del risultato. Il modello linguistico non può modificarla.

### `DataRequest` verso l'adapter

Il planner invia una richiesta limitata e già validata:

```json
{
  "request_id": "uuid",
  "source_id": "comune-058003",
  "surface": "ordinary_data",
  "capability": "services",
  "selection": {"topic": "mensa_scolastica", "canonical_ids": []},
  "filters": {},
  "freshness": {"max_age_seconds": 604800, "allow_live": true},
  "limits": {"max_records": 20, "max_documents": 5, "max_bytes": 10485760},
  "manifest_revision": 12
}
```

L'adapter non può allargare autonomamente lo scope, interrogare la seconda
piattaforma del comune o ignorare i limiti. Per una capability diversa riceve
un nuovo `DataRequest`.

### `DataBatch` dall'adapter

```json
{
  "request_id": "uuid",
  "status": "fulfilled",
  "access_mode": "direct",
  "source_id": "comune-058003",
  "surface": "ordinary_data",
  "capability": "services",
  "records": [],
  "evidence": [],
  "freshness": {"status": "fresh", "retrieved_at": "2026-08-20T12:00:00Z"},
  "limitations": [],
  "transport": {"requests": 2, "bytes": 38120, "from_cache": false},
  "connector": {"name": "wordpress_agid", "version": "1.0"}
}
```

Gli errori non vengono trasformati in lista vuota:

```text
invalid_manifest | unsupported_capability | host_not_allowed |
rate_limited | timeout | http_error | invalid_payload |
schema_drift | parse_error | document_unreadable | budget_exceeded
```

Ogni errore mantiene `request_id`, fonte, capability e fase del fallimento. Il
planner decide se usare cache, fallback, un altro adapter o `unavailable`;
l'adapter dichiara soltanto il fatto tecnico.

Invarianti:

- stesso manifest, richiesta e fonte producono lo stesso contenuto normalizzato;
- nessun record senza identificatore canonico o evidenza minima;
- nessun risultato fuori dalla capability richiesta;
- nessun errore mascherato da `fulfilled`;
- nessuna prosa e nessuna chiamata alla chat o al modello dall'adapter.

### Contratto del motore chat

Il motore chat riceve un `DataBatch` e lo proietta in una risposta, senza
conoscere piattaforma, vendor, URL interne o parser:

```json
{
  "intent": "find_service",
  "records": [],
  "facts": [],
  "access": {
    "mode": "direct",
    "label": "letto direttamente dalla fonte",
    "freshness": "fresh"
  },
  "evidence": [],
  "limitations": [],
  "status": "fulfilled"
}
```

Il renderer determina in modo stabile:

```text
DataBatch
  → risposta strutturata
  → card/link/fonte
  → eventuale chiarimento
  → testo deterministico
```

Il motore chat può mostrare all'utente soltanto una descrizione breve della
modalità di accesso (`diretto`, `mediato`, `indiretto` o `non disponibile`) e la
data di lettura. Non mostra il report AGID, il numero di richieste, il vendor,
le regole custom o il punteggio di compatibilità.

Regole:

- `fulfilled` con record vuoti non diventa automaticamente “nessun dato
  esistente”;
- `unavailable` non diventa “nessun servizio disponibile”;
- una limitation rilevante deve arrivare nella risposta strutturata;
- ogni valore fattuale esposto deve avere almeno un'evidenza;
- il renderer non chiama connettori e non invoca il modello;
- l'SLM, se usato per rendere più naturale la frase, non può modificare valori,
  modalità di accesso, stato o evidenze.

### Politica di chiarimento

Il motore distingue tre casi:

```text
required_missing
  manca un dato indispensabile per costruire il piano
  → chiedere chiarimento, non interrogare fonti a caso

optional_missing
  manca un filtro utile ma non indispensabile
  → eseguire la ricerca e dichiarare il perimetro

data_missing
  il piano è completo ma la fonte non espone il dato
  → eseguire e restituire unavailable/limitation
```

Esempi:

```text
“Quali sono gli orari?” senza comune
  → required_missing: chiedere quale comune

“Quali sono gli orari dell’anagrafe di Albano?” senza giorno specifico
  → optional_missing: cercare gli orari ordinari

Comune identificato, piattaforma leggibile, nessun orario pubblicato
  → data_missing: risposta unavailable per gli orari
```

Una domanda di chiarimento deve essere un oggetto strutturato:

```json
{
  "code": "municipality_required",
  "slot": "municipality",
  "prompt_key": "ask_municipality",
  "blocking": true,
  "accepted_inputs": ["municipality_name", "istat_code"]
}
```

Il testo mostrato all'utente viene poi scelto dal renderer. Il codice di
chiarimento resta stabile per permettere al turno successivo di produrre
`ANSWER_PENDING_QUESTION` senza rileggere liberamente la conversazione.

### Risposta parziale

Una risposta parziale è ammessa quando:

- il piano ha almeno una capability completata;
- i dati mancanti sono non bloccanti;
- ogni risultato è marcato con il proprio stato;
- non viene presentata una lista parziale come esaustiva.

Una risposta non è ammessa quando:

- manca lo scope obbligatorio;
- il piano è ambiguo su due intent incompatibili;
- la fonte restituisce dati non validabili;
- l'unico risultato deriva da scraping non verificabile per una decisione
  fattuale sensibile.

### Contratto di freschezza

La freschezza è valutata per capability e per superficie, non con una soglia
unica per tutto il comune.

```text
fresh       entro la soglia prevista dalla capability
stale       oltre soglia, ma ancora disponibile nel catalogo
live        letto durante la richiesta corrente
unknown     data di lettura assente o non affidabile
invalid     fonte cambiata o risultato non più verificabile
```

Policy iniziali indicative:

```text
opening_hours       24 ore
public_notices      8 ore
services            7 giorni
offices             7 giorni
documents           30 giorni, con controllo hash quando possibile
platform_manifest   14 giorni
```

Le soglie saranno configurabili per capability, ma sempre versionate nel
`QueryPlan`. Non possono essere modificate dall'SLM.

Regole di esecuzione:

- dato `fresh` → usare il catalogo;
- dato `stale` e capability verificabile live → tentare refresh;
- dato `stale` senza refresh possibile → restituire il dato marcato stale,
  senza chiamarlo aggiornato;
- richiesta esplicita “controlla ora” → preferire live anche entro soglia;
- hash invariato → aggiornare `retrieved_at` solo secondo la policy, senza
  creare una falsa nuova versione del contenuto;
- hash cambiato → creare nuova versione e invalidare le evidenze obsolete;
- data assente → `unknown`, mai `fresh` per default.

La chat mostra soltanto la data o un'etichetta breve quando serve, per esempio
“verificato oggi” oppure “ultimo aggiornamento: 12 agosto”. Il dettaglio della
policy resta nel catalogo e nel trace interno.

### Primo contratto tecnico implementabile

Il contratto può essere introdotto senza modificare v0 nei nuovi moduli:

```text
api/treasureiq/catalog/contracts.py
api/treasureiq/catalog/snapshots.py
api/treasureiq/catalog/registry.py
api/tests/test_catalog_contracts.py
```

Modelli strict consigliati:

```python
class Surface(str, Enum):
    ORDINARY_DATA = "ordinary_data"
    TRANSPARENCY = "transparency"

class AccessMode(str, Enum):
    DIRECT = "direct"
    MEDIATED = "mediated"
    INDIRECT = "indirect"
    UNAVAILABLE = "unavailable"

class PlatformSnapshot(BaseModel):
    platform_id: str
    surface: Surface
    vendor: str | None
    agid_model_version: str | None
    agid_compatibility: Literal["compatible", "partial", "incompatible", "unknown"]
    access_contract: AccessContract
    connector_contract: ConnectorContract | None
    fingerprint: str
    measured_at: datetime
    measurement_id: str

class MunicipalityPlatformSnapshot(BaseModel):
    municipality_istat: str
    surface: Surface
    platform_id: str | None
    base_url: AnyHttpUrl | None
    municipality_adoption: dict[str, SectionStatus]
    capabilities: dict[str, CapabilityStatus]
    access_mode: AccessMode
    fingerprint: str | None
    measured_at: datetime
    measurement_id: str
```

I modelli devono usare `extra="forbid"`, enum chiusi e validazione delle
versioni. La superficie è obbligatoria in entrambi: impedisce di confondere
un dato ordinario con un dato di Amministrazione Trasparente.

La prima integrazione sarà in shadow mode:

```text
scan v0
  ├── output attuale
  └── nuovo snapshot v1
          ↓
      confronto differenze
          ↓
      nessuna modifica alla risposta pubblica
```

Il passaggio a runtime avverrà solo dopo fixture reali per entrambe le
superfici e una matrice di parità su piattaforme già riconosciute.

### Adapter pilota: WordPress/AgID

Il primo adapter pilota è `wordpress_agid`, perché il repository possiede già
una parte della conoscenza necessaria:

- mappa della piattaforma e degli endpoint;
- lettura degli uffici;
- accesso alla superficie Amministrazione Trasparente;
- ingestione delle pagine WordPress;
- estrazione dei PDF collegati;
- fixture e test reali.

Il pilota non è una riscrittura immediata. In shadow mode incapsula le funzioni
esistenti e produce il nuovo contratto:

```text
wordpress_agid
  ├── surface=ordinary_data
  │     capability: services, offices, contacts, opening_hours
  └── surface=transparency
        capability: public_notices, documents, deadlines
```

Le due superfici restano adapter logici separati anche quando condividono
dominio e transport. Il pilota deve verificare:

1. manifest della piattaforma;
2. snapshot del comune per entrambe le superfici;
3. `direct` solo quando l'endpoint standard è realmente verificato;
4. `mediated` quando intervengono discovery o regole custom;
5. evidenze e `DataBatch` senza prosa;
6. parità con l'output v0 sui casi già coperti.

Solo dopo la parità si potrà sostituire una singola capability v0 alla volta.

### Matrice di test del pilota

La matrice minima copre entrambe le superfici e tutti gli esiti operativi:

| Caso | Superficie | Fonte | Atteso |
| --- | --- | --- | --- |
| WP AgID con REST servizi verificato | ordinaria | endpoint standard | `direct`, `fulfilled` |
| WP AgID con uffici REST ma orari in testo | ordinaria | mista | capability separate, modalità distinta |
| WP AgID con endpoint scoperto da manifest | ordinaria | adapter specifico | `mediated` |
| AT via CPT REST verificato | trasparenza | endpoint standard | `direct` |
| AT via pagine WordPress | trasparenza | fallback noto | `mediated` |
| AT con PDF collegato | trasparenza | documento | evidenza pagina/documento |
| piattaforma riconosciuta ma schema cambiato | entrambe | drift | `schema_drift`, snapshot precedente intatto |
| redirect fuori host | entrambe | trasporto | `host_not_allowed` |
| risposta vuota valida | entrambe | fonte leggibile | `empty`, mai `unavailable` |
| fonte non raggiungibile | entrambe | rete | `unavailable`, errore tracciato |
| nessuna piattaforma identificata | entrambe | HTML libero | `indirect` o `unavailable` |
| stesso hash su rilevazione successiva | entrambe | cache | nessuna nuova versione del contenuto |
| differenze tra v0 e v1 | entrambe | replay | diff esplicito, nessun cambio runtime |

Ogni caso deve verificare almeno:

```text
PlatformSnapshot
MunicipalityPlatformSnapshot
access_mode
capability status
DataBatch
evidence
freshness
error/limitation
parità con v0
```

La matrice deve avere fixture statiche per i test veloci e almeno una verifica
live controllata per ciascuna superficie. I test live non devono essere il
fondamento della suite: servono a rilevare drift e a confermare che il
transport funziona contro il portale reale.

Deliverable immediato: catalogo backoffice delle due piattaforme per comune,
misura piattaforma/AgID, misura comune/piattaforma, modalità di accesso e
selezione del connettore.

Deliverable futuro: proposta di specifica aperta, endpoint di esempio,
validator e strumento di conformance per i portali. Questi non sono parte del
perimetro runtime attuale.

## Fase 8 — accesso nazionale tramite chat

Obiettivo: rendere ricercabile tramite chat qualunque informazione disponibile,
senza classificare i comuni in una graduatoria e senza esporre per ora API
pubbliche di TIQ.

Esperienza utente:

- ricerca libera per territorio, servizio, ufficio o bando;
- risposta uniforme indipendentemente dal fornitore del portale;
- indicazione chiara della fonte;
- data di lettura e freschezza;
- distinzione tra dato disponibile e dato non pubblicato;
- link diretto alla PA;
- contatto utile per verificare i casi dubbi.

Il prodotto deve aiutare le PA a pubblicare meglio, evidenziando i gap AGID e
la dipendenza da connettori custom; non sostituisce la loro responsabilità né
crea un ranking dei comuni.

## Criteri di avanzamento

Una fase è completata solo quando:

- il contratto è documentato;
- esiste una fixture reale;
- il percorso è riproducibile;
- il fallback è esplicito;
- la suite v0 resta verde, salvo cambiamenti deliberati;
- la provenienza dei dati è visibile;
- il comportamento è verificato localmente e, quando serve, sul deployment.

## Ordine di discussione

La discussione operativa deve partire da:

1. contenuto esatto del congelamento `v0`;
2. contratto di `ConversationState`;
3. contratto di `QueryPlan`;
4. default deterministico e ruolo residuo di Ollama;
5. interfaccia universale dei connettori;
6. pipeline PDF/OCR;
7. Evidence Store;
8. prima versione dello standard aperto.
