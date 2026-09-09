# Protocollo di raccolta corpus — validazione lessico facet-variante

Stato: **DRAFT / solo disegno.** Nessun deploy, nessun logging attivato da questo
documento. Definisce schema e protocollo; la raccolta reale avviene dopo,
fuori sessione, previa base giuridica.

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
- **Pseudonimizzazione irreversibile** prima di qualsiasi persistenza durevole del
  testo cittadino. Il grezzo con PII non entra mai nel dataset versionato.
- **Separazione netta** tra tre stadi: `raw` (transitorio, con PII, mai in git) →
  `staging` (pseudonimizzato, in revisione) → `corpus` (versionato, etichettato).
- **Etichettatura umana** di `service_key` e `variante`: nessuna etichetta derivata
  dall'output del recogniser stesso (sarebbe circolare e nasconderebbe gli errori).
- **Origine tracciata** per ogni record: reale / derivato-da-fonte / sintetico. La
  validazione conta solo sui record `real`.

## 3. Schema del record (`corpus`, JSONL, uno per riga)

```jsonc
{
  "id": "q_000123",                 // id opaco progressivo, non derivato dal testo
  "text": "cambio residenza, vengo da un altro comune",  // testo pseudonimizzato
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
    "source_service_id": null       // per origin=derived_from_source: id servizio portale
  },
  "split": "test"                   // train | validation | test
}
```

Note di campo:
- `variante: "ambiguous"` è un valore di prima classe: marca le frasi che un umano
  giudica genuinamente ambigue (es. `cambio residenza` bare). Sono i casi in cui il
  recogniser DEVE restituire `None`. Vanno annotati esplicitamente, non scartati.
- `service_key: null` marca il fuori-dominio (saluti, ISEE, orari ufficio…). Servono
  come test di specificità (il recogniser non deve inventare una key).

## 4. Pipeline di raccolta

```
[1] raccolta grezza (raw)        -> testo + PII, storage transitorio cifrato, TTL breve
        |  pseudonimizzazione irreversibile (§5)
[2] staging pseudonimizzato      -> testo redatto, in coda di annotazione
        |  doppia annotazione umana + adjudication (§7)
[3] corpus versionato            -> JSONL etichettato, split assegnato (§8)
```

- Lo stadio `[1]` non esiste ancora e **non va creato senza base giuridica** (§6).
- Il testo con PII (`raw`) **non transita mai** in `[2]`/`[3]` e non entra in git.
- Solo `[3]` è versionato. Percorso proposto: `data/corpus/variante/*.jsonl`
  (da aggiungere a tracking solo quando popolato e revisionato).

## 5. Pseudonimizzazione irreversibile

Obiettivo: rendere il record non ricollegabile alla persona, mantenendo il segnale
lessicale utile al recogniser.

- **Redazione entità**, sostituzione con placeholder tipizzati che **preservano la
  forma** utile:
  - nomi persona → `«PERSONA»`
  - indirizzi/vie civici → `«VIA»` (preserva la struttura "da X a Y" senza il toponimo)
  - codice fiscale, email, telefono, IBAN → `«ID»`
  - comune/toponimo: **conservare la categoria, non l'istanza** quando è rilevante al
    servizio (es. "da un altro comune" resta; "da Codogno" → "da «COMUNE»"). Il segnale
    inter-comune sta nella relazione, non nel nome.
- **Nessun identificatore reversibile.** Se serve deduplicare (§8) si usa un hash con
  **salt casuale scartato dopo l'uso**: la mappa testo→hash non viene conservata.
- `collected_at` troncato al **mese**; nessun timestamp fine, nessun id di sessione
  reale nel record versionato.

## 6. Base giuridica e retention (GDPR)

Prerequisito all'accensione dello stadio `[1]` — **non soddisfatto da questo
documento**:

- **Base giuridica esplicita**: consenso informato al momento della query, oppure
  legittimo interesse documentato con DPIA. `consent_basis` nel record cita la
  versione dell'informativa.
- **Minimizzazione**: si raccoglie solo il testo della query, non metadati di
  profilazione.
- **Retention**: `raw` con PII a TTL breve (es. ≤ 30 gg) e cancellazione garantita;
  solo il pseudonimizzato sopravvive.
- **Diritti dell'interessato**: procedura di cancellazione. Dopo la
  pseudonimizzazione irreversibile il dato non è più personale e non è ricollegabile
  (da verificare con il DPO).
- **Accesso** al `raw` ristretto e loggato; il `corpus` versionato è condivisibile nel
  team perché privo di PII.

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
  correlate.
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
