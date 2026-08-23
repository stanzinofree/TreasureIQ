# Ramo 2 — Bandi

> Capability `notices` · Surface `TRANSPARENCY` · contratto **DA SCRIVERE**.
> Analisi 2026-08-23 (branch `analysis/rami-connettore`, dopo Ramo 1 chiuso).
> Stessa cadenza del Ramo 1: brainstorm → contratto comune → porting → censimento.

Il Ramo 2 è, nel workstream, «il buco più grande» — ma non perché manchi il
dato: perché il dato ricco **non passa dal contratto v1**. Come per gli uffici,
esiste già un rail v0 maturo (`bandi_live` + `_risposta_bandi`), e la capability
v1 (`notices`) è **dichiarata nel planner ma senza proiezione**.

---

## 1. Brainstorm — cosa possiamo già tirar fuori

A differenza del Ramo 1 (dove indirizzo/responsabile erano NET-NEW sul modello),
il modello ricco dei bandi **esiste già** ed è passato per molti cicli (KAPI 7-9,
ciclo17 documenti). Il rail v0 `bandi_live.bandi_arricchiti(istat)` ritorna:

- `BandiLiveEsito` — `esito` (`coperto_con_bandi`/`coperto_senza_bandi`/
  `non_coperto`/`comune_ignoto`), `comune_nome`, `verificato_il`, `gradino`
  (`cpt`/`pages`/`alberatura`), `tema`, `piattaforma_at`, `bandi[]`.
- `BandoArricchito` — `opportunity`, `scadenza` + `scadenza_verificata`
  (deadline SOLO se citabile, D-07), `tipo` (`agevolazione`/`concorso`/None),
  `consigliato` (ranking morbido profilo, mai verdetto), `corrisponde` (filtro
  tema conversazionale, evidenzia mai esclude), `documenti[]` (PDF linkati).

Onestà già cablata: cifre/scadenze mai passate dal verbalizzatore (D-07), testo
risposta FISSO, degrado onesto su portale irraggiungibile, I6 (niente ripiego
Albano — comune ignoto ⇒ si chiede).

### Nodi di scope da decidere (brainstorm)

1. **Finestra temporale**: il workstream elenca Ramo 2 = «aperti + **chiusi
   <90gg**». Oggi `bandi_live` legge la sezione AT e rende i bandi **attivi**;
   non c'è logica di finestra sui chiusi. I bandi chiusi vivono spesso in un
   archivio separato (o solo come PDF storici) → aggiungerli è un'ACQUISIZIONE
   nuova, non una proiezione. **Decisione**: includere i chiusi <90gg in questo
   ramo o rimandarli (contratto pronto, acquisizione dopo)?

2. **Profondità di migrazione v1**: come per il Ramo 1, due forme:
   - (A) **Migra il rail**: `_risposta_bandi` produce un `notices` DataBatch
     (in `ChatAnswer.data_batches`) mantenendo `bandi_live` come payload ricco.
     Il contratto è verificato end-to-end sulla chat (come Ramo 1).
   - (B) **Solo proiezione parallela**: `bandi_live` resta la chat, si aggiunge
     una proiezione `notices` per censimento/API senza toccare la chat.
   Ramo 1 ha scelto (A) — migrare prima, estendere poi.

3. **Naming capability**: il planner usa `notices` (`_CAPABILITY_BY_TOPIC
   = {"bandi": "notices"}`); sweep/shadow usano `public_notices`. Split da
   sanare: canonico `notices` (già nel planner), allineare sweep. Igiene di
   contratto, non una scelta di prodotto.

---

## 2. Contratto comune — lo stato reale

### ① La proiezione v1 esiste già... per `transparency`, non per `notices`

`catalog/flotta/_projection.py` proietta `amministrazione_trasparente` sotto la
capability `transparency` (indice + `BandoAT` titolo/url + `pdf_presenti`). È la
forma POVERA: indice AT, non i bandi arricchiti (niente scadenza/tipo/documenti).

```
# _projection.records(TRANSPARENCY, "transparency", esito)
#   -> [amministrazione_trasparente.model_dump()]   # indice, non i bandi ricchi
# _projection.records(TRANSPARENCY, "notices", esito)
#   -> []   # <-- NESSUN ramo: la capability notices non è proiettata
```

### ② Il gap: `notices` non ha proiezione né record shape

Il `BandoArricchito` ricco non è un campo di `EsitoConnettore` — vive solo nel
rail `bandi_live` (scansione REST separata cpt/pages/alberatura). Quindi, a
differenza del Ramo 1, la proiezione `notices` **non può leggere da `esito`**:
la sua fonte è `BandiLiveEsito`. Il contratto v1 dei bandi va costruito attorno
a quella forma, non attorno a `EsitoConnettore.amministrazione_trasparente`.

### La catena corretta (review Codex, 2026-08-23)

Il `BandiLiveEsito` che arriva a `_risposta_bandi` è **già personalizzato dalla
chat** (`consigliato`/`corrisponde`/`tema`): proiettarlo direttamente porterebbe
campi di PRESENTAZIONE nel dato canonico. La separazione corretta è:

```
acquisizione (rete/parsing/PDF/SLM)  →  bandi_live.BandiLiveEsito (neutro)
        ↓  converter puro (scarta i campi profilo-dipendenti)
snapshot canonico  →  NoticeSnapshot / NoticeRecord
        ↓
DataBatch notices
        ↓  ranking/filtro conversazionale (consigliato/corrisponde/tema)
ChatAnswer
```

Il converter legge il `BandiLiveEsito` **prima** che la chat lo ordini/filtri —
o ignora quei campi. Ranking e filtro tema restano ESCLUSIVAMENTE nella fase di
presentazione (`respond`), mai nel record canonico.

### Due contratti separati (acquisizione vs canonico)

`NoticeSnapshot` (risultato di acquisizione, compatibile con `BandiLiveEsito`):
`source_id`, `comune_nome`, `source_url`, `platform_id`, `connector_at`,
`retrieved_at`, `coverage_status`, `retrieval_stage`, `notices[]`.

**Onestà provenienza (review Codex)**: `source_url` resta `None` — `BandiLiveEsito`
non espone l'entrypoint AT; `connettore_at` è il NOME del connettore, non un URL,
e mapparlo su `source_url` produrrebbe una fonte falsa. Il nome viaggia nel campo
onesto `connector_at` (mai presentato come link); la provenienza reale è
per-record in `NoticeRecord.url` / `NoticeSource`.

`NoticeRecord` (record canonico, zero campi di presentazione):
`notice_id`, `title`, `url`, `deadline`, `deadline_verified`, `notice_type`,
`documents[]`, `source`.

### Mappatura `NoticeRecord` ← `BandoArricchito`

| NoticeRecord | da | onestà |
|---|---|---|
| `title`/`url` | `opportunity` | verbatim |
| `deadline`/`deadline_verified` | `scadenza`/`scadenza_verificata` | None se non citabile (D-07) |
| `notice_type` | `tipo` | None dove la fonte non distingue (gradini cpt/pages) |
| `documents` | `documenti[]` | vuoto ≠ inventato |
| ~~consigliato/corrisponde/tema~~ | — | ESCLUSI: presentazione, non dato |

### access_mode / status (corretto — Codex)

| coverage_status | access_mode | status | records |
|---|---|---|---|
| `coperto_con_bandi` | MEDIATED | FULFILLED | [n≥1] |
| `coperto_senza_bandi` | **MEDIATED** | **EMPTY** | [] |
| `non_coperto` | UNAVAILABLE | NOT_SUPPORTED | [] |
| `comune_ignoto` | UNAVAILABLE | NOT_SUPPORTED | [] |

**Correzione chiave**: «nessun bando pubblicato» (fonte letta, vuota) ≠ «non so
leggere il comune». Il primo è MEDIATED+EMPTY, non UNAVAILABLE — altrimenti si
confonde un'assenza reale con un buco di copertura.

**Guardia richiesta (review Codex)**: `notices_batch` rifiuta (`ValueError`) le
richieste incompatibili — `surface != TRANSPARENCY` o `capability != notices` —
così una richiesta `services`/`transparency` non genera un batch `notices` con
metadati incoerenti.

---

## 3. Porting — stato reale dei connettori

Il rail `bandi_live` è già multi-piattaforma via gradini REST (cpt/pages) +
`alberatura` (Halley `/zf/` per i concorsi, ciclo17). Non è per-famiglia come
gli estrattori ufficio: è una scala di gradini generica. Quindi il porting
Ramo 2 è meno «per vendor» e più «un connettore `notices` che avvolge la scala
esistente» — da confermare in fase contratto.

---

## 4. Censimento (slice 3, spedito 2026-08-23)

Il §4 originale (brainstorm) diceva «aggiungi `notices` a manifest+capabilities
flotta». **Corretto in fase esecuzione**: contraddice §2 e D-R2-2. I bandi NON
passano da `EsitoConnettore`/flotta (`_projection.records(TRANSPARENCY, "notices")
-> []` di proposito); nascono da `bandi_live`, e il DataBatch porta
`connector="bandi_live"`. Aggiungerli a `FLOTTA_MANIFEST` farebbe dichiarare alla
flotta una capability che risponderebbe SEMPRE con un batch vuoto — un falso
positivo, la stessa disonestà «coperto vs vuoto» che il ramo combatte.

Il censimento onesto è quindi **igiene di vocabolario**, non una proiezione flotta:

1. **Costanti al posto delle stringhe** — `_CAPABILITY_BY_TOPIC["bandi"]` usa
   `CAPABILITY_NOTICES`; `shadow.py`/`sweep_bridge.py` usano
   `CATALOG_SECTION_PUBLIC_NOTICES` (7 punti). Nessun rename, valori identici.
2. **Ponte esplicito** — `CATALOG_SECTION_TO_CAPABILITY` +
   `capability_for_section()` in `contracts.py`: `public_notices -> notices` in un
   solo posto, così un consumer del catalogo sa quale capability chat serve una
   sezione censita, senza confondere i due vocabolari (D-R2-3).
3. **Confine di onestà pinnato** — `test_notices_censimento.py` asserisce che la
   flotta NON pubblicizza `notices` e che la proiezione non ha un ramo `notices`.

I 4 punti per-connettore del memo `flotta-connettori-nazionale` (dispatch /
`_LEGGIBILI` / analytics / logo) restano per un nuovo VENDOR, non per una
capability: qui non si aggiunge un vendor.

---

## Decisioni chiuse (2026-08-23)

- **D-R2-1 finestra = solo aperti ora, contratto pronto ai chiusi.** Il record
  `notices` modella `stato` (aperto/chiuso) e `scadenza` così da accogliere i
  chiusi <90gg senza cambiare forma, ma l'ACQUISIZIONE resta sugli attivi:
  i bandi chiusi (archivio/PDF storici, spesso fuori dall'indice AT) sono una
  scoperta per-piattaforma da fare in un ciclo dedicato.
- **D-R2-2 profondità = migra il rail (A).** `_risposta_bandi` produce un
  `notices` DataBatch in `ChatAnswer.data_batches` (+ `query_plan`/
  `selected_data_batch`, come il drill del Ramo 1); `bandi_live` resta il
  payload ricco (`ChatAnswer.bandi_live`). Contratto provato end-to-end sulla
  chat. **Nota architetturale**: la fonte è `BandiLiveEsito`, NON
  `EsitoConnettore` → il DataBatch `notices` si costruisce direttamente da
  `bandi_live`, non passa per `CatalogRuntime`/flotta (che legge `esito`).
- **D-R2-3 naming = due vocabolari espliciti, NON un rename (Codex).**
  `CAPABILITY_NOTICES = "notices"` = capability del contratto chat/DataBatch;
  `CATALOG_SECTION_PUBLIC_NOTICES = "public_notices"` = sezione amministrativa
  del catalogo (sweep/shadow), già presente e mantenuta. Costanti centralizzate
  (in `catalog/contracts.py`), niente stringhe duplicate — il catalogo tiene il
  suo vocabolario senza contaminare il contratto utente.

### Piano a slice (corretto — Codex)

1. **Contratto canonico** (questo slice, NON tocca `_projection.py`):
   `NoticeSnapshot`/`NoticeRecord` + converter PURO
   `snapshot_da_bandi_live(BandiLiveEsito) -> NoticeSnapshot` (scarta i campi
   di presentazione) + builder `notices_batch(snapshot, request) -> DataBatch`
   (access_mode/status come la tabella sopra). **Golden test** sul passaggio
   `BandiLiveEsito neutro → NoticeSnapshot → DataBatch notices`: bandi aperti,
   nessun bando (MEDIATED+EMPTY), fonte non disponibile (UNAVAILABLE), scadenza
   verificata/assente, documenti linkati, gradino conservato.
2. **Wiring**: `_risposta_bandi` costruisce il DataBatch `notices` via il
   converter+builder e lo trasporta nel `ChatAnswer` (data_batches/query_plan/
   selected). Il ranking/filtro tema resta nel rail, fuori dal record.
3. **Censimento** (✅ spedito): igiene di vocabolario — costanti al posto delle
   stringhe (planner/shadow/sweep) + ponte esplicito `public_notices -> notices`
   in `contracts.py` + test che pinna il confine di onestà (la flotta NON
   pubblicizza `notices`). NON tocca `FLOTTA_MANIFEST` (vedi §4).
4. **Rendering**: già presente (rail `bandi_live`); il DataBatch è per
   censimento/API, non cambia la scheda bandi.

### Rimandato al 2° incremento

Bandi chiusi <90gg: richiede una **data strutturata** (non `deadline: str`) —
un campo normalizzato o una classificazione temporale derivata in modo
deterministico — più l'acquisizione dell'archivio storico per-piattaforma.

## Riferimenti

- Rail v0: `treasureiq/bandi_live.py`, `chat/respond.py::_risposta_bandi`.
- Proiezione v1: `catalog/flotta/_projection.py` (oggi solo transparency).
- Planner: `catalog/planner.py::_CAPABILITY_BY_TOPIC`.
- Memorie: `catena-retrieval-decisa`, `portale-halley-zf-scoperto`,
  `ciclo17-documenti-bando`, `verbalizzatore-corrompe-cifre`.
