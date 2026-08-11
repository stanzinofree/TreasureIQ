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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

from treasureiq.ingest.censimento import _Sonda
from treasureiq.ingest.piattaforma import Piattaforma, firma_da_risposta
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


class UfficioConnettore(BaseModel):
    """Un ufficio letto dal connettore, coi suoi recapiti verbatim (D-07:
    nessuna cifra passa da un LLM). `source_typed` distingue un recapito
    tipizzato dal portale (`tel:`/`mailto:`) da uno solo scritto in prosa."""

    nome: str
    url: str
    telefoni: list[str] = []
    email: list[str] = []
    pec: list[str] = []
    orari: str | None = None
    source_typed: bool
    letto_il: str


class BandoAT(BaseModel):
    """Un bando trovato nell'indice di Amministrazione Trasparente."""

    titolo: str
    url: str
    pdf_url: str | None = None


class AmministrazioneTrasparente(BaseModel):
    """L'indice AT del portale (D-11): bandi attivi verbatim, presenza PDF
    come flag — l'analisi del PDF resta su richiesta del cittadino, mai
    automatica di massa."""

    indice_url: str | None = None
    bandi_attivi: list[BandoAT] = []
    pdf_presenti: bool = False


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


def _da_store(codice_istat: str) -> EsitoConnettore | None:
    """Il record esistente se ancora fresco (< `TTL_ORE`). Un file
    illeggibile o un `letto_il` non parsabile è trattato come assente:
    meglio una rilettura di troppo che un dato silenziosamente vecchio."""
    percorso = _percorso_store(codice_istat)
    if not percorso.exists():
        return None
    try:
        esito = EsitoConnettore.model_validate_json(percorso.read_text("utf-8"))
        eta = datetime.now(timezone.utc) - datetime.fromisoformat(esito.letto_il)
    except Exception:  # noqa: BLE001 — store illeggibile è store assente
        logger.warning("store connettore illeggibile: %s", percorso)
        return None
    return esito if eta < timedelta(hours=TTL_ORE) else None


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
            firma = firma_da_risposta(headers=dict(risposta.headers), html=risposta.text)
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
    if not _esito_vuoto(esito):
        _in_store(esito)
        try:
            from treasureiq.registro import registra_scansione

            registra_scansione(comune, esito)
        except Exception:  # noqa: BLE001 — il registro non deve mai bloccare il connettore
            logger.warning("registro non aggiornato per %s", codice_istat)
    return esito
