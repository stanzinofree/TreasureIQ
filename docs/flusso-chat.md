# TreasureIQ — flusso dell'algoritmo di chat

Mappa fedele al codice (`api/treasureiq/chat/respond.py` + `intent.py` + `filtri.py`).
Legge → capisce → risolve il comune → instrada per tipo di domanda → risponde
senza mai contraddire la fonte.

```mermaid
flowchart TD
    MSG([Messaggio del cittadino]) --> NLP

    subgraph NLP["1 · Capire — due motori"]
        INT["extract_intent · LLM<br/>topic + kind + accenno comune"]
        FIL["riconosci_filtri · deterministico<br/>eta · ISEE · nucleo · figli · disabilita · stato"]
    end
    NLP --> COM

    subgraph COM["2 · Comune — mai deciso dal modello"]
        C1{"codice ISTAT scelto?"}
        C1 -- no --> C2{"parole del comune nel testo?"}
        C2 -- no --> C3["risolvi_comune<br/>contro i 7.896 su disco"]
        C1 -- si --> OK
        C2 -- si --> OK
        C3 --> AMB{">= 2 candidati<br/>col nome digitato?"}
        AMB -- si --> ASK1["_quale_comune<br/>«quale intendi?»"]:::clar
        AMB -- "1" --> OK["comune risolto"]
        AMB -- "0" --> PROF{"comune di profilo?"}
        PROF -- si --> OK
        PROF -- no --> ASK2["chiede il comune"]:::clar
    end

    OK --> SCHEDA["Scheda a sinistra<br/>logo · recapiti · servizi · uffici<br/>store se coperto · scrape live se no"]
    SCHEDA --> COV{"comune coperto?<br/>load_enti"}

    COV -- "no" --> LIVE["Premessa onesta in testa<br/>+ lettura live<br/>(mai verdetto di un altro comune)"]
    COV -- "si" --> COMP["_componi_risposta"]
    COMP --> SEED{"seed vuoto<br/>ma portale indirizzabile?"}
    SEED -- si --> LIVE
    SEED -- no --> ROUTE
    LIVE --> ROUTE

    ROUTE{"kind / topic"}

    ROUTE -- "INFORMAZIONE<br/>orari·uffici·doc" --> UFF{"_ufficio_connettore_pertinente<br/>quanti uffici combaciano?<br/>(organi politici esclusi · PR #24)"}
    UFF -- "uno" --> OR["Orari cache-first<br/>_orari_ufficio_live → altrimenti live<br/>Scheda ufficio (info.office)<br/>dump portale staccato · PR #20"]:::ok
    UFF -- "più d'uno" --> SCE["Solo i candidati che combaciano<br/>coi loro recapiti · «quale ti interessa?»<br/>mai un indovinello, D-04 · PR #24"]:::clar
    UFF -- "nessuno" --> ESP{"il portale espone<br/>gli uffici?"}
    ESP -- si --> ELE["Elenco uffici esposti<br/>«quale ufficio?»"]:::clar
    ESP -- no --> WEB["Ricerca web · M6"]
    WEB --> URP["Ripiego URP"]

    ROUTE -- "SERVIZI<br/>mappa_connettore" --> SRV["Punta il servizio<br/>servizi + 15 categorie AgID<br/>stessa cascata dell'ufficio"]:::ok

    ROUTE -- "AGEVOLAZIONE" --> AGV{"comune coperto?"}
    AGV -- si --> VER["engine · match requisiti<br/>verdetto: si / no / incerto"]:::ok
    AGV -- no --> RIF["Rifiuto onesto<br/>(niente regole altrui)"]

    ROUTE -- "BANDI" --> BND{"portale AT del comune?"}
    BND -- si --> CAT["_risposta_bandi · bandi_live<br/>bando o categorie → link PDF"]:::ok
    BND -- no --> DEG["Degrado onesto"]

    ROUTE -- "SCONOSCIUTO<br/>(ma se nomina un ufficio ed è<br/>informativa → INFORMAZIONE · PR #24)" --> SC["Chiede su cosa cercare"]:::clar

    classDef clar fill:#fff4d6,stroke:#c9922a,color:#5a4300;
    classDef ok fill:#e3f5ea,stroke:#2f9e5f,color:#134a2b;
```

## Punti che tradiscono l'intuito

| Punto | Come sembra | Come è davvero |
|---|---|---|
| Disambiguazione comune | «i più vicini a quello riconosciuto» | i comuni che **combaciano col nome digitato** (match esatto, poi parola-nel-nome). Nessuna prossimità geografica. Il comune **non lo sceglie mai il modello**. |
| Filtri personali | parte dell'NLP | motore **deterministico separato** (`riconosci_filtri`), non l'LLM. |
| Recapiti scheda | una cache | **store se coperto**, **scrape live se fuori copertura** — due sorgenti. |
| Lettura live | solo fuori copertura | scatta **anche su coperto** con seed vuoto e portale indirizzabile. |
| Ufficio non capito | subito URP | prima **elenco uffici esposti + chiedi**, poi web, **poi** URP (coda). |
| Ufficio ambiguo | dump dei 40 uffici o indovinello | **solo i candidati** che combaciano, coi loro recapiti, e sceglie il cittadino (mai un indovinello, D-04 · PR #24). Gli **organi politici** (Commissione/Giunta/Consiglio) restano fuori dal match. |
