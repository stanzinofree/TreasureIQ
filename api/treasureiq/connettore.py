"""CONTRATTO CONNETTORE condiviso (D-09): l'interfaccia comune che OGNI
scansione di piattaforma produce, a prescindere dal vendor dietro il
portale.

Municipium è la prima implementazione piena (B2/B3, altrove); questo modulo
non sa nulla di Municipium — definisce solo i modelli e il dispatcher. WP,
Halley, AgID aggiungono una entry nel dispatcher senza toccare la firma:
è il seam pensato apposta perché il rework non serva (D-09, acceptance A9).

Persistenza (D-10, key_link 5): store per-comune `LIVE_DIR/"connettore"/
{istat}.json`, stesso stampo atomico di `alberatura.py`/`scansioni.py`
(`.tmp` + `os.replace`, TTL, cache corrotta = cache assente). Come in
`alberatura._in_cache` (L-5, ciclo 7), un esito degradato-vuoto — nessun
ufficio, nessuna Amministrazione Trasparente — non si persiste mai: è un
esito onesto da ritornare al chiamante, non un fatto da fissare su disco.
"""

from __future__ import annotations

import logging
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from treasureiq.ingest.censimento import _Sonda, scopri_pagina_at
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.mappa_connettore import _base_con_schema
from treasureiq.sonda_live import LIVE_DIR, comune_per_codice

logger = logging.getLogger(__name__)

#: Stesso ordine di grandezza di `alberatura.TTL_ORE` per una scansione al
#: giorno (:56 lì), qui più largo perché uffici/AT cambiano ancora più di
#: rado dei bandi: 24h come richiesto dal brief.
TTL_ORE = 24


class AreaAmministrativa(BaseModel):
    """Una voce dell'indice amministrativo del portale: nome e dove sta."""

    nome: str
    url: str


class Responsabile(BaseModel):
    """Chi risponde di un ufficio (accountability). Best-effort: solo dove la
    scheda lo pubblica strutturato, mai inferito da un LLM (D-07). `nome`
    obbligatorio — un `Responsabile` senza nome non esiste; `ruolo`/`email`
    opzionali (`None` = non pubblicato, D-05), mai omessi in silenzio a valle."""

    nome: str = Field(min_length=1)
    ruolo: str | None = None
    email: str | None = None


class UfficioConnettore(BaseModel):
    """Un ufficio letto dal connettore, coi suoi recapiti verbatim (D-07:
    nessuna cifra passa da un LLM). `source_typed` distingue un recapito
    tipizzato dal portale (`tel:`/`mailto:`) da uno solo scritto in prosa.

    `indirizzo`/`responsabile` sono additivi (Ramo 1, ciclo estensione):
    best-effort, `None` dove la scheda non li pubblica — degrado onesto (D-05),
    mai un valore inventato. Opzionali con default: i dati esistenti su disco
    (senza questi campi) restano deserializzabili senza migrazione."""

    nome: str
    url: str
    telefoni: list[str] = []
    email: list[str] = []
    pec: list[str] = []
    orari: str | None = None
    source_typed: bool
    letto_il: str
    indirizzo: str | None = None
    responsabile: Responsabile | None = None


class BandoAT(BaseModel):
    """Un bando trovato nell'indice di Amministrazione Trasparente."""

    titolo: str
    url: str
    pdf_url: str | None = None


class AmministrazioneTrasparente(BaseModel):
    """L'indice AT del portale (D-11): bandi attivi verbatim, presenza PDF
    come flag — l'analisi del PDF resta su richiesta del cittadino, mai
    automatica di massa.

    `piattaforma_at` (B5, ciclo16): quale piattaforma serve la pagina AT
    stessa — spesso DIVERSA da `EsitoConnettore.piattaforma` (l'AT vive
    spesso su un SaaS indipendente dal portale, es. jcitygov/Halley su un
    comune WordPress). Solo classificazione: sapere QUALE connettore AT si
    userebbe, non usarlo — nessun connettore AT è costruito qui (B8)."""

    indice_url: str | None = None
    piattaforma_at: str | None = None
    bandi_attivi: list[BandoAT] = []
    pdf_presenti: bool = False


class EndpointiConnettore(BaseModel):
    """Gli URL-indice di sezione che un connettore ha DAVVERO fetchato/letto
    durante la scansione (B9, ciclo16). Onestà (D-07-like): solo URL reali,
    mai costruiti per convenzione — `null` dove il connettore non ha in
    mano un link genuino per quella sezione."""

    amministrazione: str | None = None
    servizi: str | None = None
    mappa: str | None = None


class EsitoConnettore(BaseModel):
    """Il contratto D-09: quello che UNA scansione di piattaforma produce,
    a prescindere dal vendor. `letto_il` è il momento della lettura reale
    (mai un `now()` ricalcolato quando si serve da cache — D-10)."""

    codice_istat: str
    piattaforma: str
    letto_il: str
    aree_amministrative: list[AreaAmministrativa] = []
    uffici: list[UfficioConnettore] = []
    amministrazione_trasparente: AmministrazioneTrasparente | None = None
    # `endpoints` è additivo (B9): un comune Municipium con servizi/aree ha
    # già `uffici`/`aree_amministrative` non vuoti, quindi `_esito_vuoto`
    # (sotto) resta corretto senza doverlo controllare — un esito "solo
    # endpoints, niente uffici" non esiste nel connettore Municipium attuale.
    endpoints: EndpointiConnettore | None = None
    #: Validator della fonte primaria usato dal refresh leggero. Sono
    #: diagnostica/cache, non dati mostrati al cittadino.
    fonte_hash: str | None = None
    fonte_etag: str | None = None
    fonte_last_modified: str | None = None
    controllato_il: str | None = None
    #: Diagnostica backoffice: non è parte della risposta cittadino.
    riconoscimento: dict | None = None


def _e_openweb(html: str) -> bool:
    """Discrimina SoluzioniPA OpenWeb (WordPress) da Siscom PeopleWeb
    dentro il ramo `PEOPLEWEB`. OpenWeb = WordPress: espone `wp-content`
    e i permalink AgID `/amministrazione/unita_organizzativa/`. Siscom =
    ASP.NET WebForms, nessuno di questi marcatori. Deciso sull'HTML home
    già scaricato al dispatch — nessun fetch extra."""
    return (
        "/amministrazione/unita_organizzativa/" in html
        or "wp-content" in html
    )


def _esito_vuoto(esito: EsitoConnettore) -> bool:
    """Vero se l'esito non porta nulla di utile: né uffici, né aree
    amministrative, né AT (L-5) — questo NON si persiste mai, per non
    fissare un negativo che una prossima scansione potrebbe smentire.
    Le aree contano: eGov produce `uffici=[]` per design e riempie solo
    `aree_amministrative`; senza questo un comune eGov sarebbe ri-scrapato
    live a ogni query invece che cachato/registrato."""
    return (
        not esito.uffici
        and not esito.aree_amministrative
        and esito.amministrazione_trasparente is None
    )


def _percorso_store(codice_istat: str) -> Path:
    return LIVE_DIR / "connettore" / f"{codice_istat}.json"


def _da_store_raw(codice_istat: str) -> EsitoConnettore | None:
    """Legge l'ultimo contratto anche se il TTL dati è scaduto."""
    percorso = _percorso_store(codice_istat)
    if not percorso.exists():
        return None
    try:
        return EsitoConnettore.model_validate_json(percorso.read_text("utf-8"))
    except Exception:  # noqa: BLE001 — cache corrotta = contratto assente
        logger.warning("connettore illeggibile per %s", codice_istat)
        return None


def _da_store(codice_istat: str) -> EsitoConnettore | None:
    """Il record esistente se ancora fresco (< `TTL_ORE`). Un file
    illeggibile o un `letto_il` non parsabile è trattato come assente:
    meglio una rilettura di troppo che un dato silenziosamente vecchio."""
    esito = _da_store_raw(codice_istat)
    if esito is None:
        return None
    try:
        eta = datetime.now(timezone.utc) - datetime.fromisoformat(esito.letto_il)
    except Exception:  # noqa: BLE001 — store illeggibile è store assente
        logger.warning("store connettore illeggibile: %s", percorso)
        return None
    return esito if eta < timedelta(hours=TTL_ORE) else None


def _firma_fonte(risposta: object) -> tuple[str, str | None, str | None]:
    testo = getattr(risposta, "text", "")
    headers = getattr(risposta, "headers", {})
    return (
        hashlib.sha256(testo.encode("utf-8", errors="replace")).hexdigest(),
        headers.get("etag"),
        headers.get("last-modified"),
    )


def refresh_connettore(
    codice_istat: str, *, timeout: float = 8.0
) -> EsitoConnettore | None:
    """Controllo leggero della fonte già catalogata.

    Restituisce il contratto precedente se home e validator non sono cambiati;
    in caso di variazione delega a ``leggi_connettore`` per la rilettura piena.
    Un contratto assente non viene scoperto qui: è responsabilità del worker
    in modalità ``discovery``.
    """
    precedente = _da_store_raw(codice_istat)
    if precedente is None:
        return None
    comune = comune_per_codice(codice_istat)
    if comune is None:
        return precedente
    base = _base_con_schema(comune.sito)
    if base is None:
        return precedente
    try:
        with _Sonda(timeout=timeout) as sonda:
            risposta = sonda.risposta(base)
            fonte_hash, etag, last_modified = _firma_fonte(risposta)
    except Exception:  # noqa: BLE001 — il refresh non cancella mai il dato noto
        logger.warning("refresh fonte fallito per %s", codice_istat)
        return precedente

    invariata = (
        precedente.fonte_etag and etag and precedente.fonte_etag == etag
    ) or (
        precedente.fonte_last_modified
        and last_modified
        and precedente.fonte_last_modified == last_modified
    ) or (
        precedente.fonte_hash
        and precedente.fonte_hash == fonte_hash
    )
    controllato = precedente.model_copy(
        update={
            "controllato_il": datetime.now(timezone.utc).isoformat(),
            "fonte_hash": fonte_hash,
            "fonte_etag": etag,
            "fonte_last_modified": last_modified,
        }
    )
    if invariata:
        _in_store(controllato)
        return controllato
    return leggi_connettore(codice_istat, usa_cache=False, timeout=timeout)


def refresh_dati_connettore(
    codice_istat: str, *, timeout: float = 8.0
) -> EsitoConnettore | None:
    """Aggiorna i dati usando esclusivamente la piattaforma già nota.

    Non esegue il riconoscimento della home: il dispatcher usa il valore
    persistito nel contratto precedente. La confirmation quindicinale resta
    l'unica operazione autorizzata a riclassificare la piattaforma.
    """
    precedente = _da_store_raw(codice_istat)
    if precedente is None:
        return None
    comune = comune_per_codice(codice_istat)
    if comune is None:
        return precedente

    try:
        with _Sonda(timeout=timeout) as sonda:
            piattaforma = precedente.piattaforma
            if piattaforma == Piattaforma.MUNICIPIUM.value:
                from treasureiq.municipium import leggi_municipium
                esito = leggi_municipium(comune, sonda)
            elif piattaforma in {Piattaforma.EGOV.value, Piattaforma.HGATE.value}:
                from treasureiq.egov import leggi_egov
                esito = leggi_egov(comune, sonda)
            elif piattaforma == "peopleweb":
                from treasureiq.peopleweb import leggi_peopleweb
                esito = leggi_peopleweb(comune, sonda)
            elif piattaforma == "openweb":
                from treasureiq.openweb import leggi_openweb
                esito = leggi_openweb(comune, sonda)
            elif piattaforma in {
                Piattaforma.WP_DESIGN_COMUNI.value,
                Piattaforma.WORDPRESS_GENERICO.value,
                Piattaforma.COMUNIBOOTSTRAPITALIA.value,
            }:
                from treasureiq.wordpress_agid import leggi_wordpress_agid
                esito = leggi_wordpress_agid(comune, sonda)
            elif piattaforma == Piattaforma.COMWEB.value:
                from treasureiq.comweb import leggi_comweb
                esito = leggi_comweb(comune, sonda)
            elif piattaforma == Piattaforma.OPENPA.value:
                from treasureiq.openpa import leggi_openpa
                esito = leggi_openpa(comune, sonda)
            else:
                logger.info("refresh dati non supportato per piattaforma %s", piattaforma)
                return precedente
    except Exception:  # noqa: BLE001 — il dato precedente resta disponibile
        logger.warning("refresh dati fallito per %s", codice_istat)
        return precedente

    if _esito_vuoto(esito):
        return precedente
    esito = esito.model_copy(
        update={
            "fonte_hash": precedente.fonte_hash,
            "fonte_etag": precedente.fonte_etag,
            "fonte_last_modified": precedente.fonte_last_modified,
            "controllato_il": precedente.controllato_il or precedente.letto_il,
        }
    )
    _in_store(esito)
    try:
        from treasureiq.registro import registra_scansione
        registra_scansione(comune, esito)
    except Exception:  # noqa: BLE001 — il registro non deve bloccare il refresh
        logger.warning("registro non aggiornato nel refresh dati per %s", codice_istat)
    return esito


def _in_store(esito: EsitoConnettore) -> None:
    """Scrittura atomica: un lettore concorrente vede il record vecchio o
    il nuovo, mai un record a metà. Chiamata SOLO con un esito non
    degradato-vuoto (L-5) — il chiamante fa la guardia."""
    percorso = _percorso_store(esito.codice_istat)
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(esito.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        logger.warning("store connettore non scrivibile (%s): %s", percorso, exc)


def _in_recognition_store(result: dict) -> None:
    """Persist recognition even when the connector result is empty."""
    from treasureiq.catalog.recognition import RecognitionResult

    validated = RecognitionResult.model_validate(result)
    percorso = LIVE_DIR / "riconoscimento" / validated.surface.value / f"{validated.source_id}.json"
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(validated.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        logger.warning("riconoscimento non scrivibile (%s): %s", percorso, exc)


def _in_check_store(result: object) -> None:
    """Persist any surface check independently from connector data."""
    from treasureiq.catalog.checks import CheckResult

    validated = CheckResult.model_validate(result)
    percorso = LIVE_DIR / "check" / validated.surface.value / f"{validated.source_id}.json"
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(validated.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        logger.warning("check non scrivibile (%s): %s", percorso, exc)


def leggi_connettore(
    codice_istat: str, *, usa_cache: bool = True, timeout: float = 8.0
) -> EsitoConnettore | None:
    """Il connettore di un comune, letto dal vivo o servito dallo store.

    `None` se il comune non è noto o non ha sito, o se la piattaforma non ha
    (ancora) un connettore che sa leggerla — deferred, non un guasto: WP,
    Halley, AgID aggiungeranno la loro entry senza toccare questa firma.
    """
    if usa_cache:
        cache = _da_store(codice_istat)
        if cache is not None:
            return cache

    comune = comune_per_codice(codice_istat)
    if comune is None:
        return None
    base = _base_con_schema(comune.sito)
    if base is None:
        return None

    try:
        with _Sonda(timeout=timeout) as sonda:
            risposta = sonda.risposta(base)
            from treasureiq.catalog.checks import source_identity_check
            from treasureiq.registro import recapiti_comune

            recapiti = recapiti_comune(codice_istat)
            _in_check_store(source_identity_check(
                source_id=codice_istat,
                declared_url=base,
                response=risposta,
                identity={
                    "nome": comune.nome,
                    "pec": recapiti.pec if recapiti else None,
                    "indirizzo": recapiti.indirizzo if recapiti else None,
                    "codice_ipa": recapiti.codice_ipa if recapiti else None,
                    "logo": bool("og:image" in risposta.text.lower() or "it-brand-wrapper" in risposta.text.lower()),
                },
                checked_at=datetime.now(timezone.utc),
            ))
            # BASE (home comune): una piattaforma AT-only non deve mai vincere
            # la selezione del connettore. La surface ORDINARY_DATA codifica
            # l'esclusione AT (ex `includi_at=False`); il registry porta i
            # plugin nativi + la soppressione Passo C nel dispatch reale.
            # Import locale: `catalog/__init__` importa connettore (adapters),
            # quindi un import catalog in cima creerebbe un ciclo. I test
            # patchano `recognition_adapter.firma_da_registro`.
            from treasureiq.catalog.contracts import Surface
            from treasureiq.catalog import recognition_adapter

            firma = recognition_adapter.firma_da_registro(
                headers=dict(risposta.headers),
                html=risposta.text,
                surface=Surface.ORDINARY_DATA,
                source_id=codice_istat,
                entrypoint_url=base,
            )
            if firma.piattaforma == Piattaforma.MUNICIPIUM:
                try:
                    from treasureiq.municipium import leggi_municipium
                except ImportError:  # noqa: BLE001 — B2 non ancora costruito: deferred, non un crash
                    logger.info("connettore Municipium non ancora disponibile")
                    return None
                esito = leggi_municipium(comune, sonda)
            elif firma.piattaforma == Piattaforma.EGOV:
                try:
                    from treasureiq.egov import leggi_egov
                except ImportError:  # noqa: BLE001 — B4b non ancora costruito: deferred, non un crash
                    logger.info("connettore eGov non ancora disponibile")
                    return None
                esito = leggi_egov(comune, sonda)
            elif firma.piattaforma == Piattaforma.PEOPLEWEB:
                # Il fingerprint `peopleweb` conflaziona DUE vendor (tema
                # Bootstrap-Italia generico): SoluzioniPA OpenWeb (WordPress,
                # path AgID puliti) e Siscom PeopleWeb (ASP.NET WebForms).
                # Si discriminano dall'HTML home già scaricato — nessun fetch
                # extra — e si instrada al connettore giusto.
                if _e_openweb(risposta.text):
                    try:
                        from treasureiq.openweb import leggi_openweb
                    except ImportError:  # noqa: BLE001 — deferred, non un crash
                        logger.info("connettore OpenWeb non ancora disponibile")
                        return None
                    esito = leggi_openweb(comune, sonda)
                else:
                    try:
                        from treasureiq.peopleweb import leggi_peopleweb
                    except ImportError:  # noqa: BLE001 — deferred, non un crash
                        logger.info("connettore PeopleWeb non ancora disponibile")
                        return None
                    esito = leggi_peopleweb(comune, sonda)
            elif firma.piattaforma in (
                Piattaforma.WP_DESIGN_COMUNI,
                Piattaforma.WORDPRESS_GENERICO,
                Piattaforma.COMUNIBOOTSTRAPITALIA,
            ):
                try:
                    from treasureiq.wordpress_agid import leggi_wordpress_agid
                except ImportError:  # noqa: BLE001 — connettore non ancora costruito: deferred, non un crash
                    logger.info("connettore WordPress-AgID non ancora disponibile")
                    return None
                esito = leggi_wordpress_agid(comune, sonda)
            elif firma.piattaforma == Piattaforma.COMWEB:
                try:
                    from treasureiq.comweb import leggi_comweb
                except ImportError:  # noqa: BLE001 — deferred, non un crash
                    logger.info("connettore ComWeb non ancora disponibile")
                    return None
                esito = leggi_comweb(comune, sonda)
            elif firma.piattaforma == Piattaforma.OPENPA:
                try:
                    from treasureiq.openpa import leggi_openpa
                except ImportError:  # noqa: BLE001 — deferred, non un crash
                    logger.info("connettore OpenPA non ancora disponibile")
                    return None
                esito = leggi_openpa(comune, sonda)
            else:
                return None
    except Exception:  # noqa: BLE001 — portale muto: esito assente, mai un crash
        logger.warning("connettore illeggibile per %s", codice_istat)
        return None

    if esito is None:
        return None
    if esito.riconoscimento is not None:
        _in_recognition_store(esito.riconoscimento)
    fonte_hash, fonte_etag, fonte_last_modified = _firma_fonte(risposta)
    esito = esito.model_copy(
        update={
            "fonte_hash": fonte_hash,
            "fonte_etag": fonte_etag,
            "fonte_last_modified": fonte_last_modified,
            "controllato_il": datetime.now(timezone.utc).isoformat(),
        }
    )
    if esito.amministrazione_trasparente is not None:
        # Classificazione best-effort di QUALE piattaforma serve la pagina
        # AT (B5, ciclo16): nessun fetch extra per il link — riusa l'HTML
        # home già scaricato sopra — un solo fetch extra per la pagina AT
        # stessa, dentro `scopri_pagina_at`. Non usa nessun connettore AT
        # (B8, deferred): solo sapere quale si userebbe.
        try:
            scoperta = scopri_pagina_at(html_home=risposta.text, base=base)
            if scoperta.piattaforma_at != Piattaforma.NON_TROVATA:
                esito.amministrazione_trasparente.piattaforma_at = scoperta.piattaforma_at.value
        except Exception:  # noqa: BLE001 — classificazione AT muta: campo assente, mai un crash
            logger.info("classificazione piattaforma AT non riuscita per %s", codice_istat)
    try:
        from treasureiq.catalog.checks import CheckResult, CheckStatus
        from treasureiq.catalog.contracts import Surface
        from treasureiq.catalog.recognition import (
            FingerprintEvidence,
            RecognitionAction,
        )

        at = esito.amministrazione_trasparente
        at_url = at.indice_url if at else None
        at_platform = at.piattaforma_at if at else None
        platform_known = bool(
            at_platform
            and at_platform not in {
                Piattaforma.NON_TROVATA.value,
                Piattaforma.IGNOTA.value,
            }
        )
        at_source_health = 200 <= risposta.status_code < 400
        at_score = 1.0 if platform_known else 0.5 if at_url else 0.0
        _in_check_store(CheckResult(
            source_id=codice_istat,
            surface=Surface.TRANSPARENCY,
            status=CheckStatus.OK if at_url and platform_known else CheckStatus.DEGRADED,
            source_health=at_source_health,
            completeness_score=round((bool(at_url) + platform_known) / 2, 6),
            recognition_score=at_score,
            coverage_score=1.0 if at_url else 0.0,
            connector_id="at_classifier",
            connector_version="1.0.0",
            fingerprint_version="1.0",
            identity={"indice_url": at_url, "piattaforma_at": at_platform},
            evidence=(
                FingerprintEvidence(
                    key="at_url", description="indice AT verificato", matched=bool(at_url), weight=0.5,
                    observed=at_url,
                ),
                FingerprintEvidence(
                    key="at_platform", description="piattaforma AT riconosciuta", matched=platform_known, weight=0.5,
                    observed=at_platform,
                ),
            ),
            failure_reason=None if at_url and platform_known else "at_platform_or_url_missing",
            action=RecognitionAction.KEEP if at_url and platform_known else RecognitionAction.MANUAL_REVIEW,
            checked_at=datetime.now(timezone.utc),
        ))
    except Exception:  # noqa: BLE001 — il check AT non deve bloccare BASE
        logger.info("check AT non aggiornato per %s", codice_istat)
    try:
        from treasureiq.catalog.service_discovery import (
            discover_service_portal_candidates,
            update_source_inventory,
        )

        at = esito.amministrazione_trasparente
        update_source_inventory(
            live_dir=LIVE_DIR,
            source_id=codice_istat,
            base_url=base,
            base_platform=esito.piattaforma,
            base_fingerprint=fonte_hash,
            transparency_url=at.indice_url if at else None,
            transparency_platform=at.piattaforma_at if at else None,
            candidates=discover_service_portal_candidates(
                base_url=base,
                html_home=risposta.text,
                base_platform=esito.piattaforma,
                discovered_at=datetime.now(timezone.utc),
            ),
            confirmed_at=datetime.now(timezone.utc),
        )
    except Exception:  # noqa: BLE001 — inventory is backoffice metadata
        logger.info("inventario portali non aggiornato per %s", codice_istat)
    if not _esito_vuoto(esito):
        _in_store(esito)
        try:
            from treasureiq.registro import registra_scansione

            registra_scansione(comune, esito)
        except Exception:  # noqa: BLE001 — il registro non deve mai bloccare il connettore
            logger.warning("registro non aggiornato per %s", codice_istat)
    return esito
