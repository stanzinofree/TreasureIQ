"""Golden tests per il connettore-servizio Sportello Telematico (Ramo 3, #6).

Net-free: la rete è dietro un transport stub che serve le fixture HTML **reali**
catturate in ricognizione read-only su due comuni campione — Cologno Monzese
(``C_C895``, sitemap a **indice paginato**) e Pomezia (``C_G811``, sitemap
**flat**). Nessuna risposta inventata: le pagine procedura sono i dump reali, le
sitemap sono un **sottoinsieme reale** dei loro `<loc>` (schemi ``procedure:`` e
``action:`` così come li scrive Drupal Simple XML Sitemap).

Due livelli, come per HGate/Lepida:

- ``_SportelloDiscovery`` — sitemap (root → eventuale indice paginato) → pre-filtro
  per slug → titolo/canonical dalla pagina, con dedup ``ns:slug`` scheme-agnostico
  e namespace locali (``c_*``) esclusi;
- ``SportelloServiceConnector`` — il contratto ``retrieve`` condiviso cablato alla
  discovery reale: gate ``sportello_telematico``, esattamente-uno o NOT_FOUND.

Verità di terra (dal recogniser condiviso sui titoli reali):
- Cologno IMU → 1 candidato nazionale → FULFILLED;
- Cologno carta d'identità → 2 candidati (maggiorenni, minorenni), entrambi
  confermano CARTA_IDENTITA → ≥2 → NOT_FOUND (ambiguità onesta, I-1);
- Cologno TARI → ``procedure:`` + ``action:`` stesso slug (un servizio, dedup a 1)
  più una scheda ``c_c895`` locale (esclusa) → FULFILLED exactly-one;
- Pomezia trascrizione atti stato civile → ``action:...esteri`` +
  ``procedure:...esteri;domanda`` (slug distinti, entrambi STATO_CIVILE) → ≥2 →
  NOT_FOUND. Esercita il fetch dello schema ``action:``.
"""

from __future__ import annotations

from pathlib import Path

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, AccessMode, Surface
from treasureiq.catalog.data_contracts import DataRequest, DataStatus, FreshnessPolicy
from treasureiq.catalog.service_connectors.sportello_service import (
    SportelloServiceConnector,
    _SportelloDiscovery,
)
from treasureiq.catalog.service_contracts import ServiceAccessMode, ServiceKey
from treasureiq.mappa_connettore import AssetServizi, MappaConnettore

_FIXTURES = Path(__file__).parent / "fixtures" / "sportello"


def _fix(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


# ── comuni campione ─────────────────────────────────────────────────────────

_COLOGNO = "015081"
_COLOGNO_HOST = "colognoeasy.comune.colognomonzese.mi.it"
_POMEZIA = "058079"
_POMEZIA_HOST = "sportellotelematico.comune.pomezia.rm.it"


def _u(host: str, path: str) -> str:
    return f"https://{host}{path}"


# `<loc>`/canonical reali (schemi procedure:/action:, ns:slug encoded).
_C_SITEMAP = _u(_COLOGNO_HOST, "/sitemap.xml")
_C_PAGE1 = _u(_COLOGNO_HOST, "/default/sitemap.xml?page=1")
_C_IMU = _u(_COLOGNO_HOST, "/procedure%3As_italia%3Aimposta.municipale.unica%3Bdichiarazione")
_C_CARTA_MAGG = _u(
    _COLOGNO_HOST, "/procedure%3As_italia%3Acarta.identita%3Belettronica%3Bmaggiorenni%3Bdomanda"
)
_C_CARTA_MIN = _u(
    _COLOGNO_HOST, "/procedure%3As_italia%3Acarta.identita%3Belettronica%3Bminorenni%3Bdomanda"
)
_C_TARI_PROC = _u(
    _COLOGNO_HOST, "/procedure%3As_italia%3Atassa.rifiuti%3Butenze.domestiche%3Bdichiarazione"
)
_C_TARI_ACTION = _u(
    _COLOGNO_HOST, "/action%3As_italia%3Atassa.rifiuti%3Butenze.domestiche%3Bdichiarazione"
)
_C_TARI_LOCALE = _u(
    _COLOGNO_HOST,
    "/procedure%3Ac_c895%3Atassa.rifiuti%3Butenze.domestiche%3Briduzione.compostaggio%3Bdomanda",
)

_P_SITEMAP = _u(_POMEZIA_HOST, "/sitemap.xml")
_P_TRASC = _u(_POMEZIA_HOST, "/action%3As_italia%3Atrascrizione.atti.stato.civile%3Besteri")
_P_TRASC_DOM = _u(
    _POMEZIA_HOST, "/procedure%3As_italia%3Atrascrizione.atti.stato.civile%3Besteri%3Bdomanda"
)

# Terza variante di sottodominio della famiglia Globo: `sportelloamico.*`
# (Codogno, Drupal 10 / STU3). Stesso motore, sitemap flat; il connettore è
# host-agnostico (la base viene da mappa.sito, nessun host cablato). `<loc>`
# reali: nazionali s_italia (mappati) + locali r_lombar/c_c816 (esclusi).
_CODOGNO = "098019"
_CODOGNO_HOST = "sportelloamico.comune.codogno.lo.it"
_CO_SITEMAP = _u(_CODOGNO_HOST, "/sitemap.xml")
_CO_IMU = _u(_CODOGNO_HOST, "/procedure%3As_italia%3Aimposta.municipale.unica%3Bdichiarazione")
_CO_IMU_ACTION = _u(
    _CODOGNO_HOST, "/action%3As_italia%3Aimposta.municipale.unica%3Bdichiarazione"
)
_CO_IMU_PAG = _u(_CODOGNO_HOST, "/procedure%3As_italia%3Aimposta.municipale.unica%3Bpagamento")
_CO_LOC_R = _u(
    _CODOGNO_HOST, "/action%3Ar_lombar%3Aedilizia.residenziale.pubblica%3Bassegnazione.alloggio"
)
_CO_LOC_C = _u(_CODOGNO_HOST, "/action%3Ac_c816%3Aasilo.nido%3Biscrizione")


def _pagine_cologno() -> dict[str, str]:
    return {
        _C_SITEMAP: _fix("cologno_sitemap_root.xml"),
        _C_PAGE1: _fix("cologno_sitemap_page1.xml"),
        _C_IMU: _fix("cologno_imu.html"),
        _C_CARTA_MAGG: _fix("cologno_carta_maggiorenni.html"),
        _C_CARTA_MIN: _fix("cologno_carta_minorenni.html"),
        _C_TARI_PROC: _fix("cologno_tari.html"),
        # action TARI e scheda c_c895 locale sono NEL sitemap ma non nel dict:
        # non devono mai essere fetchate (dedup / esclusione namespace).
    }


def _pagine_pomezia() -> dict[str, str]:
    return {
        _P_SITEMAP: _fix("pomezia_sitemap_root.xml"),
        _P_TRASC: _fix("pomezia_trascrizione.html"),
        _P_TRASC_DOM: _fix("pomezia_trascrizione_domanda.html"),
    }


def _pagine_codogno() -> dict[str, str]:
    # Subset curato esattamente-uno: la sola scheda procedure IMU (+ il gemello
    # action nello stesso slug, dedotto → mai fetchato) e due loc locali
    # r_lombar/c_c816 presenti NEL sitemap ma non nel dict: escluse per
    # namespace, non devono mai essere fetchate.
    return {
        _CO_SITEMAP: _fix("codogno_sitemap.xml"),
        _CO_IMU: _fix("codogno_imu.html"),
    }


def _pagine_codogno_ambiguo() -> dict[str, str]:
    # Verità di terra reale: due schede IMU nazionali distinte (dichiarazione +
    # pagamento), entrambe TRIBUTI_IMU → ≥2 → NOT_FOUND onesto.
    return {
        _CO_SITEMAP: _fix("codogno_sitemap_ambiguo.xml"),
        _CO_IMU: _fix("codogno_imu.html"),
        _CO_IMU_PAG: _fix("codogno_imu_pagamento.html"),
    }


# ── doubles ─────────────────────────────────────────────────────────────────


class _StubTransport:
    """Serve HTML per-URL; registra cosa è stato fetchato (net-free)."""

    def __init__(self, pagine: dict[str, str]) -> None:
        self._pagine = pagine
        self.letti: list[str] = []

    def leggi_pagina(self, *, url, official_host):
        self.letti.append(url)
        return self._pagine.get(url)


class _FetcherSportello:
    """``_SportelloDiscovery`` reale su transport stub → un ``ServiceFetcher``."""

    def __init__(self, pagine: dict[str, str]) -> None:
        self.transport = _StubTransport(pagine)
        self._discovery = _SportelloDiscovery()

    def scopri_servizi(self, *, base_url, term, limit):
        return self._discovery.scopri_servizi(
            self.transport, base_url=base_url, term=term, limit=limit
        )

    def leggi_pagina(self, *, url, official_host):
        return self.transport.leggi_pagina(url=url, official_host=official_host)


def _mappa(*, istat: str, host: str | None) -> MappaConnettore:
    # Lo Sportello non espone il CPT WP-REST: esposto=False, il gate non ne
    # dipende. ``sito`` è l'host dello Sportello (non la vetrina Municipium).
    return MappaConnettore(
        codice_istat=istat,
        nome="Comune",
        sito=host,
        sondato_il="2026-09-06T00:00:00+00:00",
        piattaforma_id="sportello_telematico",
        servizi=AssetServizi(esposto=False, rest_base=None, totale=0),
    )


def _request(
    *,
    istat: str,
    service_key: ServiceKey | str | None,
    surface: Surface = Surface.ORDINARY_DATA,
    capability: str = CAPABILITY_SERVICES,
) -> DataRequest:
    selection: dict[str, object] = {}
    if service_key is not None:
        selection["service_key"] = (
            service_key.value if isinstance(service_key, ServiceKey) else service_key
        )
    return DataRequest(
        request_id=f"t:{istat}:{surface.value}:{capability}",
        source_id=istat,
        surface=surface,
        capability=capability,
        selection=selection,
        freshness=FreshnessPolicy(max_age_seconds=86_400),
        manifest_revision=1,
    )


def _risolvi(istat, host, pagine, service_key):
    fetcher = _FetcherSportello(pagine)
    conn = SportelloServiceConnector(fetcher)
    result = conn.retrieve(
        _request(istat=istat, service_key=service_key),
        mappa=_mappa(istat=istat, host=host),
        esito=None,
    )
    return result, fetcher


# ── gate di piattaforma ─────────────────────────────────────────────────────


def test_supports_solo_sportello():
    conn = SportelloServiceConnector(_FetcherSportello({}))
    req = _request(istat=_COLOGNO, service_key=ServiceKey.TRIBUTI_IMU)
    assert conn.supports(req, platform_id="sportello_telematico") is True
    assert conn.supports(req, platform_id="wordpress_agid") is False
    assert conn.supports(req, platform_id="comweb") is False
    assert conn.supports(req, platform_id="drupal") is False


def test_supports_solo_capability_servizi():
    conn = SportelloServiceConnector(_FetcherSportello({}))
    req = _request(istat=_COLOGNO, service_key=ServiceKey.TRIBUTI_IMU, capability="uffici")
    assert conn.supports(req, platform_id="sportello_telematico") is False


# ── Cologno — indice paginato ───────────────────────────────────────────────


def test_cologno_imu_fulfilled_exactly_one():
    r, _ = _risolvi(_COLOGNO, _COLOGNO_HOST, _pagine_cologno(), ServiceKey.TRIBUTI_IMU)
    assert r.status is DataStatus.FULFILLED
    assert r.access_mode is AccessMode.MEDIATED
    (ref,) = r.service_references
    # id da ns:slug (mai dal titolo, I-2); prefisso sportello.
    assert ref.service_id == f"{_COLOGNO}:sportello:s_italia:imposta.municipale.unica;dichiarazione"
    assert ref.provider_platform == "sportello_telematico"
    assert _COLOGNO_HOST in str(ref.source_url)
    assert "imu" in ref.title.lower()


def test_cologno_segue_indice_paginato():
    # Root = sitemapindex → il connettore scende alla pagina `?page=1` (I-4:
    # segue i `<loc>` reali, non inventa la pagina).
    _, fetcher = _risolvi(_COLOGNO, _COLOGNO_HOST, _pagine_cologno(), ServiceKey.TRIBUTI_IMU)
    letti = fetcher.transport.letti
    assert _C_SITEMAP in letti
    assert _C_PAGE1 in letti


def test_cologno_carta_ambigua_not_found():
    # Maggiorenni + minorenni, entrambi confermano CARTA_IDENTITA → ≥2 →
    # NOT_FOUND (I-1, nessuna elezione implicita), non FULFILLED.
    r, _ = _risolvi(_COLOGNO, _COLOGNO_HOST, _pagine_cologno(), ServiceKey.CARTA_IDENTITA)
    assert r.status is DataStatus.NOT_FOUND
    assert r.access_mode is AccessMode.MEDIATED
    assert r.service_references == ()


def test_cologno_tari_dedup_schema_e_esclude_locale():
    # procedure:+action: stesso slug = UN servizio (dedup ns:slug) → 1 confermato
    # → FULFILLED; la scheda c_c895 LOCALE è fuori dal primo ciclo.
    r, fetcher = _risolvi(_COLOGNO, _COLOGNO_HOST, _pagine_cologno(), ServiceKey.TRIBUTI_TARI)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id == f"{_COLOGNO}:sportello:s_italia:tassa.rifiuti;utenze.domestiche;dichiarazione"
    letti = fetcher.transport.letti
    # dedup: l'``action:`` stesso-slug NON è stato fetchato (già visto via procedure:).
    assert _C_TARI_ACTION not in letti
    # esclusione namespace: la scheda c_c895 locale NON è stata fetchata.
    assert _C_TARI_LOCALE not in letti


def test_cologno_information_option_presente():
    r, _ = _risolvi(_COLOGNO, _COLOGNO_HOST, _pagine_cologno(), ServiceKey.TRIBUTI_IMU)
    (ref,) = r.service_references
    modi = [o.mode for o in ref.options]
    assert ServiceAccessMode.INFORMATION in modi
    info = next(o for o in ref.options if o.mode is ServiceAccessMode.INFORMATION)
    assert str(info.url) == str(ref.source_url)


def test_cologno_cambio_residenza_miss_onesto():
    # Nessuna scheda cambio.residenza nel sottoinsieme → 0 confermati → NOT_FOUND.
    r, _ = _risolvi(_COLOGNO, _COLOGNO_HOST, _pagine_cologno(), ServiceKey.CAMBIO_RESIDENZA)
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()


# ── Pomezia — sitemap flat, schema action: ──────────────────────────────────


def test_pomezia_sitemap_flat_senza_indice():
    # urlset diretto: la root È già il catalogo, nessuna pagina `?page=`.
    _, fetcher = _risolvi(_POMEZIA, _POMEZIA_HOST, _pagine_pomezia(), ServiceKey.STATO_CIVILE)
    letti = fetcher.transport.letti
    assert _P_SITEMAP in letti
    assert not any("?page=" in u for u in letti)


def test_pomezia_stato_civile_ambiguo_not_found():
    # action:...esteri + procedure:...esteri;domanda: slug distinti, entrambi
    # STATO_CIVILE → ≥2 → NOT_FOUND. Esercita il fetch dello schema action:.
    r, fetcher = _risolvi(_POMEZIA, _POMEZIA_HOST, _pagine_pomezia(), ServiceKey.STATO_CIVILE)
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()
    # ha davvero fetchato entrambe le pagine (action: incluso).
    letti = fetcher.transport.letti
    assert _P_TRASC in letti
    assert _P_TRASC_DOM in letti


def test_pomezia_imu_miss_onesto():
    # Pomezia non ha IMU nazionale nel sottoinsieme → NOT_FOUND onesto.
    r, _ = _risolvi(_POMEZIA, _POMEZIA_HOST, _pagine_pomezia(), ServiceKey.TRIBUTI_IMU)
    assert r.status is DataStatus.NOT_FOUND


# ── namespace locale escluso (unico candidato) ──────────────────────────────


def test_namespace_locale_escluso_quando_unico():
    # Sitemap con SOLO una scheda c_c895 locale per la key → 0 nazionali → NOT_FOUND.
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{_C_TARI_LOCALE}</loc></url>"
        "</urlset>"
    )
    r, fetcher = _risolvi(
        _COLOGNO, _COLOGNO_HOST, {_C_SITEMAP: sitemap}, ServiceKey.TRIBUTI_TARI
    )
    assert r.status is DataStatus.NOT_FOUND
    # escluso PRIMA del fetch: la pagina locale non è mai stata scaricata.
    assert _C_TARI_LOCALE not in fetcher.transport.letti


# ── host guard + contratto ──────────────────────────────────────────────────


def test_host_guard_scarta_loc_off_host():
    # Un `<loc>` su host esterno (stesso slug IMU) → scartato (I-5) → NOT_FOUND.
    evil = "https://evil.example/procedure%3As_italia%3Aimposta.municipale.unica%3Bdichiarazione"
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{evil}</loc></url>"
        "</urlset>"
    )
    r, fetcher = _risolvi(
        _COLOGNO, _COLOGNO_HOST, {_C_SITEMAP: sitemap}, ServiceKey.TRIBUTI_IMU
    )
    assert r.status is DataStatus.NOT_FOUND
    assert evil not in fetcher.transport.letti


def test_sito_assente_not_supported():
    conn = SportelloServiceConnector(_FetcherSportello({}))
    r = conn.retrieve(
        _request(istat=_COLOGNO, service_key=ServiceKey.TRIBUTI_IMU),
        mappa=_mappa(istat=_COLOGNO, host=None),
        esito=None,
    )
    assert r.status is DataStatus.NOT_SUPPORTED
    assert r.access_mode is AccessMode.UNAVAILABLE


def test_service_key_mancante_not_found():
    r, _ = _risolvi(_COLOGNO, _COLOGNO_HOST, _pagine_cologno(), None)
    assert r.status is DataStatus.NOT_FOUND


def test_sitemap_muta_not_found():
    # Root assente dal dict → sitemap None → NOT_FOUND onesto (non catalogo vuoto).
    r, _ = _risolvi(_COLOGNO, _COLOGNO_HOST, {}, ServiceKey.TRIBUTI_IMU)
    assert r.status is DataStatus.NOT_FOUND


def test_source_id_mismatch_solleva():
    conn = SportelloServiceConnector(_FetcherSportello(_pagine_cologno()))
    req = _request(istat=_COLOGNO, service_key=ServiceKey.TRIBUTI_IMU)
    try:
        conn.retrieve(req, mappa=_mappa(istat="099999", host=_COLOGNO_HOST), esito=None)
    except ValueError:
        return
    raise AssertionError("atteso ValueError su source_id mismatch")


# ── 3ª variante di sottodominio: sportelloamico (Codogno) ────────────────────


def test_sportelloamico_imu_fulfilled_host_agnostico():
    # Stesso motore Globo su un terzo pattern di host (sportelloamico.*): il
    # connettore NON cabla host, la base viene da mappa.sito. procedure:+action:
    # stesso slug → UN servizio (dedup ns:slug) → FULFILLED; r_lombar e c_c816
    # locali sono nel sitemap ma restano fuori (namespace non nazionale).
    r, fetcher = _risolvi(
        _CODOGNO, _CODOGNO_HOST, _pagine_codogno(), ServiceKey.TRIBUTI_IMU
    )
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id == (
        f"{_CODOGNO}:sportello:s_italia:imposta.municipale.unica;dichiarazione"
    )
    letti = fetcher.transport.letti
    # dedup: la scheda procedure è tenuta, l'action gemello NON è fetchato.
    assert _CO_IMU in letti
    assert _CO_IMU_ACTION not in letti
    # esclusione namespace locali: r_lombar e c_c816 mai fetchati.
    assert _CO_LOC_R not in letti
    assert _CO_LOC_C not in letti


def test_sportelloamico_imu_ambiguo_not_found():
    # Verità di terra reale: su Codogno l'IMU nazionale ha più schede distinte
    # (dichiarazione + pagamento), entrambe TRIBUTI_IMU → ≥2 → NOT_FOUND onesto
    # (I-1), esattamente come live. Nessuna elezione arbitraria.
    r, _ = _risolvi(
        _CODOGNO, _CODOGNO_HOST, _pagine_codogno_ambiguo(), ServiceKey.TRIBUTI_IMU
    )
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()
