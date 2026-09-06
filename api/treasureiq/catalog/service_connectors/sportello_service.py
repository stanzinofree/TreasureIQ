"""Sportello Telematico Polifunzionale (Globo) service connector.

Sesto connettore-servizio. Il target è lo **Sportello Telematico** (Globo srl):
un Drupal specializzato a portale-procedure che centinaia di comuni espongono su
un sottodominio (`sportellotelematico.comune.<x>.it`, `sportelloamico.<x>`,
`<nome>easy.<x>`). Municipium spesso ne è solo la vetrina: le card servizio sono
launcher esterni verso queste procedure, quindi il connettore vive **separato**
da Municipium, sull'host dello Sportello.

Le procedure hanno un id stabile a namespace: `<scheme>:<ns>:<slug>` con
`scheme ∈ {procedure (scheda descrittiva), action (istanza online)}` e
`ns ∈ {s_italia (nazionale AgID), s_globo (standard Globo), r_<regione>,
c_<ipa> (locale)}`. Info e action dello stesso slug sono lo **stesso** servizio
logico (si deduplica per `ns:slug`, tenendo la scheda `procedure:`); alcuni
servizi esistono solo come `action:` (es. trascrizione atti stato civile). Il
vocabolario nazionale è byte-identico cross-comune
(`s_italia:<slug>` uguale fra tenant diversi), quindi la mappa slug→ServiceKey
costruita una volta vale per tutta la famiglia. **Primo ciclo: solo `s_italia` e
`s_globo`** — i namespace locali (`c_*`/`r_*`) restano fuori per costruzione.

Discovery (GET-only, net-free rispetto a httpx — solo i primitivi guardati del
transport comune):

1. **sitemap** — Drupal Simple XML Sitemap, `/sitemap.xml`, eventualmente
   paginata a indice (`<loc>…/default/sitemap.xml?page=N</loc>`). È il catalogo
   pieno: **nessuna API JSON** (verificato: `/api*` → 404). Un solo GET per la
   root, uno per pagina-indice.
2. **pre-filtro per slug** — dallo `<loc>` si legge `ns:slug` senza scaricare la
   pagina; si tengono solo i namespace nazionali e gli slug che, per segmento,
   appartengono alla ServiceKey richiesta (`_SLUG_TERMS`). Restringe soltanto,
   non conia: la conferma esattamente-uno resta a valle. Serve a non scaricare
   centinaia di pagine — solo la manciata plausibile.
3. **titolo dalla pagina** — la sitemap porta solo URL, non titoli, e lo slug
   (`carta.identita`, coi punti) non è il titolo che il recogniser condiviso sa
   leggere («Carta d'identità»). Quindi un GET per candidato pre-filtrato legge
   il `<title>` reale e il `rel=canonical` (self, stabile). `native_id` nasce
   dallo slug (mai dal titolo, I-2); `url` è il canonical realmente presente
   (mai fabbricato, I-4); host guard sull'URL a valle (I-5).

Nessuna policy per-chiave: la granularità del catalogo (carta d'identità per
maggiorenni *e* per minorenni; TARI utenze domestiche *e* non domestiche) è una
distinzione di servizio reale che le sei ServiceKey grossolane non sciolgono —
due candidati che confermano la stessa key sono un `NOT_FOUND` onesto (I-1, la
scelta è di un livello superiore), esattamente come ≥2 su OpenPA. Invarianti,
host guard, MEDIATED, opzioni e forma della `ServiceReference` sono condivise nel
`_ServiceConnectorBase`.
"""

from __future__ import annotations

import html
import re
from urllib.parse import unquote, urljoin, urlparse

from treasureiq.catalog.data_contracts import ConnectorRef
from treasureiq.catalog.service_connectors.base import ServiceCandidate, ServiceFetcher
from treasureiq.catalog.service_connectors.connettore_base import (
    DiscoveryTarget,
    _ServiceConnectorBase,
)
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www

_CONNECTOR = ConnectorRef(name="sportello_service", version="1")

#: Namespace nazionali ammessi nel primo ciclo. Gli slug qui sono condivisi
#: cross-comune; i namespace locali (`c_*`, `r_*`) sono esclusi per costruzione.
_NS_NAZIONALI = frozenset({"s_italia", "s_globo"})

#: Pagina sitemap: path Drupal Simple XML Sitemap.
_SITEMAP_PATH = "/sitemap.xml"

#: `<loc>` della sitemap.
_RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)

#: Schema Globo in un URL: `<scheme>:<ns>:<slug>` (encoded o pieno), con
#: `scheme ∈ {procedure, action}`. `procedure:` è la scheda descrittiva AgID;
#: `action:` è l'istanza online (avvio pratica) dello **stesso** servizio, o un
#: servizio che esiste solo online (es. trascrizione atti stato civile). Si
#: leggono entrambi e si deduplica per `ns:slug` (scheme-agnostico): info+action
#: dello stesso slug sono UN servizio logico, non due (evita un falso ≥2). Cattura
#: scheme, ns e slug fino al primo separatore di URL. Il `;` interno è `%3B`.
_RE_SCHEMA = re.compile(
    r"(procedure|action)(?:%3a|:)([a-z0-9_]+)(?:%3a|:)([^?/#\s\"'<>]+)", re.IGNORECASE
)

#: `<title>` della pagina procedura.
_RE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

#: `rel=canonical` (self URL, stabile) — href in un `<link>`.
_RE_CANONICAL = re.compile(
    r'<link\b[^>]*\brel=["\']canonical["\'][^>]*\bhref=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

#: Cap difensivo (guardia memoria/fetch) sul numero di pagine-indice sitemap da
#: seguire e sui candidati da scaricare. Il catalogo nazionale più grande visto
#: (~410 s_italia) sta molto sotto; il pre-filtro per slug lascia comunque una
#: manciata di candidati per key. Non è una selezione: la conferma
#: esattamente-uno è a valle (`_confermati`).
_CAP_PAGINE_SITEMAP = 20
_CAP_DIFENSIVO_CANDIDATI = 25

#: Slug-token per ServiceKey, nel **vocabolario dello slug** (coi punti), NON del
#: titolo: lo slug scrive `tassa.rifiuti`/`imposta.municipale.unica`, mentre
#: «TARI»/«IMU» stanno solo nel titolo (li legge il recogniser a valle). Il match
#: è per segmento (confini `.`/`;`/estremi), così `tassa.rifiuti` non prende
#: «regis*tri.tari*ffari» né `imposta.municipale` prende parole a caso. Restringe
#: soltanto i fetch: se un token è largo, decide comunque il recogniser + il gate
#: esattamente-uno. Un token vuoto per una key = nessun candidato = miss onesto.
_SLUG_TERMS: dict[ServiceKey, tuple[str, ...]] = {
    ServiceKey.CARTA_IDENTITA: ("carta.identita",),
    ServiceKey.CAMBIO_RESIDENZA: (
        "cambio.residenza",
        "cambio.abitazione.residenza",
        "trasferimento.residenza",
    ),
    ServiceKey.ACCESSO_ATTI: ("accesso.atti", "accesso.documentale"),
    ServiceKey.STATO_CIVILE: (
        "stato.civile",
        "certificato.nascita",
        "certificato.morte",
        "certificato.matrimonio",
    ),
    ServiceKey.TRIBUTI_IMU: ("imposta.municipale",),
    ServiceKey.TRIBUTI_TARI: ("tassa.rifiuti",),
}


def _slug_appartiene(slug: str, tokens: tuple[str, ...]) -> bool:
    """Lo slug (decodificato) contiene un token per segmento (confini `.`/`;`)?

    Match ancorato ai confini di segmento — inizio/fine o un `.`/`;` intorno —
    così un token come ``tassa.rifiuti`` combacia con
    ``tassa.rifiuti;utenze.domestiche`` ma non con parole che lo contengono per
    caso. Solo un filtro dei fetch: la correttezza (esattamente-uno) è a valle.
    """
    for token in tokens:
        if re.search(rf"(?:^|[.;]){re.escape(token)}(?:$|[.;])", slug):
            return True
    return False


class _SportelloDiscovery:
    """Scoperta Sportello: sitemap → pre-filtro slug → titolo dalla pagina.

    Net-free rispetto a httpx: usa solo ``leggi_pagina`` del transport comune.
    ``base_url`` è la sitemap già composta dal connettore; ``term`` è il *value*
    della ServiceKey. Nessun URL fabbricato: si segue lo `<loc>` realmente
    presente e, per l'``url`` del candidato, il ``rel=canonical`` della pagina
    (fallback allo stesso `<loc>`), sempre sotto host guard (I-5).
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
        host_ufficiale = _host_senza_www(host.lower())
        try:
            service_key = ServiceKey(term)
        except ValueError:
            return ()
        tokens = _SLUG_TERMS.get(service_key, ())
        if not tokens:
            return ()

        loc_urls = self._raccogli_loc(transport, base_url, host)
        if not loc_urls:
            return ()  # sitemap muta → miss onesto (non un catalogo vuoto)
        # `procedure:` prima di `action:`: a parità di slug la dedup tiene la
        # scheda descrittiva AgID, non il launcher online (ordinamento stabile).
        loc_urls.sort(key=lambda u: 0 if "/procedure" in u.lower() else 1)

        visti: set[str] = set()
        candidati: list[ServiceCandidate] = []
        for loc in loc_urls:
            if len(candidati) >= min(limit, _CAP_DIFENSIVO_CANDIDATI):
                break  # cap DIFENSIVO (guardia fetch), non selezione
            ns_slug = self._ns_slug(loc)
            if ns_slug is None:
                continue
            ns, slug = ns_slug
            if ns not in _NS_NAZIONALI:
                continue  # primo ciclo: solo namespace nazionali
            if not _slug_appartiene(slug, tokens):
                continue  # pre-filtro: fuori dalla key → non scaricare
            native_id = f"{ns}:{slug}"
            if native_id in visti:
                continue
            # Host guard sullo `<loc>` prima di spendere un fetch (ripetuto a
            # valle da `_confermati` sull'URL finale).
            if _host_senza_www(urlparse(loc).netloc.lower()) != host_ufficiale:
                continue
            candidato = self._candidato(transport, loc, host, native_id)
            if candidato is None:
                continue
            visti.add(native_id)
            candidati.append(candidato)
        return tuple(candidati)

    # -- sitemap ----------------------------------------------------------

    def _raccogli_loc(
        self, transport: ServiceFetcher, base_url: str, host: str
    ) -> list[str]:
        """Tutti gli `<loc>` procedura, seguendo l'eventuale indice paginato.

        Root `/sitemap.xml`: o è già l'``urlset`` (Pomezia), o è un indice i cui
        `<loc>` sono le pagine `…/default/sitemap.xml?page=N` (Cologno). Si scende
        di un solo livello, con cap difensivo sul numero di pagine.
        """
        root = transport.leggi_pagina(url=base_url, official_host=host)
        if not root:
            return []
        locs = [html.unescape(u) for u in _RE_LOC.findall(root)]
        sub = [u for u in locs if u.lower().endswith(".xml") or ".xml?" in u.lower()]
        if not sub:
            return locs
        raccolti: list[str] = []
        for pagina_url in sub[:_CAP_PAGINE_SITEMAP]:
            corpo = transport.leggi_pagina(url=pagina_url, official_host=host)
            if not corpo:
                continue
            raccolti.extend(html.unescape(u) for u in _RE_LOC.findall(corpo))
        return raccolti

    @staticmethod
    def _ns_slug(loc: str) -> tuple[str, str] | None:
        """Da un URL Globo estrai ``(ns, slug)`` decodificati, o ``None``.

        Vale per entrambi gli schemi (`procedure:`/`action:`): lo scheme non entra
        nell'identità — info e action dello stesso slug sono lo stesso servizio.
        Lo slug resta leggibile (``%3B`` → ``;``); l'``ns`` è il namespace
        (``s_italia``…). L'id nativo nasce da qui, mai dal titolo (I-2).
        """
        match = _RE_SCHEMA.search(loc)
        if match is None:
            return None
        ns = match.group(2).lower()
        slug = unquote(match.group(3))
        if not ns or not slug:
            return None
        return ns, slug

    # -- pagina procedura -------------------------------------------------

    def _candidato(
        self, transport: ServiceFetcher, loc: str, host: str, native_id: str
    ) -> ServiceCandidate | None:
        """Scarica la pagina procedura → ``ServiceCandidate`` (titolo + canonical).

        ``native_id`` (``ns:slug``, dal chiamante) è già derivato dallo slug, mai
        dal titolo (I-2). Il titolo pieno ha forma ``"<Servizio> | Comune di
        <X>"``: si tiene la parte-servizio prima di `` | `` (il suffisso comune
        non serve al recogniser e non è il servizio). L'``url`` è il
        ``rel=canonical`` (self, stabile) se presente, altrimenti lo stesso
        `<loc>` — entrambi realmente osservati (I-4).
        """
        pagina = transport.leggi_pagina(url=loc, official_host=host)
        if not pagina:
            return None
        m_title = _RE_TITLE.search(pagina)
        if m_title is None:
            return None
        titolo = html.unescape(re.sub(r"\s+", " ", m_title.group(1)).strip())
        titolo = titolo.split(" | ", 1)[0].strip()
        if not titolo:
            return None
        m_canon = _RE_CANONICAL.search(pagina)
        url = urljoin(loc, html.unescape(m_canon.group(1))) if m_canon else loc
        try:
            return ServiceCandidate(native_id=native_id, title=titolo, url=url)
        except (ValueError, TypeError):
            return None


class SportelloServiceConnector(_ServiceConnectorBase):
    """Risolve un ``ServiceKey`` in un ``ServiceReference`` sullo Sportello Globo.

    Corpo condiviso in ``_ServiceConnectorBase``; qui solo il gate di piattaforma
    (``sportello_telematico``), il prefisso ``sportello`` e il target di discovery
    (la sitemap Drupal). Il gate non dipende da ``servizi.esposto``/``rest_base``
    (concetti WP-REST, assenti su Drupal): basta la piattaforma e un ``sito``
    valido — cioè l'host dello Sportello del comune, non la vetrina Municipium.
    """

    name = "sportello_service"
    version = "1"
    _CONNECTOR = _CONNECTOR
    _PIATTAFORME = frozenset({Piattaforma.SPORTELLO_TELEMATICO.value})
    _PREFISSO = "sportello"
    _PROVIDER_PLATFORM = "sportello_telematico"
    _LIMITE_RICERCA = _CAP_DIFENSIVO_CANDIDATI

    def _discovery_target(self, mappa, service_key: ServiceKey) -> DiscoveryTarget | None:
        base = _base_con_schema(getattr(mappa, "sito", None))
        if base is None:
            return None  # nessun sito Sportello → NOT_SUPPORTED
        entry = f"{base.rstrip('/')}{_SITEMAP_PATH}"
        return DiscoveryTarget(entry, service_key.value, urlparse(base).netloc)
