"""HGATE (eGov/Halley) service connector (Ramo 3, Connettore #4).

Quarto connettore-servizio: la famiglia HGATE (vendor unico Halley, ~956 comuni,
12% del parco) è HTML server-rendered con rotte ``.HBL``.  La ricognizione live
(6 archetipi, 116 schede) ha fissato il contratto che vive qui:

- **Firma a due varianti** (D-policy): la sitemap risponde su
  ``/EG0/EGSMISTMSIT.HBL?FUNZ=1`` **senza** parametro firma su ogni istanza del
  campione (incluse quelle che espongono ``en=eg{id}`` in home).  La discovery usa
  la forma parameterless come primaria; se muta, ripiega ricavando ``en`` dalla
  home e ritentando ``?en=eg{id}&FUNZ=1``.  Entrambe le firme portano alla stessa
  sitemap.
- **Un solo fetch di discovery**: la sitemap ``FUNZ=1`` è l'indice COMPLETO delle
  schede (Albavilla 39/39, Bojano 20/20) — ogni scheda è un anchor
  ``/servizi/<categoria_agid>/servizio_{id}.html`` col titolo pieno nel testo,
  formato ``"<Categoria AgID> - <Servizio>"``.  Nessun crawl degli argomenti
  ``.HBL`` (tassonomia per-comune, non-AgID): la categoria negli URL scheda è
  invece il vocabolario AgID stabile (``anagrafe_e_stato_civile``,
  ``tributi_finanze_e_contravvenzioni``, …).  L'indice ``/servizi/`` moderno è
  JS-rendered (fetch-cieco) e **non** viene usato.

Tre policy per-chiave, decise in ricognizione:

1. **ACCESSO_ATTI = solo accesso documentale ex L.241**; accesso civico e FOIA
   esclusi.  Il recogniser condiviso già li esclude (i suoi marker sono «accesso
   agli atti»/«accesso atti», assenti in «accesso civico»/«FOIA»); qui un filtro
   difensivo scarta comunque i candidati che portano quei marker anche se
   contengono «accesso atti» (I-1: nessuna elezione implicita fra istituti).
2. **STATO_CIVILE aggregato alla pagina-categoria**: le schede sono per
   life-event (nascita/matrimonio/morte, ~7 su Albavilla) e nessuna conferma da
   sola la key.  Non se ne elegge una: si emette **un** candidato = la
   pagina-categoria ``/servizi/<anagrafe_stato_civile>/`` la cui etichetta reale
   («Anagrafe e stato civile») conferma STATO_CIVILE via recogniser.
3. **Titoli sempre unescape** (``&#8217;`` → ``'``, ``&agrave;`` → à): i titoli
   sitemap sono entity-encoded (cfr. WP ``title.rendered``); senza unescape
   «Carta d'identità» non confermerebbe.

Contratto/invarianti/opzioni (esattamente-uno-o-NOT_FOUND, id mai dal titolo,
MEDIATED, host guard, conferma solo via recogniser) sono condivisi in
``_ServiceConnectorBase``.  Qui vivono solo la strategia di discovery HGATE e il
gate di piattaforma.
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin, urlparse

from treasureiq.catalog.data_contracts import ConnectorRef
from treasureiq.catalog.service_connectors.base import ServiceCandidate, ServiceFetcher
from treasureiq.catalog.service_connectors.connettore_base import (
    DiscoveryTarget,
    _ServiceConnectorBase,
)
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.chat.service_key import riconosci_service_key
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www

_CONNECTOR = ConnectorRef(name="hgate_service", version="1")

#: Rotta sitemap parameterless (firma A).  Funziona su ogni istanza del campione,
#: comprese quelle che espongono ``en=eg`` in home (verificato: identico output).
_SITEMAP_PATH = "/EG0/EGSMISTMSIT.HBL?FUNZ=1"

#: Cap difensivo (guardia memoria) sul numero di schede raccolte dalla sitemap.
#: Sta molto sopra ogni sitemap comunale reale (max osservato ~40): non è una
#: selezione, la conferma esattamente-uno è a valle (_confermati).
_CAP_DIFENSIVO_SCHEDE = 2000

#: Anchor scheda nella sitemap: href verso ``/servizi/<cat>/servizio_<id>.html``
#: + testo interno (titolo pieno "<Categoria> - <Servizio>").
_RE_SCHEDA_ANCHOR = re.compile(
    r'<a\b[^>]*\bhref=["\']([^"\']*servizi/[^"\']*servizio_\d+\.html)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
#: Path scheda → (categoria AgID, id nativo).  Ancorato a fine path.
_RE_SCHEDA_PATH = re.compile(r"/servizi/([^/]+)/servizio_(\d+)\.html$", re.IGNORECASE)
#: Firma famiglia in home (firma B, fallback): ``en=eg{id}``.
_RE_EN = re.compile(r"\ben=eg(\d{1,4})\b")
#: Rimozione tag interni all'anchor prima dell'unescape.
_RE_TAG = re.compile(r"<[^>]+>")

#: Marker (casefold) degli istituti di accesso ESCLUSI dalla key ACCESSO_ATTI:
#: accesso civico (semplice) e generalizzato/FOIA sono servizi distinti dalla
#: L.241 (accesso documentale) — policy (1).  Difensivo sopra il recogniser.
_ACCESSO_ESCLUSI = ("accesso civico", "foia", "generalizzato")


class _HGateDiscovery:
    """Scoperta HGATE: un fetch della sitemap ``FUNZ=1`` → anchor scheda.

    Net-free rispetto a httpx: usa i primitivi guardati del transport comune
    (``leggi_pagina``).  ``base_url`` è la sitemap parameterless già composta dal
    connettore; ``term`` è il **value** della ServiceKey.  La sitemap è l'indice
    completo delle schede: nessun crawl degli argomenti.  Per STATO_CIVILE si
    emette la pagina-categoria (aggregazione); per le altre key un candidato per
    scheda, col titolo depurato del prefisso categoria.  Nessun URL fabbricato:
    si segue l'anchor realmente presente (host guard I-5).
    """

    def scopri_servizi(
        self,
        transport: ServiceFetcher,
        *,
        base_url: str,
        term: str,
        limit: int,
    ) -> tuple[ServiceCandidate, ...]:
        host = urlparse(base_url).netloc
        sitemap = self._sitemap(transport, base_url, host)
        if not sitemap:
            return ()  # sitemap muta (entrambe le firme) → miss onesto
        try:
            service_key = ServiceKey(term)
        except ValueError:
            return ()

        anchors = self._schede_anchor(sitemap, base_url, host)
        if service_key is ServiceKey.STATO_CIVILE:
            # Policy (2): aggregazione alla pagina-categoria, mai una singola scheda.
            return self._aggrega_categoria(anchors)

        # Altre key: un candidato per scheda (titolo = servizio, senza il prefisso
        # categoria).  Il gate host+recogniser esattamente-uno è a valle.
        visti: set[str] = set()
        candidati: list[ServiceCandidate] = []
        for native_id, _cat, _prefix, titolo, url in anchors:
            if len(candidati) >= limit:
                break  # cap DIFENSIVO (guardia memoria), non selezione
            if native_id in visti:
                continue  # dedup per id nativo (scheda ripetuta in più argomenti)
            try:
                candidato = ServiceCandidate(native_id=native_id, title=titolo, url=url)
            except (ValueError, TypeError):
                continue
            visti.add(native_id)
            candidati.append(candidato)
        return tuple(candidati)

    # -- firma a due varianti ---------------------------------------------

    def _sitemap(self, transport: ServiceFetcher, base_url: str, host: str) -> str | None:
        """Sitemap via firma parameterless; fallback firma ``en=eg`` da home.

        Primaria: ``base_url`` (``…?FUNZ=1``).  Se non porta anchor scheda (istanza
        che rifiuta la forma nuda), ricava ``en`` dalla home e ritenta
        ``?en=eg{id}&FUNZ=1``.  Il fallback costa un solo fetch extra e solo sul
        path muto: nessun URL fabbricato oltre la rotta canonica della famiglia.
        """
        pagina = transport.leggi_pagina(url=base_url, official_host=host)
        if pagina and _RE_SCHEDA_ANCHOR.search(pagina):
            return pagina
        parti = urlparse(base_url)
        root = f"{parti.scheme}://{parti.netloc}"
        home = transport.leggi_pagina(url=f"{root}/", official_host=host)
        if not home:
            return pagina
        firma = _RE_EN.search(home)
        if not firma:
            return pagina
        alt = f"{root}/EG0/EGSMISTMSIT.HBL?en=eg{firma.group(1)}&FUNZ=1"
        return transport.leggi_pagina(url=alt, official_host=host) or pagina

    # -- parsing sitemap ---------------------------------------------------

    @staticmethod
    def _schede_anchor(
        sitemap: str, base_url: str, host: str
    ) -> list[tuple[str, str, str, str, str]]:
        """Anchor scheda della sitemap → ``(id, categoria, prefisso, titolo, url)``.

        Host guard sull'URL assoluto (I-5).  Il titolo pieno ha forma
        ``"<Categoria AgID> - <Servizio>"``: si spezza sul primo `` - `` perché il
        prefisso categoria dell'anagrafe («Anagrafe e stato civile») contiene
        «stato civile» e collide col recogniser (2 chiavi → None) su carta e
        residenza.  Il ``prefisso`` resta disponibile per l'aggregazione
        STATO_CIVILE.
        """
        host_ufficiale = _host_senza_www(host.lower())
        out: list[tuple[str, str, str, str, str]] = []
        for href, testo in _RE_SCHEDA_ANCHOR.findall(sitemap):
            assoluto = urljoin(base_url, unescape(href))
            parti = urlparse(assoluto)
            if _host_senza_www(parti.netloc.lower()) != host_ufficiale:
                continue  # host guard (I-5)
            match = _RE_SCHEDA_PATH.search(parti.path)
            if match is None:
                continue
            categoria, native_id = match.group(1), match.group(2)
            # Policy (3): unescape SEMPRE (entity-encoded), poi rimozione tag.
            pieno = unescape(_RE_TAG.sub(" ", testo))
            pieno = re.sub(r"\s+", " ", pieno).strip()
            prefisso, titolo = _spezza_titolo(pieno)
            if not titolo:
                continue
            out.append((native_id, categoria, prefisso, titolo, assoluto))
        return out

    @staticmethod
    def _aggrega_categoria(
        anchors: list[tuple[str, str, str, str, str]],
    ) -> tuple[ServiceCandidate, ...]:
        """STATO_CIVILE → un candidato = pagina-categoria anagrafe/stato civile.

        Policy (2): le schede stato civile sono per life-event e nessuna conferma
        la key da sola; sceglierne una sarebbe arbitrario (I-1).  Si prende la
        categoria reale il cui prefisso (etichetta AgID «Anagrafe e stato civile»)
        conferma STATO_CIVILE via recogniser, e si emette la sua pagina-categoria
        ``/servizi/<cat>/`` come candidato unico: ``native_id`` = slug categoria,
        ``title`` = etichetta reale (conferma a valle), ``url`` = pagina-categoria
        sull'host ufficiale.  Nessuna scheda scelta.
        """
        for _native_id, categoria, prefisso, _titolo, url in anchors:
            if riconosci_service_key(prefisso) is ServiceKey.STATO_CIVILE:
                parti = urlparse(url)
                categoria_url = f"{parti.scheme}://{parti.netloc}/servizi/{categoria}/"
                try:
                    return (
                        ServiceCandidate(
                            native_id=categoria, title=prefisso, url=categoria_url
                        ),
                    )
                except (ValueError, TypeError):
                    return ()
        return ()


def _spezza_titolo(pieno: str) -> tuple[str, str]:
    """``"<Categoria> - <Servizio>"`` → ``(prefisso, servizio)``.

    Spezza sul primo `` - `` (separatore categoria→servizio della sitemap HGATE).
    Senza `` - `` il titolo è già il servizio (nessun prefisso categoria)."""
    if " - " in pieno:
        prefisso, _, servizio = pieno.partition(" - ")
        return prefisso.strip(), servizio.strip()
    return "", pieno


class HGateServiceConnector(_ServiceConnectorBase):
    """Risolve un ``ServiceKey`` in un ``ServiceReference`` sui portali HGATE.

    Corpo condiviso in ``_ServiceConnectorBase``; qui solo il gate HGATE, il
    prefisso ``hgate``, il target di discovery (sitemap parameterless) e il filtro
    difensivo ACCESSO_ATTI.  Il gate non dipende da ``servizi.esposto``/``rest_base``
    (concetti WP-REST, assenti su HGATE): basta la piattaforma e un ``sito`` valido.
    """

    name = "hgate_service"
    version = "1"
    _CONNECTOR = _CONNECTOR
    _PIATTAFORME = frozenset({Piattaforma.HGATE.value})
    _PREFISSO = "hgate"
    _PROVIDER_PLATFORM = "hgate"
    _LIMITE_RICERCA = _CAP_DIFENSIVO_SCHEDE

    def _discovery_target(self, mappa, service_key: ServiceKey) -> DiscoveryTarget | None:
        base = _base_con_schema(getattr(mappa, "sito", None))
        if base is None:
            return None  # nessun sito → NOT_SUPPORTED
        entry = f"{base.rstrip('/')}{_SITEMAP_PATH}"
        return DiscoveryTarget(entry, service_key.value, urlparse(base).netloc)

    def _filtra_candidati(self, candidati, service_key):
        # Policy (1): per ACCESSO_ATTI scarta accesso civico/FOIA anche se il
        # titolo contenesse «accesso atti» (difensivo sopra il recogniser, che già
        # non li marca).  Restringe soltanto: nessun candidato coniato.
        if service_key is not ServiceKey.ACCESSO_ATTI:
            return candidati
        return tuple(
            c
            for c in candidati
            if not any(m in c.title.casefold() for m in _ACCESSO_ESCLUSI)
        )
