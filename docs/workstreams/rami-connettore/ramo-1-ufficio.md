# Ramo 1 — Ufficio

> Orari, contatti e responsabili di un ufficio comunale.
> Surface `ORDINARY_DATA` · capability `offices` + `contacts` (+ `responsible` da aggiungere).

> **Nota di lettura.** Questo documento è aggiornato allo **stato reale della Fase 3**
> (motore unico, branch `refactor/source-engine`). Ogni sezione distingue
> **① già presente in Fase 3** da **② prossimo ciclo**. Il brainstorm resta valido
> come direzione; la parte di "porting" che era descritta come da fare è, per la
> proiezione, **già realizzata** — quello che resta è estendere il *contenuto*
> (nuovi campi), non ricostruire la meccanica.

---

## 1. Brainstorm — cosa possiamo tirar fuori

Il cittadino chiede di **un ufficio** (anagrafe, tributi, edilizia, servizi
sociali…). Da una scheda-ufficio di un portale comunale si può tirar fuori:

| Dato | Oggi | Note |
|------|------|------|
| **nome ufficio** | ✅ tutti | chiave di match (`_ufficio_connettore_pertinente`) |
| **url scheda** | ✅ tutti | evidenza / fonte ricontrollabile |
| **telefoni** | ⚠️ municipium + drill on-demand | `tel:` tipizzato vs prosa (`source_typed`) |
| **email** | ⚠️ municipium + drill on-demand | `mailto:` tipizzato |
| **pec** | ⚠️ municipium + drill on-demand | distinta dalla email ordinaria |
| **orari** | ⚠️ municipium + drill on-demand | normalizzati (`OrarioSettimanale`) + verbatim come fonte (D-07) |
| **responsabile** | ❌ nessuno | nome dirigente/RASA — **buco**: nessun campo nel modello |
| indirizzo fisico / sede | ❌ | dove si trova lo sportello — **buco**: nessun campo |
| unità organizzativa padre | parziale | `aree_amministrative` cattura l'albero, non il legame ufficio→area |

### Candidati decisi (brainstorm 2026-08-22)
- **responsabile** = `{nome, ruolo?, email?}` — no RASA (estrazione fragile).
- **indirizzo/sede** = sì, campo dedicato ("dove vado di persona").
- **appuntamento**: link prenotazione → territorio SP (Ramo 3), fuori da qui.
- **orari**: doppio binario forma-normalizzata + verbatim, sempre (D-07).

---

## 2. Contratto comune universale

**Scoperta chiave (confermata in Fase 3)**: `EsitoConnettore.uffici:
list[UfficioConnettore]` è **la forma comune** — tutti i reader v0 di piattaforma
la producono identica. Non servono 6/7 adapter: serve **una proiezione**
`EsitoConnettore → DataBatch`, generica su tutte le piattaforme.

### ① Già presente in Fase 3 — la proiezione unica ESISTE

La proiezione generica **non è più un TODO**: vive in
`api/treasureiq/catalog/flotta/_projection.py` (funzioni pure `records` /
`access_mode` / `evidence` / `freshness` / `status`) ed è consumata da
`_base.py` (`FlottaBaseConnettore.retrieve`). È **condivisa dall'intera flotta**
per contratto: legge `EsitoConnettore`, non una piattaforma — quindi Municipium,
ComWeb, PeopleWeb, OpenWeb, OpenPA, eGov e HGate proiettano tutti con lo stesso
codice. `retrieve()` **proietta soltanto** l'`esito` già acquisito da
`leggi_connettore` (mai un re-fetch).

Forma reale della proiezione oggi:

```python
# _projection.records(surface, capability, esito)
ORDINARY_DATA · "offices"  → [office.model_dump() for office in esito.uffici]
ORDINARY_DATA · "contacts" → [{nome,url,telefoni,email,pec} …se ha almeno un recapito]
TRANSPARENCY  · "transparency" → [esito.amministrazione_trasparente] (Ramo 2)
```

> ⚠️ Correzione: il riferimento a `wordpress_agid._records` come "unica proiezione,
> da rendere generica" era **superato**. `wordpress_agid` è un **bridge esplicito**
> per quattro platform ID WordPress (`wordpress_agid`, `wp_design_comuni`,
> `wordpress_generico`, `comunibootstrapitalia`), con proprie capability — non la
> sede della proiezione di flotta. Il fallback wildcard è `web_scrape`
> (`platforms=("*",)`).

### Forma attuale `UfficioConnettore` (② manca ancora l'estensione)

```python
UfficioConnettore {
  nome: str
  url: str
  telefoni: list[str]
  email: list[str]
  pec: list[str]
  orari: str | None
  source_typed: bool     # recapito tipizzato (tel:/mailto:) vs prosa — provenienza, non qualità
  letto_il: str
}
# indirizzo e responsabile NON esistono ancora nel modello.
```

### ② Prossimo ciclo — estensione DECISA (sblocca "responsabili" + "dove vado")

```python
UfficioConnettore {
  ...campi attuali...
  indirizzo: str | None                # NUOVO — sede fisica, "dove vado di persona"
  responsabile: Responsabile | None    # NUOVO — accountability
}

Responsabile {
  nome: str
  ruolo: str | None      # "Dirigente", "Responsabile del procedimento"…
  email: str | None      # contatto diretto quando pubblicato
}
```

Regola dura (D-05/D-07): campo assente → riga onesta «non pubblicato», mai
omesso in silenzio, mai inferito da un LLM. `indirizzo`/`responsabile`
best-effort: dove la scheda li pubblica strutturati, altrimenti `None`.

**I nuovi campi devono attraversare i tre livelli separati** (vincolo
architetturale): Acquisizione (`leggi_*` → `EsitoConnettore`) → Proiezione
(`_projection.records`) → Arricchimento on-demand. Mai iniettare un campo
direttamente in chat scavalcando `EsitoConnettore`.

### Mappatura sul contratto v1 (stato reale)

| capability | Surface | records da `EsitoConnettore` | AccessMode | Stato |
|------------|---------|------------------------------|------------|-------|
| `offices` | ORDINARY_DATA | `uffici[]` (dump completo — porta anche `indirizzo`+`responsabile`) | **MEDIATED se record, UNAVAILABLE se no** | ① in Fase 3 |
| `contacts` | ORDINARY_DATA | `uffici[]` → {nome,url,telefoni,email,pec,**indirizzo**} — gate sui recapiti telematici, indirizzo supplementare | **MEDIATED se record, UNAVAILABLE se no** | ① proiezione estesa |
| `responsible` | ORDINARY_DATA | `uffici[]` → {nome, responsabile} | come sopra | ② nuova capability |

> `offices` porta `indirizzo`/`responsabile` **gratis** (dump completo del
> modello). `contacts` include `indirizzo` (canale fisico) ma **non**
> `responsabile`: l'accountability avrà la capability dedicata `responsible`.
> Il gate `contacts` resta sui recapiti telematici — l'indirizzo da solo non
> basta a far comparire un ufficio fra i contatti.

> ⚠️ Correzione AccessMode: non è "DIRECT se REST / MEDIATED se scrape". Queste
> piattaforme espongono dati strutturati **solo** via connettore HTML dedicato,
> mai un campo REST tipizzato → **DIRECT è irraggiungibile**. `_projection.access_mode`
> ritorna **MEDIATED** se la proiezione produce record, **UNAVAILABLE** se vuota
> (allineato al v0: `uffici` vuoto = "non servito"). `source_typed` è
> **provenienza del recapito** (tel:/mailto: vs prosa), **non** determina l'AccessMode.

---

## 3. Porting — stato reale dei connettori

**7 piattaforme** × 2 surface = **14 unità versionate** (Base + Trasparenza),
più il **bridge WordPress esplicito** per quattro platform ID (`wordpress_agid`,
`wp_design_comuni`, `wordpress_generico`, `comunibootstrapitalia`) — connettore
multi-platform con proprie capability, **non** un wildcard. Il fallback wildcard
è `web_scrape` (`platforms=("*",)`). HGate è una piattaforma **distinta**
(`HGateBaseConnettore`, `platform_id="hgate"`) ma **colocata nel modulo `egov`**
perché condivide il reader v0 (`leggi_egov` → `_leggi_uffici_egov`).

`FlottaBaseConnettore` fissa `surface=ORDINARY_DATA`,
`capabilities={"offices","contacts"}`; le classi foglia fissano solo
`platform_id`/`name`/`version` (isolamento I2: bump di versione = una riga nel
modulo di quella piattaforma).

Cosa riempie **oggi** ciascuna piattaforma per il ramo Ufficio (contenuto
dell'`EsitoConnettore.uffici`, a monte della proiezione):

| Piattaforma | uffici | tel/email/pec | orari | responsabile | source_typed | Livello |
|-------------|--------|---------------|-------|--------------|--------------|---------|
| **municipium** | scheda per-ufficio letta | ✅ popolati | ✅ | ❌ | true se recapiti | **pieno** |
| **egov** | indice statico nome+url | ❌ (deferred on-demand) | ❌ | ❌ | false | indice |
| **hgate** | indice (reader eGov condiviso) | ❌ (deferred on-demand) | ❌ | ❌ | false | indice |
| **openweb** | indice uffici | da verificare | da verificare | ❌ | ? | indice |
| **comweb** | indice uffici | da verificare | da verificare | ❌ | ? | indice |
| **openpa** | indice uffici | da verificare | da verificare | ❌ | ? | indice |
| **peopleweb** | ancore → nome+url | ❌ (solo ancore) | ❌ | ❌ | false | indice |

**Asimmetria da sanare**: solo municipium legge la scheda per-ufficio (recapiti
tipizzati + orari) **allo sweep**. Gli altri fermano all'indice; i recapiti
vivono sulle schede individuali, lette **on-demand** — ma questo drill **è ancora
legacy** (vedi sotto), non passa dal contratto v1.

### ① Già fatto in Fase 3
- Proiezione generica unica (`_projection.py`) — non serve un adapter per famiglia.
- 14 unità registrate, isolate (I2), con `ConnectorRef(name, version)` per unità.
- Gating AccessMode deterministico (MEDIATED/UNAVAILABLE) nel `retrieve`.

### ✅ Fatto nel ciclo estensione
1. **Modello** `UfficioConnettore` (+`indirizzo`, +`responsabile`) + `Responsabile`
   (`nome` `min_length=1`, `ruolo`/`email` opzionali) + mirror TS. Additivi, default
   `None`, JSON legacy deserializzati senza migrazione. Review contratto: APPROVE.
2. **Proiezione** `_projection.records` estesa: `offices` porta i due campi via dump
   completo; `contacts` aggiunge `indirizzo` (gate recapiti invariato). Un solo punto
   toccato, non 7 adapter.

### ② Prossimo ciclo — cosa resta
3. **Capability `responsible`** — aggiunta a `FlottaBaseConnettore.capabilities`,
   manifest, planner (`_CAPABILITY_BY_TOPIC`), test. **Solo quando** almeno una
   piattaforma produce dati reali (altrimenti capability sempre UNAVAILABLE = rumore).
4. **Estrazione per famiglia** di `indirizzo`/`responsabile` (best-effort, degrado onesto).
5. **Migrazione drill on-demand a v1**: oggi `_office_da_ufficio_nominato` →
   `leggi_connettore` + `leggi_orari_ufficio` è **ancora legacy** (chiamata diretta
   al reader v0, non un `DataRequest`/`DataBatch`). Va portato sul contratto v1 e
   generalizzato oltre municipium.
6. **Rendering UX/chat** — per ultimo, quando i campi arrivano dal `DataBatch`.

---

## 4. Censimento da completare

- Verificare tel/email/pec/orari per openweb/comweb/openpa (celle "da verificare").
- Estrazione `responsabile`/`indirizzo` per famiglia — quali portali li pubblicano struttura.
- Coda lunga piattaforme senza connettore (~31% comuni): fuori scope, ripiego URP.

---

## Decisioni chiuse (brainstorm 2026-08-22)

1. **`responsabile`** = `{nome, ruolo?, email?}`. No RASA (estrazione fragile).
2. **`indirizzo`** = sì, campo dentro il Ramo 1.
3. **Proiezione generica unica** — ✅ **già realizzata** in Fase 3 (`_projection.py`),
   condivisa dall'intera flotta. Il "porting" della meccanica è chiuso.
4. **Drill on-demand generalizzato** — sì, ma è ② prossimo ciclo: oggi è legacy v0.

## Prossimo passo → estensione (non ricostruzione)

Ordine di lavoro, per livelli separati:
1. Estendere modello `UfficioConnettore` (+`indirizzo`, +`responsabile`) + mirror TS.
2. Estendere `_projection.records` per `offices`/`contacts` con i nuovi campi.
3. Aggiungere capability `responsible` **solo** quando ≥1 piattaforma dà dati reali.
4. Estrazione `indirizzo`/`responsabile` per famiglia (best-effort, degrado onesto).
5. Migrare il drill on-demand su `DataRequest`/`DataBatch` e generalizzarlo.
6. Rendering UX/chat per ultimo.
