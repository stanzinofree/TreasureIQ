"""Connettore-servizio per la famiglia **Drupal Bootstrap Italia "Modello
Comuni"** (Drupal 9/10/11), Ramo 3.

Terza famiglia HTML dopo il pilota WP/AgID e ComWeb: stessa classe di adapter
(indice → una categoria mappata → schede → gate esattamente-uno), **non** un
client REST.  La recon read-only (15 comuni/12 regioni) ha stabilito che
"Drupal" nei comuni italiani non è un vendor eterogeneo ma **una distribuzione
unica** — il tema BI "Modello Comuni" — con una superficie stabile:

- l'indice ``/servizi`` è la vetrina universale (14/15; assente solo sul
  Drupal-7 legacy pre-BI, che resta **honest miss**);
- l'indice porta le **categorie** (argomenti della tassonomia nazionale BI:
  ``<a href="/servizi/<slug>" hreflang="it">Nome argomento</a>``) e un set di
  servizi in evidenza;
- la pagina **categoria** ``/servizi/<slug-argomento>`` elenca i servizi
  dell'argomento, ognuno come ``<a … data-element="service-link"><span>Titolo…``;
- l'URL canonica del servizio è ``/servizi/<slug-servizio>``.

Due differenze rispetto a ComWeb, entrambe imposte dal template reale:

1. **categoria e servizio condividono la forma** ``/servizi/<un-segmento>`` — non
   si distinguono per numero di segmenti come su ComWeb.  Il discriminante è il
   design token ``data-element="service-link"`` (servizio) vs il suo assenza +
   ``hreflang`` (tile categoria).  Verificato sul markup BI reale.
2. **gli slug-argomento variano per comune** (Torino ``anagrafe-stato-civile`` vs
   Alpignano-BI ``anagrafe-e-stato-civile``): la mappa key→categoria **non** può
   essere per-slug.  Si mappa invece sul **nome visualizzato normalizzato**
   dell'argomento (la tassonomia BI nazionale è stabile nei nomi anche quando gli
   slug divergono), scegliendo il tile categoria presente sull'indice.

Tutto il resto — gate su ``source_id``, conferma via recogniser condiviso sul
titolo, opzioni dalla pagina servizio, forma di ``ServiceReference`` e
``ConnectorResult``, invarianti I-1…I-6 — è ereditato invariato da
``_ServiceConnectorBase``.
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

#: L'unico entry-point costruito dal connettore (come il root REST di WP): la
#: vetrina servizi.  Rotta universale nel campione recon (14/15).
_INDICE = "/servizi"

#: Key → **parola-chiave dell'argomento** (nome visualizzato normalizzato, NON
#: uno slug).  La discovery segue il tile categoria dell'indice il cui nome
#: contiene la parola-chiave — robusto alla varianza di slug per-comune.  Mappa
#: **totale** sul vocabolario ServiceKey: una key senza voce risolverebbe
#: silenziosamente in NOT_SUPPORTED.  ``accesso_atti`` è filato sotto l'argomento
#: anagrafe/URP nella maggior parte dei comuni; dove è altrove resta honest miss
#: (recuperabile ampliando la mappa dopo lo sweep mirato, non qui).
DRUPAL_BI_ARGOMENTO: dict[ServiceKey, str] = {
    ServiceKey.CARTA_IDENTITA: "anagrafe",
    ServiceKey.CAMBIO_RESIDENZA: "anagrafe",
    ServiceKey.STATO_CIVILE: "anagrafe",
    ServiceKey.ACCESSO_ATTI: "anagrafe",
    ServiceKey.TRIBUTI_IMU: "tributi",
    ServiceKey.TRIBUTI_TARI: "tributi",
}

#: Cap **difensivo** sui servizi raccolti (guardia memoria, non selezione): la
#: conferma esattamente-uno gira a valle nel connettore, troncare qui darebbe un
#: falso NOT_FOUND se la scheda utile cade oltre il cap.  Sta sopra ogni
#: categoria comunale reale con ampio margine (cfr. ComWeb).
_CAP_DIFENSIVO_SERVIZI = 2000

#: Numero massimo di pagine categoria seguite via ``?page=N``.  La paginazione BI
#: è opzionale (i comuni piccoli stanno in una pagina; i grandi impaginano lato
#: server): si segue finché emergono servizi **nuovi**, con questo tetto come
#: guardia (una categoria abnorme non deve moltiplicare le richieste).
_MAX_PAGINE = 20

#: Un anchor: attributi del tag di apertura + testo interno (DOTALL: l'anchor BI
#: avvolge uno ``<span>`` su più righe).
_RE_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_RE_HREF = re.compile(r'\bhref="([^"]*)"', re.IGNORECASE)
_RE_TAG = re.compile(r"<[^>]+>")
#: Design token BI del servizio (vs il tile argomento, che ne è privo).
_RE_SERVICE_LINK = re.compile(r'\bdata-element="service-link"', re.IGNORECASE)
#: **Tile argomento**: ``/servizi/<slug-argomento>`` a UN segmento (il tile della
#: categoria).  Il servizio invece può stare piatto (Torino) o **annidato** sotto
#: la categoria (``/servizi/<argomento>/<slug-servizio>``, comuni piccoli): la
#: recon ha trovato entrambe le forme nella stessa famiglia.
_RE_ARGOMENTO = re.compile(r"^/servizi/([^/?#]+)/?$", re.IGNORECASE)
#: **Servizio**: ``/servizi/…/<slug>`` a profondità qualsiasi; il gruppo cattura
#: l'**ultimo** segmento (lo slug proprio del servizio, l'id).  Il discriminante
#: servizio-vs-argomento è il token ``service-link``, non la profondità del path.
_RE_SERVIZIO = re.compile(r"^/servizi/(?:[^/?#]+/)*([^/?#]+)/?$", re.IGNORECASE)

_CONNECTOR = ConnectorRef(name="drupal_bi_service", version="1")


def _testo(interno: str) -> str:
    """Titolo umano da un anchor: via i tag interni (``<span>``…), entità decodificate."""
    return unescape(_RE_TAG.sub("", interno)).strip()


def _href_di(attrs: str) -> str | None:
    m = _RE_HREF.search(attrs)
    return unescape(m.group(1)) if m else None


class _RisultatoServizi(tuple):
    """``tuple`` di ``ServiceCandidate`` che porta il segnale ``troncato``.

    Il contratto ``ServiceFetcher`` espone una tuple piatta di candidati. La
    troncatura (cap ``_MAX_PAGINE`` raggiunto con la lista ancora aperta, o cap
    difensivo servizi toccato) è un fatto sulla *completezza* del crawl, non un
    candidato: la si porta come attributo extra, invisibile a chi tratta il
    risultato come sequenza (``len``/iterazione/indice restano quelli della
    tuple) e letta a valle solo via ``getattr(result, "troncato", False)``. Le
    altre famiglie restituiscono una tuple nuda → ``troncato`` assente = ``False``.
    """

    troncato: bool

    def __new__(cls, candidati, *, troncato: bool) -> "_RisultatoServizi":
        self = super().__new__(cls, candidati)
        self.troncato = troncato
        return self


class _DrupalBiDiscovery:
    """Scoperta Drupal BI bounded, robusta a **due layout reali** dell'indice.

    Net-free rispetto a httpx: usa i primitivi guardati del transport comune
    (``leggi_pagina``).  ``base_url`` è l'indice ``/servizi`` già composto dal
    connettore; ``term`` è il **value** della ServiceKey.

    La recon ha trovato due layout dell'indice ``/servizi`` nella stessa famiglia:

    - **vetrina** (Torino, Almè, Dicomano): l'indice porta i **tile argomento**
      (tassonomia BI nazionale) e pochi servizi in evidenza; ``?page`` è ignorato.
      La lista completa di un argomento sta sulla **pagina categoria**
      ``/servizi/<slug-argomento>``;
    - **indice impaginato** (Anzio, Salerno): ``/servizi?page=N`` impagina
      **tutti** i servizi direttamente; i tile possono mancare dal HTML statico
      (render JS).

    Strategia a due livelli, per tenere il caso comune economico:

    1. si cerca il **tile argomento** mappato sull'indice (match sul nome
      visualizzato, non sullo slug che varia per comune) e — se c'è — si segue la
      sua **pagina categoria** (bounded, il ramo ComWeb-like);
    2. **solo se il tile manca** (indice impaginato senza tile statici) si
      impagina l'indice stesso.

    In entrambi i rami si raccolgono i soli anchor col design token
    ``data-element="service-link"``, seguendo ``?page=N`` finché emergono servizi
    nuovi (cap ``_MAX_PAGINE``).  Nessuno slug fabbricato, nessun crawler.
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
            return ()  # indice muto → miss onesto (Drupal-7 legacy o endpoint_muto)
        try:
            service_key = ServiceKey(term)
        except ValueError:
            return ()
        parola = DRUPAL_BI_ARGOMENTO.get(service_key)
        if parola is None:
            return ()
        visti: set[str] = set()
        candidati: list[ServiceCandidate] = []
        categoria_url = self._trova_argomento(indice, base_url, host, parola)
        if categoria_url is not None:
            # Ramo vetrina/normale: la pagina categoria mappata (bounded).
            troncato = self._paginare(transport, categoria_url, host, limit, visti, candidati)
        else:
            # Ramo indice-impaginato (tile assenti dall'HTML statico): l'indice è
            # già la lista servizi; si impagina esso stesso, riusando la p0 già
            # scaricata per non rifetcharla.
            troncato = self._paginare(
                transport, base_url, host, limit, visti, candidati, prima_pagina=indice
            )
        return _RisultatoServizi(candidati, troncato=troncato)

    @classmethod
    def _paginare(
        cls,
        transport,
        start_url: str,
        host: str,
        limit: int,
        visti: set[str],
        candidati: list[ServiceCandidate],
        *,
        prima_pagina: str | None = None,
    ) -> bool:
        """Segue ``?page=N`` da ``start_url`` accumulando i servizi, finché una
        pagina non porta slug nuovi (cap ``_MAX_PAGINE``).  ``prima_pagina``, se
        dato, è l'HTML già scaricato di ``start_url`` (evita un refetch).

        Ritorna ``True`` se la paginazione è stata **troncata** da un cap — cap
        difensivo servizi raggiunto, oppure ``_MAX_PAGINE`` esaurito mentre
        l'ultima pagina portava ancora slug freschi: oltre il tetto restano
        pagine non lette, il crawl è parziale.  Ritorna ``False`` sulle fini
        **naturali** (pagina muta / oltre la fine, o nessuno slug nuovo): la
        lista è completa.  Al confine esatto (contenuto multiplo pieno della
        dimensione pagina) non si può distinguere «completo al cap» da «altro
        oltre» senza una fetch in più: si marca troncato in via **prudente** —
        sbagliare verso il parziale non promuove dati incompleti (requisito)."""
        for page in range(_MAX_PAGINE):
            if len(candidati) >= limit:
                return True  # cap difensivo servizi: lista troncata
            if page == 0 and prima_pagina is not None:
                url, pagina = start_url, prima_pagina
            else:
                url = start_url if page == 0 else f"{start_url}?page={page}"
                pagina = transport.leggi_pagina(url=url, official_host=host)
            if not pagina:
                return False  # pagina muta / oltre la fine: paginazione completa
            prima = len(visti)
            cls._raccogli_servizi(pagina, url, host, limit, visti, candidati)
            if page > 0 and len(visti) == prima:
                return False  # nessun servizio nuovo: fine naturale, lista completa
        # ``range`` esaurito senza fine naturale: l'ultima pagina letta portava
        # ancora slug freschi (altrimenti sarebbe uscito col ramo sopra) →
        # ``_MAX_PAGINE`` ha tagliato una lista ancora aperta.
        return True

    @staticmethod
    def _trova_argomento(html: str, base_url: str, host: str, parola: str) -> str | None:
        """URL del tile argomento il cui nome visualizzato **inizia** con ``parola``.

        Il tile argomento è un anchor ``/servizi/<slug>`` **senza** il token
        ``data-element="service-link"`` (quello marca i servizi); il match è sul
        nome, non sullo slug (che varia per comune).  Si richiede ``startswith``,
        non ``in``: i nomi canonici della tassonomia BI iniziano con la parola
        («Anagrafe e stato civile», «Tributi, finanze e contravvenzioni»), mentre
        un titolo-servizio surrogato da tile («Pagare i tributi…») no — così un
        servizio non viene scambiato per una categoria.  Primo in ordine
        documento = deterministico.  La mappa sceglie QUALE seguire, non
        costruisce il path.
        """
        host_ufficiale = _host_senza_www(host.lower())
        parola_norm = parola.casefold()
        for attrs, interno in _RE_ANCHOR.findall(html):
            if _RE_SERVICE_LINK.search(attrs):
                continue  # è un servizio in evidenza, non un tile argomento
            href = _href_di(attrs)
            if not href:
                continue
            assoluto = urljoin(base_url, href)
            parti = urlparse(assoluto)
            if _host_senza_www(parti.netloc.lower()) != host_ufficiale:
                continue
            if not _RE_ARGOMENTO.match(parti.path):
                continue  # il tile argomento è a un solo segmento
            if _testo(interno).casefold().startswith(parola_norm):
                return assoluto
        return None

    @staticmethod
    def _raccogli_servizi(
        html: str,
        pagina_url: str,
        host: str,
        limit: int,
        visti: set[str],
        candidati: list[ServiceCandidate],
    ) -> None:
        # Accumula in ``candidati`` (in-place), deduplicando su ``visti`` per
        # **URL canonica** (host minuscolo senza www + path senza slash finale):
        # cap e dedup valgono sul TOTALE impaginato.  L'id resta l'ultimo segmento
        # del path (slug proprio del servizio, mai dal titolo — I-2), ma la chiave
        # di dedup è l'URL, non lo slug: servizi annidati in categorie diverse
        # potrebbero condividere l'ultimo segmento.  Solo anchor col design token
        # servizio, sull'host ufficiale.
        host_ufficiale = _host_senza_www(host.lower())
        for attrs, interno in _RE_ANCHOR.findall(html):
            if len(candidati) >= limit:
                break  # cap DIFENSIVO (guardia memoria), non selezione (P1)
            if not _RE_SERVICE_LINK.search(attrs):
                continue  # tile argomento / link non-servizio scartati
            href = _href_di(attrs)
            if not href:
                continue
            assoluto = urljoin(pagina_url, href)
            parti = urlparse(assoluto)
            if _host_senza_www(parti.netloc.lower()) != host_ufficiale:
                continue  # host guard (I-5)
            match = _RE_SERVIZIO.match(parti.path)
            if match is None:
                continue  # non è /servizi/…/<slug>
            slug = match.group(1)  # id = ultimo segmento (dall'URL, non dal titolo)
            canonica = f"{host_ufficiale}{parti.path.rstrip('/')}"
            if canonica in visti:
                continue  # dedup per URL canonica (cross-pagina)
            titolo = _testo(interno)
            if not titolo:
                continue
            try:
                candidato = ServiceCandidate(native_id=slug, title=titolo, url=assoluto)
            except (ValueError, TypeError):
                continue
            visti.add(canonica)
            candidati.append(candidato)


class DrupalBiServiceConnector(_ServiceConnectorBase):
    """Resolve un ``ServiceKey`` a un ``ServiceReference`` sui portali Drupal BI.

    Corpo condiviso in ``_ServiceConnectorBase``; qui solo il gate di piattaforma
    (``drupal``), il prefisso ``drupal`` e il target di discovery (indice
    ``/servizi`` + parola-chiave argomento).  Come ComWeb, il gate **non** dipende
    da ``servizi.esposto``/``rest_base`` (concetti WP-REST, assenti su Drupal BI):
    basta la piattaforma e un ``sito`` valido.  Il Drupal-7 legacy senza
    ``/servizi`` cade in ``NOT_FOUND`` onesto (indice muto), non forzato.
    """

    name = "drupal_bi_service"
    version = "1"
    _CONNECTOR = _CONNECTOR
    _PIATTAFORME = frozenset({Piattaforma.DRUPAL.value})
    _PREFISSO = "drupal"
    _PROVIDER_PLATFORM = "drupal"
    _LIMITE_RICERCA = _CAP_DIFENSIVO_SERVIZI

    def _discovery_target(self, mappa, service_key: ServiceKey) -> DiscoveryTarget | None:
        base = _base_con_schema(getattr(mappa, "sito", None))
        if base is None:
            return None
        if service_key not in DRUPAL_BI_ARGOMENTO:
            return None
        entry = f"{base.rstrip('/')}{_INDICE}"
        # term = la ServiceKey (value): la discovery sceglie il tile argomento
        # dall'indice e ne segue la pagina.  Il gate esattamente-uno
        # (_confermati) resta ancorato a ``service_key`` sul titolo.
        return DiscoveryTarget(entry, service_key.value, urlparse(base).netloc)
