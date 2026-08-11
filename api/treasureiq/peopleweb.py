"""Connettore Siscom PeopleWeb (D-09): ASP.NET WebForms/IIS, ~953 comuni.

Scouting reale (3 comuni Siscom, fixture in
`api/tests/fixtures/peopleweb_*.html`, markup non verificabile a tavolino —
stesso vincolo CK-3 di `egov.py`): Airasca (TO), Andrate (TO), Angrogna
(TO). Firma comune: `Microsoft-IIS/10.0`, `Set-Cookie: ASP.NET_SessionId=`,
`X-Powered-By: ASP.NET` — coerente col fingerprint di piattaforma
(`piattaforma._PEOPLEWEB`, asset Bootstrap Italia coi backslash).

**Due template distinti sotto lo stesso vendor** (osservato reale, non
assunto): Airasca usa rotte "a percorso" (`/amministrazione/uffici`,
`/amministrazione/ufficio/{id}/{slug}`, `/servizi/amministrazione-trasparente`);
Andrate e Angrogna usano rotte "a querystring" (`Uffici`,
`Uffici?IDUfficio={id}`, `Dettaglioargomenti?IDCategoria={id}` per AT — l'id
categoria NON è fisso, cambia per installazione, si trova per TESTO
dell'ancora come in `egov._RE_AT_TESTO`). Ogni estrattore qui sotto tratta
i due template con la STESSA logica quando possibile (pattern sull'URL
risolto, non sul path grezzo) — vedi `_url_indice_uffici`/`_url_at`.

**Uffici**: entrambi i template mostrano l'indice come una griglia di card
`<a href="...">​<h3 class="card-title...">Nome</h3></a>` (apici singoli o
doppi secondo il template) — un'unica regex generica (`_ancore`, tollerante
a entrambi gli apici) basta per i due. Le schede di dettaglio individuali
espongono `tel:`/`mailto:`/PEC tipizzati (verificato su Airasca — tabella
`#recapiti_sezione` — e su Andrate — blocco `#Contatti`), ma il drill di
massa (+1 GET per ufficio, su comuni con anche solo 15-20 uffici) NON è
gentile a scala nazionale (953 comuni): stessa scelta di scope di
`egov._leggi_uffici_egov` — indice statico (nome+url), `source_typed=False`,
recapiti vuoti, deferred a un ciclo futuro on-demand.

**Amministrazione Trasparente**: si trova per PATTERN URL nel template a
percorso (`amministrazione-trasparente` nel path) o per TESTO ancora nel
template a querystring ("amministrazione trasparente" / "trasparenza
amministrativa"). Solo il link si registra (`indice_url`): la struttura
delle sotto-categorie (bandi di gara/concorso) non è stata verificata in
modo uniforme sui 3 comuni in questo ciclo — degrado D-10 onesto, niente
drill fantasioso su 3 campioni. `bandi_attivi` resta `[]`.

**Logo**: `<img src="...">` dentro `.it-brand-wrapper` nell'header (NON SVG
inline come ipotizzato a priori — dato reale osservato su tutti e 3 i
comuni, sia percorso assoluto sia relativo).

`leggi_peopleweb` non solleva MAI: stesso stampo di `leggi_egov` — una
sezione impraticabile resta al degrado D-10, le altre estraggono.
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
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www
from treasureiq.sonda_live import ComuneNoto

logger = logging.getLogger(__name__)

#: Stesso ordine di grandezza del cap-logo/eGov (`registro.py`, `egov.py`):
#: nessuna pagina di questo connettore ha mostrato bisogno di più.
MAX_RISPOSTA_BYTES = 2_000_000

#: Cap difensivo sul numero di uffici estratti dall'indice — stesso valore
#: di `egov.MAX_UFFICI_INDICE`, stessa ragione (nessun comune osservato ha
#: bisogno di più di poche centinaia di schede).
MAX_UFFICI_INDICE = 200

#: Anchor generico, tollerante a entrambi gli apici (osservati reali: il
#: template "a percorso" di Airasca usa apici singoli su `href`/`class`,
#: quello "a querystring" di Andrate/Angrogna usa apici doppi) e a markup
#: annidato (`<svg>`/`<use>` dentro `<a>`, reale sulle card-ufficio con
#: icona) — stesso ruolo di `egov._RE_ANCORA`.
_RE_ANCORA = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_RE_TAG = re.compile(r"<[^>]+>")

#: Le rotte di dettaglio-ufficio osservate sui due template: percorso
#: (`/amministrazione/ufficio/{id}/{slug}`) o querystring
#: (`?IDUfficio={id}`/`&IDUfficio={id}`) — un'unica card-grid le produce
#: entrambe secondo il template, mai insieme sullo stesso comune.
_RE_UFFICIO_DETTAGLIO = re.compile(r"/amministrazione/ufficio/\d+|[?&]IDUfficio=\d+\b", re.IGNORECASE)

#: Testo dell'ancora AT sul template a querystring (id di categoria non
#: fisso, si trova per TESTO — stesso principio di `egov._RE_AT_TESTO`,
#: qui con l'aggiunta della variante "trasparenza amministrativa" osservata
#: su Andrate/Angrogna).
_RE_AT_TESTO = re.compile(r"amministrazione\s+trasparente|trasparenza\s+amministrativa", re.IGNORECASE)


def _ora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stesso_host(url: str, host_comune: str) -> bool:
    return _host_senza_www(urlparse(url).netloc.lower()) == host_comune


def _richiedi_con_guardia(url: str, host_comune: str, *, timeout: float) -> tuple[str, str] | None:
    """GET guardato (W1) — stesso stampo di `egov._richiedi_con_guardia`:
    schema http/https, host verificato DOPO il follow-301 (TOCTOU/SSRF),
    size-cap che ABORTISCE lo streaming (mai un `len()` post-download,
    W-3). Ritorna `(testo, url_finale)`."""
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
                        "peopleweb: redirect fuori host scartato %s -> %s", url, risposta.url
                    )
                    return None
                buffer = bytearray()
                for pezzo in risposta.iter_bytes():
                    buffer.extend(pezzo)
                    if len(buffer) > MAX_RISPOSTA_BYTES:
                        logger.info(
                            "peopleweb: risposta oltre size-cap, connessione interrotta: %s", url
                        )
                        return None
                url_finale = str(risposta.url)
    except Exception:  # noqa: BLE001 — portale PeopleWeb muto: nessun esito, mai un crash
        logger.info("peopleweb: pagina irraggiungibile: %s", url)
        return None
    return bytes(buffer).decode("utf-8", errors="replace"), url_finale


def _fetch(url: str, host_comune: str, timeout: float, sonda: _Sonda) -> tuple[str, str] | None:
    """`_richiedi_con_guardia` con lo stesso contatore-costo della home
    (D-08) — stesso ruolo di `egov._fetch`."""
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


def _url_indice_uffici(ancore: list[tuple[str, str]]) -> str | None:
    """L'indice uffici, riconosciuto sul path RISOLTO (non sul path grezzo
    dell'href): entrambi i template atterrano su un path che termina in
    `/uffici` senza querystring — `/amministrazione/uffici` (Airasca) o
    `/Uffici` (Andrate/Angrogna, relativo, risolto dal `base`). Un'unica
    regola per i due template, niente branching per nome del vendor."""
    for url, _ in ancore:
        pezzi = urlparse(url)
        if not pezzi.query and pezzi.path.rstrip("/").lower().endswith("/uffici"):
            return url
    return None


def _url_at(ancore: list[tuple[str, str]]) -> str | None:
    """Il link ad Amministrazione Trasparente: prima per PATTERN URL (il
    template a percorso lo mette in chiaro, `.../amministrazione-trasparente`
    — nessun testo-ancora serve), poi per TESTO (il template a querystring
    lo linka come `Dettaglioargomenti?IDCategoria={id}`, id non fisso —
    stesso principio di `egov._cerca_link` con `_RE_AT_TESTO`)."""
    for url, _ in ancore:
        if "amministrazione-trasparente" in urlparse(url).path.lower():
            return url
    for url, testo in ancore:
        if _RE_AT_TESTO.search(testo):
            return url
    return None


def _estrai_uffici_peopleweb(
    ancore_indice: list[tuple[str, str]],
) -> list[UfficioConnettore]:
    """Indice uffici index-only (nome+url), filtrato sulle due forme di URL
    di dettaglio osservate (`_RE_UFFICIO_DETTAGLIO`) — stesso motivo di
    `egov._leggi_uffici_egov`: i recapiti tipizzati vivono sulle schede
    individuali, il drill di massa resta deferred (+1 GET/ufficio non è
    gentile su 953 comuni)."""
    ora = _ora()
    uffici: list[UfficioConnettore] = []
    visti: set[str] = set()
    for url, testo in ancore_indice:
        if not _RE_UFFICIO_DETTAGLIO.search(url) or url in visti or not testo:
            continue
        visti.add(url)
        uffici.append(
            UfficioConnettore(
                nome=testo,
                url=url,
                source_typed=False,
                letto_il=ora,
            )
        )
        if len(uffici) >= MAX_UFFICI_INDICE:
            break
    return uffici


def estrai_logo_peopleweb(pagina_home: str, base: str, host_comune: str) -> str | None:
    """Il logo del comune, letto dall'header: `<img src="...">` dentro
    `.it-brand-wrapper` — dato REALE osservato sui 3 comuni (non l'SVG
    inline ipotizzato a priori: qui il tema serve un `<img>`, percorso
    assoluto o relativo secondo il comune). Accettato SOLO se resta sullo
    stesso host del portale sondato (D-S8, stessa guardia di
    `registro._estrai_logo_header`); assente o host estraneo → `None`."""
    inizio = pagina_home.find("it-brand-wrapper")
    if inizio == -1:
        return None
    finestra = pagina_home[inizio : inizio + 1500]
    trovato = re.search(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', finestra, re.IGNORECASE)
    if trovato is None:
        return None
    src = html.unescape(trovato.group(1)).strip()
    if not src:
        return None
    url = urljoin(base, src)
    if not _stesso_host(url, host_comune):
        return None
    return url


def leggi_peopleweb(comune: ComuneNoto, sonda: _Sonda) -> EsitoConnettore:
    """Contratto D-09 per la famiglia Siscom PeopleWeb. Firma congelata
    (mirror di `leggi_egov`): `(comune, sonda) -> EsitoConnettore`, MAI
    `None` — un comune senza nulla da leggere è un esito vuoto onesto
    (`connettore._esito_vuoto` lo riconosce), non un guasto. Non solleva
    mai: una sezione impraticabile resta al degrado D-10, le altre sezioni
    estraggono.

    `aree_amministrative` resta `[]` in questo ciclo: nessun pattern comune
    ai 3 campioni per il catalogo aree è stato verificato in modo
    sufficientemente robusto da generalizzare a 953 comuni — meglio vuoto
    onesto che un'assunzione su 3 campioni (best-effort, non fabbricato).
    `amministrazione_trasparente` porta solo `indice_url`: la struttura
    delle sotto-categorie (bandi) non è stata riscontrata uniforme sui 3
    comuni, drill deferred a un ciclo futuro (stesso principio D-10 di
    `egov` per la mappa del sito: link noto, contenuto non letto).
    """
    letto_il = _ora()
    base = _base_con_schema(comune.sito)
    if base is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=Piattaforma.PEOPLEWEB.value, letto_il=letto_il
        )
    host_comune = _host_senza_www(urlparse(base).netloc.lower())

    letta = _richiedi_con_guardia(base, host_comune, timeout=8.0)
    if letta is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=Piattaforma.PEOPLEWEB.value, letto_il=letto_il
        )
    # Stesso contatore di `_Sonda._get`/`.risposta` (D-08): la richiesta
    # guardata bypassa `_Sonda` per lo streaming, ma il costo verso il
    # portale va comunque contato.
    sonda.richieste += 1
    sonda.raggiungibile = True
    pagina, url_finale = letta

    try:
        ancore_home = _ancore(pagina, url_finale, host_comune)
    except Exception:  # noqa: BLE001 — home muta lato-ancore: nessun link, non un crash
        logger.warning("peopleweb: lettura ancore home fallita per %s", comune.nome)
        ancore_home = []

    aree_amministrative: list[AreaAmministrativa] = []

    uffici: list[UfficioConnettore] = []
    try:
        url_uffici = _url_indice_uffici(ancore_home)
        if url_uffici is not None:
            letto_uffici = _fetch(url_uffici, host_comune, 8.0, sonda)
            if letto_uffici is not None:
                pagina_uffici, url_finale_uffici = letto_uffici
                ancore_uffici = _ancore(pagina_uffici, url_finale_uffici, host_comune)
                uffici = _estrai_uffici_peopleweb(ancore_uffici)
    except Exception:  # noqa: BLE001 — indice uffici muto: esito senza uffici, mai un crash
        logger.warning("peopleweb: lettura indice uffici fallita per %s", comune.nome)
        uffici = []

    amministrazione_trasparente: AmministrazioneTrasparente | None = None
    try:
        indice_url = _url_at(ancore_home)
        if indice_url is not None:
            amministrazione_trasparente = AmministrazioneTrasparente(indice_url=indice_url)
    except Exception:  # noqa: BLE001 — link AT muto: esito senza AT, mai un crash
        logger.warning("peopleweb: ricerca link AT fallita per %s", comune.nome)
        amministrazione_trasparente = None

    return EsitoConnettore(
        codice_istat=comune.codice_istat,
        piattaforma=Piattaforma.PEOPLEWEB.value,
        letto_il=letto_il,
        aree_amministrative=aree_amministrative,
        uffici=uffici,
        amministrazione_trasparente=amministrazione_trasparente,
    )


def _leggi_peopleweb_cli(codice_istat: str, *, timeout: float = 8.0) -> None:
    """Uso standalone (`python -m treasureiq.peopleweb <istat>`), stesso
    stampo del CLI di `egov.py`."""
    from treasureiq.sonda_live import comune_per_codice

    comune = comune_per_codice(codice_istat)
    if comune is None:
        print(f"comune non trovato: {codice_istat}")
        return
    with _Sonda(timeout=timeout) as sonda:
        esito = leggi_peopleweb(comune, sonda)
    print(esito.model_dump_json(indent=1))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Connettore Siscom PeopleWeb (D-09)")
    parser.add_argument("codice_istat", help="codice ISTAT del comune (es. 001008 Airasca)")
    parser.add_argument("--timeout", type=float, default=8.0, help="timeout per richiesta (default 8.0)")
    args = parser.parse_args()
    _leggi_peopleweb_cli(args.codice_istat, timeout=args.timeout)
