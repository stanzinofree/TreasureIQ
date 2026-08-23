# T2 SP — piano di cablaggio SERVICE_PORTAL

Stato: proposta. Branch `perf/accumula-filtri-cache-intent-rust`, mai su main.
Prerequisito: T2 A+B fatti e approvati da Codex (`fa80e09..f8d8e5d`).

## Problema

I due plugin SP nativi — `municipium_portalegen` e `filodiretto` — sono estratti,
attivi nel registry e testati in isolamento, ma **inerti in produzione**: nessun
call site gira il registry sulla superficie `SERVICE_PORTAL`.

Oggi:
- **Discovery** (`service_discovery.discover_service_portal_candidates`) assegna
  `provider_hint` con `_provider_hint(url)` — pura euristica su sottostringhe
  dell'URL, **nessun fetch** della pagina portale. Può indovinare `filodiretto`
  dalla parola nell'URL (il segnale ambiguo che il plugin è nato per NON fidarsi),
  e non può mai produrre `municipium_portalegen` (serve la firma HTML a due segnali).
- **Confirmation** (`confirmation._confirm_one`, ramo `SERVICE_PORTAL`) fa il fetch
  della pagina ma **non riconosce**: si fida di `expected_platform` (= `provider_hint`)
  e conferma solo che l'entrypoint è vivo. Commento in codice: *"must not infer a
  new vendor from generic HTML on an authenticated portal."*

`ServicePortalCandidate` ha già i campi `platform_id` / `fingerprint` /
`recognition_status` — progettati per l'esito del riconoscimento, mai popolati.

## Vincolo Gate 0 (perché A+B si fermarono a BASE/AT)

`recognition_adapter.firma_da_registro` **rifiuta** `SERVICE_PORTAL` con `ValueError`:
gli id nativi `municipium_portalegen` / `filodiretto` non sono membri dell'enum
`Piattaforma`, e degradare a `IGNOTA` perderebbe l'identità del portale. Quindi la
seam SP **non deve passare da `Firma`/`Piattaforma`**.

## Decisione portante: registry SP native-only (no bridge, no enum)

Due strade erano aperte in `done.md`:
- (a) estendere l'enum `Piattaforma` con gli id SP + tutti i consumer;
- (b) una seam SP che restituisca il contratto senza passare da `Firma`/`Piattaforma`.

**Si va con (b).** Motivo tecnico decisivo: `build_recognition_registry` registra il
`LegacyRecognitionBridge` **anche su `SERVICE_PORTAL`** (con `includi_at=True`). Su
quella superficie il bridge è solo rumore o, peggio, dannoso:
- `filodiretto`: il classificatore legacy è cieco → `ignota`, score 0;
- `municipium_portalegen`: su una pagina portale con `container-municipium-agid`
  ma **senza** l'asset `/portalegen/plugins/`, il bridge rivendica `municipium`
  (un id **BASE**, non in `_RETIRED_TO_NATIVE`) a 0,995. Il registry restituirebbe
  un id BASE come identità di un SERVICE_PORTAL.

Un `Piattaforma("municipium_portalegen")` andrebbe comunque in `ValueError`, e
l'enum non ha ragione di crescere per due id che vivono solo su questa superficie.
La seam SP usa quindi un **registry composto dai soli plugin SP nativi**, niente
bridge: `recognize()` ritorna `portalegen` / `filodiretto` / `None`. Niente id BASE
può contaminare l'esito SP, e il "non indovinare da HTML generico" resta vero — un
registry native-only non indovina mai (firme involontarie a due segnali in AND), e
un miss è `None`, non una rivendicazione.

## La seam

Nuovo helper accanto agli altri costruttori di registry (in `recognition_bridge.py`
o modulo dedicato):

```python
def build_service_portal_registry():
    """Registry con i soli plugin SP nativi — niente bridge.
    Il bridge su SERVICE_PORTAL produce id BASE spurii (municipium) o è cieco
    (filodiretto): su questa superficie l'unica autorità sono i nativi."""
    from treasureiq.catalog.recognition_registry import RecognitionRegistry
    from treasureiq.plugins.recognition.service_portal import (
        FILODIRETTO_RECOGNITION_PLUGIN,
        MUNICIPIUM_PORTALEGEN_RECOGNITION_PLUGIN,
    )
    registry = RecognitionRegistry()
    registry.register(MUNICIPIUM_PORTALEGEN_RECOGNITION_PLUGIN)
    registry.register(FILODIRETTO_RECOGNITION_PLUGIN)
    return registry
```

Nuova funzione adapter, **separata** da `firma_da_registro` (che resta BASE/AT-only
e continua a rifiutare SP). Non ritorna `Firma`, ritorna un piccolo dato SP:

```python
@dataclass(frozen=True)
class RiconoscimentoSP:
    platform_id: str | None          # es. "municipium_portalegen", o None su miss
    fingerprint: str | None
    recognition_score: float
    evidence: tuple[FingerprintEvidence, ...]

def riconosci_service_portal(*, headers, html, source_id, entrypoint_url,
                             expected_platform=None) -> RiconoscimentoSP:
    obs = RecognitionObservation(
        source_id=source_id, surface=Surface.SERVICE_PORTAL,
        entrypoint_url=entrypoint_url, http_status=200,
        headers=headers, body=html, expected_platform=expected_platform,
    )
    match = _SP_REGISTRY.recognize(obs)   # _SP_REGISTRY = build_service_portal_registry()
    if match is None:
        return RiconoscimentoSP(None, None, 0.0, ())
    r = match.result
    return RiconoscimentoSP(r.platform_id, r.fingerprint, r.recognition_score, r.evidence)
```

## Call site: `_confirm_one`, ramo SERVICE_PORTAL (additivo)

È il sito con l'HTML già in mano. Modifica **additiva**, non sostituisce la semantica
"conferma liveness":

```python
else:  # SERVICE_PORTAL
    sp = riconosci_service_portal(
        headers=dict(headers), html=html, source_id=source_id,
        entrypoint_url=url, expected_platform=expected_platform,
    )
    if sp.platform_id is not None:
        platform = sp.platform_id            # identità nativa deterministica
    else:
        platform = expected_platform         # miss → comportamento di oggi
    known = bool(platform)
```

Con questo, la logica `changed`/`action`/`status` già esistente vale anche per SP:
- riconosciuto **e** combacia con `expected_platform` → `KEEP` / `OK`;
- riconosciuto ma **diverso** dal persistito → `platform_changed` → `REDISCOVER`
  (drift detection reale, prima impossibile su SP);
- **miss** (`None`) → identico a oggi: si fida di `provider_hint`, conferma liveness.
  Un miss non declassa mai un hint persistito a manual review: il registry
  native-only è greenfield-stretto, un no-match non è una smentita.

Le `evidence` e il `fingerprint` nativi entrano nell'envelope `CheckResult` quando
c'è un match (oggi l'evidence SP è la sola riga sintetica "piattaforma invariata").

## Guardrail (da non violare)

1. **Nessun id BASE su SP.** Il registry SP è native-only per costruzione; un test
   deve provare che una pagina Municipium senza asset portalegen NON produce
   `municipium` (dà `None`, non un id BASE).
2. **Miss ≠ smentita.** `None` mantiene il comportamento odierno (trust hint +
   liveness), non forza `MANUAL_REVIEW`.
3. **`firma_da_registro` resta BASE/AT-only** e continua a rifiutare SP: la seam SP
   è una funzione distinta, il Gate 0 non si tocca.
4. **Confine plugin invariato**: la seam non importa chat/sweep/connettore.

## Test (nuovo `test_sp_recognition.py` + estensione confirmation)

- portalegen reale (theme + asset) → `platform_id == "municipium_portalegen"`, score 0,995;
- Municipium con solo `container-municipium-agid`, **senza** asset → `None`
  (prova che il bridge-BASE non contamina: NON `municipium`);
- filodiretto reale (rotta + siscomJS) → `platform_id == "filodiretto"`;
- HTML generico → `None`;
- `_confirm_one` SP: match+combacia → OK/KEEP; match+drift → `platform_changed`/
  REDISCOVER; miss → envelope di oggi invariato (trust hint);
- `confirm_inventory` end-to-end con un `service_portal` in inventario → check SP
  scritto con `platform` nativo.

## Non in questo giro (follow-up)

- **Discovery-time stamping**: popolare `ServicePortalCandidate.platform_id` /
  `fingerprint` / `recognition_status` in `discover_service_portal_candidates`
  richiede un fetch-per-candidato (oggi discovery è fetch-free) → cambia costo e
  firma della discovery. Rimandato: il valore immediato (identità nativa + drift)
  si ottiene già in confirmation, dove l'HTML c'è. Da valutare a parte.
- **Estensione enum `Piattaforma`**: scartata (vedi Decisione portante).

## Ordine operativo

1. `build_service_portal_registry()` + `riconosci_service_portal()` + `RiconoscimentoSP`.
2. Test seam SP isolati (i primi 4 casi sopra) — verde prima di toccare il runtime.
3. Cablaggio `_confirm_one` ramo SERVICE_PORTAL (additivo).
4. Test confirmation SP (drift + miss-invariato + e2e).
5. Suite Docker completa; aggiornare `done.md` e memoria.
