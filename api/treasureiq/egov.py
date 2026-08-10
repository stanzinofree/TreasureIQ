"""Connettore eGov (B4b): parser reale per la firma-famiglia
`/EG0/EGS*.HBL?en=eg###` (D-09) — vista su Marino (RM), `en=eg176`.

Scouting reale su Marino (fixture in `api/tests/fixtures/egov_*.html`,
markup non verificabile a tavolino — CK-3):
- **Argomenti (servizi)**: la home page linka DIRETTAMENTE ~12 pagine
  tema (`EGSCHTST45.HBL?ARG=N`), niente crawl a due livelli — un solo
  fetch (la home) basta a costruire `aree_amministrative` reali.
- **Mappa del sito**: endpoint noto (`EGSMISTMSIT.HBL?en=eg{id}&FUNZ=1`,
  `id` letto dal primo `en=eg\\d+` visto in pagina, MAI hardcoded), ma il
  file reale pesa ~2.7MB > `MAX_RISPOSTA_BYTES` (verificato sulla fixture
  reale, `test_richiedi_con_guardia_mappa_reale_supera_cap_size`) — non lo
  si fetcha mai (richiesta certa di sforare il cap, quindi inutile ogni
  query): resta un link verificato (D-10), non un contenuto letto.
- **Amministrazione Trasparente**: il link AT sulla home NON è nella
  famiglia EGS (è una pagina statica `/amministrazione/trasparenza/...`);
  si trova per TESTO dell'anchor (`_RE_AT_TESTO`), non per URL. Da lì la
  catena reale è home → AT → "Bandi di concorso" → "…aperti" → blocco
  `#latest-posts` (bandi verbatim, D-07: nessuna cifra passa da un LLM).
  Ogni hop può fallire senza abbattere quelli già letti: `indice_url`
  resta noto anche se i bandi non si raggiungono (degrado per-sezione).
- **Uffici**: nessun indice uffici scoperto nel boundary EGS (i recapiti
  vivono dentro ogni pagina-servizio individuale, crawl non limitato,
  fuori scope di questo ciclo) — `uffici` resta `[]`, degrado onesto.

`leggi_egov` non solleva MAI: una sezione impraticabile resta al degrado
D-10 (link noto, contenuto non letto), le altre sezioni estraggono. La
firma è congelata (D-09 acceptance A9, ciclo 10) — il corpo no.

Guardia security (W1) — stessa forma di `municipium.py:246` (follow-301
same-host) e `registro.py._scarica_logo` (size-cap streaming-con-abort):
schema allow-list http/https, host allow-list = dominio del comune
verificato DOPO il follow-301 (TOCTOU/SSRF: un host che non è il comune —
IP privato incluso — non passa mai questo confronto; non c'è un elenco di
range IP da mantenere separatamente), timeout esplicito per richiesta,
size-cap che ABORTISCE lo streaming (mai un `len()` calcolato dopo un
download intero, W-3). OGNI fetch di questo modulo passa da
`_richiedi_con_guardia` — home page e i tre hop della catena AT (indice,
categoria concorso, aperti). Gli "argomenti" sono già nella home (nessun
fetch aggiuntivo); la "mappa" è un link costruito, mai fetchato (sopra).
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
)
from treasureiq.ingest.base import USER_AGENT
from treasureiq.ingest.censimento import _Sonda
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www
from treasureiq.sonda_live import ComuneNoto

logger = logging.getLogger(__name__)

#: Osservato ~2.7MB sulla "Mappa del sito" reale di Marino — oltre questo
#: cap la guardia aborta lo streaming (quella sezione degrada, non crasha).
#: Stesso ordine di grandezza del cap-logo in `registro.py`.
MAX_RISPOSTA_BYTES = 2_000_000

#: La firma-famiglia (D-09 A9): asset/rotta `EGS*.HBL` con querystring
#: `en=eg###`, letta dentro un `href` — stesso pattern del riconoscimento
#: piattaforma in `piattaforma.py` (`_ASSET`), qui applicato al singolo
#: link per costruire il degrado D-10 di fallback (nessun argomento
#: riconosciuto — vedi `_estrai_argomenti`).
_RE_HREF_EGOV = re.compile(
    r'<a[^>]+href=["\']([^"\']*?/EG0/EGS\w+\.HBL\?[^"\']*\ben=eg\d{1,4}\b[^"\']*)["\'][^>]*>([^<]*)</a>',
    re.IGNORECASE,
)
_RE_AT_TESTO = re.compile(r"amministrazione\s+trasparente", re.IGNORECASE)

#: Anchor generico, tollerante a markup annidato (`<span>`/`<svg>` dentro
#: `<a>` — reale sui chip-topic e sui link AT di Marino): il testo si pulisce
#: rimuovendo i tag interni, non richiedendo `</a>` immediato come
#: `_RE_HREF_EGOV`. Usato per ogni ricerca "per testo" della catena AT.
_RE_ANCORA = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_RE_TAG = re.compile(r"<[^>]+>")

#: Pagine-argomento reali (D-09 osservato): stessa famiglia `EGSCHTST*.HBL`
#: ma querystring `ARG=N`, non `en=eg###` — un ramo distinto della stessa
#: famiglia di asset, linkato in chiaro dalla home (nessun crawl aggiuntivo).
_RE_ARG_URL = re.compile(r"/EG0/EGS\w+\.HBL\?(?:[^\"'&]*&)*ARG=\d+", re.IGNORECASE)

#: L'id `en=eg###` del comune (176 per Marino) — letto dalla pagina, mai
#: hardcoded, per costruire l'URL noto della mappa del sito.
_RE_EN_EG = re.compile(r"\ben=eg(\d{1,4})\b")

_RE_CONCORSO_TESTO = re.compile(r"bandi\s+di\s+concorso\b", re.IGNORECASE)
_RE_APERTI_TESTO = re.compile(r"\baperti\b", re.IGNORECASE)
_RE_BANDI_VUOTO = re.compile(r"nessun\s+elemento\s+estratto", re.IGNORECASE)


def _ora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stesso_host(url: str, host_comune: str) -> bool:
    return _host_senza_www(urlparse(url).netloc.lower()) == host_comune


def _richiedi_con_guardia(url: str, host_comune: str, *, timeout: float) -> tuple[str, str] | None:
    """GET guardato (W1). `None` per qualunque esito non valido: schema
    non-http, stato non-200, redirect fuori host (controllato DOPO il
    follow-301, non sull'URL iniziale — TOCTOU/SSRF, stesso punto di
    `municipium.py:246`), o risposta oltre il size-cap. Lo stream si
    interrompe ABORTENDO la connessione al superamento del cap — mai un
    `len()` calcolato dopo un download intero (W-3, pattern identico a
    `registro._scarica_logo`). Ritorna `(testo, url_finale)`."""
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
                        "eGov: redirect fuori host scartato %s -> %s", url, risposta.url
                    )
                    return None
                buffer = bytearray()
                for pezzo in risposta.iter_bytes():
                    buffer.extend(pezzo)
                    if len(buffer) > MAX_RISPOSTA_BYTES:
                        logger.info(
                            "eGov: risposta oltre size-cap, connessione interrotta: %s", url
                        )
                        return None
                url_finale = str(risposta.url)
    except Exception:  # noqa: BLE001 — portale eGov muto: nessun esito, mai un crash
        logger.info("eGov: pagina irraggiungibile: %s", url)
        return None
    return bytes(buffer).decode("utf-8", errors="replace"), url_finale


def _estrai_aree_egov(pagina: str, base: str, host_comune: str) -> list[AreaAmministrativa]:
    """Gli endpoint `EGS*.HBL` riconosciuti nella pagina, come link (D-10):
    solo quelli che restano sul dominio del comune. Nessun contenuto letto
    — è il degrado onesto in attesa di B4b."""
    aree: list[AreaAmministrativa] = []
    visti: set[str] = set()
    for grezzo, testo in _RE_HREF_EGOV.findall(pagina):
        url = urljoin(base, grezzo)
        if url in visti or not _stesso_host(url, host_comune):
            continue
        visti.add(url)
        nome = testo.strip() or url
        aree.append(AreaAmministrativa(nome=nome, url=url))
    return aree


def _ancore(pagina: str, base: str, host_comune: str) -> list[tuple[str, str]]:
    """Ogni `<a href>` della pagina come `(url_assoluto, testo_pulito)`,
    solo quelli che restano sul dominio del comune. Tollerante a markup
    annidato (`<span>`/`<svg>` dentro l'anchor, reale sui link AT/topic di
    Marino) — il testo si ottiene rimuovendo i tag interni, non
    richiedendo `</a>` immediatamente dopo il contenuto."""
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


def _cerca_link(ancore: list[tuple[str, str]], pattern: re.Pattern[str]) -> str | None:
    """Il primo url tra `ancore` il cui testo matcha `pattern` — usato per
    ogni hop della catena AT (identificata per TESTO, non per URL: il link
    AT reale di Marino non è nella famiglia EGS)."""
    for url, testo in ancore:
        if pattern.search(testo):
            return url
    return None


def _estrai_argomenti(pagina: str, base: str, host_comune: str) -> list[AreaAmministrativa]:
    """Le pagine-argomento reali (`EGSCHTST*.HBL?ARG=N`) linkate in chiaro
    dalla home — un solo fetch (già fatto per arrivare qui), nessun crawl
    a due livelli. Lista vuota se il markup non presenta questa forma
    (fallback al degrado D-10 generico, deciso dal chiamante)."""
    aree: list[AreaAmministrativa] = []
    visti: set[str] = set()
    for url, testo in _ancore(pagina, base, host_comune):
        if not _RE_ARG_URL.search(url) or url in visti or not testo:
            continue
        visti.add(url)
        aree.append(AreaAmministrativa(nome=testo, url=url))
    return aree


def _area_mappa(pagina: str, base: str, host_comune: str) -> AreaAmministrativa | None:
    """L'endpoint noto della mappa del sito (`EGSMISTMSIT.HBL?en=eg{id}
    &FUNZ=1`), `id` letto dal primo `en=eg###` visto in pagina — MAI
    hardcoded (precedente Pomezia ciclo 10). Solo il link: il contenuto
    reale (~2.7MB su Marino) supera `MAX_RISPOSTA_BYTES` e la guardia lo
    aborta — degrado onesto per questa sola sezione."""
    trovato = _RE_EN_EG.search(pagina)
    if trovato is None:
        return None
    url = urljoin(base, f"/EG0/EGSMISTMSIT.HBL?en=eg{trovato.group(1)}&FUNZ=1")
    if not _stesso_host(url, host_comune):
        return None
    return AreaAmministrativa(nome="Mappa del sito", url=url)


def _blocco_latest_posts(pagina: str) -> str | None:
    """Il blocco `#latest-posts` della pagina "…aperti": stessa forma di
    `municipium._blocco_contatti` (finestra delimitata, non l'intera
    pagina) — più sotto c'è un widget di feedback con la STESSA classe CSS
    `card-teaser` ma non è un bando, e va escluso da qui."""
    inizio = pagina.find('id="latest-posts"')
    if inizio == -1:
        inizio = pagina.find("id='latest-posts'")
    if inizio == -1:
        return None
    fine = pagina.find("<nav", inizio)
    if fine == -1:
        fine = inizio + 20_000  # margine di cortesia, non l'intera pagina
    return pagina[inizio:fine]


def _estrai_bandi_aperti(pagina: str, base: str, host_comune: str) -> tuple[list[BandoAT], bool]:
    """Bandi attivi VERBATIM (D-07: nessuna cifra passa da un LLM) dal
    blocco `#latest-posts`. "Nessun elemento estratto" è uno zero onesto
    (osservato reale su Marino oggi), non un degrado — lista vuota
    legittima, non un fallback."""
    blocco = _blocco_latest_posts(pagina)
    if blocco is None or _RE_BANDI_VUOTO.search(blocco):
        return [], False
    bandi: list[BandoAT] = []
    visti: set[str] = set()
    for url, testo in _ancore(blocco, base, host_comune):
        if url in visti or not testo:
            continue
        visti.add(url)
        pdf_url = url if url.lower().endswith(".pdf") else None
        bandi.append(BandoAT(titolo=testo, url=url, pdf_url=pdf_url))
    pdf_presenti = any(bando.pdf_url is not None for bando in bandi)
    return bandi, pdf_presenti


def _fetch(url: str, host_comune: str, timeout: float, sonda: _Sonda) -> tuple[str, str] | None:
    """`_richiedi_con_guardia` con lo stesso contatore-costo della home
    (D-08): ogni hop della catena AT/mappa passa da qui, mai da un client
    non guardato."""
    esito = _richiedi_con_guardia(url, host_comune, timeout=timeout)
    if esito is not None:
        sonda.richieste += 1
        sonda.raggiungibile = True
    return esito


def _leggi_aree(pagina: str, base: str, host_comune: str) -> list[AreaAmministrativa]:
    """`aree_amministrative`: argomenti reali (D-09 osservato) + il link
    noto della mappa del sito. Se il markup non presenta argomenti
    riconoscibili, ripiega sul degrado D-10 generico (endpoint EGS grezzi)
    — degrado per-sezione, non tutto-o-niente."""
    argomenti = _estrai_argomenti(pagina, base, host_comune)
    aree = list(argomenti) if argomenti else _estrai_aree_egov(pagina, base, host_comune)
    mappa = _area_mappa(pagina, base, host_comune)
    if mappa is not None:
        aree.append(mappa)
    return aree


def _leggi_at_egov(
    ancore_home: list[tuple[str, str]], host_comune: str, timeout: float, sonda: _Sonda
) -> AmministrazioneTrasparente | None:
    """Amministrazione Trasparente reale: catena home → AT → "Bandi di
    concorso" → "…aperti" → bandi. Ogni hop che non chiude ferma la
    catena lì, MAI a mani vuote se un hop precedente è riuscito — l'indice
    resta noto anche quando i bandi non si raggiungono (D-11, degrado
    per-sezione)."""
    indice_url = _cerca_link(ancore_home, _RE_AT_TESTO)
    if indice_url is None:
        return None

    letta_at = _fetch(indice_url, host_comune, timeout, sonda)
    if letta_at is None:
        return AmministrazioneTrasparente(indice_url=indice_url)
    pagina_at, url_at = letta_at
    concorso_url = _cerca_link(_ancore(pagina_at, url_at, host_comune), _RE_CONCORSO_TESTO)
    if concorso_url is None:
        return AmministrazioneTrasparente(indice_url=indice_url)

    letta_concorso = _fetch(concorso_url, host_comune, timeout, sonda)
    if letta_concorso is None:
        return AmministrazioneTrasparente(indice_url=indice_url)
    pagina_concorso, url_concorso = letta_concorso
    aperti_url = _cerca_link(_ancore(pagina_concorso, url_concorso, host_comune), _RE_APERTI_TESTO)
    if aperti_url is None:
        return AmministrazioneTrasparente(indice_url=indice_url)

    letta_aperti = _fetch(aperti_url, host_comune, timeout, sonda)
    if letta_aperti is None:
        return AmministrazioneTrasparente(indice_url=indice_url)
    pagina_aperti, url_aperti = letta_aperti
    bandi, pdf_presenti = _estrai_bandi_aperti(pagina_aperti, url_aperti, host_comune)
    return AmministrazioneTrasparente(indice_url=indice_url, bandi_attivi=bandi, pdf_presenti=pdf_presenti)


def leggi_egov(comune: ComuneNoto, sonda: _Sonda) -> EsitoConnettore:
    """Contratto D-09 per la famiglia eGov. Firma congelata (B4a):
    `(comune, sonda) -> EsitoConnettore`, MAI `None` — un comune senza
    nulla da leggere è un esito vuoto onesto (`connettore._esito_vuoto` lo
    riconosce), non un guasto. Non solleva mai: una sezione impraticabile
    resta al degrado D-10 (link noto, contenuto non letto), le altre
    sezioni estraggono (`_leggi_aree`, `_leggi_at_egov`).

    `uffici` resta sempre `[]`: nessun indice uffici scoperto nel boundary
    EGS di Marino (i recapiti vivono dentro ogni pagina-servizio
    individuale — crawl non limitato, fuori scope) — degrado onesto,
    documentato, non un buco silenzioso.
    """
    letto_il = _ora()
    base = _base_con_schema(comune.sito)
    if base is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=Piattaforma.EGOV.value, letto_il=letto_il
        )
    host_comune = _host_senza_www(urlparse(base).netloc.lower())

    letta = _richiedi_con_guardia(base, host_comune, timeout=8.0)
    if letta is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=Piattaforma.EGOV.value, letto_il=letto_il
        )
    # Stesso contatore di `_Sonda._get`/`.risposta` (D-08): la richiesta
    # guardata bypassa `_Sonda` per lo streaming, ma il costo verso il
    # portale va comunque contato — la scansione non deve sembrare gratis.
    sonda.richieste += 1
    sonda.raggiungibile = True
    pagina, url_finale = letta

    try:
        aree = _leggi_aree(pagina, url_finale, host_comune)
    except Exception:  # noqa: BLE001 — sezione argomenti/mappa muta: degrado D-10 grezzo
        logger.warning("eGov: lettura argomenti/mappa fallita per %s", comune.nome)
        aree = _estrai_aree_egov(pagina, url_finale, host_comune)

    try:
        amministrazione_trasparente = _leggi_at_egov(
            _ancore(pagina, url_finale, host_comune), host_comune, 8.0, sonda
        )
    except Exception:  # noqa: BLE001 — catena AT muta: esito senza AT, mai un crash
        logger.warning("eGov: lettura amministrazione trasparente fallita per %s", comune.nome)
        amministrazione_trasparente = None

    return EsitoConnettore(
        codice_istat=comune.codice_istat,
        piattaforma=Piattaforma.EGOV.value,
        letto_il=letto_il,
        aree_amministrative=aree,
        amministrazione_trasparente=amministrazione_trasparente,
    )


def _leggi_egov_cli(codice_istat: str, *, timeout: float = 8.0) -> None:
    """Uso standalone (`python -m treasureiq.egov <istat>`), stesso stampo
    del CLI di `municipium.py`."""
    from treasureiq.sonda_live import comune_per_codice

    comune = comune_per_codice(codice_istat)
    if comune is None:
        print(f"comune non trovato: {codice_istat}")
        return
    with _Sonda(timeout=timeout) as sonda:
        esito = leggi_egov(comune, sonda)
    print(esito.model_dump_json(indent=1))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Connettore eGov (D-09) — scheletro B4a")
    parser.add_argument("codice_istat", help="codice ISTAT del comune (es. 058057 Marino)")
    parser.add_argument("--timeout", type=float, default=8.0, help="timeout per richiesta (default 8.0)")
    args = parser.parse_args()
    _leggi_egov_cli(args.codice_istat, timeout=args.timeout)
