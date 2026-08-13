"""Connettore OpenPA (Maggioli/OpenCity, D-09): parser reale per la
piattaforma OpenPA — riconosciuta a monte da
`ingest.piattaforma._DA_IMPRONTA` (directory `argomenti|content|extension`,
`Piattaforma.OPENPA`).

Scouting reale su Storo (TN, `api/tests/fixtures/openpa_storo_*.html`) e
Lodrino (BS, solo verifica live, markup non salvato a fixture — stesso
vincolo CK-3 di `openweb.py`/Gargallo):
- **Uffici**: indice statico `{base}/Amministrazione/Uffici` — card-grid con
  anchor `{base}/Amministrazione/Uffici/{slug}#page-content` e nome dentro un
  `<h3 class="card-title...">` annidato (stesso stampo tollerante-a-markup di
  `egov._ancore`/`openweb._ancore`). Nessuna paginazione osservata (Storo: 9
  card su una sola pagina) — index-only: nome+url, MAI i recapiti, stesso
  taglio di `egov._leggi_uffici_egov`.
- **Aree amministrative**: OpenPA raggruppa i contenuti sotto `Argomenti`
  (temi, non servizi) — indice `{base}/Argomenti`, gerarchico
  (`/Argomenti/{Tema}` e sotto-temi `/Argomenti/{Tema}/{Sotto}`). Si tiene
  SOLO il livello 1 (`/Argomenti/{Tema}`, due segmenti di path): il livello 2
  è già dettaglio, fuori scope di un indice aree.
- **Amministrazione Trasparente**: `{base}/Amministrazione-Trasparente`,
  confermato 200 reale su ENTRAMBI i comuni scoutati — rotta OpenPA
  convenzionale, non un'ipotesi. A differenza di `openweb`/`peopleweb`
  (che tornano `None` se il probe fallisce), qui l'indice_url convenzionale
  si registra COMUNQUE anche a probe fallito (rotta osservata 2/2, non
  un'invenzione): solo `bandi_attivi`/`pdf_presenti` restano ai default
  onesti, nessun drill.
- **Logo**: `<img class="icon" alt="Logo ...">` dentro `.it-brand-wrapper`
  (tema Bootstrap Italia, stesso stampo di `openweb`/`peopleweb`), ma il
  `src` osservato su ENTRAMBI i comuni scoutati non è mai same-host: vive su
  un proxy-immagini del vendor (`flyimg.opencityitalia.it`, che a sua volta
  incapsula un URL S3 `static.opencity.opencontent.it`) — un CDN del
  fornitore, non un sottodominio del comune. Con la guardia same-host
  stretta richiesta da questo connettore, il logo degrada a `None` su
  ENTRAMBI i campioni reali: gap onesto documentato, non un bug — nessun
  `<img>`/`<svg>` alternativo same-host è stato osservato nell'header di
  nessuno dei due comuni.

`leggi_openpa` non solleva MAI: una sezione impraticabile degrada a vuoto/
None per quella sola sezione, le altre sezioni estraggono comunque — stesso
taglio di `egov.leggi_egov`/`openweb.leggi_openweb`.

Guardia security (W1) — stessa forma di `egov._richiedi_con_guardia` e
`openweb._richiedi_con_guardia`: schema allow-list http/https, host
allow-list = dominio del comune verificato DOPO il follow-301
(TOCTOU/SSRF), timeout esplicito, size-cap che ABORTISCE lo streaming (mai
un `len()` post-download, W-3). OGNI fetch di questo modulo (home, uffici,
argomenti, probe AT) passa da `_fetch`/`_richiedi_con_guardia`.
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

#: Piattaforma dichiarata da questo connettore — coincide col valore di
#: `Piattaforma.OPENPA.value` (`ingest/piattaforma.py:73`).
PIATTAFORMA_OPENPA = "openpa"

#: Stesso ordine di grandezza del cap-logo/cap-home di `registro.py`/
#: `openweb.py` — una pagina OpenPA anomala non deve entrare in RAM intera.
MAX_RISPOSTA_BYTES = 2_000_000

#: Anchor generico, tollerante a markup annidato (`<h3>` dentro `<a>` —
#: osservato reale sulle card-ufficio di Storo) e a entrambi gli apici,
#: stesso stampo di `egov._RE_ANCORA`/`openweb._RE_ANCORA`.
_RE_ANCORA = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_RE_TAG = re.compile(r"<[^>]+>")

#: Cap difensivo sul numero di uffici estratti — stesso taglio di
#: `egov.MAX_UFFICI_INDICE`/`openweb.MAX_UFFICI_INDICE`.
MAX_UFFICI_INDICE = 200


def _ora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stesso_host(url: str, host_comune: str) -> bool:
    return _host_senza_www(urlparse(url).netloc.lower()) == host_comune


#: Il CDN di brand OpenCity/OpenContent: il logo dei comuni OpenPA non vive
#: mai sull'host del comune ma su un proxy-immagini del fornitore
#: (`flyimg.opencityitalia.it` che incapsula `static.opencity.opencontent.it`).
#: Con la sola guardia same-host il logo degradava a `None` su TUTTI i campioni
#: reali. Allowlist per-suffisso (scelta: confinata al fornitore, tollerante ai
#: sottodomini) — non un any-host: un `src` fuori da questi domini resta scartato.
_CDN_LOGO_OPENCITY = (".opencityitalia.it", ".opencontent.it")


def _host_logo_ammesso(url: str, host_comune: str) -> bool:
    """Il `src` del logo è sull'host del comune o sul CDN OpenCity del vendor."""
    if _stesso_host(url, host_comune):
        return True
    host = urlparse(url).hostname or ""
    return host.lower().endswith(_CDN_LOGO_OPENCITY)


def _richiedi_con_guardia(url: str, host_comune: str, *, timeout: float) -> tuple[str, str] | None:
    """GET guardato (W1) — stesso stampo di `openweb._richiedi_con_guardia`:
    schema http/https, host-check DOPO il follow-301 (TOCTOU/SSRF), size-cap
    che ABORTISCE lo streaming. Ritorna `(testo, url_finale)`."""
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
                        "openpa: redirect fuori host scartato %s -> %s", url, risposta.url
                    )
                    return None
                buffer = bytearray()
                for pezzo in risposta.iter_bytes():
                    buffer.extend(pezzo)
                    if len(buffer) > MAX_RISPOSTA_BYTES:
                        logger.info(
                            "openpa: risposta oltre size-cap, connessione interrotta: %s", url
                        )
                        return None
                url_finale = str(risposta.url)
    except Exception:  # noqa: BLE001 — portale OpenPA muto: nessun esito, mai un crash
        logger.info("openpa: pagina irraggiungibile: %s", url)
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
    `egov._ancore`/`openweb._ancore`."""
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


def _segmenti_path(url: str) -> list[str]:
    """Il path dell'url spezzato in segmenti non vuoti, minuscoli — per
    riconoscere la profondità di una rotta senza dipendere da apici/
    fragment/querystring (`#page-content` osservato su Storo)."""
    return [p for p in urlparse(url).path.lower().split("/") if p]


def _e_scheda_ufficio(url: str) -> bool:
    """Vero per la scheda-ufficio individuale (`{base}/Amministrazione/
    Uffici/{slug}`, osservato reale: Storo) — profondità 3, MAI l'indice
    stesso (`{base}/Amministrazione/Uffici`, profondità 2), che comparirebbe
    come link di rientro nella stessa pagina."""
    segmenti = _segmenti_path(url)
    return len(segmenti) >= 3 and segmenti[0] == "amministrazione" and segmenti[1] == "uffici"


def _leggi_uffici_openpa(
    base: str, host_comune: str, sonda: _Sonda, timeout: float
) -> list[UfficioConnettore]:
    """Indice uffici OpenPA: `{base}/Amministrazione/Uffici`, index-only
    (nome+url), MAI i recapiti (deferred — stesso taglio di
    `egov._leggi_uffici_egov`). Nessuna paginazione osservata sul campione
    scoutato: una sola pagina, cap difensivo comunque applicato."""
    url = urljoin(base, "/Amministrazione/Uffici")
    letto = _fetch(url, host_comune, timeout, sonda)
    if letto is None:
        return []
    pagina, url_finale = letto
    ora = _ora()
    uffici: list[UfficioConnettore] = []
    visti: set[str] = set()
    for url_ufficio, testo in _ancore(pagina, url_finale, host_comune):
        if not _e_scheda_ufficio(url_ufficio) or url_ufficio in visti or not testo:
            continue
        visti.add(url_ufficio)
        uffici.append(
            UfficioConnettore(nome=testo, url=url_ufficio, source_typed=False, letto_il=ora)
        )
        if len(uffici) >= MAX_UFFICI_INDICE:
            break
    return uffici


def _e_argomento_primo_livello(url: str) -> bool:
    """Vero per un tema di primo livello (`{base}/Argomenti/{Tema}`,
    profondità 2) — i sotto-temi (`/Argomenti/{Tema}/{Sotto}`, profondità 3+,
    osservati reali su Storo) sono già dettaglio, fuori scope di un indice
    aree amministrative."""
    segmenti = _segmenti_path(url)
    return len(segmenti) == 2 and segmenti[0] == "argomenti"


def _leggi_aree_openpa(
    base: str, host_comune: str, sonda: _Sonda, timeout: float
) -> list[AreaAmministrativa]:
    """`aree_amministrative`: temi di primo livello di `{base}/Argomenti`.
    Fetch fallito o nessun tema di primo livello riconosciuto → `[]` onesto:
    gli uffici restano il risultato principale di questo connettore."""
    url = urljoin(base, "/Argomenti")
    letto = _fetch(url, host_comune, timeout, sonda)
    if letto is None:
        return []
    pagina, url_finale = letto
    aree: list[AreaAmministrativa] = []
    visti: set[str] = set()
    for url_area, testo in _ancore(pagina, url_finale, host_comune):
        if not _e_argomento_primo_livello(url_area) or url_area in visti or not testo:
            continue
        visti.add(url_area)
        aree.append(AreaAmministrativa(nome=testo, url=url_area))
    return aree


def _leggi_at_openpa(
    base: str, host_comune: str, sonda: _Sonda, timeout: float
) -> AmministrazioneTrasparente:
    """Amministrazione Trasparente: `{base}/Amministrazione-Trasparente`,
    rotta OpenPA convenzionale confermata 200 reale su 2/2 comuni scoutati
    (Storo, Lodrino) — non un'ipotesi a tavolino. A differenza di
    `openweb`/`peopleweb` (che tornano `None` se il probe fallisce), qui
    l'`indice_url` convenzionale si registra COMUNQUE anche a probe
    fallito: la rotta è osservata, non inventata. Solo `bandi_attivi`/
    `pdf_presenti` restano ai default onesti (`[]`/`False`) — NO drill di
    bandi/PDF, index-only stesso taglio degli altri connettori D-09."""
    url_convenzionale = urljoin(base, "/Amministrazione-Trasparente")
    letto = _fetch(url_convenzionale, host_comune, timeout, sonda)
    if letto is not None:
        _, url_finale = letto
        return AmministrazioneTrasparente(indice_url=url_finale)
    return AmministrazioneTrasparente(indice_url=url_convenzionale)


def estrai_logo_openpa(pagina_home: str, base: str, host_comune: str) -> str | None:
    """Il logo del comune. Prova, in ordine: (1) `<img>` Bootstrap-Italia
    dentro `.it-brand-wrapper` (tema OpenPA osservato reale su Storo e
    Lodrino); (2) un `<img>` generico nell'header con `alt`/`class` che
    richiama "logo"/"stemma"; (3) un `<image>` SVG inline. Guardia host
    `_host_logo_ammesso`: host del comune OPPURE CDN OpenCity del vendor
    (`_CDN_LOGO_OPENCITY`), pura, nessun fetch.

    Il `src` reale, su tutti i campioni, non è mai same-host — vive sul
    proxy-immagini del vendor (`flyimg.opencityitalia.it`, che incapsula un
    URL S3 `static.opencity.opencontent.it`), il CDN OpenCity/OpenContent.
    Prima la guardia stretta lo scartava e il logo degradava sempre a `None`;
    ora l'allowlist per-suffisso del fornitore lo ammette (un `src` fuori da
    quei domini resta comunque scartato)."""
    pagina_lower = pagina_home.lower()

    inizio_brand = pagina_lower.find("it-brand-wrapper")
    if inizio_brand != -1:
        finestra = pagina_home[inizio_brand : inizio_brand + 1500]
        trovato = re.search(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', finestra, re.IGNORECASE)
        if trovato is not None:
            src = html.unescape(trovato.group(1)).strip()
            if src:
                url = urljoin(base, src)
                if _host_logo_ammesso(url, host_comune):
                    return url

    inizio_header = pagina_lower.find("<header")
    if inizio_header != -1:
        fine_header = pagina_lower.find("</header>", inizio_header)
        if fine_header == -1:
            fine_header = inizio_header + 40_000  # margine di cortesia, non l'intera pagina
        blocco = pagina_home[inizio_header:fine_header]
        for trovato in re.finditer(r"<img\b[^>]*>", blocco, re.IGNORECASE):
            tag = trovato.group(0)
            if not re.search(r"logo|stemma", tag, re.IGNORECASE):
                continue
            src_match = re.search(r'\bsrc=["\']([^"\']+)["\']', tag, re.IGNORECASE)
            if src_match is None:
                continue
            src = html.unescape(src_match.group(1)).strip()
            if not src:
                continue
            url = urljoin(base, src)
            if _host_logo_ammesso(url, host_comune):
                return url

        match_svg = re.search(
            r'<image\b[^>]*(?:xlink:href|href)=["\']([^"\']+)["\']', blocco, re.IGNORECASE
        )
        if match_svg is not None:
            href = html.unescape(match_svg.group(1)).strip()
            if href:
                url = urljoin(base, href)
                if _host_logo_ammesso(url, host_comune):
                    return url

    return None


def leggi_openpa(comune: ComuneNoto, sonda: _Sonda) -> EsitoConnettore:
    """Contratto D-09 per la piattaforma OpenPA (Maggioli/OpenCity). Firma
    congelata come `egov.leggi_egov`/`openweb.leggi_openweb`:
    `(comune, sonda) -> EsitoConnettore`, MAI `None` — un comune senza
    nulla da leggere è un esito vuoto onesto (`connettore._esito_vuoto` lo
    riconosce), non un guasto.

    Non solleva mai: una sezione impraticabile resta al degrado (uffici/
    aree vuoti per quella sola sezione), le altre estraggono comunque —
    stesso taglio di `egov.leggi_egov`.
    """
    letto_il = _ora()
    base = _base_con_schema(comune.sito)
    if base is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=PIATTAFORMA_OPENPA, letto_il=letto_il
        )
    host_comune = _host_senza_www(urlparse(base).netloc.lower())

    letta = _richiedi_con_guardia(base, host_comune, timeout=8.0)
    if letta is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=PIATTAFORMA_OPENPA, letto_il=letto_il
        )
    # Stesso contatore di `_Sonda._get`/`.risposta` (D-08): la richiesta
    # guardata bypassa `_Sonda` per lo streaming, ma il costo verso il
    # portale va comunque contato.
    sonda.richieste += 1
    sonda.raggiungibile = True
    _pagina_home, url_home_finale = letta

    try:
        uffici = _leggi_uffici_openpa(url_home_finale, host_comune, sonda, 8.0)
    except Exception:  # noqa: BLE001 — indice uffici muto: esito senza uffici, mai un crash
        logger.warning("openpa: lettura indice uffici fallita per %s", comune.nome)
        uffici = []

    try:
        aree = _leggi_aree_openpa(url_home_finale, host_comune, sonda, 8.0)
    except Exception:  # noqa: BLE001 — indice argomenti muto: esito senza aree, mai un crash
        logger.warning("openpa: lettura aree amministrative fallita per %s", comune.nome)
        aree = []

    try:
        amministrazione_trasparente = _leggi_at_openpa(url_home_finale, host_comune, sonda, 8.0)
    except Exception:  # noqa: BLE001 — catena AT muta: esito senza AT, mai un crash
        logger.warning("openpa: lettura amministrazione trasparente fallita per %s", comune.nome)
        amministrazione_trasparente = None

    return EsitoConnettore(
        codice_istat=comune.codice_istat,
        piattaforma=PIATTAFORMA_OPENPA,
        letto_il=letto_il,
        aree_amministrative=aree,
        uffici=uffici,
        amministrazione_trasparente=amministrazione_trasparente,
    )


def _leggi_openpa_cli(codice_istat: str, *, timeout: float = 8.0) -> None:
    """Uso standalone (`python -m treasureiq.openpa <istat>`), stesso
    stampo del CLI di `egov.py`/`openweb.py`."""
    from treasureiq.sonda_live import comune_per_codice

    comune = comune_per_codice(codice_istat)
    if comune is None:
        print(f"comune non trovato: {codice_istat}")
        return
    with _Sonda(timeout=timeout) as sonda:
        esito = leggi_openpa(comune, sonda)
    print(esito.model_dump_json(indent=1))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Connettore OpenPA/Maggioli (D-09)")
    parser.add_argument("codice_istat", help="codice ISTAT del comune (es. 022183 Storo)")
    parser.add_argument("--timeout", type=float, default=8.0, help="timeout per richiesta (default 8.0)")
    args = parser.parse_args()
    _leggi_openpa_cli(args.codice_istat, timeout=args.timeout)
