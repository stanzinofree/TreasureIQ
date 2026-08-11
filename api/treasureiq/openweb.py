"""Connettore OpenWeb (SoluzioniPA, D-09): parser reale per la piattaforma
OpenWeb — sottoinsieme della firma condivisa `PEOPLEWEB` (Bootstrap Italia)
che, in verità, conflate DUE vendor distinti: Siscom PeopleWeb (ASP.NET
WebForms, `/Servizi?ID=###`) e SoluzioniPA OpenWeb (WordPress, permalink
`/amministrazione/...`). Questo modulo copre solo il secondo — vedi
`leggi_openweb` per il discriminatore osservato.

Scouting reale su Collegno (TO, `api/tests/fixtures/openweb_*.html`) e
Gargallo (NO, solo verifica live, markup non salvato a fixture — CK-3):
- **Uffici**: indice statico WordPress `{base}/amministrazione/uffici/`,
  paginato (`/amministrazione/uffici/page/N/`, WP standard). Ogni scheda-
  ufficio ha un anchor `{base}/amministrazione/unita_organizzativa/{slug}/`
  con il nome dentro un `<h3>` annidato — stesso stampo tollerante-a-markup
  di `egov._ancore` (testo pulito rimuovendo i tag interni). Index-only:
  nome+url, MAI i recapiti — le schede individuali restano deferred, fuori
  scope di questo ciclo, stesso taglio di `egov._leggi_uffici_egov`.
- **Amministrazione Trasparente**: VARIA per comune (osservato reale) — a
  volte una pagina same-domain (`{base}/amministrazione/amministrazione-
  trasparente/`, 200 diretto o dietro un redirect same-host), a volte un
  sottodominio vendor fuori dal dominio del comune (`{slug}.soluzionipa.it/
  openweb/trasparenza/` o `portale.comune.*/openweb/trasparenza/`, osservato
  su Collegno: la pagina same-domain risponde 404). Nel secondo caso il link
  si trova per TESTO/HREF nella home (pattern vendor `soluzionipa.it` o
  `/openweb/trasparenza`), MAI fetchato — resta un link noto (D-10), non un
  contenuto letto: è fuori dal dominio del comune, quindi fuori dal
  perimetro della guardia SSRF same-host di questo modulo.
- **Aree amministrative**: best-effort dalle categorie di `{base}/servizi/`
  (`/servizi-categoria/{slug}/`, un solo GET in più) — se il fetch fallisce
  o il markup non presenta questa forma, lista vuota onesta: gli uffici
  restano il risultato principale di questo connettore, non le aree.

`leggi_openweb` non solleva MAI: una sezione impraticabile degrada a vuoto/
None per quella sola sezione (stesso taglio di `egov.leggi_egov`), le altre
sezioni estraggono comunque.

Guardia security (W1) — stessa forma di `egov._richiedi_con_guardia` e
`municipium.py:246`: schema allow-list http/https, host allow-list = dominio
del comune verificato DOPO il follow-301 (TOCTOU/SSRF), timeout esplicito,
size-cap che ABORTISCE lo streaming (mai un `len()` post-download, W-3).
OGNI fetch di questo modulo (uffici, paginazione, probe AT same-domain,
servizi) passa da `_fetch`/`_richiedi_con_guardia`. Il link AT vendor
fuori-dominio è un'eccezione dichiarata: si estrae dal testo HTML della
home già letta, non si fetcha mai.
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
    EsitoConnettore,
    UfficioConnettore,
)
from treasureiq.ingest.base import USER_AGENT
from treasureiq.ingest.censimento import _Sonda
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www
from treasureiq.sonda_live import ComuneNoto

logger = logging.getLogger(__name__)

#: Piattaforma dichiarata da questo connettore. Nessun membro `OPENWEB` in
#: `Piattaforma` (enum) ad oggi — questa stringa letterale coincide col
#: valore che avrebbe un futuro `Piattaforma.OPENWEB.value` (vedi nota di
#: integrazione nel report), MAI un'importazione da un membro che non esiste.
PIATTAFORMA_OPENWEB = "openweb"

#: Stesso ordine di grandezza del cap-logo/cap-home di `registro.py` — una
#: pagina WordPress anomala non deve entrare in RAM intera.
MAX_RISPOSTA_BYTES = 2_000_000

#: Anchor generico, tollerante a markup annidato (`<h3>`/`<span>` dentro
#: `<a>` — reale sulle card-ufficio di Collegno): stesso stampo di
#: `egov._RE_ANCORA` + `egov._RE_TAG`.
_RE_ANCORA = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_RE_TAG = re.compile(r"<[^>]+>")

#: La scheda-ufficio individuale (D-09 osservato: Collegno) — permalink
#: WordPress uniforme sulla piattaforma OpenWeb.
_RE_UNITA_URL = re.compile(r"/amministrazione/unita_organizzativa/[^\"'?#]+/?", re.IGNORECASE)

#: La pagina N dell'indice uffici (paginazione WP standard).
_RE_PAGE_URL = re.compile(r"/amministrazione/uffici/page/(\d+)/?", re.IGNORECASE)

#: Cap sul numero di pagine dell'indice uffici seguite in paginazione — non
#: c'è ragione di aspettarsi più di poche decine di pagine per comune, e
#: questo tiene lo sweep gentile (poche GET/comune).
MAX_PAGINE_UFFICI = 10

#: Cap difensivo sul numero di uffici estratti, stesso taglio di
#: `egov.MAX_UFFICI_INDICE`.
MAX_UFFICI_INDICE = 200

#: Categoria di servizio (D-09 osservato: Collegno) — best-effort per
#: `aree_amministrative`, non il risultato principale di questo connettore.
_RE_SERVIZI_CATEGORIA = re.compile(r"/servizi-categoria/[^\"'?#]+/?", re.IGNORECASE)

#: Il link vendor di Amministrazione Trasparente quando NON è same-domain
#: (osservato reale: Collegno risponde 404 sulla pagina same-domain e la AT
#: reale vive su un sottodominio SoluzioniPA/OpenWeb) — MAI fetchato, solo
#: estratto dalla home già letta (fuori dal perimetro SSRF di questo modulo:
#: è per costruzione un dominio diverso da quello del comune).
_RE_AT_HREF_VENDOR = re.compile(
    r'href=["\']([^"\']*(?:soluzionipa\.it|/openweb/trasparenza|amministrazione-trasparente)[^"\']*)["\']',
    re.IGNORECASE,
)

#: Il blocco `<header>...</header>` della home, dove vive il logo inline
#: SVG (osservato reale: Collegno, `<image xlink:href=...>` dentro `<svg>`
#: dentro `<header>`).
_RE_IMAGE_TAG = re.compile(r"<image\b[^>]*(?:xlink:href|href)=[\"']([^\"']+)[\"']", re.IGNORECASE)


def _ora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stesso_host(url: str, host_comune: str) -> bool:
    return _host_senza_www(urlparse(url).netloc.lower()) == host_comune


def _stesso_sito(url: str, host_comune: str) -> bool:
    """Come `_stesso_host`, ma tollerante a un sottodominio del dominio del
    comune (osservato reale: il logo di Collegno vive su `static-www.
    comune.collegno.to.it`, un CDN dello stesso sito, non l'host esatto
    della home). Un dominio genuinamente diverso (`evil.example.com`,
    `soluzionipa.it`) NON termina con `.{host_comune}` e resta scartato —
    stessa intenzione della guardia di `registro._estrai_logo_header`, solo
    meno stretta sull'uguaglianza esatta dell'host. Usata SOLO dall'
    estrattore logo (nessun fetch coinvolto): i fetch guardati di questo
    modulo restano su `_stesso_host` stretto."""
    host_url = _host_senza_www(urlparse(url).netloc.lower())
    return host_url == host_comune or host_url.endswith("." + host_comune)


def _richiedi_con_guardia(url: str, host_comune: str, *, timeout: float) -> tuple[str, str] | None:
    """GET guardato (W1) — stesso stampo di `egov._richiedi_con_guardia`:
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
                        "openweb: redirect fuori host scartato %s -> %s", url, risposta.url
                    )
                    return None
                buffer = bytearray()
                for pezzo in risposta.iter_bytes():
                    buffer.extend(pezzo)
                    if len(buffer) > MAX_RISPOSTA_BYTES:
                        logger.info(
                            "openweb: risposta oltre size-cap, connessione interrotta: %s", url
                        )
                        return None
                url_finale = str(risposta.url)
    except Exception:  # noqa: BLE001 — portale OpenWeb muto: nessun esito, mai un crash
        logger.info("openweb: pagina irraggiungibile: %s", url)
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
    `egov._ancore`."""
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


def _leggi_uffici_openweb(
    base: str, host_comune: str, sonda: _Sonda, timeout: float
) -> list[UfficioConnettore]:
    """Indice uffici WordPress, paginato: index-only (nome+url), MAI i
    recapiti (deferred, on-demand — stesso taglio di
    `egov._leggi_uffici_egov`). Il pager WP reale (osservato Collegno) è a
    finestra scorrevole con ellissi (`1 2 3 ... 6 7`): la pagina 1 non linka
    necessariamente `page/4/` anche se esiste — per questo si tiene il
    massimo numero di pagina VISTO fin qui (aggiornato ad ogni pagina letta,
    non solo dalla prima) e si avanza in sequenza fino a quel massimo, mai
    oltre `MAX_PAGINE_UFFICI`. Fermarsi solo su un fetch fallito o
    sull'esaurimento delle pagine conosciute — non su un singolo `N+1`
    assente dal pager visibile."""
    ora = _ora()
    uffici: list[UfficioConnettore] = []
    visti: set[str] = set()
    url_corrente = urljoin(base, "/amministrazione/uffici/")
    pagina_num = 1
    massima_pagina_vista = 1

    while pagina_num <= min(massima_pagina_vista, MAX_PAGINE_UFFICI):
        letto = _fetch(url_corrente, host_comune, timeout, sonda)
        if letto is None:
            break
        pagina, url_finale = letto

        for url, testo in _ancore(pagina, url_finale, host_comune):
            if not _RE_UNITA_URL.search(url) or url in visti or not testo:
                continue
            visti.add(url)
            uffici.append(
                UfficioConnettore(nome=testo, url=url, source_typed=False, letto_il=ora)
            )
            if len(uffici) >= MAX_UFFICI_INDICE:
                return uffici

        numeri_pagina_linkati = {int(n) for n in _RE_PAGE_URL.findall(pagina)}
        if numeri_pagina_linkati:
            massima_pagina_vista = max(massima_pagina_vista, max(numeri_pagina_linkati))
        pagina_num += 1
        url_corrente = urljoin(base, f"/amministrazione/uffici/page/{pagina_num}/")

    return uffici


def _leggi_aree_openweb(
    base: str, host_comune: str, sonda: _Sonda, timeout: float
) -> list[AreaAmministrativa]:
    """`aree_amministrative`: categorie di `{base}/servizi/`, best-effort —
    un solo GET in più. Fetch fallito o markup senza questa forma → `[]`
    onesto: gli uffici restano il risultato principale di questo
    connettore."""
    url = urljoin(base, "/servizi/")
    letto = _fetch(url, host_comune, timeout, sonda)
    if letto is None:
        return []
    pagina, url_finale = letto
    aree: list[AreaAmministrativa] = []
    visti: set[str] = set()
    for url_area, testo in _ancore(pagina, url_finale, host_comune):
        if not _RE_SERVIZI_CATEGORIA.search(url_area) or url_area in visti or not testo:
            continue
        visti.add(url_area)
        aree.append(AreaAmministrativa(nome=testo, url=url_area))
    return aree


def _cerca_link_at_vendor(pagina_home: str, base: str) -> str | None:
    """Il link vendor di Amministrazione Trasparente (SoluzioniPA/OpenWeb)
    quando non è same-domain — scansione TESTUALE della home già letta, MAI
    un fetch: per costruzione un dominio diverso dal comune, fuori dal
    perimetro della guardia SSRF di questo modulo (D-10, link noto, non
    contenuto letto)."""
    for grezzo in _RE_AT_HREF_VENDOR.findall(pagina_home):
        href = html.unescape(grezzo).strip()
        if not href or href.startswith("#") or "servizi-categoria" in href.lower():
            continue
        return urljoin(base, href)
    return None


def _leggi_at_openweb(
    pagina_home: str, base: str, host_comune: str, sonda: _Sonda, timeout: float
) -> AmministrazioneTrasparente | None:
    """Amministrazione Trasparente: prova la pagina same-domain, poi
    ripiega sul link vendor letto dalla home (osservato reale: Collegno
    risponde 404 same-domain, la AT reale vive su sottodominio SoluzioniPA).
    Solo `indice_url` — bandi/PDF restano fuori scope di questo ciclo
    (index-only, stesso taglio di `uffici`)."""
    url_same_domain = urljoin(base, "/amministrazione/amministrazione-trasparente/")
    letto = _fetch(url_same_domain, host_comune, timeout, sonda)
    if letto is not None:
        _, url_finale = letto
        return AmministrazioneTrasparente(indice_url=url_finale)

    link_vendor = _cerca_link_at_vendor(pagina_home, base)
    if link_vendor is not None:
        return AmministrazioneTrasparente(indice_url=link_vendor)
    return None


def estrai_logo_openweb(pagina_home: str, base: str, host_comune: str) -> str | None:
    """Il logo del comune: `<image xlink:href=...>`/`href=...` inline SVG
    dentro `<header>` (osservato reale: Collegno). Pura — nessun fetch.
    Same-SITO (non same-host esatto, `_stesso_sito`): un `src` fuori dal
    dominio del comune non diventa mai il logo, ma un CDN sotto lo stesso
    dominio (`static-www.comune.collegno.to.it`, osservato reale) sì —
    mirror ADATTATO della guardia di `registro._estrai_logo_header` (che è
    same-host esatto: da rivalutare in integrazione se il download reale in
    `registro._scarica_logo` deve accettare lo stesso sottodominio, vedi
    report)."""
    pagina_lower = pagina_home.lower()
    inizio = pagina_lower.find("<header")
    if inizio == -1:
        return None
    fine = pagina_lower.find("</header>", inizio)
    if fine == -1:
        fine = inizio + 40_000  # margine di cortesia, non l'intera pagina
    blocco = pagina_home[inizio:fine]

    match = _RE_IMAGE_TAG.search(blocco)
    if match is None:
        return None
    href = html.unescape(match.group(1)).strip()
    if not href:
        return None
    url = urljoin(base, href)
    if not _stesso_sito(url, host_comune):
        return None
    return url


def leggi_openweb(comune: ComuneNoto, sonda: _Sonda) -> EsitoConnettore:
    """Contratto D-09 per la piattaforma OpenWeb (SoluzioniPA). Firma
    congelata come `egov.leggi_egov`: `(comune, sonda) -> EsitoConnettore`,
    MAI `None` — un comune senza nulla da leggere è un esito vuoto onesto
    (`connettore._esito_vuoto` lo riconosce), non un guasto.

    DISCRIMINATORE OpenWeb vs Siscom-PeopleWeb (entrambi dietro la stessa
    firma `Piattaforma.PEOPLEWEB`, D-09 osservato ciclo 15): Siscom è
    ASP.NET WebForms (`/Servizi?ID=###`, mappa `/Mappasito`); OpenWeb è
    WordPress (permalink `/amministrazione/unita_organizzativa/{slug}/`,
    `/servizi-categoria/{slug}/`, asset `wp-content`). Questo connettore
    NON fa la disambiguazione da solo — vedi report di integrazione per il
    punto esatto dove va agganciata nel dispatcher.

    Non solleva mai: una sezione impraticabile resta al degrado (uffici/AT/
    aree vuoti per quella sola sezione), le altre estraggono comunque —
    stesso taglio di `egov.leggi_egov`.
    """
    letto_il = _ora()
    base = _base_con_schema(comune.sito)
    if base is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=PIATTAFORMA_OPENWEB, letto_il=letto_il
        )
    host_comune = _host_senza_www(urlparse(base).netloc.lower())

    letta = _richiedi_con_guardia(base, host_comune, timeout=8.0)
    if letta is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=PIATTAFORMA_OPENWEB, letto_il=letto_il
        )
    # Stesso contatore di `_Sonda._get`/`.risposta` (D-08): la richiesta
    # guardata bypassa `_Sonda` per lo streaming, ma il costo verso il
    # portale va comunque contato.
    sonda.richieste += 1
    sonda.raggiungibile = True
    pagina_home, url_home_finale = letta

    try:
        uffici = _leggi_uffici_openweb(url_home_finale, host_comune, sonda, 8.0)
    except Exception:  # noqa: BLE001 — indice uffici muto: esito senza uffici, mai un crash
        logger.warning("openweb: lettura indice uffici fallita per %s", comune.nome)
        uffici = []

    try:
        amministrazione_trasparente = _leggi_at_openweb(
            pagina_home, url_home_finale, host_comune, sonda, 8.0
        )
    except Exception:  # noqa: BLE001 — catena AT muta: esito senza AT, mai un crash
        logger.warning("openweb: lettura amministrazione trasparente fallita per %s", comune.nome)
        amministrazione_trasparente = None

    try:
        aree = _leggi_aree_openweb(url_home_finale, host_comune, sonda, 8.0)
    except Exception:  # noqa: BLE001 — categorie servizi mute: esito senza aree, mai un crash
        logger.warning("openweb: lettura aree amministrative fallita per %s", comune.nome)
        aree = []

    return EsitoConnettore(
        codice_istat=comune.codice_istat,
        piattaforma=PIATTAFORMA_OPENWEB,
        letto_il=letto_il,
        aree_amministrative=aree,
        uffici=uffici,
        amministrazione_trasparente=amministrazione_trasparente,
    )


def _leggi_openweb_cli(codice_istat: str, *, timeout: float = 8.0) -> None:
    """Uso standalone (`python -m treasureiq.openweb <istat>`), stesso
    stampo del CLI di `egov.py`."""
    from treasureiq.sonda_live import comune_per_codice

    comune = comune_per_codice(codice_istat)
    if comune is None:
        print(f"comune non trovato: {codice_istat}")
        return
    with _Sonda(timeout=timeout) as sonda:
        esito = leggi_openweb(comune, sonda)
    print(esito.model_dump_json(indent=1))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Connettore OpenWeb/SoluzioniPA (D-09)")
    parser.add_argument("codice_istat", help="codice ISTAT del comune (es. 001090 Collegno)")
    parser.add_argument("--timeout", type=float, default=8.0, help="timeout per richiesta (default 8.0)")
    args = parser.parse_args()
    _leggi_openweb_cli(args.codice_istat, timeout=args.timeout)
