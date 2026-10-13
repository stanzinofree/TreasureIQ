"""Alberatura di Amministrazione Trasparente: scopre i rami ANAC bersaglio
(bandi di concorso, criteri/sovvenzioni) sulla pagina AT di un comune — anche
quando vive su un host esterno (`/zf/` Halley) — ed estrae i bandi col
connettore giusto per la firma del vendor trovato (D-B7, nessuna cifra
generata dal modello).

Ciclo 8 (bandi-alberatura), brief B1. Riusa gli helper di `mappa_connettore.py`
per import, MAI modificandolo — stesso stampo di `bandi_live._rung1_cpt`.

Due gradini, in ordine:
1. WP REST (`_rami_wp`): se il portale espone la tassonomia AT
   (`_rest_base_tassonomia_per_tipo`), i rami si risolvono per SLUG del term
   — niente scraping HTML, l'AT del tema Design Comuni non linka i term in
   pagina (verificato dal vivo su Figline: nessun `<a>` verso
   `criteri-e-modalita`/`bandi-di-concorso`, sono JS-side).
2. HTML tollerante (`_rami_html`): fallback per i portali che non hanno REST
   AT (Halley e simili). Si legge la pagina `/amministrazione-trasparente/`;
   se redirige alla home (caso Benevento: WordPress la sposta sull'apex), si
   cerca in home un link con testo/href che contenga "trasparen", e lo si
   segue — anche su host esterno (`albo.comune.x.it`, `web.comune.x.it`): mai
   indovinato, sempre un href letto DA una pagina già raggiunta navigando dal
   sito del comune (A7).
"""

from __future__ import annotations

import html
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urljoin, urlparse, urlsplit

import httpx
from pydantic import BaseModel

from treasureiq.ingest.censimento import _Sonda
from treasureiq.ingest.host_guard import fetch_guardato
from treasureiq.mappa_connettore import (
    CPT_AMM_TRASPARENTE,
    Bando,
    _bando_da_riga,
    _base_con_schema,
    _categorie,
    _normalizza_link,
    _rest_base_tassonomia_per_tipo,
)
from treasureiq.sonda_live import LIVE_DIR, comune_per_codice
from treasureiq.storico import portale_del_comune

logger = logging.getLogger(__name__)

#: Stesso ordine di grandezza di `bandi_live.TTL_ORE` (:71): una scansione
#: al giorno basta, i bandi non cambiano ora per ora.
TTL_ORE = 8
CACHE_DIR = LIVE_DIR / "alberatura"
#: Cap righe listing Halley: la sola tabella HTML non ha il taglio di
#: `bandi_live.MAX_BANDI_ARRICCHITI` (:81, =5) a monte — evita una cache
#: gonfiata da un listing enorme, lasciando margine alla discovery.
MAX_RIGHE_HALLEY = 20
#: Cache DEDICATA dei rami (D-05, ciclo18a): TTL lungo, stesso ordine di
#: grandezza di `sonda_live.GIORNI_VALIDITA` (:64, =14) — i rami di un
#: comune non si spostano da un giorno all'altro come i bandi (`TTL_ORE`).
#: Percorso separato da `_percorso_cache` (`bandi.json`): NON è la stessa
#: cache riletta con uno schema diverso, è un file affiancato.
TTL_ORE_RAMI = 14 * 24
#: Cap byte sulla pagina AT già catalogata (`registro.endpoints.at`), stesso
#: ordine di grandezza di `bandi_hgate.MAX_BYTES` (=4_000_000).
MAX_BYTES_AT = 4_000_000
STORICO_DB = Path(__file__).resolve().parent.parent.parent / "data" / "storico.db"


@dataclass
class RamoAT:
    """Un ramo ANAC bersaglio trovato su Amministrazione Trasparente: dove
    sta (`url`, assoluto) e cosa ci si aspetta di trovare (`tipo`)."""

    etichetta: str
    url: str
    tipo: Literal["agevolazione", "concorso"]


class BandoScoperto(BaseModel):
    """Un bando estratto da un `RamoAT`, con la prova di dove è stato letto."""

    bando: Bando
    tipo: Literal["agevolazione", "concorso"]
    vendor: Literal["wp", "halley", "bootstrap_italia", "asmenet", "dgegovpa", "peopleweb", "hgate", "siscom_dnn", "hypersic"]
    parser_version: str = "1.0.0"


@dataclass(frozen=True)
class ParserAT:
    """Una voce del registry locale dei parser AT versionati.

    ``None`` significa che la pagina non prova una lettura affidabile; una
    lista vuota e' riservata a una sezione AT riconosciuta e davvero vuota.
    """

    nome: str
    versione: str
    riconosce: Callable[[RamoAT], bool]
    estrai: Callable[[_Sonda, str, RamoAT], list[BandoScoperto] | None]


class _CacheAlberatura(BaseModel):
    """Formato su disco della cache — stesso stampo atomico di
    `bandi_live._da_cache`/`_in_cache` (:138/:153): `.tmp` + replace, cache
    corrotta è cache assente, MAI si cachano gli esiti negativi (nessuna
    istanza si crea quando `bandi` è vuoto o i rami sono `None`)."""

    versione: Literal[2]
    verificato_il: str
    bandi: list[BandoScoperto]


class _CacheRami(BaseModel):
    """Formato su disco della cache DEDICATA dei rami (D-05, ciclo18a):
    stesso stampo atomico di `_CacheAlberatura` (`.tmp` + replace, cache
    corrotta è cache assente, mai un negativo cachato) ma percorso, schema
    e TTL propri (`_percorso_rami`/`TTL_ORE_RAMI`) — non tocca né rilegge
    `bandi.json`. `rami` accetta `RamoAT` (dataclass, non pydantic)
    verbatim: pydantic v2 valida/serializza dataclass semplici come campo
    senza conversioni a mano, il contratto verso `_estrai_ramo` resta
    identico dopo un giro disco."""

    versione: Literal[3]
    verificato_il: str
    rami: list[RamoAT]


# --- §1 Matching tollerante delle ancore -------------------------------

_SLUG_CONCORSO: tuple[str, ...] = ("bandi-di-concorso",)
_SLUG_AGEVOLAZIONE: tuple[str, ...] = ("criteri-e-modalita", "sovvenzioni")
_TESTO_CONCORSO: tuple[str, ...] = ("bandi di concorso",)
_TESTO_AGEVOLAZIONE: tuple[str, ...] = ("criteri e modalita", "sovvenzioni")


def _normalizza_testo(testo: str) -> str:
    """Minuscolo, accenti sciolti (NFKD), spazi collassati: confronta
    l'ancora del portale col vocabolario atteso senza dipendere dalla grafia
    esatta del tema (es. «Criteri e modalità» / «CRITERI E MODALITA»)."""
    scomposto = unicodedata.normalize("NFKD", testo)
    senza_accenti = "".join(c for c in scomposto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", senza_accenti).strip().lower()


def _tipo_da_slug(slug: str) -> Literal["agevolazione", "concorso"] | None:
    slug = slug.lower()
    if any(s in slug for s in _SLUG_CONCORSO):
        return "concorso"
    if any(s in slug for s in _SLUG_AGEVOLAZIONE):
        return "agevolazione"
    return None


def _tipo_da_testo(testo: str) -> Literal["agevolazione", "concorso"] | None:
    normalizzato = _normalizza_testo(testo)
    if any(t in normalizzato for t in _TESTO_CONCORSO):
        return "concorso"
    if any(t in normalizzato for t in _TESTO_AGEVOLAZIONE):
        return "agevolazione"
    return None


def _slug_da_url(url: str) -> str:
    """L'ultimo segmento del path, per il match sullo SLUG (D-B2: mai id
    fissi). I portali Halley usano id numerici per le categorie generiche —
    lì lo slug non decide nulla e si scende al match sul testo."""
    segmenti = [s for s in urlparse(url).path.split("/") if s]
    return segmenti[-1].lower() if segmenti else ""


# --- §2 Ancore reali di una pagina --------------------------------------

_ANCORA_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
_HREF_RE = re.compile(r"href\s*=\s*['\"]([^'\"]*)['\"]", re.I)
_SCARTABILI = ("mailto:", "tel:", "javascript:")


def _ancore(pagina: str) -> list[tuple[str, str]]:
    """Le ancore (href, testo) di una pagina, scartate quelle che non sono
    una destinazione reale: `href="#"` (apre un sottomenu, non una pagina),
    `mailto:`/`tel:`/`javascript:`, e i duplicati nascosti allo schermo
    (`display:none`, tipici dei portali Halley per l'accessibilità) — sono
    voci del menu invisibili al cittadino, non vanno seguite due volte."""
    ancore: list[tuple[str, str]] = []
    for corrispondenza in _ANCORA_RE.finditer(pagina):
        attributi, interno = corrispondenza.group(1), corrispondenza.group(2)
        if re.search(r"display\s*:\s*none", attributi, re.I):
            continue
        href_trovato = _HREF_RE.search(attributi)
        if href_trovato is None:
            continue
        href = href_trovato.group(1).strip()
        # `#` apre un sottomenu, `#titolo5` è un'ancora sulla STESSA pagina
        # (layout AT «a pagina unica»): nessuna delle due porta a una
        # destinazione diversa da leggere, quindi nessuna delle due è un ramo.
        if not href or href.startswith("#") or href.lower().startswith(_SCARTABILI):
            continue
        testo = html.unescape(re.sub(r"<[^>]+>", " ", interno))
        testo = re.sub(r"\s+", " ", testo).strip()
        ancore.append((href, testo))
    return ancore


def _rami_da_pagina(base: str, pagina: str) -> list[RamoAT]:
    """I rami trovati sulle ancore di una pagina AT. Due passate: prima lo
    SLUG dell'href (più specifico — un id numerico Halley non decide, quindi
    non genera falsi positivi come «Bandi di concorso» generico), poi il
    testo tollerante SOLO per i tipi non ancora risolti. La prima ancora che
    decide vince: sul portale di Benevento sia «Bandi di concorso attivi»
    che «...scaduti ed esiti» matchano lo slug `bandi-di-concorso`, e in
    ordine di pagina «attivi» precede «scaduti»."""
    ancore = _ancore(pagina)
    trovati: dict[str, RamoAT] = {}

    for href, testo in ancore:
        if len(trovati) == 2:
            break
        tipo = _tipo_da_slug(_slug_da_url(href))
        if tipo is not None and tipo not in trovati:
            trovati[tipo] = RamoAT(
                etichetta=testo or href, url=urljoin(base, html.unescape(href)), tipo=tipo
            )

    for href, testo in ancore:
        if len(trovati) == 2:
            break
        tipo = _tipo_da_testo(testo)
        if tipo is not None and tipo not in trovati:
            trovati[tipo] = RamoAT(
                etichetta=testo, url=urljoin(base, html.unescape(href)), tipo=tipo
            )

    return list(trovati.values())


# --- §3 Decodifica esplicita del charset (A6) ---------------------------


def _decodifica_bytes(content_type: str, contenuto: bytes) -> str:
    """Nucleo di `_decodifica`, sui soli byte + header (senza un
    `httpx.Response`): riusato da `_rami_da_registro`, che legge il corpo
    via `fetch_guardato` (headers + bytes grezzi, non una `Response`)."""
    trovato = re.search(r"charset=([\w-]+)", content_type, re.I)
    charset = trovato.group(1) if trovato else "iso-8859-1"
    try:
        return contenuto.decode(charset, errors="replace")
    except LookupError:
        return contenuto.decode("iso-8859-1", errors="replace")


def _decodifica(risposta: httpx.Response) -> str:
    """Decodifica il corpo secondo il charset dichiarato in Content-Type,
    ripiego ISO-8859-1 se assente o sconosciuto. I portali Halley dichiarano
    windows-1252/ISO-8859-1: un decode UTF-8 a forza corromperebbe gli
    accenti («mobilità» -> «mobilitÃ »), esattamente ciò che questa funzione
    esiste per evitare."""
    content_type = risposta.headers.get("content-type", "") or ""
    return _decodifica_bytes(content_type, risposta.content)


# --- §4 Scoperta dei rami (due gradini) ---------------------------------


def _rami_wp(sonda: _Sonda, base: str) -> list[RamoAT] | None:
    """Gradino 1: REST AT del tema Design Comuni. `None` se il portale non
    espone la tassonomia — il chiamante prova poi l'HTML. `url` di ogni ramo
    è la query REST già pronta (stesso stampo di `bandi_live._rung1_cpt`):
    reale, dereferenziabile, e riusata verbatim in `_estrai_wp`."""
    rest_base_tax = _rest_base_tassonomia_per_tipo(sonda, base, CPT_AMM_TRASPARENTE)
    if rest_base_tax is None:
        return None
    rami: list[RamoAT] = []
    for categoria in _categorie(sonda, base, rest_base_tax):
        tipo = _tipo_da_slug(categoria.slug)
        if tipo is None:
            continue
        url = (
            f"{base}/wp-json/wp/v2/{CPT_AMM_TRASPARENTE}"
            f"?{rest_base_tax}={categoria.id}&per_page=20"
            "&_fields=title,link,date,excerpt,content&orderby=date&order=desc"
        )
        rami.append(RamoAT(etichetta=categoria.nome, url=url, tipo=tipo))
    return rami or None


def _pagina_at(sonda: _Sonda, base: str) -> str | None:
    """Il testo della pagina AT, letta da `{base}/amministrazione-trasparente/`
    o — se quella redirige alla home (WordPress la sposta sull'apex, caso
    Benevento) — dal link "trasparen..." trovato in home, anche fuori sito
    (A7: mai un host indovinato, sempre un href letto da una pagina già
    raggiunta navigando dal comune). `None` se nessuna delle due si legge."""
    try:
        risposta = sonda.risposta(f"{base}/amministrazione-trasparente/")
    except Exception:  # noqa: BLE001 — pagina muta: si prova la home
        risposta = None
    if risposta is not None and risposta.status_code == 200:
        percorso_finale = urlparse(str(risposta.url)).path
        if percorso_finale not in ("", "/"):
            return _decodifica(risposta)

    try:
        home = sonda.risposta(f"{base}/")
    except Exception:  # noqa: BLE001 — home muta: nessuna pagina AT
        return None
    if home.status_code != 200:
        return None
    pagina_home = _decodifica(home)
    for href, testo in _ancore(pagina_home):
        if "trasparen" not in _normalizza_testo(testo) and "trasparen" not in href.lower():
            continue
        url_at = _normalizza_link(base, href)
        try:
            risposta_at = sonda.risposta(url_at)
        except Exception:  # noqa: BLE001 — link trovato ma portale muto
            continue
        if risposta_at.status_code == 200:
            return _decodifica(risposta_at)
    return None


def _rami_html(sonda: _Sonda, base: str) -> list[RamoAT] | None:
    """Gradino 2: pagina AT letta come HTML, ancore matchate tollerante."""
    pagina = _pagina_at(sonda, base)
    if pagina is None:
        return None
    rami = _rami_da_pagina(base, pagina)
    return rami or None


# --- §4bis Cache dedicata dei rami (D-05) e semina dal registro (D-01/D-02) ---


def _percorso_rami(codice_istat: str) -> Path:
    return CACHE_DIR / codice_istat / "rami.json"


def _rami_da_cache(codice_istat: str) -> list[RamoAT] | None:
    """I rami già scoperti, letti dalla cache DEDICATA (`rami.json`, TTL
    lungo `TTL_ORE_RAMI`) — percorso e schema separati da `_da_cache`
    (`bandi.json`, TTL `TTL_ORE`): questa funzione non tocca né rilegge la
    cache bandi. Cache assente, scaduta o illeggibile -> `None`, mai un
    crash (stesso trattamento di `_da_cache`)."""
    percorso = _percorso_rami(codice_istat)
    if not percorso.exists():
        return None
    try:
        esito = _CacheRami.model_validate_json(percorso.read_text("utf-8"))
        eta = datetime.now(timezone.utc) - datetime.fromisoformat(esito.verificato_il)
    except Exception:  # noqa: BLE001 — cache illeggibile è cache assente
        logger.warning("cache rami illeggibile: %s", percorso)
        return None
    return esito.rami if eta.total_seconds() < TTL_ORE_RAMI * 3600 else None


def _rami_in_cache(codice_istat: str, rami: list[RamoAT]) -> None:
    """Scrittura atomica (`.tmp` + replace), stesso stampo di `_in_cache`.
    Chiamata SOLO con `rami` non vuota — un esito negativo non deve mai
    fissarsi su disco (stessa regola di `_in_cache`, [[predicato-gating-
    cieco-a-nuovo-campo]])."""
    percorso = _percorso_rami(codice_istat)
    esito = _CacheRami(versione=3, verificato_il=datetime.now(timezone.utc).isoformat(), rami=rami)
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(esito.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        logger.warning("cache rami non scrivibile (%s): %s", percorso, exc)


def _rami_da_registro(codice_istat: str, *, timeout: float) -> list[RamoAT] | None:
    """Semina i rami dalla pagina AT già catalogata in
    `registro.endpoints.at` (D-01: parte da un fatto già scritto da una
    scansione connettore precedente, non ripete la ricerca sulla home).
    Import lazy di `leggi_registro`, stesso stampo di
    `bandi_live._piattaforma_e_connettore_at`: evita un giro di import a
    modulo (`registro` non è mai stata una dipendenza forte di
    `alberatura`) e qualunque anomalia (registro non ancora scritto, modulo
    assente) degrada a `None`, mai un crash.

    D-02: la URL catalogata NON salta la guardia host — è passata a
    `fetch_guardato` con `host_atteso` derivato dal SUO stesso host
    (`urlsplit(at_url).hostname`, minuscolo, senza `www.`), stesso stampo di
    `bandi_hgate.bandi_hgate`. `base` per risolvere gli href relativi è lo
    schema+host della pagina EFFETTIVAMENTE raggiunta (`url_finale` da
    `fetch_guardato`, dopo eventuali redirect), non `comune.sito`: la pagina
    AT può vivere su un SaaS fuori dal dominio del comune."""
    at_urls: list[str] = []
    try:
        from treasureiq.registro import leggi_registro

        record = leggi_registro(codice_istat)
    except Exception:  # noqa: BLE001 — registro muto: nessun seme, mai un crash
        record = None
    if record is not None and record.endpoints.at:
        at_urls.append(record.endpoints.at)
    # Il registro runtime può esistere ma non avere ancora l'endpoint AT;
    # il census nazionale resta il fallback read-only in entrambi i casi.
    try:
        catalogo_at = (portale_del_comune(STORICO_DB, codice_istat) or {}).get("at_url")
    except Exception:  # noqa: BLE001 — catalogo nazionale non disponibile
        catalogo_at = None
    if catalogo_at and catalogo_at not in at_urls:
        at_urls.append(catalogo_at)
    if not at_urls:
        return None
    for at_url in at_urls:
        host = urlsplit(at_url).hostname
        host_atteso = host.lower().removeprefix("www.") if host else None
        esito = fetch_guardato(
            at_url, timeout=timeout, max_bytes=MAX_BYTES_AT, host_atteso=host_atteso,
        )
        if esito is None:
            continue
        intestazioni, contenuto, url_finale = esito
        pagina = _decodifica_bytes(intestazioni.get("content-type", "") or "", contenuto)
        rami = _rami_da_pagina(url_finale, pagina)
        if rami:
            return rami
    return None


def scopri_rami(codice_istat: str, *, timeout: float = 8.0) -> list[RamoAT] | None:
    """I rami ANAC bersaglio (bandi/agevolazioni) di un comune. `None` se il
    comune non è noto, non ha sito, o il portale non è leggibile / non ha
    nessun ramo riconosciuto — esito onesto a monte.

    Ordine di scoperta (D-01/D-05/D-06): (1) cache DEDICATA dei rami
    (`_rami_da_cache`, TTL lungo) — zero rete se calda; (2) la pagina AT già
    catalogata in `registro.endpoints.at` (`_rami_da_registro`) — nessuna
    ripartenza dalla home, ma la guardia host resta intera; (3) la catena
    originale (`_rami_wp` poi `_rami_html`, a partire dalla home del
    comune). Qualunque gradino produca rami non vuoti finisce in cache —
    anche il gradino (3), così una prossima chiamata non ripete la
    scansione. Mai un negativo cachato (stessa regola di `_in_cache`)."""
    cache = _rami_da_cache(codice_istat)
    if cache is not None:
        return cache

    comune = comune_per_codice(codice_istat)
    if comune is None or not comune.sito:
        return None

    rami = _rami_da_registro(codice_istat, timeout=timeout)
    if not rami:
        base = _base_con_schema(comune.sito)
        if base is None:
            return None
        with _Sonda(timeout=timeout) as sonda:
            rami = _rami_wp(sonda, base)
            if rami is None:
                rami = _rami_html(sonda, base)

    if rami:
        _rami_in_cache(codice_istat, rami)
    return rami


# --- §5 Estrazione per vendor ---------------------------------------------


def _estrai_wp(sonda: _Sonda, base: str, ramo: RamoAT) -> list[BandoScoperto]:
    """`ramo.url` è già la query REST completa (`_rami_wp`): un fetch solo,
    nessuna ricostruzione."""
    try:
        righe = sonda.json(ramo.url)
    except Exception:  # noqa: BLE001 — collezione muta: nessun bando da qui
        return []
    if not isinstance(righe, list):
        return []
    trovati: list[BandoScoperto] = []
    for riga in righe:
        bando = _bando_da_riga(base, riga)
        if bando is not None:
            trovati.append(BandoScoperto(bando=bando, tipo=ramo.tipo, vendor="wp"))
    return trovati


_RIGA_HALLEY_RE = re.compile(
    r"<tr\s+data-href=['\"](?P<href>[^'\"]+)['\"][^>]*>(?P<corpo>.*?)</tr>", re.I | re.S
)
_TITOLO_HALLEY_RE = re.compile(r"<a\b[^>]*>(?P<titolo>.*?)</a>", re.I | re.S)
_DATA_HALLEY_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


def _bandi_da_listing_halley(pagina: str, host_listing: str, tipo: str) -> list[BandoScoperto]:
    """Righe della tabella `cms-table` (listing concorsi Halley): un `<tr
    data-href>` per bando, titolo dal primo `<a>` dentro la riga, data dalla
    prima `dd/mm/yyyy` trovata (colonna «Data scadenza»), normalizzata a ISO
    `YYYY-MM-DD` (stessa data letta, solo riformattata — mai una cifra
    generata dal modello, D-06). Righe cappate a `MAX_RIGHE_HALLEY`."""
    trovati: list[BandoScoperto] = []
    for riga in _RIGA_HALLEY_RE.finditer(pagina):
        href = riga.group("href").strip()
        if href.lower().startswith(("http://", "https://")):
            if urlparse(href).netloc.lower() != host_listing.lower():
                continue  # guardia host: mai un dettaglio fuori dal portale letto (A7)
        corpo = riga.group("corpo")
        titolo_trovato = _TITOLO_HALLEY_RE.search(corpo)
        if titolo_trovato is None:
            continue
        titolo = html.unescape(re.sub(r"<[^>]+>", " ", titolo_trovato.group("titolo")))
        titolo = re.sub(r"\s+", " ", titolo).strip()
        if not titolo:
            continue
        data_trovata = _DATA_HALLEY_RE.search(corpo)
        data_grezza = data_trovata.group(1) if data_trovata else ""
        data_iso = data_grezza
        if data_grezza:
            try:
                data_iso = datetime.strptime(data_grezza, "%d/%m/%Y").date().isoformat()
            except ValueError:  # noqa: BLE001 — formato inatteso, si tiene il testo letto
                pass
        bando = Bando(
            titolo=titolo,
            url=_normalizza_link(f"https://{host_listing}", href),
            data=data_iso,
            anteprima=None,
        )
        trovati.append(BandoScoperto(bando=bando, tipo=tipo, vendor="halley"))  # type: ignore[arg-type]
    return trovati[:MAX_RIGHE_HALLEY]


def _estrai_halley(sonda: _Sonda, ramo: RamoAT) -> list[BandoScoperto]:
    """Concorsi: si segue `ramo.url` (già l'ancora «Bandi di concorso
    attivi», scoperta DALLA pagina AT — A7) più la route fissa del listing
    in corso. Le agevolazioni Halley non hanno un listing tabellare
    equivalente: fuori scope B1, si estraggono solo i concorsi."""
    if ramo.tipo != "concorso":
        return []
    listing_url = f"{ramo.url.rstrip('/')}/index/index/concorsi/in-corso"
    try:
        risposta = sonda.risposta(listing_url)
    except Exception:  # noqa: BLE001 — listing muto: nessun bando da qui
        return []
    if risposta.status_code != 200:
        return []
    pagina = _decodifica(risposta)
    host_listing = urlparse(listing_url).netloc
    return _bandi_da_listing_halley(pagina, host_listing, ramo.tipo)


_BOOTSTRAP_EMPTY_RE = re.compile(r"nessun\s+(?:bando|avviso).*?(?:pubblicazione|presente)", re.I | re.S)


def _estrai_bootstrap_italia(sonda: _Sonda, ramo: RamoAT) -> tuple[list[BandoScoperto], bool]:
    """Recognise an explicit empty Bootstrap Italia listing.

    A non-empty page is deliberately left unsupported: returning an empty list
    there would turn unknown content into "no notice published".
    """
    try:
        risposta = sonda.risposta(ramo.url)
    except Exception:  # noqa: BLE001
        return [], False
    if risposta.status_code != 200:
        return [], False
    pagina = _decodifica(risposta)
    if "bootstrap-italia" not in pagina or not _BOOTSTRAP_EMPTY_RE.search(pagina):
        return [], False
    return [], True


_DATA_ITALIANA_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_RIGA_ASMENET_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
_CELLA_ASMENET_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.I | re.S)
_ALLEGATO_ASMENET_RE = re.compile(
    r"href\s*=\s*['\"]([^'\"]*event=vediallegato[^'\"]*)['\"]", re.I
)


def _testo_html(testo: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", testo))).strip()


def _estrai_asmenet(sonda: _Sonda, _base: str, ramo: RamoAT) -> list[BandoScoperto] | None:
    """Legge il listing tabellare Asmenet senza aprire gli allegati."""
    try:
        risposta = sonda.risposta(ramo.url)
    except Exception:  # noqa: BLE001
        return None
    if risposta.status_code != 200:
        return None
    pagina = _decodifica(risposta)
    if "asmenet.it" not in urlparse(ramo.url).netloc.lower() or "ogg_table" not in pagina:
        return None
    host = urlparse(ramo.url).netloc.lower()
    trovati: list[BandoScoperto] = []
    for riga in _RIGA_ASMENET_RE.findall(pagina):
        celle = _CELLA_ASMENET_RE.findall(riga)
        if len(celle) < 4:
            continue
        titolo = _testo_html(celle[3])
        allegato = _ALLEGATO_ASMENET_RE.search(riga)
        if not titolo or allegato is None:
            continue
        url = urljoin(ramo.url, html.unescape(allegato.group(1)))
        if urlparse(url).netloc.lower() != host:
            continue
        data = _DATA_ITALIANA_RE.search(_testo_html(celle[0]))
        data_iso = ""
        if data:
            data_iso = f"{data.group(3)}-{data.group(2)}-{data.group(1)}"
        trovati.append(
            BandoScoperto(
                bando=Bando(titolo=titolo, url=url, data=data_iso, anteprima=None),
                tipo=ramo.tipo,
                vendor="asmenet",
            )
        )
    return trovati[:MAX_RIGHE_HALLEY]


def _estrai_dgegovpa(sonda: _Sonda, _base: str, ramo: RamoAT) -> list[BandoScoperto] | None:
    """Legge i dettagli pubblicati nelle pagine BandiConcorso di dgegovpa."""
    try:
        risposta = sonda.risposta(ramo.url)
    except Exception:  # noqa: BLE001
        return None
    if risposta.status_code != 200:
        return None
    pagina = _decodifica(risposta)
    if "dgegovpa.it" not in urlparse(ramo.url).netloc.lower() or "Bandi di concorso" not in pagina:
        return None
    trovati: list[BandoScoperto] = []
    for href, testo in _ancore(pagina):
        if "bandiconcorso.aspx?dettaglio=" not in href.lower():
            continue
        titolo = _testo_html(testo)
        if not titolo:
            continue
        trovati.append(
            BandoScoperto(
                bando=Bando(
                    titolo=titolo,
                    url=urljoin(ramo.url, href),
                    data="",
                    anteprima=None,
                ),
                tipo=ramo.tipo,
                vendor="dgegovpa",
            )
        )
    return trovati[:MAX_RIGHE_HALLEY]


def _estrai_peopleweb(sonda: _Sonda, _base: str, ramo: RamoAT) -> list[BandoScoperto] | None:
    """Legge le card della sezione concorsi PeopleWeb, senza aprire dettagli."""
    try:
        risposta = sonda.risposta(ramo.url)
    except Exception:  # noqa: BLE001
        return None
    if risposta.status_code != 200:
        return None
    pagina = _decodifica(risposta)
    if "card-teaser" not in pagina or "Bandi di concorso" not in pagina:
        return None
    trovati: list[BandoScoperto] = []
    for href, testo in _ancore(pagina):
        path = urlparse(href).path.lower()
        titolo = _testo_html(testo)
        if not re.search(r"/amministrazione-trasparente-dett/\d+/", path):
            continue
        titolo_normalizzato = _normalizza_testo(titolo)
        if titolo_normalizzato == _normalizza_testo(ramo.etichetta):
            continue
        if titolo_normalizzato.startswith("bandi di concorso "):
            continue
        if not re.search(r"\b(?:bando|avviso|concorso)\b", titolo_normalizzato):
            continue
        trovati.append(
            BandoScoperto(
                bando=Bando(titolo=titolo, url=urljoin(ramo.url, href), data="", anteprima=None),
                tipo=ramo.tipo,
                vendor="peopleweb",
            )
        )
    return trovati[:MAX_RIGHE_HALLEY]


_SISCOM_DNN_BANDO_RE = re.compile(
    r'<a\b(?=[^>]*\bSiscomTitolo\b)(?=[^>]*\bhref=[\'\"](?P<href>[^\'\"]+))[^>]*>(?P<titolo>.*?)</a>',
    re.I | re.S,
)
_SISCOM_DNN_DELEGA_RE = re.compile(r"concorsi.*?\bbanditi\s+dall", re.I | re.S)


def _estrai_siscom_dnn(sonda: _Sonda, _base: str, ramo: RamoAT) -> list[BandoScoperto] | None:
    """Legge le schede locali Siscom/DotNetNuke, lasciando le deleghe in review."""
    try:
        risposta = sonda.risposta(ramo.url)
    except Exception:  # noqa: BLE001
        return None
    if risposta.status_code != 200:
        return None
    pagina = _decodifica(risposta)
    if "SiscomVociMenu_LabelTitolo3" not in pagina or "BANDI DI CONCORSO" not in pagina.upper():
        return None
    if _SISCOM_DNN_DELEGA_RE.search(_testo_html(pagina)):
        return None
    host = urlparse(ramo.url).hostname.lower() if urlparse(ramo.url).hostname else ""
    trovati: list[BandoScoperto] = []
    for corrispondenza in _SISCOM_DNN_BANDO_RE.finditer(pagina):
        titolo = _testo_html(corrispondenza.group("titolo"))
        if not titolo or _normalizza_testo(titolo) == _normalizza_testo(ramo.etichetta):
            continue
        url = urljoin(ramo.url, html.unescape(corrispondenza.group("href")))
        if urlparse(url).hostname.lower() != host:
            continue
        trovati.append(
            BandoScoperto(
                bando=Bando(titolo=titolo, url=url, data="", anteprima=None),
                tipo=ramo.tipo,
                vendor="siscom_dnn",
            )
        )
    return trovati[:MAX_RIGHE_HALLEY]


_HYPERSIC_RIGA_RE = re.compile(r'<li class="my-3">(?P<corpo>.*?)</li>', re.I | re.S)
_HYPERSIC_TESTO_RE = re.compile(r'<div class="text-dark fs-6">(?P<testo>.*?)</div>', re.I | re.S)
_HYPERSIC_DETT_RE = re.compile(r'href=[\'\"](?P<href>[^\'\"]*trasparenzaamministrativadettaglio\.aspx[^\'\"]*)', re.I)
_HYPERSIC_DATA_RE = re.compile(r"Pubblicato\s+il\s+(\d{2})/(\d{2})/(\d{4})", re.I)


def _estrai_hypersic(sonda: _Sonda, _base: str, ramo: RamoAT) -> list[BandoScoperto] | None:
    """HyperSIC richiede il cookie della landing prima del listing AT."""
    landing = urljoin(ramo.url, "trasparenzaamministrativa.aspx")
    try:
        if sonda.risposta(landing).status_code != 200:
            return None
        risposta = sonda.risposta(ramo.url)
    except Exception:  # noqa: BLE001
        return None
    if risposta.status_code != 200:
        return None
    pagina = _decodifica(risposta)
    if '<h1 id="pagTitle">Bandi di concorso</h1>' not in pagina:
        return None
    host = urlparse(ramo.url).hostname.lower() if urlparse(ramo.url).hostname else ""
    trovati: list[BandoScoperto] = []
    for riga in _HYPERSIC_RIGA_RE.finditer(pagina):
        corpo = riga.group("corpo")
        dettaglio = _HYPERSIC_DETT_RE.search(corpo)
        testo = _HYPERSIC_TESTO_RE.search(corpo)
        if dettaglio is None or testo is None:
            continue
        titolo = _testo_html(testo.group("testo"))
        url = urljoin(ramo.url, html.unescape(dettaglio.group("href")))
        if (
            not titolo
            or "nessun documento da pubblicare" in _normalizza_testo(titolo)
            or urlparse(url).hostname.lower() != host
        ):
            continue
        data = _HYPERSIC_DATA_RE.search(_testo_html(corpo))
        data_iso = f"{data.group(3)}-{data.group(2)}-{data.group(1)}" if data else ""
        trovati.append(BandoScoperto(bando=Bando(titolo=titolo, url=url, data=data_iso, anteprima=None), tipo=ramo.tipo, vendor="hypersic"))
    return trovati[:MAX_RIGHE_HALLEY]


_HGATE_SEZIONE_RE = re.compile(r"/EG0/EGSCHTST(?:49|50|51)\.HBL", re.I)
_HGATE_SCHEDA_RE = re.compile(
    r'<a\b[^>]*href=[\'\"](?P<href>[^\'\"]*scheda_bando_di_concorso[^\'\"]*)[\'\"][^>]*>'
    r"(?P<titolo>.*?)</a>",
    re.I | re.S,
)
_HGATE_PAGINA_RE = re.compile(r"Pagina\s+(?P<corrente>\d+)\s+di\s+(?P<totale>\d+)", re.I)
_HGATE_SUCCESSIVA_RE = re.compile(
    r"LEGGE\(\s*'(?P<query>[^']*MESSA=PAGSUCC=)'\s*\+\s*"
    r"\(Number\((?P<corrente>\d+)\)\s*\+\s*1\)\s*\)",
    re.I,
)
MAX_PAGINE_HGATE = 20


def _decodifica_hgate(risposta: httpx.Response) -> str:
    """HGate moderno dichiara UTF-8 nel markup, spesso non nell'header."""
    if b'charset="utf-8"' in risposta.content[:2048].lower():
        return risposta.content.decode("utf-8", errors="replace")
    return _decodifica(risposta)


def _estrai_hgate(sonda: _Sonda, _base: str, ramo: RamoAT) -> list[BandoScoperto] | None:
    """Legge le tre liste concorsi HGate già linkate dalla landing AT."""
    try:
        landing = sonda.risposta(ramo.url)
    except Exception:  # noqa: BLE001
        return None
    if landing.status_code != 200:
        return None
    pagina_landing = _decodifica_hgate(landing)
    if 'id="titolo_social">Bandi di concorso' not in pagina_landing:
        return None
    host = urlparse(ramo.url).netloc.lower()
    sezioni: list[str] = []
    for href, testo in _ancore(pagina_landing):
        url = urljoin(ramo.url, href)
        if (
            _HGATE_SEZIONE_RE.search(urlparse(url).path)
            and _normalizza_testo(testo).startswith("bandi di concorso")
            and urlparse(url).netloc.lower() == host
            and url not in sezioni
        ):
            sezioni.append(url)
    if not sezioni:
        return None

    trovati: list[BandoScoperto] = []
    for sezione in sezioni:
        pagina_url = sezione
        viste: set[str] = set()
        while pagina_url:
            if pagina_url in viste or len(viste) >= MAX_PAGINE_HGATE:
                return None
            viste.add(pagina_url)
            try:
                risposta = sonda.risposta(pagina_url)
            except Exception:  # noqa: BLE001
                return None
            if risposta.status_code != 200:
                return None
            pagina = _decodifica_hgate(risposta)
            if "lista-aggiuntivo" not in pagina or "Bandi di concorso" not in pagina:
                return None
            for corrispondenza in _HGATE_SCHEDA_RE.finditer(pagina):
                url = urljoin(pagina_url, html.unescape(corrispondenza.group("href")))
                if urlparse(url).netloc.lower() != host:
                    continue
                titolo = _testo_html(corrispondenza.group("titolo"))
                if titolo:
                    trovati.append(
                        BandoScoperto(
                            bando=Bando(titolo=titolo, url=url, data="", anteprima=None),
                            tipo=ramo.tipo,
                            vendor="hgate",
                        )
                    )
            paginazione = _HGATE_PAGINA_RE.search(pagina)
            if paginazione is None or int(paginazione.group("corrente")) >= int(paginazione.group("totale")):
                break
            if int(paginazione.group("totale")) > MAX_PAGINE_HGATE:
                return None
            successiva = _HGATE_SUCCESSIVA_RE.search(pagina)
            if successiva is None or int(successiva.group("corrente")) != int(paginazione.group("corrente")):
                return None
            pagina_url = (
                pagina_url.split("?", 1)[0]
                + "?"
                + html.unescape(successiva.group("query"))
                + str(int(paginazione.group("corrente")) + 1)
            )
    return trovati[:MAX_RIGHE_HALLEY]


_PARSER_AT: tuple[ParserAT, ...] = (
    ParserAT(
        nome="asmenet",
        versione="1.0.0",
        riconosce=lambda ramo: "asmenet.it" in urlparse(ramo.url).netloc.lower(),
        estrai=_estrai_asmenet,
    ),
    ParserAT(
        nome="dgegovpa",
        versione="1.0.0",
        riconosce=lambda ramo: (
            ramo.tipo == "concorso" and "dgegovpa.it" in urlparse(ramo.url).netloc.lower()
        ),
        estrai=_estrai_dgegovpa,
    ),
    ParserAT(
        nome="peopleweb",
        versione="1.0.0",
        riconosce=lambda ramo: "/amministrazione-trasparente-dett/" in ramo.url,
        estrai=_estrai_peopleweb,
    ),
    ParserAT(
        nome="siscom_dnn",
        versione="1.0.0",
        riconosce=lambda ramo: (
            "servizipubblicaamministrazione.it" in urlparse(ramo.url).netloc.lower()
            and "iddettaglio=" in ramo.url.lower()
        ),
        estrai=_estrai_siscom_dnn,
    ),
    ParserAT(
        nome="hypersic",
        versione="1.0.0",
        riconosce=lambda ramo: (
            "hypersicapp.net" in urlparse(ramo.url).netloc.lower()
            and "trasparenzaamministrativadocs.aspx?cp=" in ramo.url.lower()
        ),
        estrai=_estrai_hypersic,
    ),
    ParserAT(
        nome="hgate",
        versione="1.0.0",
        riconosce=lambda ramo: (
            ramo.tipo == "concorso"
            and "/EG0/EGSCHTST48.HBL" in urlparse(ramo.url).path.upper()
        ),
        estrai=_estrai_hgate,
    ),
)


def _parser_at(ramo: RamoAT) -> ParserAT | None:
    return next((parser for parser in _PARSER_AT if parser.riconosce(ramo)), None)


def _ramo_gestito(ramo: RamoAT) -> bool:
    """`True` se `ramo.url` porta la firma di un vendor con estrattore reale
    (wp o halley). Un ramo scoperto ma di vendor non gestito (openweb,
    PeopleWeb, Plone...) non è "coperto senza bandi": è non estraibile — la
    distinzione che fa `estrai_bandi` per non restituire `[]` (A4)."""
    return _parser_at(ramo) is not None or "/wp-json/wp/v2/" in ramo.url or "/zf/index.php/" in ramo.url


def _estrai_ramo(sonda: _Sonda, base: str, ramo: RamoAT) -> list[BandoScoperto] | None:
    """Il connettore si sceglie dalla forma di `ramo.url`, mai da un
    controllo separato: chi l'ha prodotto (`_rami_wp`/`_rami_html`) ha già
    incorporato la firma del vendor nell'url stesso."""
    parser = _parser_at(ramo)
    if parser is not None:
        return parser.estrai(sonda, base, ramo)
    if "/wp-json/wp/v2/" in ramo.url:
        return _estrai_wp(sonda, base, ramo)
    if "/zf/index.php/" in ramo.url:
        return _estrai_halley(sonda, ramo)
    return []


# --- §6 Cache (stampo `bandi_live._da_cache`/`_in_cache`, :138/:153) -----


def _percorso_cache(codice_istat: str) -> Path:
    return CACHE_DIR / codice_istat / "bandi.json"


def _da_cache(codice_istat: str) -> list[BandoScoperto] | None:
    percorso = _percorso_cache(codice_istat)
    if not percorso.exists():
        return None
    try:
        esito = _CacheAlberatura.model_validate_json(percorso.read_text("utf-8"))
        eta = datetime.now(timezone.utc) - datetime.fromisoformat(esito.verificato_il)
    except Exception:  # noqa: BLE001 — cache illeggibile è cache assente
        logger.warning("cache alberatura illeggibile: %s", percorso)
        return None
    return esito.bandi if eta.total_seconds() < TTL_ORE * 3600 else None


def _in_cache(codice_istat: str, bandi: list[BandoScoperto]) -> None:
    """Scrittura atomica: un lettore concorrente vede la cache vecchia o la
    nuova, mai una lista a metà. Chiamata SOLO con `bandi` non vuota — un
    esito negativo non deve mai fissarsi su disco."""
    percorso = _percorso_cache(codice_istat)
    esito = _CacheAlberatura(versione=2, verificato_il=datetime.now(timezone.utc).isoformat(), bandi=bandi)
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(esito.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        logger.warning("cache alberatura non scrivibile (%s): %s", percorso, exc)


def estrai_bandi(codice_istat: str, *, timeout: float = 8.0) -> list[BandoScoperto] | None:
    """I bandi scoperti sui rami AT del comune. `None` se `scopri_rami` è
    `None` (portale non leggibile/nessun ramo — esito onesto, mai cachato),
    o se i rami scoperti sono TUTTI di vendor non gestito (A4: openweb,
    PeopleWeb, Plone... esistono ma nessun estrattore li legge — non è
    "coperto senza bandi", è non supportato).
    Lista vuota se almeno un ramo è di vendor gestito ma nessun bando si
    estrae; anche questa NON si cachea, per non fissare un esito che una
    prossima scansione (un bando appena pubblicato) potrebbe smentire."""
    cache = _da_cache(codice_istat)
    if cache is not None:
        return cache

    rami = scopri_rami(codice_istat, timeout=timeout)
    if rami is None:
        return None
    comune = comune_per_codice(codice_istat)
    if comune is None or not comune.sito:
        return None
    base = _base_con_schema(comune.sito)
    if base is None:
        return None

    risultati: list[BandoScoperto] = []
    coperto = False
    with _Sonda(timeout=timeout) as sonda:
        for ramo in rami:
            if _ramo_gestito(ramo):
                estratti = _estrai_ramo(sonda, base, ramo)
                if estratti is None:
                    continue
                coperto = True
                risultati.extend(estratti)
            else:
                bootstrap, gestito = _estrai_bootstrap_italia(sonda, ramo)
                coperto = coperto or gestito
                risultati.extend(bootstrap)

    if not coperto:
        return None

    if risultati:
        _in_cache(codice_istat, risultati)
    return risultati
