"""Connettore ComWeb (ePublic, D-09): parser reale per la piattaforma ComWeb —
si dichiara nel `generator` (`piattaforma._PEOPLEWEB` non la riguarda: ComWeb
ha una firma propria, `Piattaforma.COMWEB`), pubblica un feed RSS per
categoria.

Scouting reale su Alpignano (TO, `api/tests/fixtures/comweb_*_alpignano.html`,
6 GET live, CK-3: markup non verificabile a tavolino):
- **Home**: `{base}/it-it/home` (redirect dalla root). Header Bootstrap
  Italia: `.it-brand-wrapper` con `<img src="/it-it/immagine/img-..." alt=
  "Stemma Comune di ...">` (NON SVG inline — osservato reale, a differenza
  dell'ipotesi a priori). Nessun `<image xlink:href>` trovato in `<header>`.
- **Uffici**: indice statico `{base}/it-it/amministrazione/uffici` (200
  diretto, confermato reale — NON serve il fallback `/amministrazione/uffici`
  su questo comune). Card `<h3 class="title-xlarge ..."><a href="/it-it/
  amministrazione/uffici/{slug}-{id}-{n}-{hash}">Nome</a></h3>`, nessuna
  paginazione osservata (30 uffici in una sola pagina) — indice-only
  (nome+url), MAI i recapiti (deferred, stesso taglio di
  `openweb._leggi_uffici_openweb`).
- **Aree amministrative**: `{base}/it-it/servizi`, categorie a UN solo
  segmento di path (`/it-it/servizi/{categoria}`, es. `/it-it/servizi/
  ambiente`) — le schede di servizio individuali hanno SEMPRE un secondo
  segmento nested con id numerici e hash (`/it-it/servizi/{categoria}/
  {slug}-{id}-{id}-{hash}`). Sul campione osservato NESSUN link categoria
  termina in `-c"` (il marker ipotizzato da `censimento._ROTTE_SERVIZI` per
  il discriminatore-dettaglio non si è manifestato su questo comune): il
  discriminatore usato qui è la PROFONDITÀ del path (un segmento = categoria,
  due o più = dettaglio), coerente col dato osservato e più robusto di un
  marker mai visto dal vivo.
- **Amministrazione Trasparente**: `{base}/it-it/amministrazione-
  trasparente/` risponde 200 diretto (confermato reale). `bandi_attivi`
  best-effort dal feed RSS per categoria: la home linka un hub feed
  (`/it-it/feed-rss`) che a sua volta linka `/it-it/feed-rss/bandi-e-avvisi-
  di-gara` — URL CONFERMATO dal testo della pagina hub, ma il CONTENUTO
  XML del feed non è stato fetchato in questo ciclo (budget di 6 GET
  esaurito sulla scoperta delle rotte): il parsing `<item><title>/<link>`
  è quindi best-effort dichiarato — un feed che non produce voci riconoscibili
  degrada silenziosamente a `bandi_attivi=[]`, mai un errore.

`leggi_comweb` non solleva MAI: una sezione impraticabile degrada a vuoto/
None per quella sola sezione (stesso taglio di `openweb.leggi_openweb`), le
altre sezioni estraggono comunque.

Guardia security (W1) — stessa forma di `openweb._richiedi_con_guardia`:
schema allow-list http/https, host allow-list = dominio del comune verificato
DOPO il follow-301 (TOCTOU/SSRF), timeout esplicito, size-cap che ABORTISCE
lo streaming (mai un `len()` post-download, W-3). OGNI fetch di questo
modulo (uffici, servizi, probe AT, feed RSS) passa da `_fetch`/
`_richiedi_con_guardia`.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

from treasureiq.connettore import (
    AmministrazioneTrasparente,
    AreaAmministrativa,
    BandoAT,
    EsitoConnettore,
    UfficioConnettore,
)
from treasureiq.ingest.base import USER_AGENT
from treasureiq.ingest.censimento import _Sonda
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www
from treasureiq.sonda_live import ComuneNoto

logger = logging.getLogger(__name__)

#: Piattaforma dichiarata da questo connettore — stringa letterale (non
#: `Piattaforma.COMWEB.value`) per lo stesso motivo di `openweb.
#: PIATTAFORMA_OPENWEB`: il valore letterale è quello che il resto del
#: sistema (dispatcher, D-09) confronta, indipendentemente da come
#: `piattaforma.py` nomina il proprio membro.
PIATTAFORMA_COMWEB = "comweb"

#: Stesso ordine di grandezza del cap-logo/cap-home degli altri connettori
#: (`openweb.py`, `peopleweb.py`) — una pagina ComWeb anomala non deve
#: entrare in RAM intera.
MAX_RISPOSTA_BYTES = 2_000_000

#: Anchor generico, tollerante a markup annidato (`<h3>` fuori O dentro
#: `<a>`, osservato reale sulle card-ufficio di Alpignano: qui è `<h3><a>
#: Nome</a></h3>`, l'opposto di OpenWeb) — stesso stampo di
#: `openweb._RE_ANCORA`.
_RE_ANCORA = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_RE_TAG = re.compile(r"<[^>]+>")

#: Le due rotte AgID convenzionali dell'indice uffici, provate in ordine —
#: nessuna delle due è nel repo (D-09, gap dichiarato): su Alpignano la
#: prima ha risposto 200 diretto.
_ROTTE_UFFICI = ("/it-it/amministrazione/uffici", "/amministrazione/uffici")

#: Cap difensivo sul numero di uffici estratti, stesso taglio di
#: `openweb.MAX_UFFICI_INDICE`.
MAX_UFFICI_INDICE = 200

#: Cap difensivo sul numero di aree amministrative estratte.
MAX_AREE = 200

#: Categoria di servizio: UN solo segmento di path dopo `/it-it/servizi/`
#: (osservato reale su Alpignano: `/it-it/servizi/ambiente`, `/it-it/
#: servizi/anagrafe-e-stato-civile`) — una scheda di dettaglio ha sempre un
#: secondo segmento nested con id numerici e hash, quindi NON matcha questo
#: pattern ancorato a fine-stringa.
_RE_AREA_CATEGORIA = re.compile(r"^/it-it/servizi/[^/\"'?#]+/?$", re.IGNORECASE)

#: Rotta AT convenzionale — confermata reale (200 diretto) su Alpignano.
_ROTTA_AT = "/it-it/amministrazione-trasparente/"

#: Feed RSS per categoria — URL confermato dal testo della pagina hub
#: `/it-it/feed-rss` su Alpignano (il link `/it-it/feed-rss/bandi-e-avvisi-
#: di-gara` compare in chiaro), il CONTENUTO XML non è stato fetchato in
#: questo ciclo (vedi docstring di modulo): parsing best-effort, degrado
#: silenzioso se la forma non produce voci riconoscibili.
_ROTTA_FEED_BANDI = "/it-it/feed-rss/bandi-e-avvisi-di-gara"

#: Cap sul numero di bandi estratti dal feed RSS.
MAX_BANDI = 50

#: Un `<item>...</item>` del feed RSS, con `<title>`/`<link>` interni —
#: tollerante a CDATA (osservato standard su feed RSS 2.0 italiani).
_RE_ITEM = re.compile(r"<item\b[^>]*>(.*?)</item>", re.IGNORECASE | re.DOTALL)
_RE_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_RE_LINK = re.compile(r"<link\b[^>]*>(.*?)</link>", re.IGNORECASE | re.DOTALL)
_RE_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)

#: Il blocco `<header>...</header>` della home, dove OpenWeb tiene il logo
#: inline SVG — provato PRIMA su ComWeb per simmetria di stampo, anche se lo
#: scouting reale (Alpignano) non l'ha mai mostrato: se assente si ripiega
#: sull'`<img>` in `.it-brand-wrapper` (osservato reale).
_RE_IMAGE_TAG = re.compile(r"<image\b[^>]*(?:xlink:href|href)=[\"']([^\"']+)[\"']", re.IGNORECASE)


def _ora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stesso_host(url: str, host_comune: str) -> bool:
    return _host_senza_www(urlparse(url).netloc.lower()) == host_comune


def _richiedi_con_guardia(url: str, host_comune: str, *, timeout: float) -> tuple[str, str] | None:
    """GET guardato (W1) — stesso stampo di `openweb._richiedi_con_guardia`:
    schema http/https, host-check DOPO il follow-301 (TOCTOU/SSRF), size-cap
    che ABORTISCE lo streaming. `None` per qualunque esito non valido.
    Ritorna `(testo, url_finale)`."""
    if urlparse(url).scheme not in ("http", "https"):
        return None
    try:
        with httpx.Client(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            with client.stream("GET", url) as risposta:
                if risposta.status_code != 200:
                    return None
                if not _stesso_host(str(risposta.url), host_comune):
                    logger.warning(
                        "comweb: redirect fuori host scartato %s -> %s", url, risposta.url
                    )
                    return None
                buffer = bytearray()
                for pezzo in risposta.iter_bytes():
                    buffer.extend(pezzo)
                    if len(buffer) > MAX_RISPOSTA_BYTES:
                        logger.info(
                            "comweb: risposta oltre size-cap, connessione interrotta: %s", url
                        )
                        return None
                url_finale = str(risposta.url)
    except Exception:  # noqa: BLE001 — portale ComWeb muto: nessun esito, mai un crash
        logger.info("comweb: pagina irraggiungibile: %s", url)
        return None
    return bytes(buffer).decode("utf-8", errors="replace"), url_finale


def _fetch(url: str, host_comune: str, timeout: float, sonda: _Sonda) -> tuple[str, str] | None:
    """`_richiedi_con_guardia` con lo stesso contatore-costo di `_Sonda`
    (D-08): ogni GET di questo modulo passa da qui."""
    esito = _richiedi_con_guardia(url, host_comune, timeout=timeout)
    if esito is not None:
        sonda.richieste += 1
        sonda.raggiungibile = True
    return esito


def _ancore(pagina: str, base: str, host_comune: str) -> list[tuple[str, str]]:
    """Ogni `<a href>` della pagina come `(url_assoluto, testo_pulito)`,
    solo quelli che restano sul dominio del comune — stesso stampo di
    `openweb._ancore`."""
    trovate: list[tuple[str, str]] = []
    for grezzo, corpo in _RE_ANCORA.findall(pagina):
        href = html.unescape(grezzo).strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        url = urljoin(base, href)
        if not _stesso_host(url, host_comune):
            continue
        testo = html.unescape(_RE_TAG.sub(" ", corpo))
        testo = re.sub(r"\s+", " ", testo).strip()
        trovate.append((url, testo))
    return trovate


def _leggi_uffici_comweb(
    base: str, host_comune: str, sonda: _Sonda, timeout: float
) -> list[UfficioConnettore]:
    """Indice uffici: prova le due rotte AgID convenzionali in ordine
    (`_ROTTE_UFFICI`) — nessuna delle due è verificata nel repo, gap
    dichiarato (D-09). La prima che risponde 200 vince; il pattern di
    dettaglio si deriva dal path RISOLTO di quella rotta (un segmento in
    più, qualunque prefisso), non da una regex fissata a priori — così
    funziona sia per `/it-it/amministrazione/uffici/...` (osservato reale
    su Alpignano) sia per l'eventuale fallback `/amministrazione/uffici/...`.
    Index-only (nome+url), MAI i recapiti (deferred, stesso taglio di
    `openweb._leggi_uffici_openweb`)."""
    ora = _ora()
    for rotta in _ROTTE_UFFICI:
        url_indice = urljoin(base, rotta)
        letto = _fetch(url_indice, host_comune, timeout, sonda)
        if letto is None:
            continue
        pagina, url_finale = letto
        prefisso_path = urlparse(url_finale).path.rstrip("/")
        if not prefisso_path:
            continue
        re_dettaglio = re.compile(re.escape(prefisso_path) + r"/[^\"'?#]+", re.IGNORECASE)

        uffici: list[UfficioConnettore] = []
        visti: set[str] = set()
        for url, testo in _ancore(pagina, url_finale, host_comune):
            if not re_dettaglio.search(urlparse(url).path) or url in visti or not testo:
                continue
            visti.add(url)
            uffici.append(
                UfficioConnettore(nome=testo, url=url, source_typed=False, letto_il=ora)
            )
            if len(uffici) >= MAX_UFFICI_INDICE:
                break
        return uffici
    return []


def _leggi_aree_comweb(
    base: str, host_comune: str, sonda: _Sonda, timeout: float
) -> list[AreaAmministrativa]:
    """`aree_amministrative`: categorie di `{base}/it-it/servizi` — un
    segmento di path dopo `/servizi/`, discriminatore osservato reale
    (vedi docstring di modulo). Fetch fallito o markup senza questa forma
    → `[]` onesto."""
    url = urljoin(base, "/it-it/servizi")
    letto = _fetch(url, host_comune, timeout, sonda)
    if letto is None:
        return []
    pagina, url_finale = letto
    aree: list[AreaAmministrativa] = []
    visti: set[str] = set()
    for url_area, testo in _ancore(pagina, url_finale, host_comune):
        if not _RE_AREA_CATEGORIA.search(urlparse(url_area).path) or url_area in visti or not testo:
            continue
        visti.add(url_area)
        aree.append(AreaAmministrativa(nome=testo, url=url_area))
        if len(aree) >= MAX_AREE:
            break
    return aree


def _leggi_bandi_feed_comweb(
    base: str, host_comune: str, sonda: _Sonda, timeout: float
) -> list[BandoAT]:
    """`bandi_attivi` best-effort dal feed RSS per categoria
    (`bandi-e-avvisi-di-gara`, URL confermato dal testo dell'hub feed su
    Alpignano — vedi docstring di modulo). Il contenuto XML non è stato
    verificato dal vivo in questo ciclo: un fetch riuscito ma senza `<item>`
    riconoscibili degrada a `[]`, MAI un errore — stesso principio D-10
    degli altri connettori. Titoli verbatim, nessun fetch dei PDF."""
    url = urljoin(base, _ROTTA_FEED_BANDI)
    letto = _fetch(url, host_comune, timeout, sonda)
    if letto is None:
        return []
    feed, url_finale = letto
    bandi: list[BandoAT] = []
    for blocco in _RE_ITEM.findall(feed):
        match_titolo = _RE_TITLE.search(blocco)
        match_link = _RE_LINK.search(blocco)
        if match_titolo is None or match_link is None:
            continue
        titolo = _RE_CDATA.sub(r"\1", match_titolo.group(1)).strip()
        link = _RE_CDATA.sub(r"\1", match_link.group(1)).strip()
        titolo = html.unescape(titolo)
        link = html.unescape(link)
        if not titolo or not link:
            continue
        url_bando = urljoin(url_finale, link)
        if not _stesso_host(url_bando, host_comune):
            continue
        bandi.append(BandoAT(titolo=titolo, url=url_bando, pdf_url=None))
        if len(bandi) >= MAX_BANDI:
            break
    return bandi


def _leggi_at_comweb(
    base: str, host_comune: str, sonda: _Sonda, timeout: float
) -> AmministrazioneTrasparente:
    """Amministrazione Trasparente: prova la rotta convenzionale
    (confermata reale, 200 diretto, su Alpignano); se non risponde si tiene
    comunque l'`indice_url` convenzionale SENZA conferma (D-10, link noto
    non verificato) — mai `None` per questa sezione, a differenza di
    OpenWeb/PeopleWeb dove l'AT può mancare del tutto: qui la rotta è
    talmente standard (dichiarata dal task) da valere come default onesto.
    `bandi_attivi` è il best-effort del feed RSS (`_leggi_bandi_feed_comweb`),
    mai fatale se vuoto."""
    url_at = urljoin(base, _ROTTA_AT)
    letto = _fetch(url_at, host_comune, timeout, sonda)
    indice_url = letto[1] if letto is not None else url_at

    bandi_attivi = _leggi_bandi_feed_comweb(base, host_comune, sonda, timeout)

    return AmministrazioneTrasparente(
        indice_url=indice_url,
        bandi_attivi=bandi_attivi,
        pdf_presenti=False,
    )


def estrai_logo_comweb(pagina_home: str, base: str, host_comune: str) -> str | None:
    """Il logo del comune: prova PRIMA l'SVG inline dentro `<header>`
    (stesso stampo di `openweb.estrai_logo_openweb`, mai osservato reale su
    ComWeb ma provato per simmetria), poi ripiega sull'`<img>` in
    `.it-brand-wrapper` (osservato reale su Alpignano: `<img src="/it-it/
    immagine/img-...">` dentro `.it-brand-wrapper`, stesso stampo di
    `peopleweb.estrai_logo_peopleweb`). Guardia same-host STRETTA
    (`_stesso_host`, non la variante tollerante-a-sottodominio di OpenWeb):
    un `src` fuori dal dominio esatto del comune non diventa mai il logo.
    Pura — nessun fetch."""
    pagina_lower = pagina_home.lower()

    inizio_header = pagina_lower.find("<header")
    if inizio_header != -1:
        fine_header = pagina_lower.find("</header>", inizio_header)
        if fine_header == -1:
            fine_header = inizio_header + 40_000  # margine di cortesia, non l'intera pagina
        blocco_header = pagina_home[inizio_header:fine_header]
        match_svg = _RE_IMAGE_TAG.search(blocco_header)
        if match_svg is not None:
            href = html.unescape(match_svg.group(1)).strip()
            if href:
                url = urljoin(base, href)
                if _stesso_host(url, host_comune):
                    return url

    inizio_brand = pagina_lower.find("it-brand-wrapper")
    if inizio_brand == -1:
        return None
    finestra = pagina_home[inizio_brand : inizio_brand + 1500]
    match_img = re.search(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', finestra, re.IGNORECASE)
    if match_img is None:
        return None
    src = html.unescape(match_img.group(1)).strip()
    if not src:
        return None
    url = urljoin(base, src)
    if not _stesso_host(url, host_comune):
        return None
    return url


def leggi_comweb(comune: ComuneNoto, sonda: _Sonda) -> EsitoConnettore:
    """Contratto D-09 per la piattaforma ComWeb (ePublic). Firma congelata
    come `openweb.leggi_openweb`: `(comune, sonda) -> EsitoConnettore`, MAI
    `None` — un comune senza nulla da leggere è un esito vuoto onesto
    (`connettore._esito_vuoto` lo riconosce), non un guasto.

    Non solleva mai: una sezione impraticabile resta al degrado (uffici/AT/
    aree vuoti per quella sola sezione), le altre sezioni estraggono
    comunque — stesso taglio di `openweb.leggi_openweb`.
    """
    letto_il = _ora()
    base = _base_con_schema(comune.sito)
    if base is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=PIATTAFORMA_COMWEB, letto_il=letto_il
        )
    host_comune = _host_senza_www(urlparse(base).netloc.lower())

    letta = _richiedi_con_guardia(base, host_comune, timeout=8.0)
    if letta is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=PIATTAFORMA_COMWEB, letto_il=letto_il
        )
    # Stesso contatore di `_Sonda._get`/`.risposta` (D-08): la richiesta
    # guardata bypassa `_Sonda` per lo streaming, ma il costo verso il
    # portale va comunque contato.
    sonda.richieste += 1
    sonda.raggiungibile = True
    pagina_home, url_home_finale = letta

    try:
        uffici = _leggi_uffici_comweb(url_home_finale, host_comune, sonda, 8.0)
    except Exception:  # noqa: BLE001 — indice uffici muto: esito senza uffici, mai un crash
        logger.warning("comweb: lettura indice uffici fallita per %s", comune.nome)
        uffici = []

    try:
        amministrazione_trasparente = _leggi_at_comweb(url_home_finale, host_comune, sonda, 8.0)
    except Exception:  # noqa: BLE001 — catena AT muta: esito senza AT, mai un crash
        logger.warning("comweb: lettura amministrazione trasparente fallita per %s", comune.nome)
        amministrazione_trasparente = None

    try:
        aree = _leggi_aree_comweb(url_home_finale, host_comune, sonda, 8.0)
    except Exception:  # noqa: BLE001 — categorie servizi mute: esito senza aree, mai un crash
        logger.warning("comweb: lettura aree amministrative fallita per %s", comune.nome)
        aree = []

    return EsitoConnettore(
        codice_istat=comune.codice_istat,
        piattaforma=PIATTAFORMA_COMWEB,
        letto_il=letto_il,
        aree_amministrative=aree,
        uffici=uffici,
        amministrazione_trasparente=amministrazione_trasparente,
    )


def _leggi_comweb_cli(codice_istat: str, *, timeout: float = 8.0) -> None:
    """Uso standalone (`python -m treasureiq.comweb <istat>`), stesso
    stampo del CLI di `openweb.py`."""
    from treasureiq.sonda_live import comune_per_codice

    comune = comune_per_codice(codice_istat)
    if comune is None:
        print(f"comune non trovato: {codice_istat}")
        return
    with _Sonda(timeout=timeout) as sonda:
        esito = leggi_comweb(comune, sonda)
    print(esito.model_dump_json(indent=1))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Connettore ComWeb/ePublic (D-09)")
    parser.add_argument("codice_istat", help="codice ISTAT del comune (es. 001008 Alpignano)")
    parser.add_argument("--timeout", type=float, default=8.0, help="timeout per richiesta (default 8.0)")
    args = parser.parse_args()
    _leggi_comweb_cli(args.codice_istat, timeout=args.timeout)
