"""Registro locale per-comune (D-01/D-02/D-03/D-11, ciclo 14 brief B2):
store zero-fetch-al-render con logo, endpoint, snapshot servizi e storia
scansioni per la change-detection.

Analogo ESATTO di `connettore.py`: store JSON per-comune sotto `LIVE_DIR`
(mai SQLite — precedente esplicito `scansioni.py:13` «Niente sqlite»;
SQLite esiste solo per i costi in `storico.py`), scrittura atomica
`.tmp` + `os.replace`, record corrotto = record assente.

`GET /api/registro/{istat}` (in `api.py`) legge SOLO da qui, mai una fetch
al render (D-01): il logo e il resto sono catturati one-shot DENTRO
`registra_scansione`, chiamata dal connettore dopo una scansione riuscita.

CONTRATTO-O2 (congelato nel plan, W4 interface-first): `RegistroComune` è
la forma esatta che B3 consuma senza esplorare questo modulo — non
aggiungere/spostare campi qui senza aggiornare il contratto nel plan.
"""

from __future__ import annotations

import base64
import hashlib
import html
import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel

from treasureiq.connettore import EsitoConnettore
from treasureiq.ingest.base import USER_AGENT
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www
from treasureiq.sonda_live import LIVE_DIR, ComuneNoto

logger = logging.getLogger(__name__)

#: Size-cap del logo one-shot (D-11): l'abort è in streaming, non un
#: controllo di `len()` a valle di un download intero (il DoS resterebbe).
MAX_LOGO_BYTES = 200_000

#: Cap sulla home page letta per estrarre l'url del logo (D-11). Anche il
#: primo hop va in streaming-con-abort come il secondo: una home enorme non
#: deve entrare in RAM intera a ogni scansione riuscita.
MAX_HOME_BYTES = 1_000_000

#: Quante scansioni tenere in storia: basta l'ultima coppia per il diff
#: (R-04), un margine oltre serve solo a non far crescere il file all'infinito.
MAX_STORIA = 10

_RE_META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_RE_LINK_TAG = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_RE_CONTENT_ATTR = re.compile(r'content=["\']([^"\']+)["\']', re.IGNORECASE)
_RE_HREF_ATTR = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_RE_REL_ICON = re.compile(r'rel=["\'](?:shortcut icon|icon)["\']', re.IGNORECASE)


class ServizioSnapshot(BaseModel):
    """Una voce del `servizi_snapshot` (D-03): nome+url, mai altro — è
    input al fingerprint di change-detection, non un profilo servizio."""

    nome: str
    url: str


class EndpointsRegistro(BaseModel):
    """Gli endpoint noti del portale. Oggi solo `at` è popolato dal
    connettore Municipium; `servizi`/`mappa` restano per i connettori eGov
    futuri (Truth 3 del plan) — nessuna inflazione qui, solo la forma."""

    amministrazione: str | None = None
    servizi: str | None = None
    mappa: str | None = None
    at: str | None = None


class Cambiato(BaseModel):
    """`campi` non vuoto (R-04): solo dati stabili, mai il set-pagine
    d'ingestione ([[ingest-non-riproducibile]])."""

    campi: list[str]


class RegistroComune(BaseModel):
    """CONTRATTO-O2 (congelato): la forma esatta di `GET /api/registro/
    {istat}` che B3 consuma. Non toccare senza aggiornare il plan."""

    codice_istat: str
    nome: str
    logo_b64: str | None = None
    dominio: str
    piattaforma: str
    endpoints: EndpointsRegistro
    ultima_scansione: str
    servizi_snapshot: list[ServizioSnapshot] = []
    prima_scansione: bool
    cambiato: Cambiato | None = None


class ScansioneStorico(BaseModel):
    """Una riga di storia (D-03): solo i fingerprint stabili usati dal
    diff, mai il set-pagine (R-04)."""

    quando: str
    servizi_fingerprint: str
    contatti_fingerprint: str
    logo_hash: str | None = None


class RecordRegistro(RegistroComune):
    """Il record persistito: CONTRATTO-O2 più la storia scansioni che
    serve solo al diff — la route la esclude (`leggi_registro`)."""

    scansioni: list[ScansioneStorico] = []


def _percorso_store(codice_istat: str) -> Path:
    return LIVE_DIR / "registro" / f"{codice_istat}.json"


def _da_store(codice_istat: str) -> RecordRegistro | None:
    """Il record esistente, o `None` se assente/illeggibile. Nessun TTL
    qui (a differenza di `connettore._da_store`): il registro riflette
    l'ultima scansione riuscita finché una nuova non arriva, la route
    legge sempre e solo questo — mai una fetch al render (D-01)."""
    percorso = _percorso_store(codice_istat)
    if not percorso.exists():
        return None
    try:
        return RecordRegistro.model_validate_json(percorso.read_text("utf-8"))
    except Exception:  # noqa: BLE001 — record illeggibile è record assente
        logger.warning("store registro illeggibile: %s", percorso)
        return None


def _in_store(record: RecordRegistro) -> None:
    """Scrittura atomica, stesso stampo di `connettore._in_store`."""
    percorso = _percorso_store(record.codice_istat)
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(record.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        logger.warning("store registro non scrivibile (%s): %s", percorso, exc)


def leggi_registro(codice_istat: str) -> RegistroComune | None:
    """La scheda pubblica (CONTRATTO-O2), letta SOLO da disco. `None` =
    comune mai scansionato (404 lato route, D-02: la card degrada a
    glifo+nome)."""
    record = _da_store(codice_istat)
    if record is None:
        return None
    return RegistroComune(**record.model_dump(exclude={"scansioni"}))


def _fingerprint_servizi(esito: EsitoConnettore) -> str:
    """Nomi+conteggio ordinati (Truth 4/R-04): stabile a prescindere
    dall'ordine di scoperta, mai sul set-pagine."""
    nomi = sorted(u.nome for u in esito.uffici)
    return f"{len(nomi)}:{'|'.join(nomi)}"


def _fingerprint_contatti(esito: EsitoConnettore) -> str:
    """Recapiti verbatim, ordinati e deduplicati: stabili anche se un
    ufficio cambia posizione nella pagina."""
    contatti: list[str] = []
    for ufficio in esito.uffici:
        contatti.extend(ufficio.telefoni)
        contatti.extend(ufficio.email)
        contatti.extend(ufficio.pec)
    return "|".join(sorted(set(contatti)))


def _estrai_logo_url(pagina: str, base: str) -> str | None:
    """`og:image` prima, `<link rel="icon">` come fallback (D-11).
    Nessun'altra euristica: assente qui = `logo_b64: null`, mai un
    errore (D-02, fallback glifo lato UI)."""
    for tag in _RE_META_TAG.findall(pagina):
        if "og:image" not in tag.lower():
            continue
        match = _RE_CONTENT_ATTR.search(tag)
        if match:
            return urljoin(base, html.unescape(match.group(1)).strip())
    for tag in _RE_LINK_TAG.findall(pagina):
        if not _RE_REL_ICON.search(tag):
            continue
        match = _RE_HREF_ATTR.search(tag)
        if match:
            return urljoin(base, html.unescape(match.group(1)).strip())
    return None


def _scarica_logo(url: str, host_comune: str, *, timeout: float = 6.0) -> tuple[str | None, str | None]:
    """Il logo (D-11), scaricato in streaming con la guardia SSRF
    post-redirect di `municipium.py:246` (host allow-list DOPO il
    follow-301) e un size-cap che ABORTISCE la connessione al superamento
    — mai un `len()` dopo un download intero, il DoS resterebbe altrimenti.
    Ritorna `(data_uri, hash_sha256)`; qualunque fallimento → `(None, None)`,
    mai un'eccezione che risale al chiamante."""
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            with client.stream("GET", url) as risposta:
                if risposta.status_code != 200:
                    return None, None
                if _host_senza_www(urlparse(str(risposta.url)).netloc.lower()) != host_comune:
                    logger.warning("logo redirect fuori host scartato: %s -> %s", url, risposta.url)
                    return None, None
                content_type = risposta.headers.get("content-type", "")
                if content_type and not content_type.lower().startswith("image/"):
                    return None, None
                buffer = bytearray()
                for pezzo in risposta.iter_bytes():
                    buffer.extend(pezzo)
                    if len(buffer) > MAX_LOGO_BYTES:
                        logger.info("logo oltre size-cap, connessione interrotta: %s", url)
                        return None, None
    except Exception:  # noqa: BLE001 — logo muto: fallback glifo, mai un crash
        logger.info("logo irraggiungibile: %s", url)
        return None, None

    dati = bytes(buffer)
    if not dati:
        return None, None
    hash_sha256 = hashlib.sha256(dati).hexdigest()
    mime = content_type or "image/png"
    data_uri = f"data:{mime};base64,{base64.b64encode(dati).decode('ascii')}"
    return data_uri, hash_sha256


def _logo_one_shot(comune: ComuneNoto) -> tuple[str | None, str | None]:
    """Home page del comune → url logo → download guardato. Chiamata una
    volta per scansione (D-11), mai al render."""
    base = _base_con_schema(comune.sito)
    if base is None:
        return None, None
    host_comune = _host_senza_www(urlparse(base).netloc.lower())
    try:
        with httpx.Client(timeout=6.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            with client.stream("GET", base) as risposta:
                # host-check DOPO i redirect (SSRF): un redirect fuori dal
                # dominio del comune non deve essere seguito nel corpo.
                if risposta.status_code != 200 or _host_senza_www(
                    urlparse(str(risposta.url)).netloc.lower()
                ) != host_comune:
                    return None, None
                buffer = bytearray()
                for chunk in risposta.iter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > MAX_HOME_BYTES:
                        # home spropositata: abort in streaming, mai in RAM intera
                        logger.info("home page oltre cap per logo: %s", comune.nome)
                        return None, None
                finale = str(risposta.url)
    except Exception:  # noqa: BLE001 — home page muta: niente logo, non un crash
        logger.info("home page irraggiungibile per logo: %s", comune.nome)
        return None, None
    testo = buffer.decode("utf-8", errors="replace")
    logo_url = _estrai_logo_url(testo, finale)
    if logo_url is None:
        return None, None
    return _scarica_logo(logo_url, host_comune)


def _campi_cambiati(precedente: ScansioneStorico, attuale: ScansioneStorico) -> list[str]:
    campi = []
    if precedente.servizi_fingerprint != attuale.servizi_fingerprint:
        campi.append("servizi")
    if precedente.contatti_fingerprint != attuale.contatti_fingerprint:
        campi.append("contatti")
    if precedente.logo_hash != attuale.logo_hash:
        campi.append("logo")
    return campi


def registra_scansione(comune: ComuneNoto, esito: EsitoConnettore) -> RecordRegistro | None:
    """Aggiorna il registro dopo una scansione connettore riuscita
    (D-03): fingerprint stabili, change-detection (R-04) e logo one-shot
    (D-11). Chiamata da `connettore.leggi_connettore` dopo `_in_store
    (esito)` — non deve mai bloccare il chiamante: il chiamante avvolge
    già questa chiamata in un try/except, qui in più ogni sotto-passo
    degrada da solo (nessuna eccezione propagata)."""
    base = _base_con_schema(comune.sito)
    dominio = urlparse(base).netloc if base else (comune.sito or "")

    precedente = _da_store(comune.codice_istat)
    storia_precedente = precedente.scansioni if precedente else []
    prima_scansione = len(storia_precedente) == 0

    logo_b64, logo_hash = _logo_one_shot(comune)

    attuale = ScansioneStorico(
        quando=esito.letto_il,
        servizi_fingerprint=_fingerprint_servizi(esito),
        contatti_fingerprint=_fingerprint_contatti(esito),
        logo_hash=logo_hash,
    )

    cambiato: Cambiato | None = None
    if not prima_scansione:
        campi = _campi_cambiati(storia_precedente[-1], attuale)
        if campi:
            cambiato = Cambiato(campi=campi)

    storia = [*storia_precedente, attuale][-MAX_STORIA:]

    record = RecordRegistro(
        codice_istat=comune.codice_istat,
        nome=comune.nome,
        logo_b64=logo_b64,
        dominio=dominio,
        piattaforma=esito.piattaforma,
        endpoints=EndpointsRegistro(
            at=esito.amministrazione_trasparente.indice_url if esito.amministrazione_trasparente else None
        ),
        ultima_scansione=esito.letto_il,
        servizi_snapshot=[ServizioSnapshot(nome=u.nome, url=u.url) for u in esito.uffici],
        prima_scansione=prima_scansione,
        cambiato=cambiato,
        scansioni=storia,
    )
    _in_store(record)
    return record
