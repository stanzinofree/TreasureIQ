"""ComWeb service connector (Ramo 3, Connettore #2).

Secondo connettore-servizio: prova che l'astrazione del pilota WP/AgID regge su
un trasporto diverso.  ComWeb è HTML statico Bootstrap Italia (niente SPA, niente
WAF): la discovery **scrape** l'indice servizi, segue **una** pagina categoria e
raccoglie gli anchor scheda — nessun REST, nessun crawler.

Contratto/invarianti/opzioni sono condivisi in ``_ServiceConnectorBase``.  Qui
vivono solo le due parti ComWeb:

- ``_ComWebDiscovery`` — la strategia di scoperta bounded (indice → categoria →
  schede), iniettata nel transport comune (§3.2);
- ``ComWebServiceConnector`` — gate di piattaforma + ``service_id`` prefix +
  target di discovery (indice + slug categoria).

Discovery bounded (V-1 su Alpignano): l'indice ``/it-it/servizi`` è una vetrina
(0 schede anagrafe); le schede complete stanno nella pagina categoria.  Quindi il
drill per-categoria è il **path primario**, non un fallback.  Il mapping
``COMWEB_SERVICE_CATEGORY`` sceglie **quale anchor categoria seguire**
sull'indice; l'URL non è mai fabbricato (né categoria né scheda), si **segue**
l'anchor realmente trovato (I-4/I-5).  La conferma resta sul titolo via
``riconosci_service_key`` (I-6); ambiguità (≥2 schede) → NOT_FOUND (I-1).
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin, urlparse

from treasureiq.catalog.data_contracts import ConnectorRef
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.connettore_base import (
    DiscoveryTarget,
    _ServiceConnectorBase,
)
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www

#: Slug di **categoria** (percorso di navigazione, NON un termine di ricerca) da
#: seguire sull'indice per ogni key.  V-1: 5 key → 2 categorie.  Costante
#: specifica del connettore: non riusa ``SERVICE_SEARCH_TERM``.
COMWEB_SERVICE_CATEGORY: dict[ServiceKey, str] = {
    ServiceKey.CARTA_IDENTITA: "anagrafe-e-stato-civile",
    ServiceKey.CAMBIO_RESIDENZA: "anagrafe-e-stato-civile",
    ServiceKey.STATO_CIVILE: "anagrafe-e-stato-civile",
    ServiceKey.ACCESSO_ATTI: "anagrafe-e-stato-civile",
    ServiceKey.TRIBUTI: "tributi-finanze-e-contravvenzioni",
}

#: L'unico entry-point costruito dal connettore (come il root REST di WP).
_INDICE = "/it-it/servizi"

#: Cap **difensivo** sulle schede raccolte da UNA pagina categoria — NON un
#: limite di selezione.  Una pagina categoria è un documento singolo (già
#: limitato dal transport): la discovery deve raccoglierla **tutta** perché la
#: conferma (``_confermati``, nel connettore) gira DOPO la discovery — troncare
#: qui prima della conferma darebbe un falso NOT_FOUND se la scheda utile cade
#: oltre il cap (P1, review 23 ago; rischioso su categorie lunghe tipo tributi).
#: Il valore sta ben sopra ogni categoria comunale reale (anagrafe 56, tributi
#: 16) con enorme margine: morde solo su una pagina abnorme (guardia memoria).
_CAP_DIFENSIVO_SCHEDE = 2000

#: Categoria = **un** segmento dopo ``/it-it/servizi/`` (mai candidata a servizio).
_RE_CATEGORIA = re.compile(r"^/it-it/servizi/([^/?#]+)/?$", re.IGNORECASE)

#: Scheda = **due** segmenti; l'ultimo è ``{slug}-{id}(-{id})*-{hash32}``.
#: Cattura l'intero ultimo segmento come ``native_id`` stabile (I-2: mai dal
#: titolo).  Relativi e assoluti gestiti a monte via ``urljoin``; query/fragment
#: sono fuori da ``path`` quindi ignorati.  Rifiuta le categorie a un segmento e
#: qualunque path non-scheda.
_RE_SCHEDA = re.compile(
    r"^/it-it/servizi/[^/?#]+/([^/?#]+-\d+(?:-\d+)*-[0-9a-f]{32})/?$",
    re.IGNORECASE,
)

#: Anchor: href + testo interno (DOTALL per anchor su più righe).
_RE_ANCHOR = re.compile(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_RE_TAG = re.compile(r"<[^>]+>")

_CONNECTOR = ConnectorRef(name="comweb_service", version="1")


class _ComWebDiscovery:
    """Scoperta ComWeb bounded: indice → **una** categoria → anchor scheda.

    Net-free rispetto a httpx: usa i primitivi guardati del transport comune
    (``leggi_pagina``).  ``base_url`` è l'indice servizi già composto dal
    connettore; ``term`` è lo slug della categoria da seguire.  Nessun URL
    fabbricato: si segue l'anchor realmente presente.  Nessun crawler ricorsivo.
    """

    def scopri_servizi(
        self,
        transport,
        *,
        base_url: str,
        term: str,
        limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        host = urlparse(base_url).netloc
        indice = transport.leggi_pagina(url=base_url, official_host=host)
        if not indice:
            return ()
        categoria_url = self._trova_categoria(indice, base_url, host, term)
        if categoria_url is None:
            # Categoria mappata assente dagli anchor indice: nessun path
            # fabbricato → miss onesto (il connettore ripiega su NOT_FOUND).
            return ()
        pagina = transport.leggi_pagina(url=categoria_url, official_host=host)
        if not pagina:
            return ()
        return self._schede(pagina, categoria_url, host, limit)

    @staticmethod
    def _trova_categoria(html: str, base_url: str, host: str, term: str) -> str | None:
        # Primo anchor categoria (ordine documento = deterministico) sull'host
        # ufficiale il cui slug == term.  Il mapping sceglie QUALE seguire, non
        # costruisce il path.
        host_ufficiale = _host_senza_www(host.lower())
        term_norm = term.lower()
        for href, _testo in _RE_ANCHOR.findall(html):
            assoluto = urljoin(base_url, href)
            parti = urlparse(assoluto)
            if _host_senza_www(parti.netloc.lower()) != host_ufficiale:
                continue
            match = _RE_CATEGORIA.match(parti.path)
            if match and match.group(1).lower() == term_norm:
                return assoluto
        return None

    @staticmethod
    def _schede(html: str, categoria_url: str, host: str, limit: int) -> tuple[ServiceCandidate, ...]:
        host_ufficiale = _host_senza_www(host.lower())
        visti: set[str] = set()
        candidati: list[ServiceCandidate] = []
        for href, testo in _RE_ANCHOR.findall(html):
            if len(candidati) >= limit:
                break  # cap DIFENSIVO (guardia memoria), non selezione: sta
                # sopra ogni categoria reale, la conferma è a valle (P1)
            assoluto = urljoin(categoria_url, href)
            parti = urlparse(assoluto)
            if _host_senza_www(parti.netloc.lower()) != host_ufficiale:
                continue  # host guard (I-5)
            match = _RE_SCHEDA.match(parti.path)
            if match is None:
                continue  # categorie/link non-scheda scartati
            native_id = match.group(1)
            if native_id in visti:
                continue
            titolo = unescape(_RE_TAG.sub("", testo)).strip()
            if not titolo:
                continue
            try:
                candidato = ServiceCandidate(native_id=native_id, title=titolo, url=assoluto)
            except (ValueError, TypeError):
                continue
            visti.add(native_id)
            candidati.append(candidato)
        return tuple(candidati)


class ComWebServiceConnector(_ServiceConnectorBase):
    """Resolve a ``ServiceKey`` to one ``ServiceReference`` on ComWeb portals.

    Corpo condiviso in ``_ServiceConnectorBase``; qui solo il gate ComWeb, il
    prefisso ``comweb`` e il target di discovery (indice + slug categoria).  Il
    gate **non** dipende da ``servizi.esposto``/``rest_base`` (concetti WP-REST,
    ``False`` su ComWeb, §3.4): basta la piattaforma e un ``sito`` valido."""

    name = "comweb_service"
    version = "1"
    _CONNECTOR = _CONNECTOR
    _PIATTAFORME = frozenset({Piattaforma.COMWEB.value})
    _PREFISSO = "comweb"
    _PROVIDER_PLATFORM = "comweb"
    _LIMITE_RICERCA = _CAP_DIFENSIVO_SCHEDE

    def _discovery_target(self, mappa, service_key: ServiceKey) -> DiscoveryTarget | None:
        base = _base_con_schema(getattr(mappa, "sito", None))
        if base is None:
            return None
        categoria = COMWEB_SERVICE_CATEGORY.get(service_key)
        if categoria is None:
            return None
        entry = f"{base.rstrip('/')}{_INDICE}"
        return DiscoveryTarget(entry, categoria, urlparse(base).netloc)
