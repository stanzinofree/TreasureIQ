"""AgID organisational-unit types, read from the WordPress REST taxonomy.

WordPress sites on the AgID municipal model (Design Comuni theme, SoluzioniPA
OpenWeb) publish every organisational unit as one post type
(`unita_organizzativa`) and tag it with the `tipi_unita_organizzativa`
taxonomy: area, ufficio, giunta/consiglio comunale, commissione, ente, …
Without that tag a reader cannot tell an office from an administrative area,
a political body or an external company, and puts them all in `uffici`.

Term ids differ per site (Lesa: area=234, Cuneo: area=235), so the mapping
is by slug, read from the same site. The editorial tagging is a strong
default, not ground truth (on Lesa "Sindaco" is tagged `commissione`).

`leggi_unita_tipizzate` returns ``None`` when the site exposes no usable
taxonomy: callers then keep their previous, untyped behaviour. A site that is
only temporarily unavailable (timeout, 429, 5xx) is NOT "no taxonomy": that
raises `LetturaIncompleta`, so callers keep the last complete reading instead
of saving a truncated or untyped one.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

import httpx

TASSONOMIA = "tipi_unita_organizzativa"

UFFICIO = "ufficio"
AREA = "area"
#: Not a municipal office: political or collegial bodies, external entities.
FUORI = "fuori"

_SLUG_AREA = frozenset({"area"})
_SLUG_FUORI = frozenset({
    "struttura-politica", "giunta-comunale", "consiglio-comunale", "commissione",
    "gruppo-consiliare", "ente", "societa-partecipata", "fondazione",
    "azienda-municipalizzata",
})
# Everything else stays an office: `ufficio`, `struttura-amministrativa`,
# `altra-struttura`, places citizens contact (biblioteca, museo, scuola,
# centro-culturale), unknown future slugs and untyped units.

_PER_PAGINA = 100
#: 300 units at most: well above the largest observed (Cuneo, ~150).
MAX_PAGINE = 3


class LetturaIncompleta(RuntimeError):
    """The site answered only in part: keep the previous reading."""


def _transitorio(exc: BaseException) -> bool:
    """Network failure, rate limit or server error: try again later."""
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        stato = exc.response.status_code
        return stato == 429 or stato >= 500
    return False


def _fine_pagine(exc: BaseException) -> bool:
    """The proven end of the list: WordPress' 400 with its own error code.
    Any other 400 (e.g. `rest_invalid_param`) is not an end."""
    if not (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 400):
        return False
    try:
        corpo = exc.response.json()
    except ValueError:
        return False
    return isinstance(corpo, dict) and corpo.get("code") == "rest_post_invalid_page_number"


class _CollezioneAssente(Exception):
    """Page 1 of the unit collection does not exist (e.g. 404)."""


@dataclass(frozen=True)
class UnitaTipizzata:
    nome: str
    url: str
    categoria: str


def _categoria(slugs: set[str]) -> str:
    if "ufficio" in slugs or not slugs:
        return UFFICIO
    if slugs & _SLUG_AREA:
        return AREA
    if slugs <= _SLUG_FUORI:
        return FUORI
    return UFFICIO


def _slug_per_id(sonda: object, base: str) -> dict[int, str] | None:
    try:
        termini = sonda.json(f"{base}/wp-json/wp/v2/{TASSONOMIA}?per_page=100&_fields=id,slug")
    except Exception as exc:  # noqa: BLE001 — absence vs outage decided below
        if _transitorio(exc):
            raise LetturaIncompleta(f"tassonomia non disponibile: {exc}") from exc
        return None  # 404, not JSON, …: the site has no usable taxonomy
    if not isinstance(termini, list):
        return None
    mappa = {
        t["id"]: str(t["slug"])
        for t in termini
        if isinstance(t, dict) and isinstance(t.get("id"), int) and t.get("slug")
    }
    return mappa or None


def _righe(sonda: object, base: str, rest_base: str) -> list[dict]:
    righe: list[dict] = []
    for pagina in range(1, MAX_PAGINE + 1):
        url = (
            f"{base}/wp-json/wp/v2/{rest_base}?per_page={_PER_PAGINA}&page={pagina}"
            f"&_fields=title,link,{TASSONOMIA}"
        )
        try:
            blocco = sonda.json(url)
        except Exception as exc:  # noqa: BLE001 — end of pages vs outage decided below
            if _transitorio(exc):
                raise LetturaIncompleta(f"pagina {pagina} non disponibile: {exc}") from exc
            if pagina > 1 and _fine_pagine(exc):
                break
            if pagina == 1:
                raise _CollezioneAssente(str(exc)) from exc
            raise LetturaIncompleta(f"pagina {pagina} illeggibile: {exc}") from exc
        if not isinstance(blocco, list):
            # A WordPress error object served with 200, or anything else that
            # is not a page of units: never read it as "no more units".
            raise LetturaIncompleta(f"pagina {pagina} non e' un elenco di unita'")
        righe.extend(r for r in blocco if isinstance(r, dict))
        if len(blocco) < _PER_PAGINA:
            break
    return righe


def leggi_unita_tipizzate(
    sonda: object, base: str, rest_base: str
) -> list[UnitaTipizzata] | None:
    """Every organisational unit of the site with its category, deduplicated
    by URL, in site order. ``None`` if the site has no usable taxonomy."""
    slug_per_id = _slug_per_id(sonda, base)
    if slug_per_id is None:
        return None
    try:
        righe = _righe(sonda, base, rest_base)
    except _CollezioneAssente:
        return None  # taxonomy without this unit collection: stay untyped
    unita: list[UnitaTipizzata] = []
    visti: set[str] = set()
    for riga in righe:
        titolo_raw = riga.get("title")
        titolo = titolo_raw.get("rendered") if isinstance(titolo_raw, dict) else titolo_raw
        link = riga.get("link")
        if not titolo or not link or str(link) in visti:
            continue
        visti.add(str(link))
        tipi = riga.get(TASSONOMIA) or []
        slugs = {slug_per_id[t] for t in tipi if t in slug_per_id}
        unita.append(
            UnitaTipizzata(
                nome=html.unescape(str(titolo)).strip(),
                url=str(link),
                categoria=_categoria(slugs),
            )
        )
    return unita
