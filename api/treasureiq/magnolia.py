"""Connettore servizi Magnolia — variant A (catalogo KIB strutturato).

Un comune Magnolia con template civico condiviso espone il catalogo servizi via
un endpoint REST del componente KIB:

    {root}/.rest/kibernetes/v1/servizi/rendered?tipo=/Servizi/{NNN}&q=&page=1&pageSize=100

che risponde JSON ``{"total": N, "renderedPages": ["<card html>", ...]}``.  La
card canonica di un servizio è l'ancora ``<a data-element="service-link">``: il
titolo pulito sta nel testo, l'URL nell'``href`` (spesso un *sibling* SaaS
``servizi.comune.*``, stesso dominio registrabile del sito).

Confini onesti (misurati sullo sweep dei 59 comuni magnolia):

* **Solo variant A.**  Se l'endpoint REST non risponde JSON (variant B — il
  comune non ha deployato il catalogo strutturato, es. Massa Marittima), NON si
  indovina: ``esito='variante_non_strutturata'``, ``servizi=[]``, il rail
  ricade su URP.  Non è "0 copertura", è superficie diversa.
* **Categorie 106 / 109 / 113** (Anagrafe e stato civile · Tributi, finanze ·
  Autorizzazioni), le tre che coprono le sei ServiceKey note.
* **Indice completo**, non i soli servizi in evidenza: ``pageSize=100`` prende
  tutto in una chiamata (max osservato 57 servizi/categoria).
* **Guardia host**: ogni URL servizio deve restare sullo stesso dominio
  registrabile del comune; il sibling SaaS ``servizi.comune.*`` è ammesso, un
  host cross-dominio è scartato (non inseguito).
* **TARI non forzata**: la resa reale è ~25% dei comuni — la maggioranza espone
  IMU ma non una TARI a catalogo.  L'assenza è un miss onesto, non un errore.

Questo modulo NON tocca il recognizer, il catalogo flat o il resolver: è un
lettore self-contained (come ``bandi_hgate``) esposto via
``LETTORE_SERVIZI_PER_PIATTAFORMA`` per il futuro rail servizi.

CLI:

    python -m treasureiq.magnolia 008017      # Cervo (variant A)
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
PAGE_SIZE = 100

#: Categorie AgID sondate, in ordine. Codice → etichetta canonica.
CATEGORIE: dict[str, str] = {
    "106": "Anagrafe e stato civile",
    "109": "Tributi, finanze",
    "113": "Autorizzazioni",
}

#: ServiceKey → pattern sui TITOLI servizio. TARI con lessico esteso (tariffa
#: gestione rifiuti, TARIP, rifiuti solidi urbani) — ma mai forzata: se non
#: compare a catalogo resta assente.
_SERVICE_KEY: dict[str, str] = {
    "CARTA_IDENTITA": r"carta d.?identit|\bcie\b|identit[aà] elettronic",
    "CAMBIO_RESIDENZA": r"residenz|cambio di (indirizzo|abitazione)",
    "ACCESSO_ATTI": r"accesso agli atti|accesso civico|accesso document",
    "STATO_CIVILE": r"stato civile|matrimoni|nascit|cittadinanz|unione civile|morte|decess",
    "TRIBUTI_IMU": r"\bimu\b|imposta municipale",
    "TRIBUTI_TARI": (
        r"\btari\b|\btarip\b|tassa rifiuti|tassa sui rifiuti|rifiuti urbani|"
        r"tariffa.{0,20}rifiuti|rifiuti solidi urbani|gestione dei rifiuti|"
        r"tassa (sull.?)?igiene ambientale"
    ),
}

_ENDPOINT = "/.rest/kibernetes/v1/servizi/rendered"
_TAG = re.compile(r"<[^>]+>")
#: ancora servizio canonica: cattura l'intera <a data-element="service-link"...>...</a>
_ANCHOR = re.compile(r'<a\b[^>]*data-element="service-link"[^>]*>.*?</a>', re.I | re.S)
_HREF = re.compile(r'href=["\']([^"\']+)', re.I)


# --------------------------------------------------------------------------- #
# Modelli                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ServizioMagnolia:
    """Un servizio a catalogo. ``url``/``host`` possono puntare al sibling SaaS."""

    titolo: str
    url: str
    host: str
    categoria: str  # codice AgID (es. "106")
    service_key: str | None  # ServiceKey riconosciuta dal titolo, o None


@dataclass
class EsitoMagnoliaServizi:
    """Esito del lettore servizi Magnolia per un comune.

    ``esito``: ``ok`` | ``vuoto`` (strutturato, 0 servizi) |
    ``variante_non_strutturata`` (variant B → URP) | ``irraggiungibile``.
    ``variante``: ``strutturata`` | ``non_strutturata`` | ``irraggiungibile`` —
    esattamente una, mutuamente esclusive.
    """

    esito: str
    codice_istat: str
    comune: str
    home: str
    variante: str
    servizi: list[ServizioMagnolia] = field(default_factory=list)
    per_categoria: dict[str, int | None] = field(default_factory=dict)
    service_keys: list[str] = field(default_factory=list)
    note: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Helper puri                                                                  #
# --------------------------------------------------------------------------- #
def _pulisci(testo: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG.sub("", testo))).strip()


def _host_di(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _registrable(host: str) -> str:
    """Dominio registrabile grezzo (ultimi due label) per il confine SaaS-sibling."""
    parti = (host or "").split(".")
    return ".".join(parti[-2:]) if len(parti) >= 2 else host


def _root(home: str) -> str:
    """scheme://netloc/ del sito, ignorando ogni path dichiarato (es. .../home)."""
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


def _estrai_servizi(
    cards_html: str, categoria: str, host_comune: str
) -> tuple[list[ServizioMagnolia], list[ServizioMagnolia]]:
    """Card ``data-element=service-link`` → (ammessi, scartati) con guardia host.

    Un URL su dominio registrabile diverso dal comune è scartato (non inseguito):
    il sibling SaaS ``servizi.comune.*`` passa perché condivide il registrabile.
    href relativo (host vuoto) = on-site, sempre ammesso.
    """
    reg_comune = _registrable(host_comune)
    dentro: list[ServizioMagnolia] = []
    fuori: list[ServizioMagnolia] = []
    for anchor in _ANCHOR.findall(cards_html):
        titolo = _pulisci(anchor)
        if not titolo:
            continue
        mh = _HREF.search(anchor)
        url = mh.group(1) if mh else ""
        host = _host_di(url) if url else ""
        servizio = ServizioMagnolia(
            titolo=titolo, url=url, host=host, categoria=categoria,
            service_key=service_key_di(titolo),
        )
        if host and _registrable(host) != reg_comune:
            fuori.append(servizio)
        else:
            dentro.append(servizio)
    return dentro, fuori


def _fetch(fetch, url: str, host_atteso: str, timeout: float):
    """Wrapper: ritorna (body_bytes, final_url) o None. Isola la forma del guard."""
    res = fetch(url, timeout=timeout, max_bytes=MAX_BYTES, host_atteso=host_atteso)
    if res is None:
        return None
    return res[1], res[2]


def _sonda_categoria(fetch, root: str, host: str, code: str, timeout: float):
    """Ritorna dict {modo, total, servizi, scartati}. modo: rendered_json | muto."""
    url = urljoin(
        root, f".rest/kibernetes/v1/servizi/rendered?tipo=/Servizi/{code}&q=&page=1&pageSize={PAGE_SIZE}".lstrip("/")
    )
    got = _fetch(fetch, url, host, timeout)
    if got is None:
        return {"modo": "muto", "total": None, "servizi": [], "scartati": []}
    body = got[0].decode("utf-8", "replace").lstrip()
    if body[:1] != "{":
        return {"modo": "muto", "total": None, "servizi": [], "scartati": []}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"modo": "muto", "total": None, "servizi": [], "scartati": []}
    cards = " ".join(payload.get("renderedPages", []))
    servizi, scartati = _estrai_servizi(cards, code, host)
    return {"modo": "rendered_json", "total": payload.get("total"),
            "servizi": servizi, "scartati": scartati}


# --------------------------------------------------------------------------- #
# Lettore                                                                      #
# --------------------------------------------------------------------------- #
def leggi_magnolia_servizi(
    codice_istat: str,
    *,
    home: str | None = None,
    comune: str = "",
    fetch=fetch_guardato,
    categorie: dict[str, str] = CATEGORIE,
    timeout: float = TIMEOUT_DEFAULT,
) -> EsitoMagnoliaServizi:
    """Legge il catalogo servizi Magnolia (variant A). Non solleva mai.

    ``home`` e ``comune`` di norma vengono risolti da ``storico.db``; sono
    parametri per rendere il lettore testabile net-free con fixture.
    """
    if home is None:
        home, comune = _risolvi_home(codice_istat)
    if not home:
        return EsitoMagnoliaServizi(
            esito="irraggiungibile", codice_istat=codice_istat, comune=comune,
            home="", variante="irraggiungibile",
            note=("home del comune non nota in storico.db",),
        )
    root = _root(home)
    host = _host_di(root)

    per_categoria: dict[str, int | None] = {}
    strutturata = False
    tutti: list[ServizioMagnolia] = []
    n_scartati = 0
    for code in categorie:
        c = _sonda_categoria(fetch, root, host, code, timeout)
        per_categoria[code] = c["total"]
        if c["modo"] == "rendered_json":
            strutturata = True
            tutti.extend(c["servizi"])
            n_scartati += len(c["scartati"])

    # Gate esattamente-uno: la variante del comune è UNA sola.
    if strutturata:
        servizi = _dedup(tutti)
        chiavi = sorted({s.service_key for s in servizi if s.service_key})
        note: list[str] = []
        if n_scartati:
            note.append(f"{n_scartati} link servizio scartati (host fuori dominio comune)")
        if "TRIBUTI_TARI" not in chiavi:
            note.append("TARI non a catalogo: assenza reale, non forzata")
        return EsitoMagnoliaServizi(
            esito="ok" if servizi else "vuoto",
            codice_istat=codice_istat, comune=comune, home=home,
            variante="strutturata", servizi=servizi, per_categoria=per_categoria,
            service_keys=chiavi, note=tuple(note),
        )

    # Nessuna categoria strutturata: variant B se la home risponde, altrimenti muto.
    home_viva = _fetch(fetch, urljoin(root, "home/servizi.html"), host, timeout) is not None
    if home_viva:
        return EsitoMagnoliaServizi(
            esito="variante_non_strutturata", codice_istat=codice_istat,
            comune=comune, home=home, variante="non_strutturata",
            per_categoria=per_categoria,
            note=("catalogo KIB non deployato (variant B): fallback URP, miss onesto",),
        )
    return EsitoMagnoliaServizi(
        esito="irraggiungibile", codice_istat=codice_istat, comune=comune,
        home=home, variante="irraggiungibile", per_categoria=per_categoria,
        note=("endpoint REST e pagina servizi non raggiungibili",),
    )


def _dedup(servizi: list[ServizioMagnolia]) -> list[ServizioMagnolia]:
    """Dedup per URL (chiave forte); a URL assente/uguale, per titolo. Ordine stabile."""
    visti: set[str] = set()
    out: list[ServizioMagnolia] = []
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


#: Registry per-piattaforma del rail servizi STANDALONE (idioma di
#: ``bandi_live._GRADINI_PER_PIATTAFORMA``, come ``bandi_hgate``). Solo Magnolia
#: per ora. NON è il ``ConnectorRegistry`` di ``service_registry.py``: quel
#: registry (WP/AgID, ComWeb, OpenPA) alimenta il resolver ed è fenced; questo
#: dict è un rail separato, non ancora agganciato a un consumatore.
LETTORE_SERVIZI_PER_PIATTAFORMA = {
    Piattaforma.MAGNOLIA.value: leggi_magnolia_servizi,
}


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Legge il catalogo servizi Magnolia (variant A).")
    ap.add_argument("codice_istat", help="ISTAT del comune (es. 008017 = Cervo)")
    ap.add_argument("--timeout", type=float, default=TIMEOUT_DEFAULT)
    args = ap.parse_args(argv)
    esito = leggi_magnolia_servizi(args.codice_istat, timeout=args.timeout)
    d = asdict(esito)
    print(json.dumps(d, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
