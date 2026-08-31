"""Connettore servizi CSC OrchardCorePA/CKube — piattaforma ``comunibootstrapitalia``.

Un comune CSC (vendor *CSC Società Cooperativa Sociale*, ``coopcsc.it``, prodotto
CKube su Orchard Core, tema Bootstrap-Italia) pubblica il catalogo servizi come
**HTML server-rendered on-site**, senza REST né indice macchina:

* indice categorie: ``{root}/servizi/`` — ancore ``/servizi/categoria/{slug}``
  (15 categorie AgID canoniche);
* listato categoria: ``{root}/servizi/categoria/{slug}?pagenum=N`` — paginazione
  a finestra (il pager mostra solo i vicini della pagina corrente, quindi il
  massimo NON è deducibile dalla prima pagina: si itera finché una pagina non
  aggiunge servizi nuovi);
* dettaglio servizio: ``{root}/servizio/{slug}`` — slug AgID canonico, on-site.

Confini onesti (misurati sulla recon read-only dei 50 comuni):

* **Solo superficie informativa on-site.**  Il portale transazionale sta su
  ``servizi.<comune>`` (host diverso, form/appuntamenti): NON è inseguito.  Le
  ancore accettate sono ``/servizio/{slug}`` sullo **stesso host** del comune;
  un href cross-host è scartato (miss onesto, ``access_mode`` resta informativo).
* **Gate esattamente-uno (I-1)** per ServiceKey: 0 servizi → miss, esattamente 1
  → risolvibile, ≥2 → ambiguo (NOT_FOUND).  Su questa famiglia solo
  ``CARTA_IDENTITA`` e ``CAMBIO_RESIDENZA`` sono pulite (1 servizio ciascuna); le
  altre 4 key fanno fan-out (stato civile, atti, IMU, TARI) → ambigue.
* **service_id dall'URL**, mai dal titolo.
* **Nessuna key forzata**: TARI compare spesso come TARIP (tassa puntuale) — il
  lessico esteso la riconosce, ma se non è a catalogo resta assente.

Questo modulo NON tocca il recognizer, il catalogo flat o il resolver: è un
lettore self-contained (come ``magnolia``/``bandi_hgate``) esposto via
``LETTORE_SERVIZI_PER_PIATTAFORMA`` per il futuro rail servizi.  Nessun aggancio
a ``ConnectorRegistry``, nessuno sweep, nessuna scrittura.

CLI:

    python -m treasureiq.csc_orchardcore 017022      # Borno
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from treasureiq.ingest.host_guard import fetch_guardato
from treasureiq.ingest.piattaforma import Piattaforma

STORICO_DB = Path(__file__).resolve().parent.parent.parent / "data" / "storico.db"
CONNETTORE_VERSION = "1"
TIMEOUT_DEFAULT = 20.0
MAX_BYTES = 6_000_000
#: Tetto pagine per categoria: guardia contro pager patologici. Le categorie
#: reali osservate arrivano a 3 pagine; 15 è un margine largo ma finito.
MAX_PAGINE = 15

#: ServiceKey → pattern sui TITOLI servizio. Lessico AgID condiviso con il
#: connettore Magnolia (stessa tassonomia): TARI con lessico esteso (TARIP,
#: tariffa rifiuti, rifiuti solidi urbani) — ma mai forzata.
_SERVICE_KEY: dict[str, str] = {
    "CARTA_IDENTITA": r"carta d.?identit|\bcie\b|identit[aà] elettronic",
    # `residenz(?!ial)` tiene «cambio di residenza», «certificato di residenza»
    # ma esclude «(edilizia) residenziale» / ERP (falso positivo cross-categoria
    # visto sul crawl full di Borno). Il gate I-1 resta l'ultima difesa.
    "CAMBIO_RESIDENZA": r"residenz(?!ial)|cambio di (indirizzo|abitazione)",
    "ACCESSO_ATTI": r"accesso agli atti|accesso civico|accesso document",
    "STATO_CIVILE": r"stato civile|matrimoni|nascit|cittadinanz|unione civile|morte|decess",
    "TRIBUTI_IMU": r"\bimu\b|imposta municipale",
    "TRIBUTI_TARI": (
        r"\btari\b|\btarip\b|tassa rifiuti|tassa sui rifiuti|rifiuti urbani|"
        r"tariffa.{0,20}rifiuti|rifiuti solidi urbani|gestione dei rifiuti|"
        r"tassa (sull.?)?igiene ambientale"
    ),
}

_TAG = re.compile(r"<[^>]+>")
#: ancora servizio-dettaglio: cattura href (/servizio/{slug}) + testo interno.
_ANCHOR_SERVIZIO = re.compile(
    r'<a\b[^>]*?href=["\']([^"\']*/servizio/[^"\']*)["\'][^>]*>(.*?)</a>', re.I | re.S
)
#: ancora categoria nell'indice /servizi/.
_ANCHOR_CATEGORIA = re.compile(
    r'href=["\']([^"\']*/servizi/categoria/[^"\'?#]+)', re.I
)
#: link "pagina successiva" del pager Bootstrap-Italia (segnale di fine esplicito).
_ANCHOR_A = re.compile(r"<a\b[^>]*>", re.I)
_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_SEGNALE_NEXT = re.compile(r"successiv|rel=[\"']next[\"']|destination=next", re.I)


# --------------------------------------------------------------------------- #
# Modelli                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ServizioCsc:
    """Un servizio a catalogo. ``url`` è la pagina-dettaglio on-site."""

    titolo: str
    url: str
    host: str
    categoria: str  # slug AgID categoria (es. "anagrafe-e-stato-civile")
    service_key: str | None  # ServiceKey riconosciuta dal titolo, o None


@dataclass
class EsitoCscServizi:
    """Esito del lettore servizi CSC per un comune.

    ``esito``: ``ok`` | ``vuoto`` (indice presente, 0 servizi) |
    ``irraggiungibile`` (indice /servizi/ muto).
    """

    esito: str
    codice_istat: str
    comune: str
    home: str
    servizi: list[ServizioCsc] = field(default_factory=list)
    categorie: list[str] = field(default_factory=list)
    per_categoria: dict[str, int] = field(default_factory=dict)
    service_keys: list[str] = field(default_factory=list)
    note: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Helper puri                                                                  #
# --------------------------------------------------------------------------- #
def _pulisci(testo: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG.sub("", testo))).strip()


def _host_di(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _root(home: str) -> str:
    """scheme://netloc/ del sito, ignorando ogni path dichiarato."""
    sp = urlsplit(home if "//" in home else "https://" + home.lstrip("/"))
    scheme = sp.scheme or "https"
    return f"{scheme}://{sp.netloc}/"


def service_key_di(titolo: str) -> str | None:
    """Prima ServiceKey il cui pattern combacia col titolo, o None. TARI mai forzata."""
    t = titolo.lower()
    for chiave, pattern in _SERVICE_KEY.items():
        if re.search(pattern, t, re.I):
            return chiave
    return None


def _slug_categorie(index_html: str) -> list[str]:
    """Slug categoria dall'indice /servizi/, ordine di apparizione, dedup."""
    visti: set[str] = set()
    out: list[str] = []
    for href in _ANCHOR_CATEGORIA.findall(index_html):
        slug = urlsplit(href).path.rstrip("/").rsplit("/servizi/categoria/", 1)[-1]
        slug = slug.strip("/")
        if slug and slug not in visti:
            visti.add(slug)
            out.append(slug)
    return out


def _estrai_servizi(
    page_html: str, categoria: str, host_comune: str, root: str
) -> tuple[list[ServizioCsc], int]:
    """Ancore ``/servizio/{slug}`` → (ammessi on-site, n_scartati cross-host).

    Un URL su host diverso da quello del comune (es. portale transazionale
    ``servizi.<comune>``) è scartato, non inseguito.  href relativo = on-site.
    """
    dentro: list[ServizioCsc] = []
    scartati = 0
    for href, inner in _ANCHOR_SERVIZIO.findall(page_html):
        titolo = _pulisci(inner)
        if not titolo:
            continue
        assoluto = urljoin(root, href)
        host = _host_di(assoluto)
        if host and host != host_comune:
            scartati += 1
            continue
        dentro.append(
            ServizioCsc(
                titolo=titolo, url=assoluto, host=host, categoria=categoria,
                service_key=service_key_di(titolo),
            )
        )
    return dentro, scartati


def _next_href(html: str) -> str | None:
    """href del link 'pagina successiva' del pager, o None se assente (ultima pagina).

    Cerca un ``<a>`` con segnale next (aria-label 'successiva', ``rel=next`` o
    ``Destination=Next``). L'assenza è il segnale di fine AFFIDABILE: sull'ultima
    pagina il pager Bootstrap-Italia non emette il link successiva.
    """
    for tag in _ANCHOR_A.findall(html):
        if _SEGNALE_NEXT.search(tag):
            m = _HREF.search(tag)
            if m:
                return unescape(m.group(1))
    return None


def _prossima_pagina(html: str, corrente: int) -> int | None:
    """Numero della pagina successiva secondo il pager, o None se è l'ultima.

    Il ``pagenum`` viene letto dall'href del link successiva (URL canonico,
    ignorando il ``Destination=Next`` del SaaS); se l'href non lo espone si
    incrementa. Ritorna None anche se il pager punta indietro/uguale (guardia
    anti-loop)."""
    href = _next_href(html)
    if href is None:
        return None
    m = re.search(r"pagenum=(\d+)", href)
    prossima = int(m.group(1)) if m else corrente + 1
    return prossima if prossima > corrente else None


def _fetch(fetch, url: str, host_atteso: str, timeout: float):
    """Wrapper: ritorna body_bytes o None. Isola la forma del guard."""
    res = fetch(url, timeout=timeout, max_bytes=MAX_BYTES, host_atteso=host_atteso)
    if res is None:
        return None
    return res[1]


def _sonda_categoria(fetch, root: str, host: str, slug: str, timeout: float):
    """Crawl paginato di una categoria. Ritorna (servizi, n_scartati, troncata).

    **Criterio di fine = il pager stesso.** Si segue il link "pagina successiva"
    finché il pager lo emette; la sua ASSENZA è il segnale affidabile di ultima
    pagina. NON ci si ferma su "0 servizi nuovi": una pagina di soli duplicati
    (pager a finestra) può precedere una pagina con servizi nuovi. In assenza di
    un pager leggibile si procede fino al limite hard ``MAX_PAGINE`` (``troncata``
    = True se raggiunto senza segnale di fine → possibile catalogo incompleto).
    Nota: il server risponde 200 anche a ``pagenum`` oltre l'ultima (clamp
    sull'ultima pagina), quindi il non-200 NON è un criterio di stop valido.
    """
    servizi: list[ServizioCsc] = []
    scartati = 0
    visti: set[str] = set()
    pagina = 1
    troncata = False
    for iterazione in range(MAX_PAGINE):
        url = urljoin(root, f"servizi/categoria/{slug}?pagenum={pagina}")
        body = _fetch(fetch, url, host, timeout)
        if body is None:
            break
        html = body.decode("utf-8", "replace")
        trovati, sc = _estrai_servizi(html, slug, host, root)
        scartati += sc
        # ogni servizio ha due ancore (titolo + "Vai alla pagina", stesso URL):
        # il titolo reale arriva per primo → tenuto; dedup su URL intra/cross-pagina.
        for s in trovati:
            u = s.url.lower()
            if u in visti:
                continue
            visti.add(u)
            servizi.append(s)
        prossima = _prossima_pagina(html, pagina)
        if prossima is None:
            break  # pager senza link successiva → ultima pagina (segnale affidabile)
        pagina = prossima
    else:
        troncata = True  # cap hard raggiunto senza segnale di fine dal pager
    return servizi, scartati, troncata


# --------------------------------------------------------------------------- #
# Lettore                                                                      #
# --------------------------------------------------------------------------- #
def leggi_csc_servizi(
    codice_istat: str,
    *,
    home: str | None = None,
    comune: str = "",
    fetch=fetch_guardato,
    timeout: float = TIMEOUT_DEFAULT,
) -> EsitoCscServizi:
    """Legge il catalogo servizi CSC OrchardCorePA. Non solleva mai.

    ``home`` e ``comune`` di norma vengono risolti da ``storico.db``; sono
    parametri per rendere il lettore testabile net-free con fixture.
    """
    if home is None:
        home, comune = _risolvi_home(codice_istat)
    if not home:
        return EsitoCscServizi(
            esito="irraggiungibile", codice_istat=codice_istat, comune=comune,
            home="", note=("home del comune non nota in storico.db",),
        )
    root = _root(home)
    host = _host_di(root)

    index = _fetch(fetch, urljoin(root, "servizi/"), host, timeout)
    if index is None:
        return EsitoCscServizi(
            esito="irraggiungibile", codice_istat=codice_istat, comune=comune,
            home=home, note=("indice /servizi/ non raggiungibile",),
        )
    categorie = _slug_categorie(index.decode("utf-8", "replace"))

    per_categoria: dict[str, int] = {}
    tutti: list[ServizioCsc] = []
    n_scartati = 0
    troncate: list[str] = []
    for slug in categorie:
        servizi, sc, troncata = _sonda_categoria(fetch, root, host, slug, timeout)
        per_categoria[slug] = len(servizi)
        n_scartati += sc
        if troncata:
            troncate.append(slug)
        tutti.extend(servizi)

    servizi = _dedup(tutti)
    chiavi = sorted({s.service_key for s in servizi if s.service_key})
    note: list[str] = []
    if n_scartati:
        note.append(f"{n_scartati} link servizio scartati (host fuori dal comune)")
    if troncate:
        note.append(
            f"limite hard {MAX_PAGINE} pagine raggiunto senza fine pager "
            f"(catalogo possibilmente incompleto): {', '.join(troncate)}"
        )
    if not categorie:
        note.append("indice /servizi/ senza categorie: catalogo assente")
    return EsitoCscServizi(
        esito="ok" if servizi else "vuoto",
        codice_istat=codice_istat, comune=comune, home=home,
        servizi=servizi, categorie=categorie, per_categoria=per_categoria,
        service_keys=chiavi, note=tuple(note),
    )


def risolvi_per_chiave(esito: EsitoCscServizi, chiave: str) -> ServizioCsc | None:
    """Gate esattamente-uno (I-1): il servizio SE e SOLO SE la ServiceKey ha
    esattamente un candidato a catalogo. 0 → miss, ≥2 → ambiguo (NOT_FOUND)."""
    candidati = [s for s in esito.servizi if s.service_key == chiave]
    return candidati[0] if len(candidati) == 1 else None


def _dedup(servizi: list[ServizioCsc]) -> list[ServizioCsc]:
    """Dedup per URL (chiave forte); a URL assente/uguale, per titolo. Ordine stabile."""
    visti: set[str] = set()
    out: list[ServizioCsc] = []
    for s in servizi:
        chiave = s.url.strip().lower() if s.url.strip() else f"titolo::{s.titolo.lower()}"
        if chiave in visti:
            continue
        visti.add(chiave)
        out.append(s)
    return out


def _risolvi_home(codice_istat: str) -> tuple[str, str]:
    """(home, nome) dall'ultimo portale_snapshot; ('', '') se assente."""
    try:
        con = sqlite3.connect(str(STORICO_DB))
        row = con.execute(
            "SELECT url_finale, url_dichiarato, nome FROM portale_snapshot "
            "WHERE codice_istat=? ORDER BY rilevato_il DESC LIMIT 1",
            (codice_istat,),
        ).fetchone()
        con.close()
    except sqlite3.Error:
        return "", ""
    if not row:
        return "", ""
    home = (row[0] or row[1] or "").strip()
    return home, (row[2] or "")


#: Registry per-piattaforma del rail servizi STANDALONE (idioma di Magnolia /
#: ``bandi_hgate``). NON è il ``ConnectorRegistry`` di ``service_registry.py``:
#: quel registry (WP/AgID, ComWeb, OpenPA) alimenta il resolver ed è fenced;
#: questo dict è un rail separato, non ancora agganciato a un consumatore.
LETTORE_SERVIZI_PER_PIATTAFORMA = {
    Piattaforma.COMUNIBOOTSTRAPITALIA.value: leggi_csc_servizi,
}


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Legge il catalogo servizi CSC OrchardCorePA (comunibootstrapitalia)."
    )
    ap.add_argument("codice_istat", help="ISTAT del comune (es. 017022 = Borno)")
    ap.add_argument("--timeout", type=float, default=TIMEOUT_DEFAULT)
    args = ap.parse_args(argv)
    esito = leggi_csc_servizi(args.codice_istat, timeout=args.timeout)
    print(json.dumps(asdict(esito), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
