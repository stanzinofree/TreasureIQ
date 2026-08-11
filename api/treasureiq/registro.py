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
from treasureiq.integration import DATA_DIR
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www
from treasureiq.sonda_live import LIVE_DIR, ComuneNoto

logger = logging.getLogger(__name__)

#: Recapiti ufficiali IPA (`data/ipa-recapiti.json`, keyed per codice_istat):
#: PEC + indirizzo dell'ente dall'Indice PA. Statico, indipendente dalla
#: scansione — NON entra nel record persistito né nei fingerprint di
#: change-detection (sarebbe rumore), si innesta a read-time in
#: `leggi_registro`. Lettura disco locale, non una fetch (D-01 salvo).
_IPA_RECAPITI_PATH = DATA_DIR / "ipa-recapiti.json"
_ipa_recapiti_cache: dict[str, dict[str, str]] | None = None


def _carica_ipa_recapiti() -> dict[str, dict[str, str]]:
    """L'indice IPA in memoria (cache di processo). Assente/illeggibile =
    dizionario vuoto: i recapiti degradano a `None`, la card resta valida."""
    global _ipa_recapiti_cache
    if _ipa_recapiti_cache is None:
        try:
            import json

            _ipa_recapiti_cache = json.loads(
                _IPA_RECAPITI_PATH.read_text("utf-8")
            )
        except Exception:  # noqa: BLE001 — indice assente = nessun recapito
            logger.warning("ipa-recapiti.json assente/illeggibile: %s", _IPA_RECAPITI_PATH)
            _ipa_recapiti_cache = {}
    return _ipa_recapiti_cache


#: Codice Univoco IPA per codice_istat, dall'elenco nazionale
#: (`data/comuni-istat.json`, arricchito da `ingest.ipa`). Statico come i
#: recapiti — identità dell'ente, non dato di scansione: read-time, mai
#: persistito nel record né nei fingerprint. Lettura disco locale (D-01 salvo).
_COMUNI_ISTAT_PATH = DATA_DIR / "comuni-istat.json"
_comuni_ipa_cache: dict[str, str] | None = None


def _carica_comuni_ipa() -> dict[str, str]:
    """Mappa codice_istat → codice_ipa in memoria (cache di processo).
    Assente/illeggibile = dizionario vuoto: il codice degrada a `None`, la
    card resta valida (stesso patto dei recapiti)."""
    global _comuni_ipa_cache
    if _comuni_ipa_cache is None:
        try:
            import json

            righe = json.loads(_COMUNI_ISTAT_PATH.read_text("utf-8"))
            _comuni_ipa_cache = {
                r["codice_istat"]: r["codice_ipa"]
                for r in righe
                if r.get("codice_istat") and r.get("codice_ipa")
            }
        except Exception:  # noqa: BLE001 — elenco assente = nessun codice
            logger.warning("comuni-istat.json assente/illeggibile: %s", _COMUNI_ISTAT_PATH)
            _comuni_ipa_cache = {}
    return _comuni_ipa_cache


def _codice_ipa(codice_istat: str) -> str | None:
    """Il Codice Univoco IPA dell'ente, o `None` se non agganciato."""
    return _carica_comuni_ipa().get(codice_istat)

#: Size-cap del logo one-shot (D-11): l'abort è in streaming, non un
#: controllo di `len()` a valle di un download intero (il DoS resterebbe).
MAX_LOGO_BYTES = 200_000

#: Cap sulla home page letta per estrarre l'url del logo (D-11). Anche il
#: primo hop va in streaming-con-abort come il secondo: una home enorme non
#: deve entrare in RAM intera a ogni scansione riuscita.
MAX_HOME_BYTES = 1_000_000

#: Cap sul frammento statico `header.html` (eGov): è un frammento, non una
#: pagina intera — un cap piccolo basta e tiene onesto lo streaming-con-abort.
MAX_HEADER_BYTES = 200_000

#: Quante scansioni tenere in storia: basta l'ultima coppia per il diff
#: (R-04), un margine oltre serve solo a non far crescere il file all'infinito.
MAX_STORIA = 10

_RE_META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_RE_LINK_TAG = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_RE_CONTENT_ATTR = re.compile(r'content=["\']([^"\']+)["\']', re.IGNORECASE)
_RE_HREF_ATTR = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_RE_REL_ICON = re.compile(r'rel=["\'](?:shortcut icon|icon)["\']', re.IGNORECASE)

#: Il logo eGov non è nella home ma nel frammento statico `header.html`
#: (`<img alt="Stemma Comune" ...>` — verificato 12/12 su comuni Halley
#: sparsi). Tollerante all'ordine degli attributi: si estraggono i tag
#: `<img>` per intero e si cerca `alt`/`class`/`src` dentro ognuno,
#: nessuna posizione relativa presunta.
_RE_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_RE_SRC_ATTR = re.compile(r'src=["\']([^"\']+)["\']', re.IGNORECASE)
_RE_ALT_ATTR = re.compile(r'alt=["\']([^"\']+)["\']', re.IGNORECASE)
_RE_CLASS_ATTR = re.compile(r'class=["\']([^"\']+)["\']', re.IGNORECASE)


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


class Recapiti(BaseModel):
    """Recapiti e identità ufficiali dall'Indice PA (`fonte`), innestati a
    read-time: statici, indipendenti dalla scansione del portale. PEC,
    indirizzo e `codice_ipa` (il Codice Univoco dell'ente) possono mancare
    singolarmente. `codice_ipa` viene dall'elenco nazionale
    (`comuni-istat.json`), gli altri due da `ipa-recapiti.json`."""

    pec: str | None = None
    indirizzo: str | None = None
    codice_ipa: str | None = None
    fonte: str = "IndicePA"


class RegistroComune(BaseModel):
    """CONTRATTO-O2 (congelato): la forma esatta di `GET /api/registro/
    {istat}` che B3 consuma. Non toccare senza aggiornare il plan.

    `recapiti` è additivo (default `None`): non è persistito nel record ma
    innestato a read-time da `leggi_registro` — i client vecchi lo ignorano."""

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
    recapiti: Recapiti | None = None


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
    scheda = RegistroComune(**record.model_dump(exclude={"scansioni"}))
    scheda.recapiti = _recapiti_ipa(codice_istat)
    return scheda


def _recapiti_ipa(codice_istat: str) -> Recapiti | None:
    """Recapiti + identità IPA per questo comune, o `None` se non c'è nulla
    da dire: né PEC, né indirizzo, né Codice Univoco (nessun campo vuoto
    spacciato per dato). `codice_ipa` viene dall'elenco nazionale, quindi
    un comune assente da `ipa-recapiti.json` può comunque avere il codice."""
    voce = _carica_ipa_recapiti().get(codice_istat) or {}
    pec = (voce.get("pec") or "").strip() or None
    indirizzo = (voce.get("indirizzo") or "").strip() or None
    codice_ipa = _codice_ipa(codice_istat)
    if not pec and not indirizzo and not codice_ipa:
        return None
    return Recapiti(pec=pec, indirizzo=indirizzo, codice_ipa=codice_ipa)


def recapiti_comune(codice_istat: str) -> Recapiti | None:
    """Recapiti ufficiali IPA per QUALSIASI comune, censito o meno: join
    statico per ISTAT (D-01, letto da disco), indipendente dalla scansione
    del portale. È l'unica scheda disponibile per un comune fuori copertura,
    che nel registro non ha ancora un record: la card mostra comunque
    PEC+indirizzo istituzionali invece del solo telefono letto dal vivo."""
    return _recapiti_ipa(codice_istat)


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


def _estrai_logo_header(pagina: str, base: str, host_comune: str) -> str | None:
    """`<img alt="Stemma Comune" src="...">` dentro `header.html` (eGov,
    verificato 12/12 su comuni Halley sparsi) — fallback: `class` che
    contiene sia `me-3` sia `icon`. Same-host qui: un `src` fuori dominio
    non diventa mai il logo (D-04: l'asset deve essere del comune stesso,
    non un URL arbitrario nel frammento).

    `header.html` reale è costruito da un blocco JS (`head += "<img ...>"`)
    con le virgolette dell'attributo escapate (`\\"`) — non HTML piano.
    Si normalizza `\\"` → `"` prima di cercare il tag, altrimenti nessun
    `_RE_IMG_TAG` matcherebbe mai (osservato reale su Marino)."""
    pagina = pagina.replace('\\"', '"')
    for tag in _RE_IMG_TAG.findall(pagina):
        alt_match = _RE_ALT_ATTR.search(tag)
        e_stemma = alt_match is not None and alt_match.group(1).strip().lower() == "stemma comune"
        class_match = _RE_CLASS_ATTR.search(tag)
        e_icona = (
            class_match is not None
            and "me-3" in class_match.group(1).lower()
            and "icon" in class_match.group(1).lower()
        )
        if not e_stemma and not e_icona:
            continue
        src_match = _RE_SRC_ATTR.search(tag)
        if src_match is None:
            continue
        url = urljoin(base, html.unescape(src_match.group(1)).strip())
        if _host_senza_www(urlparse(url).netloc.lower()) != host_comune:
            continue
        return url
    return None


def _leggi_header_html(base: str, host_comune: str, *, timeout: float = 6.0) -> tuple[str, str] | None:
    """GET guardato di `header.html` (D-04): stessa guardia host-check
    DOPO il follow-301 e size-cap-streaming-con-abort di `_scarica_logo`.
    `None` per qualunque esito non valido — innocuo quando manca (es.
    Municipium, dove `header.html` spesso risponde 404): il chiamante
    ripiega sul comportamento attuale (`og:image`→favicon)."""
    url = urljoin(base, "/header.html")
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            with client.stream("GET", url) as risposta:
                if risposta.status_code != 200:
                    return None
                if _host_senza_www(urlparse(str(risposta.url)).netloc.lower()) != host_comune:
                    logger.warning("header.html redirect fuori host scartato: %s -> %s", url, risposta.url)
                    return None
                buffer = bytearray()
                for pezzo in risposta.iter_bytes():
                    buffer.extend(pezzo)
                    if len(buffer) > MAX_HEADER_BYTES:
                        logger.info("header.html oltre size-cap, connessione interrotta: %s", url)
                        return None
                finale = str(risposta.url)
    except Exception:  # noqa: BLE001 — header.html muto: fallback al comportamento attuale
        logger.info("header.html irraggiungibile: %s", url)
        return None
    return bytes(buffer).decode("utf-8", errors="replace"), finale


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


def _estrattori_logo_portale():
    """Estrattori logo brand-portale, import deferred per evitare cicli
    (openweb/peopleweb non importati a modulo). Ognuno prende
    `(html_home, base, host_comune)` e ritorna un url o `None`. Se un
    connettore manca, si salta — mai un crash."""
    estrattori = []
    try:
        from treasureiq.openweb import estrai_logo_openweb

        estrattori.append(estrai_logo_openweb)
    except ImportError:
        pass
    try:
        from treasureiq.peopleweb import estrai_logo_peopleweb

        estrattori.append(estrai_logo_peopleweb)
    except ImportError:
        pass
    try:
        from treasureiq.wordpress_agid import estrai_logo_wordpress_agid

        estrattori.append(estrai_logo_wordpress_agid)
    except ImportError:
        pass
    try:
        from treasureiq.comweb import estrai_logo_comweb

        estrattori.append(estrai_logo_comweb)
    except ImportError:
        pass
    try:
        from treasureiq.openpa import estrai_logo_openpa

        estrattori.append(estrai_logo_openpa)
    except ImportError:
        pass
    return estrattori


def _logo_one_shot(comune: ComuneNoto) -> tuple[str | None, str | None]:
    """Home page del comune → url logo → download guardato. Chiamata una
    volta per scansione (D-11), mai al render.

    L'url logo si sceglie in ordine: `header.html` (brand statico eGov,
    D-04 — l'asset reale del comune, non fabbricato) prima, poi il
    comportamento attuale `og:image`→favicon sulla home come fallback se
    `header.html` manca/404 o non presenta il markup atteso."""
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

    # Candidati logo in ordine di preferenza. Ognuno scaricato con la
    # guardia SSRF stretta di `_scarica_logo` (host-check post-redirect):
    # se un candidato fallisce il download si ripiega sul successivo,
    # invece di arrendersi al primo url che non scarica.
    candidati: list[str] = []
    letto_header = _leggi_header_html(base, host_comune)
    if letto_header is not None:
        pagina_header, url_header = letto_header
        u = _estrai_logo_header(pagina_header, url_header, host_comune)
        if u:
            candidati.append(u)
    # Brand dei portali Bootstrap-Italia (openweb SVG inline, peopleweb
    # <img>): letto dall'HTML home GIÀ scaricato, nessun fetch extra.
    for estrai in _estrattori_logo_portale():
        u = estrai(testo, base, host_comune)
        if u and u not in candidati:
            candidati.append(u)
    u = _estrai_logo_url(testo, finale)
    if u and u not in candidati:
        candidati.append(u)

    for logo_url in candidati:
        data_uri, logo_hash = _scarica_logo(logo_url, host_comune)
        if data_uri is not None:
            return data_uri, logo_hash
    return None, None


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
