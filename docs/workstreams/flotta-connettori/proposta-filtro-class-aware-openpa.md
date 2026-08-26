# Filtro class-aware per il connettore OpenPA

**Stato:** due strati, entrambi OpenPA-local, recogniser condiviso **intatto**.
1. **Allow-list di classe** (`_CLASSI_AMMESSE`) — già su `main` (commit b2455d4).
2. **Filtro titolo/classe** (filtro-2) — questa PR, branch `feat/openpa-filtro-titolo-classe`.
   Vedi la sezione [«Filtro-2»](#filtro-2--stoplist-detrito--priorità-classe) in fondo.

**Origine:** campione read-only 28 comuni OpenPA (2026-08-26), Fase B.
**Vincolo:** nessuno sweep live aggiuntivo, nessun deploy, nessun aggiornamento del
catalogo finché PR + suite + review non sono verdi.

## Problema

La query eZ Find del connettore (`costruisci_query_ezfind`, `q = '<term>' and limit 20`)
**non filtra per `classIdentifier`** — e non deve, per non perdere recall (TARI vive in
`document`, non `public_service`). Su un campione di 28 comuni × 6 ServiceKey (168 query
production-faithful, limit=20):

- **solo 21/168 confermati (12,5%)**; esito dominante **ambiguo 124/168 (73,8%)**;
- dei 772 candidati che il recogniser mappa a una key, **`document` (244) e `article` (110)
  superano `public_service` (121)**: documenti e notizie contengono le keyword del servizio e
  affollano il set, facendo scattare il rifiuto per ambiguità (invariante I-1, esattamente-1);
- anche quando il gate scatta, **solo 10/21 confermati puntano a un servizio reale**; 3 puntano
  a **notizie** (destinazione sbagliata: San Prisco/TARI, Sorso+Pantelleria/carta).

## Policy effettiva (implementata)

Allow-list per `classIdentifier` applicata ai candidati **PRIMA** del gate host/recogniser e
del gate esattamente-1. **Per-key ma uniforme** sulle 6 chiavi:

| ServiceKey | classi ammesse |
|---|---|
| CARTA_IDENTITA, CAMBIO_RESIDENZA, ACCESSO_ATTI, STATO_CIVILE | `public_service`, `document`, `output` |
| TRIBUTI_IMU, TRIBUTI_TARI | `public_service`, `document`, `output` |

Escluse (prima del gate 0/≥2): `article` (notizie), `channel`, `organization`, e **tutte** le
classi non elencate (media, `topic`, `place`, …). Un candidato senza `classIdentifier`
(`native_class` = `None`) non è in allow-list → scartato: un hit non classificabile non è un
servizio confermato.

**Perché uniforme e non `public_service` secco per l'anagrafe.** `document`/`output` sono
ammessi su tutte e sei perché su OpenPA non solo i tributi ma anche parte di anagrafe/atti
vivono lì (regolamenti, moduli, nodi *«cosa puoi richiedere»* — es. ACCESSO_ATTI: San Prisco in
`document`, Paceco in `online_contact_point`). Un filtro `public_service`-only ucciderebbe
quei confermati veri. La mappa resta **per-key** (non un set globale) così una chiave può
divergere in futuro senza allargare le altre.

**IMU/TARI restano strutturalmente più deboli.** Il rumore nei tributi vive proprio in
`document`/`output` (regolamenti, moduli, avvisi) e **non è separabile per classe**: l'allow-list
lo *contiene*, non lo *risolve*. Sul campione TARI/IMU si muovono poco (vedi sotto). Resta un
problema a parte (matching sul titolo o accettazione della debolezza), non chiuso da questo filtro.

## Controfattuale misurato — ⚠️ variante per-key, non uniforme

Il controfattuale sotto è stato misurato in Fase B sotto una **variante più restrittiva**
(anagrafe/atti → `public_service` **secco**; tributi → `public_service|document|output`). La
policy implementata è **uniforme** e quindi **più permissiva sull'anagrafe** (aggiunge
`document|output` a carta/residenza/atti/stato civile): la resa reale sarà **≥** questi numeri,
non <. Non è stato rimisurato in live (nessuno sweep nazionale consentito in questa fase).

| ServiceKey | conf. oggi | conf. filtro (variante per-key) | Δ |
|---|---|---|---|
| CAMBIO_RESIDENZA | 1 | 19 | +18 |
| ACCESSO_ATTI | 4 | 12 | +8 |
| CARTA_IDENTITA | 4 | 11 | +7 |
| STATO_CIVILE | 6 | 12 | +6 |
| TRIBUTI_TARI | 3 | 6 | +3 |
| TRIBUTI_IMU | 3 | 4 | +1 |
| **TOTALE** | **21 (12,5%)** | **64 (38%)** | **+43** |

Effetti: la resa **triplica**; i confermati-notizia **spariscono** (article fuori allow-list).
I `vuoto` che crescono sono NOT_FOUND onesti (nessun servizio in classe ammessa). Il filtro può
solo **restringere** i candidati → non introduce falsi confermati; al più aumenta i `vuoto`.

## Implementazione

Il filtro è **interno al connettore OpenPA**: nessun impatto su contratti pubblici, manifest o
altri connettori.

- **`ServiceCandidate`** (`service_connectors/base.py`): nuovo campo opzionale
  `native_class: str | None = None`. Le famiglie senza classe nativa (WP, ComWeb) lo lasciano
  `None` → nessun filtro le tocca.
- **`_ServiceConnectorBase.retrieve`** (`connettore_base.py`): nuovo hook
  `_filtra_candidati(candidati, service_key)` chiamato **tra** la discovery e `_confermati`
  (host + recogniser), quindi prima del gate 0/≥2. Default **no-op**: gli altri connettori
  restano invariati.
- **`OpenPAServiceConnector`** (`openpa_service.py`): la costante `_CLASSI_AMMESSE` (allow-list
  per-key) e l'override di `_filtra_candidati` che tiene solo i candidati la cui `native_class`
  è ammessa per la key. `candidato_da_hit_ezfind` estrae ora `classIdentifier` dall'hit eZ e lo
  porta sul candidato.
- La **query** eZ Find resta invariata (nessun `classes [...]`): il filtro è post-fetch, così la
  recall non cala.

**Test fixture-driven** (`tests/test_openpa_service_connector.py`):
`test_filtro_esclude_articolo_notizia` (articolo escluso → NOT_FOUND);
`test_filtro_risolve_ambiguita_tra_servizio_e_notizia` (article scartato → esattamente 1 →
FULFILLED sul public_service); `test_filtro_mantiene_servizio_valido` e
`test_filtro_mantiene_document_per_tributi` (servizio/document validi mantenuti);
`test_filtro_zero_candidati_ammessi_not_found` (solo classi escluse/assenti → NOT_FOUND onesto);
`test_allow_list_copre_le_sei_chiavi_e_esclude_le_classi_giuste` (guardia sulla policy).

## Rischi e limiti

- **`native_class` sempre presente negli hit reali?** Nel campione sì, sempre valorizzato. Un
  hit senza classe viene scartato (conservativo): un candidato non classificabile non è un
  servizio. Rischio: perdere un raro servizio senza classe — accettato come restrizione onesta.
- **IMU/TARI**: la debolezza è strutturale (rumore in `document`/`output`), non chiusa qui.
- **Numeri non rimisurati sotto la policy uniforme**: da confermare a valle, sullo sweep dei
  ~363 OpenPA, quando (e se) autorizzato — non in questa fase.

## Prossimo passo (fuori da questa PR)

Con la PR verde e mergiata, valutare lo sweep dei ~363 comuni OpenPA per rimisurare la resa reale
sotto la policy uniforme. Nessun run nazionale finché non esplicitamente autorizzato.

## Artefatti campione

`scratchpad/openpa_campione/`: `manifest.json`
(sha256 `db996829b889aaf39cc531aa1a492d223a9c4160da200e57c216639dd5208d5d`),
`results.json`, `openpa_campione.sqlite3`, `report-fase-b.md`, `build_manifest.py`, `collect.py`.

---

## Filtro-2 — stoplist detrito + priorità classe

**Problema residuo dopo l'allow-list.** Con la sola allow-list di classe, il replay
offline sulla baseline congelata (`baseline_results.LOCKED.json`, md5 `92187dd9…`,
168 query, zero rete) dà **39/168 confermati** ma **96 ambigui**: 13–20 comuni per
chiave hanno ≥2 titoli class-ammessi che il recogniser condiviso matcha, quindi il
gate esattamente-1 (I-1) cade su NOT_FOUND. Il rumore è quasi tutto **detrito
amministrativo in `document`** (regolamenti, delibere, determine, tariffe, aliquote,
ruoli, registri) più due over-match egregi del recogniser (`residenza taxi`,
`Registro di accesso agli atti`). Non è separabile per classe: `document` va tenuto
(la TARI legittima vive lì), il taglio va fatto sul **titolo**.

**Design — 3 layer OpenPA-local, `riconosci_service_key` NON toccato.**
Tutto vive in `_filtra_candidati` di `OpenPAServiceConnector`; base e recogniser
restano invariati (blast radius zero fuori dal connettore).

| Layer | Cosa fa | Simbolo |
|---|---|---|
| 0 | marcatore negativo per-chiave dominio-sbagliato (`taxi` per anagrafe) — **incondizionale** | `_MARCATORI_NEGATIVI` |
| B | detrito amministrativo (regolamenti/delibere/determine/tariffe/registri) — **incondizionale, anche a match unico** | `_STOPLIST_DETRITO`, `_DETRITO_RX`, `_e_detrito` |
| — | **short-circuit `len(non_detrito) <= 1`**: 0 → NOT_FOUND onesto, 1 → confermato dal gate; salta solo il Layer A | — |
| A | priorità classe: fra i **≥2** non-detrito, se sopravvive **un solo** `public_service` vince su document/output | — |

Ordine: **neg → B (incondizionale) → short-circuit ≤1 → A**. Se dopo A restano 0 o
≥2 `public_service` non-detrito, resta **ambiguo** → NOT_FOUND (I-1): il filtro non
inventa un vincitore.

> **Revisione (review PR #37).** La prima stesura applicava il detrito **solo** in
> presenza di ≥2 match (short-circuit prima del Layer B): un `Regolamento`/`Registro`
> **solitario** passava comunque. Il falso positivo era coperto solo nel contesto del
> replay, non come invariante. Corretto: il detrito è **incondizionale**, quindi
> «detrito solitario → NOT_FOUND» è ora una proprietà del connettore, con test
> dedicato. Costo: 6 confermati-di-controllo erano `Regolamento` solitari — falsi
> positivi, non servizi veri — ora onestamente NOT_FOUND.
>
> Inoltre `accertament` è stato **rimosso** dalla stoplist: è polisemico
> («avviso di accertamento» = atto, ma «rateizzazione / riesame / autotutela
> accertamento» = servizi veri e frequenti). La substring li uccideva insieme; il
> rischio di rimuovere servizi tributari legittimi supera il guadagno. Verificato:
> **0** confermati contengono «accertament» (nessun FP introdotto dalla rimozione).

**Risultato replay (offline, baseline congelata):**

| | confermati | ambiguo | vuoto |
|---|---|---|---|
| control (solo allow-list, = `main`) | 39 | 96 | 33 |
| **filtro-2** | **84** | 42 | 42 |

Scomposizione degli 84: **33 veri-servizio** già confermati dal controllo e rimasti
invarianti (stesso `native_id`, test golden caso per caso) + **51 nuovi** recuperati
dalla disambiguazione a ≥2. **0 regressioni vere** (nessun servizio non-detrito
perso) e **0 falsi positivi netti**.

### Conteggi: da 90 (prima stesura) a 84 (dopo review)

La prima stesura riportava **90** confermati. La review ha mostrato che **6** di
quei confermati erano `Regolamento …` **solitari**, passati perché il detrito
agiva solo a ≥2: falsi positivi, non servizi veri. Con il detrito incondizionale
diventano NOT_FOUND → **84**, tutti servizi reali. La precisione migliora (6 FP
rimossi), la recall dei servizi veri è invariata (i 51 nuovi non cambiano).

I 6 droppati (tutti `Regolamento`): Chianocco/TARI, Pantelleria/ACCESSO_ATTI,
Pantelleria/IMU, Bolzano/IMU, Storo/TARI, Verona/TARI. Verificato con
`_e_detrito`: tutti detrito, nessun servizio vero fra loro.

> Nota storica sui numeri precedenti: una misura ancora anteriore dava **91** con 2
> FP egregi (Maddaloni `Registro…`, Verona `…residenza taxi`), chiusi con `registro`
> in stoplist e `taxi` nei marcatori negativi → 90. La review ha poi portato a 84.
> Numero canonico corrente = **84**.

### «Stesso dominio» è un criterio scelto, non una certezza semantica

Il Layer A assume che, tra i candidati che (a) il recogniser matcha sulla chiave e
(b) non sono detrito, l'unico `public_service` sia **la scheda-servizio**. È
un'euristica di dominio — «stesso comune, classe scheda-servizio» — **non** una prova
che il contenuto sia semanticamente quel servizio. OpenPA è mono-sito per comune (host
guard, 0 fallimenti sul campione), quindi il rischio cross-dominio è basso; ma dove
sopravvivono ≥2 `public_service` plausibili il filtro **fallisce in sicurezza** verso
NOT_FOUND anziché indovinare. È una scelta di precisione, dichiarata come tale.

### Borderline (~8) — narrow ma difendibili, da riveder e in review

Confermati «stretti»: titolo corretto sulla chiave ma sotto-servizio o modulistica,
non la scheda canonica. Nessuno è un errore di dominio; li elenco per trasparenza.

| Comune | Chiave | Classe | Titolo | URL |
|---|---|---|---|---|
| Maddaloni | STATO_CIVILE | public_service | Certificato di nascita per cittadini europei | https://www.comune.maddaloni.ce.it/Servizi/Certificato-di-nascita-per-cittadini-europei |
| Sorso | STATO_CIVILE | public_service | Certificato di nascita per cittadini europei | https://www.comune.sorso.ss.it/Servizi/Certificato-di-nascita-per-cittadini-europei |
| Pantelleria | STATO_CIVILE | public_service | Certificato di nascita per cittadini europei | https://www.comune.pantelleria.tp.it/Servizi/Certificato-di-nascita-per-cittadini-europei |
| Tarquinia | STATO_CIVILE | public_service | Reperibilità Stato Civile per decessi | https://www.comune.tarquinia.vt.it/Servizi/Reperibilita-Stato-Civile-per-decessi |
| Sorso | TRIBUTI_IMU | document | IMU istanza rimborso | https://www.comune.sorso.ss.it/Amministrazione/Documenti-e-dati/Modulistica/IMU-istanza-rimborso |
| Pantelleria | TRIBUTI_TARI | document | Modulistica TARI | https://www.comune.pantelleria.tp.it/Amministrazione/Documenti-e-dati/Modulistica/Modulistica-TARI |
| Verona | CAMBIO_RESIDENZA | document | Dichiarazione di trasferimento di residenza all'estero: modulo | https://www.comune.verona.it/Amministrazione/Documenti-e-dati/Modulistica/Dichiarazione-di-trasferimento-di-residenza-all-estero-modulo |
| Verona | ACCESSO_ATTI | public_service | Accesso agli atti Edilizia e Imprese | https://www.comune.verona.it/Servizi/Accesso-agli-atti-Edilizia-e-Imprese |

I tre `Certificato di nascita per cittadini europei` sono l'unica scheda-nascita
esposta da quei comuni: confermarli è ragionevole finché non compare una scheda
stato-civile più generale. `IMU istanza rimborso` / `Modulistica TARI` /
`…residenza all'estero` sono moduli reali e azionabili (per questo `modulo`/`istanza`
NON sono in stoplist), ma stretti. `Accesso agli atti Edilizia e Imprese` è
dominio-ristretto all'edilizia. Da confermare in review se la policy li accetta.

### Test (questa PR)

`tests/test_openpa_filtro_titolo_classe.py`, net-free:
- **golden 33 veri-servizio**: ogni caso resta confermato con lo stesso `native_id`;
- **stoplist**: parametrico su **ogni** termine di `_STOPLIST_DETRITO` e ogni token della regex;
- **regex `\b`**: `det`/`imp` dentro parola legittima (`Detrazione`, `Impegno civico`) NON è detrito;
- **taxi**: `residenza taxi` rimosso dalle chiavi anagrafiche; guardia sui marcatori registrati;
- **detrito solitario → NOT_FOUND** (review #1): `Regolamento TARI` da solo e
  `Registro di accesso agli atti` da solo → nessun confermato;
- **servizio vero solitario resta** (non-detrito, es. `IMU istanza rimborso`);
- **accertamento legittimo** (review #2): `_e_detrito` è `False` su
  rateizzazione/riesame/autotutela accertamento, e `accertament` non è più in stoplist;
  un servizio di accertamento solitario resta confermato;
- **priorità classe** + **due public_service veri restano ambigui** + **classi fuori allow-list scartate**.

102 test verdi (nuovi + connettore esistente); blast radius connettori/recogniser 564 verdi.
Suite completa in locale si blocca su test pre-esistenti Ollama-dipendenti (ambientale, CI autorità).
