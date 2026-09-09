# Protocollo di raccolta corpus — validazione lessico facet-variante

Stato: **DRAFT / solo disegno.** Nessun deploy, nessun logging attivato da questo
documento. Definisce schema e protocollo; la raccolta reale avviene dopo,
fuori sessione, previa base giuridica.

> **Nota GDPR (fail-safe).** In questo documento *redazione* e *minimizzazione*
> **non** equivalgono ad *anonimizzazione*. La redazione, anche aggressiva, punta
> all'anonimizzazione ma non la garantisce da sola: query rare, combinazioni di
> dettagli e placeholder contestuali possono lasciare un rischio residuo di
> re-identificazione. Finché il **DPO non conferma** per iscritto l'avvenuta
> anonimizzazione, **tutti** gli stadi — `raw`, `staging` e `corpus` — vanno
> trattati come **dati personali** e soggetti alla base giuridica (§6).

## 1. Perché

Gli assi resolve-time su `main` (ACTION IMU; VARIANT TARI domestiche/non.domestiche
e CAMBIO_RESIDENZA interno/immigrazione) sono `fail-closed` e coperti da test
**net-free sintetici**. Manca la prova che il **recogniser cittadino**
(`chat/service_key.py`: `riconosci_service_key`, `riconosci_variante`) regga su
**query reali**.

Misura del 2026-09-09 (read-only, 32 frasi distinte dai DB conversazioni dev):
0 query con variante, 0 `cambio residenza`, 1 TARI bare, 2 CIE, 29 senza key;
**0 falsi positivi variante** ma **nessun segnale reale sull'asse variante**. Il
lessico variante **non è validabile** finché non esiste un corpus reale. Questo
protocollo definisce come costruirlo in forma anonimizzata.

## 2. Principi

- **No deploy in questa fase.** Nessun logging di produzione viene acceso qui. Il
  protocollo descrive il come; l'attivazione è una decisione separata con base
  giuridica esplicita.
- **Redazione e minimizzazione** prima di qualsiasi persistenza durevole del testo
  cittadino. Il grezzo con PII diretta non entra mai nel dataset versionato. La
  redazione riduce il rischio, **non lo azzera**: nessun claim di irreversibilità.
- **Tutti gli stadi personali fino a conferma DPO.** `raw`, `staging` e `corpus`
  restano dati personali finché il DPO non certifica l'anonimizzazione.
- **Separazione netta** tra tre stadi: `raw` (transitorio, con PII diretta, mai in
  git) → `staging` (redatto, in revisione) → `corpus` (versionato, etichettato).
- **Etichettatura umana** di `service_key` e `variante`: nessuna etichetta derivata
  dall'output del recogniser stesso (sarebbe circolare e nasconderebbe gli errori).
- **Origine tracciata** per ogni record: reale / derivato-da-fonte / sintetico. La
  validazione conta solo sui record `real`.

## 3. Schema del record (`corpus`, JSONL, uno per riga)

```jsonc
{
  "id": "q_000123",                 // id opaco progressivo, non derivato dal testo
  "text": "cambio residenza, vengo da un altro comune",  // testo redatto (§5)
  "origin": "real",                 // real | derived_from_source | synthetic
  "label": {
    "service_key": "cambio_residenza",   // enum ServiceKey, oppure null (nessuna)
    "variante": "immigrazione",          // enum VarianteServizio, null, o "ambiguous"
    "azione": null                       // enum AzioneServizio o null (fuori MVP variante)
  },
  "annotation": {
    "annotators": ["A", "B"],       // iniziali/ruolo, MAI nome persona
    "agreement": true,              // doppia annotazione concorde
    "adjudicated_by": null,         // presente solo se A≠B e risolto da terzo
    "notes": "cue inter-comune esplicito"
  },
  "provenance": {
    "collected_at": "2026-09",      // COARSE: mese, mai timestamp fine
    "channel": "chat",              // canale di raccolta
    "consent_basis": "consent_v1",  // riferimento alla base giuridica (vedi §6)
    "collection_batch_id": "b_2026-09_a",  // batch/sessione di raccolta: chiave dello split (§8)
    "source_service_id": null       // per origin=derived_from_source: id servizio portale
  },
  "split": "test"                   // train | validation | test
}
```

Note di campo:
- `collection_batch_id` è un **pseudonimo di gruppo**, non un id individuale: raggruppa
  le frasi di una stessa origine di raccolta. Sopravvive alla rimozione degli
  identificativi diretti e permette di applicare lo split per fonte (§8) **dopo** la
  redazione, senza reintrodurre un identificatore di persona. La mappa
  `collection_batch_id → sessione reale` sta in un **manifest esterno** (fuori dal
  corpus versionato, accesso ristretto), cancellabile insieme al batch (§6).
- `variante: "ambiguous"` è un valore di prima classe: marca le frasi che un umano
  giudica genuinamente ambigue (es. `cambio residenza` bare). Sono i casi in cui il
  recogniser DEVE restituire `None`. Vanno annotati esplicitamente, non scartati.
- `service_key: null` marca il fuori-dominio (saluti, ISEE, orari ufficio…). Servono
  come test di specificità (il recogniser non deve inventare una key).

## 4. Pipeline di raccolta

```
[1] raccolta grezza (raw)        -> testo + PII, storage transitorio cifrato, TTL breve
        |  redazione / minimizzazione (§5)
[2] staging redatto              -> testo redatto, in coda di annotazione
        |  doppia annotazione umana + adjudication (§7)
[3] corpus versionato            -> JSONL etichettato, split assegnato (§8)
```

- Lo stadio `[1]` non esiste ancora e **non va creato senza base giuridica** (§6).
- Il testo con PII diretta (`raw`) **non transita mai** in `[2]`/`[3]` e non entra
  in git.
- Solo `[3]` è versionato. Percorso proposto: `data/corpus/variante/*.jsonl`
  (da aggiungere a tracking solo quando popolato e revisionato). Resta trattato come
  dato personale fino a conferma DPO (§6).

## 5. Redazione e minimizzazione

Obiettivo: **ridurre** il rischio di re-identificazione mantenendo il segnale
lessicale utile al recogniser. La redazione **non** garantisce l'anonimizzazione
(vedi nota GDPR in testa e §6): finché il DPO non conferma, il record resta dato
personale.

- **Redazione entità**, sostituzione con placeholder tipizzati che **preservano la
  forma** utile:
  - nomi persona → `«PERSONA»`
  - indirizzi/vie civici → `«VIA»` (preserva la struttura "da X a Y" senza il toponimo)
  - codice fiscale, email, telefono, IBAN → `«ID»`
  - comune/toponimo: **conservare la categoria, non l'istanza** quando è rilevante al
    servizio (es. "da un altro comune" resta; "da Codogno" → "da «COMUNE»"). Il segnale
    inter-comune sta nella relazione, non nel nome.
- **Nessun identificatore diretto reversibile nel record.** Se serve deduplicare (§8)
  si usa un hash con **salt casuale scartato dopo l'uso**: la mappa testo→hash non
  viene conservata.
- `collected_at` troncato al **mese**; nessun timestamp fine, nessun id di sessione
  reale nel record versionato.
- **Rischio residuo.** Anche dopo la redazione, query rare o combinazioni di dettagli
  possono restare re-identificabili. La valutazione del rischio residuo e l'eventuale
  dichiarazione di anonimizzazione competono al DPO (§6), non a questo protocollo.

## 6. Base giuridica e retention (GDPR)

Prerequisito all'accensione dello stadio `[1]` — **non soddisfatto da questo
documento**:

- **Base giuridica esplicita**: consenso informato al momento della query, oppure
  legittimo interesse documentato con DPIA. `consent_basis` nel record cita la
  versione dell'informativa.
- **Minimizzazione**: si raccoglie solo il testo della query, non metadati di
  profilazione.
- **Retention**: `raw` con PII diretta a TTL breve (es. ≤ 30 gg) e cancellazione
  garantita; oltre sopravvive solo il testo redatto.
- **Diritti dell'interessato**: procedura di cancellazione/revoca operativa **anche
  dopo il versionamento** del `corpus`. Poiché lo split usa `collection_batch_id` e un
  manifest esterno (§3, §8), una revoca si propaga eliminando il/i record del batch e
  la voce di manifest corrispondente.
- **Copie storiche in Git e backup.** Git conserva la storia dei commit e i backup
  conservano snapshot: una cancellazione dal `corpus` **non** rimuove da sola le copie
  pregresse. La cancellazione effettiva richiede procedura dedicata (riscrittura
  storia / purge backup) documentata prima di popolare il corpus versionato. È una
  ragione in più per **non versionare finché il DPO non ha valutato il rischio**.
- **Accesso** al `raw` e allo `staging` ristretto e loggato. Il `corpus`, finché il
  DPO non conferma l'anonimizzazione, resta dato personale: **non** trattarlo come
  liberamente condivisibile; accesso secondo la base giuridica e need-to-know.
- **Classificazione DPO.** Solo una valutazione del DPO può dichiarare un dataset
  anonimizzato (e quindi fuori GDPR). Fino ad allora vale il regime dati personali per
  ogni stadio.

## 7. Annotazione umana

- **Doppia annotazione cieca** (due revisori indipendenti) su `service_key` +
  `variante`. Concordanza → `agreement: true`. Disaccordo → adjudication da un terzo,
  registrato in `adjudicated_by`.
- Etichette dall'**enum del contratto** (`ServiceKey`, `VarianteServizio`,
  `AzioneServizio`), più i valori speciali `null` e `variante:"ambiguous"`.
- **Mai** etichettare con l'output del recogniser: l'annotazione è l'oracolo, il
  recogniser è l'oggetto sotto test.
- Casi guida obbligatori da coprire (dal blocker chiuso su PR #94):
  - intra-comune (via→via, appartamento→appartamento) → `variante: interno` se il cue
    è esplicito, altrimenti `ambiguous`;
  - inter-comune esplicito ("da un altro comune") → `immigrazione`;
  - estero/AIRE (`all'estero` vs `dall'estero`) → fuori MVP: `service_key` sì,
    `variante: null` (deve restare `None`);
  - TARI domestiche/non.domestiche vs bare.

## 8. Split senza leakage

- **Deduplica** near-duplicate PRIMA dello split (frasi quasi identiche non devono
  finire a cavallo di train/test).
- **Split per fonte/sessione, non per frase**: tutte le frasi di una stessa origine di
  raccolta stanno nello stesso split, per non gonfiare le metriche con parafrasi
  correlate. La chiave dello split è `collection_batch_id` (§3), pseudonimo di gruppo
  che **sopravvive alla rimozione degli identificativi diretti**: lo split resta
  applicabile dopo la redazione, senza reintrodurre un id di persona. Il legame
  batch→sessione reale vive nel **manifest esterno**, non nel corpus.
- Proporzioni indicative train/validation/test = 60/20/20; il **test è congelato** e
  non si guarda durante lo sviluppo dei marker.
- La parte `real` deve essere presente in `validation` e `test`; i record `synthetic`
  possono stare in `train` ma **non** costituiscono da soli evidenza di validazione.

## 9. Metriche di validazione (una volta popolato)

Sul solo sottoinsieme `origin: real`, split `test`:

- **Precisione quando spara**: dei record dove `riconosci_variante ≠ None`, quota con
  variante corretta. Target alto (il costo di un FULFILLED errato è il difetto chiuso
  su #94).
- **Tasso di falsi positivi variante** su record `service_key ≠ residenza/tari` e su
  `variante: ambiguous`/`null` → deve tendere a 0.
- **Copertura (recall)**: quota di query realmente variante-portanti riconosciute.
  Secondaria: la disciplina è precision-first, `None → NOT_FOUND` è sicuro.
- **Specificità service_key**: fuori-dominio (`service_key: null`) non deve produrre
  key.
- Analisi errori per famiglia (interno/immigrazione/estero/domestiche/non.domestiche).

## 10. Prossimi passi

1. (decisione separata) accendere lo stadio `[1]` con base giuridica — **fuori da
   questa sessione, richiede deploy/consenso**.
2. Fino ad allora il ciclo CIE e residenza estero/AIRE resta **bloccato sulla
   validazione reale**: si può progettare, non si può certificare la precisione.
3. Quando esiste `real` in `test`, eseguire §9 e decidere se il lessico regge.
