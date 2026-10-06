"""Lettura degli indici amministrativi HTML dei portali Drupal e Magnolia.

Le due famiglie espongono sulla home i link alle sezioni Uffici e Aree
amministrative. Leggiamo solo quelle sezioni, seguendo la paginazione sullo
stesso host. I link di Amministrazione Trasparente sono registrati come link,
senza scaricare o interpretare il portale esterno.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from treasureiq.connettore import (
    AmministrazioneTrasparente,
    AreaAmministrativa,
    EndpointiConnettore,
    EsitoConnettore,
    UfficioConnettore,
)
from treasureiq.ingest.host_guard import fetch_guardato, host_senza_www
from treasureiq.mappa_connettore import _base_con_schema
from treasureiq.sonda_live import ComuneNoto
from treasureiq.unita_tipizzate import LetturaIncompleta

_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
_ATTR = re.compile(r"([\w:-]+)\s*=\s*([\"'])(.*?)\2", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_MAX_BYTES = 2_000_000
# Rimini dichiara 15 pagine nell'indice Uffici. Il crawler segue soltanto il
# link ``rel=next`` pubblicato dal portale, quindi un cap di 20 mantiene un
# limite difensivo senza troncare una paginazione esplicitamente dichiarata.
_MAX_PAGINE = 20
_MAX_VOCI = 200


@dataclass(frozen=True)
class _Link:
    href: str
    testo: str
    title: str
    rel: str


def _link(html_pagina: str) -> list[_Link]:
    links: list[_Link] = []
    for attributi, contenuto in _ANCHOR.findall(html_pagina):
        attrs = {m.group(1).lower(): html.unescape(m.group(3)) for m in _ATTR.finditer(attributi)}
        href = attrs.get("href", "").strip()
        if not href:
            continue
        testo = re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", contenuto))).strip()
        links.append(_Link(href, testo, attrs.get("title", ""), attrs.get("rel", "")))
    return links


def _host(url: str) -> str:
    return host_senza_www((urlsplit(url).hostname or "").lower())


def _url_sito(base: str, href: str) -> str | None:
    url = urljoin(base, href)
    parti = urlsplit(url)
    if parti.scheme not in {"http", "https"} or _host(url) != _host(base):
        return None
    return url


def _pagina(url: str, host: str, timeout: float) -> tuple[str, str]:
    risultato = fetch_guardato(url, timeout=timeout, max_bytes=_MAX_BYTES, host_atteso=host)
    if risultato is None:
        # Non si salva uno snapshot dimezzato se una pagina dell'indice tace.
        raise LetturaIncompleta(f"indice amministrativo illeggibile: {url}")
    return risultato[1].decode("utf-8", "replace"), risultato[2]


def _indice_home(links: list[_Link], base: str, nome: str) -> str | None:
    for link in links:
        if link.testo.casefold() == nome:
            url = _url_sito(base, link.href)
            if url is not None:
                return url
    return None


def _at_home(links: list[_Link], base: str) -> AmministrazioneTrasparente | None:
    candidati: list[tuple[int, str]] = []
    for link in links:
        label = link.testo.casefold()
        if "amministrazione trasparente" not in label:
            continue
        url = urljoin(base, link.href)
        if urlsplit(url).scheme not in {"http", "https"}:
            continue
        punteggio = -1 if "fino al" in label else 1 if "dal " in label else 0
        candidati.append((punteggio, url))
    if not candidati:
        return None
    # A parità di punteggio vince l'ultimo link: spesso è quello del footer.
    indice = max(enumerate(candidati), key=lambda c: (c[1][0], c[0]))[1][1]
    return AmministrazioneTrasparente(indice_url=indice)


def _nome(link: _Link) -> str:
    nome = link.testo
    if nome.casefold() in {"ulteriori informazioni", "vai al contenuto", "leggi tutto"}:
        nome = re.sub(r"^ulteriori dettagli per\s*", "", link.title, flags=re.I).strip()
    return nome


def _scheda(path: str, famiglia: str, sezione: str) -> bool:
    path = path.rstrip("/").lower()
    if famiglia == "magnolia":
        tipo = "ufficio" if sezione == "uffici" else "area"
        directory = "uffici" if sezione == "uffici" else "aree_amministrative"
        return bool(re.fullmatch(
            rf"/home/amministrazione/{directory}/{tipo}-[^/]+\.html", path
        ))
    if sezione == "uffici":
        return bool(re.fullmatch(
            r"/(?:unita-organizzativa|amministrazione/uffici)/[^/]+", path
        ) or re.fullmatch(r"/amministrazione/ufficio-[^/]+", path))
    return bool(re.fullmatch(
        r"/(?:unita-organizzativa|amministrazione/aree-amministrative)/[^/]+", path
    ) or re.fullmatch(r"/amministrazione/(?:settore|area|dipartimento)-[^/]+", path))


def _leggi_indice(
    url: str | None, *, base: str, famiglia: str, sezione: str, timeout: float
) -> list[tuple[str, str]]:
    if url is None:
        return []
    visti_pagine: set[str] = set()
    voci: dict[str, str] = {}
    corrente: str | None = url
    while corrente is not None:
        if corrente in visti_pagine or len(visti_pagine) >= _MAX_PAGINE:
            raise LetturaIncompleta(f"paginazione amministrativa non completa: {url}")
        visti_pagine.add(corrente)
        pagina, finale = _pagina(corrente, _host(base), timeout)
        links = _link(pagina)
        for link in links:
            scheda = _url_sito(finale, link.href)
            if scheda is None or not _scheda(urlsplit(scheda).path, famiglia, sezione):
                continue
            nome = _nome(link)
            if nome and scheda not in voci:
                voci[scheda] = nome
                if len(voci) > _MAX_VOCI:
                    raise LetturaIncompleta(f"indice amministrativo oltre il limite: {url}")
        corrente = None
        for link in links:
            if "next" not in link.rel.lower() and link.testo.casefold() not in {
                "pagina successiva", "carica altri risultati",
            }:
                continue
            prossimo = _url_sito(finale, link.href)
            if prossimo is not None and prossimo != finale:
                corrente = prossimo
                break
    return [(nome, scheda) for scheda, nome in voci.items()]


def _leggi_portale(
    comune: ComuneNoto, famiglia: str, *, timeout: float, home_html: str | None
) -> EsitoConnettore:
    base = _base_con_schema(comune.sito)
    letto_il = datetime.now(timezone.utc).isoformat()
    if base is None:
        return EsitoConnettore(codice_istat=comune.codice_istat, piattaforma=famiglia, letto_il=letto_il)
    if home_html is None:
        home_html, base = _pagina(base, _host(base), timeout)
    home_links = _link(home_html)
    url_uffici = _indice_home(home_links, base, "uffici")
    url_aree = _indice_home(home_links, base, "aree amministrative")
    uffici_letti = _leggi_indice(
        url_uffici, base=base, famiglia=famiglia, sezione="uffici", timeout=timeout
    )
    aree_lette = _leggi_indice(
        url_aree, base=base, famiglia=famiglia, sezione="aree", timeout=timeout
    )
    return EsitoConnettore(
        codice_istat=comune.codice_istat,
        piattaforma=famiglia,
        letto_il=letto_il,
        uffici=[
            UfficioConnettore(
                nome=nome, url=url, telefoni=[], email=[], pec=[], orari=None,
                source_typed=False, letto_il=letto_il,
            )
            for nome, url in uffici_letti
        ],
        aree_amministrative=[AreaAmministrativa(nome=nome, url=url) for nome, url in aree_lette],
        amministrazione_trasparente=_at_home(home_links, base),
        endpoints=EndpointiConnettore(amministrazione=url_uffici or url_aree),
    )


def leggi_magnolia(comune: ComuneNoto, _sonda=None, *, timeout: float = 8.0,
                   home_html: str | None = None) -> EsitoConnettore:
    return _leggi_portale(comune, "magnolia", timeout=timeout, home_html=home_html)


def leggi_drupal(comune: ComuneNoto, _sonda=None, *, timeout: float = 8.0,
                 home_html: str | None = None) -> EsitoConnettore:
    return _leggi_portale(comune, "drupal", timeout=timeout, home_html=home_html)
