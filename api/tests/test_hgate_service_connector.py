"""Golden tests per il connettore-servizio HGATE (Ramo 3, Connettore #4).

Net-free: la rete è dietro un transport stub che serve le fixture dei 6 archetipi
catturati in ricognizione live.  Due livelli, come per ComWeb:

- ``_HGateDiscovery`` — un solo fetch della sitemap ``FUNZ=1`` (indice completo
  delle schede), firma a due varianti (parameterless + fallback ``en=eg`` da
  home), host guard, titolo unescape e spezzato del prefisso categoria;
- ``HGateServiceConnector`` — il contratto ``retrieve`` condiviso cablato alla
  discovery reale, più le tre policy: ACCESSO_ATTI solo documentale, STATO_CIVILE
  aggregato alla pagina-categoria, exactly-one invariato per le altre chiavi e
  IMU/TARI assenti come miss onesti.
"""

from __future__ import annotations

from pathlib import Path

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, AccessMode, Surface
from treasureiq.catalog.data_contracts import DataRequest, DataStatus, FreshnessPolicy
from treasureiq.catalog.service_connectors.hgate_service import (
    HGateServiceConnector,
    _HGateDiscovery,
)
from treasureiq.catalog.service_contracts import ServiceAccessMode, ServiceKey
from treasureiq.mappa_connettore import AssetServizi, MappaConnettore

_FIXTURES = Path(__file__).parent / "fixtures" / "hgate"


def _fix(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


def _param_url(host: str) -> str:
    return f"https://{host}/EG0/EGSMISTMSIT.HBL?FUNZ=1"


# ── doubles ─────────────────────────────────────────────────────────────────


class _StubTransport:
    """Serve HTML per-URL; registra cosa è stato fetchato."""

    def __init__(self, pagine: dict[str, str]) -> None:
        self._pagine = pagine
        self.letti: list[str] = []

    def leggi_pagina(self, *, url, official_host):
        self.letti.append(url)
        return self._pagine.get(url)


class _FetcherHGate:
    """``_HGateDiscovery`` reale su transport stub → un ``ServiceFetcher``."""

    def __init__(self, pagine: dict[str, str]) -> None:
        self.transport = _StubTransport(pagine)
        self._discovery = _HGateDiscovery()

    def scopri_servizi(self, *, base_url, term, limit):
        return self._discovery.scopri_servizi(
            self.transport, base_url=base_url, term=term, limit=limit
        )

    def leggi_pagina(self, *, url, official_host):
        return self.transport.leggi_pagina(url=url, official_host=official_host)


def _mappa(*, istat: str, host: str | None) -> MappaConnettore:
    # HGATE non espone il CPT WP-REST: esposto=False, il gate non ne dipende.
    return MappaConnettore(
        codice_istat=istat,
        nome="Comune",
        sito=host,
        sondato_il="2026-09-04T00:00:00+00:00",
        piattaforma_id="hgate",
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


def _connector(pagine: dict[str, str]) -> HGateServiceConnector:
    return HGateServiceConnector(_FetcherHGate(pagine))


def _risolvi(istat, host, sitemap_pagine, service_key):
    conn = _connector(sitemap_pagine)
    return conn.retrieve(
        _request(istat=istat, service_key=service_key),
        mappa=_mappa(istat=istat, host=host),
        esito=None,
    )


# ── supports() — barriera di piattaforma ────────────────────────────────────


def test_supports_solo_hgate():
    conn = _connector({})
    req = _request(istat="010002", service_key=ServiceKey.CARTA_IDENTITA)
    assert conn.supports(req, platform_id="hgate") is True
    assert conn.supports(req, platform_id="comweb") is False
    assert conn.supports(req, platform_id="wordpress_agid") is False


def test_supports_solo_capability_servizi_e_ordinary():
    conn = _connector({})
    req_wrong_cap = _request(
        istat="010002", service_key=ServiceKey.CARTA_IDENTITA, capability="uffici"
    )
    assert conn.supports(req_wrong_cap, platform_id="hgate") is False


# ── Archetipo A — Avegno, firma parameterless, copertura ricca ──────────────

_AVEGNO = "010002"
_AVEGNO_HOST = "comune.avegno.ge.it"


def _pagine_avegno() -> dict[str, str]:
    return {_param_url(_AVEGNO_HOST): _fix("avegno_sitemap.html")}


def test_avegno_carta_identita_fulfilled_id_da_path():
    r = _risolvi(_AVEGNO, _AVEGNO_HOST, _pagine_avegno(), ServiceKey.CARTA_IDENTITA)
    assert r.status is DataStatus.FULFILLED
    assert r.access_mode is AccessMode.MEDIATED
    (ref,) = r.service_references
    # id dalla path (servizio_66), MAI dal titolo (I-2).
    assert ref.service_id == f"{_AVEGNO}:hgate:66"
    assert ref.provider_platform == "hgate"
    assert str(ref.source_url).endswith("/servizi/anagrafe_e_stato_civile/servizio_66.html")
    # unescape del titolo entity-encoded (&#8217; + &agrave;) → policy (3).
    assert "identità" in ref.title.lower()


def test_avegno_cambio_residenza_fulfilled():
    r = _risolvi(_AVEGNO, _AVEGNO_HOST, _pagine_avegno(), ServiceKey.CAMBIO_RESIDENZA)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id == f"{_AVEGNO}:hgate:35"


def test_avegno_imu_e_tari_fulfilled():
    imu = _risolvi(_AVEGNO, _AVEGNO_HOST, _pagine_avegno(), ServiceKey.TRIBUTI_IMU)
    tari = _risolvi(_AVEGNO, _AVEGNO_HOST, _pagine_avegno(), ServiceKey.TRIBUTI_TARI)
    assert imu.status is DataStatus.FULFILLED
    assert tari.status is DataStatus.FULFILLED
    assert imu.service_references[0].service_id == f"{_AVEGNO}:hgate:90"
    assert tari.service_references[0].service_id == f"{_AVEGNO}:hgate:91"


def test_avegno_accesso_atti_miss_onesto():
    # Nessuna scheda accesso documentale → NOT_FOUND (0 confermati), MEDIATED.
    r = _risolvi(_AVEGNO, _AVEGNO_HOST, _pagine_avegno(), ServiceKey.ACCESSO_ATTI)
    assert r.status is DataStatus.NOT_FOUND
    assert r.access_mode is AccessMode.MEDIATED
    assert r.service_references == ()


def test_avegno_information_option_presente():
    r = _risolvi(_AVEGNO, _AVEGNO_HOST, _pagine_avegno(), ServiceKey.CARTA_IDENTITA)
    (ref,) = r.service_references
    modi = [o.mode for o in ref.options]
    assert ServiceAccessMode.INFORMATION in modi
    info = next(o for o in ref.options if o.mode is ServiceAccessMode.INFORMATION)
    assert str(info.url) == str(ref.source_url)


# ── STATO_CIVILE — aggregazione alla pagina-categoria (policy 2) ────────────


def test_stato_civile_aggrega_alla_categoria_non_una_scheda():
    r = _risolvi(_AVEGNO, _AVEGNO_HOST, _pagine_avegno(), ServiceKey.STATO_CIVILE)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    # id = slug categoria, non un id scheda numerico; url = pagina-categoria.
    assert ref.service_id == f"{_AVEGNO}:hgate:anagrafe_e_stato_civile"
    assert str(ref.source_url).endswith("/servizi/anagrafe_e_stato_civile/")
    assert "servizio_" not in str(ref.source_url)


# ── Archetipo B — Albavilla, firma en=eg da home (fallback) ─────────────────

_ALBA = "013003"
_ALBA_HOST = "www.comune.albavilla.co.it"


def _pagine_albavilla() -> dict[str, str]:
    base = f"https://{_ALBA_HOST}"
    return {
        # sitemap parameterless MUTA (assente dal dict) → fallback firma-B
        f"{base}/": _fix("albavilla_home.html"),
        f"{base}/EG0/EGSMISTMSIT.HBL?en=eg927&FUNZ=1": _fix("albavilla_sitemap_en.html"),
    }


def test_albavilla_firma_en_fallback_da_home():
    pagine = _pagine_albavilla()
    fetcher = _FetcherHGate(pagine)
    conn = HGateServiceConnector(fetcher)
    r = conn.retrieve(
        _request(istat=_ALBA, service_key=ServiceKey.CAMBIO_RESIDENZA),
        mappa=_mappa(istat=_ALBA, host=_ALBA_HOST),
        esito=None,
    )
    assert r.status is DataStatus.FULFILLED
    assert r.service_references[0].service_id == f"{_ALBA}:hgate:35"
    # Ha davvero seguito la firma-B: parameterless muta → home → en-sitemap.
    letti = fetcher.transport.letti
    assert _param_url(_ALBA_HOST) in letti
    assert f"https://{_ALBA_HOST}/" in letti
    assert f"https://{_ALBA_HOST}/EG0/EGSMISTMSIT.HBL?en=eg927&FUNZ=1" in letti


def test_albavilla_stato_civile_aggrega_pur_con_7_schede():
    r = _risolvi(_ALBA, _ALBA_HOST, _pagine_albavilla(), ServiceKey.STATO_CIVILE)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id == f"{_ALBA}:hgate:anagrafe_e_stato_civile"


def test_albavilla_tari_miss_onesto():
    r = _risolvi(_ALBA, _ALBA_HOST, _pagine_albavilla(), ServiceKey.TRIBUTI_TARI)
    assert r.status is DataStatus.NOT_FOUND


# ── Archetipo C — Aiello, ambiguità IMU (≥2 → NOT_FOUND) ────────────────────

_AIELLO = "064001"
_AIELLO_HOST = "comune.aiellodelsabato.av.it"


def _pagine_aiello() -> dict[str, str]:
    return {_param_url(_AIELLO_HOST): _fix("aiello_sitemap.html")}


def test_aiello_imu_ambiguo_not_found():
    # Due schede IMU → ≥2 confermati → NOT_FOUND (I-1), non elezione implicita.
    r = _risolvi(_AIELLO, _AIELLO_HOST, _pagine_aiello(), ServiceKey.TRIBUTI_IMU)
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()


def test_aiello_residenza_resta_exactly_one():
    # L'ambiguità IMU non contamina le altre key.
    r = _risolvi(_AIELLO, _AIELLO_HOST, _pagine_aiello(), ServiceKey.CAMBIO_RESIDENZA)
    assert r.status is DataStatus.FULFILLED
    assert r.service_references[0].service_id == f"{_AIELLO}:hgate:35"


# ── Archetipo D — Archi, policy ACCESSO_ATTI solo documentale ───────────────

_ARCHI = "069002"
_ARCHI_HOST = "comune.archi.ch.it"


def _pagine_archi() -> dict[str, str]:
    return {_param_url(_ARCHI_HOST): _fix("archi_sitemap.html")}


def test_archi_accesso_atti_solo_documentale():
    # Co-presenti documentale + civico + FOIA → conferma SOLO il documentale.
    r = _risolvi(_ARCHI, _ARCHI_HOST, _pagine_archi(), ServiceKey.ACCESSO_ATTI)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id == f"{_ARCHI}:hgate:12"
    assert "civico" not in ref.title.lower()
    assert "foia" not in ref.title.lower()


def test_archi_tari_fulfilled_imu_miss():
    tari = _risolvi(_ARCHI, _ARCHI_HOST, _pagine_archi(), ServiceKey.TRIBUTI_TARI)
    imu = _risolvi(_ARCHI, _ARCHI_HOST, _pagine_archi(), ServiceKey.TRIBUTI_IMU)
    assert tari.status is DataStatus.FULFILLED
    assert imu.status is DataStatus.NOT_FOUND


# ── Archetipo E — Bojano, carta assente (isolamento del miss) ───────────────

_BOJANO = "070003"
_BOJANO_HOST = "comune.bojano.cb.it"


def _pagine_bojano() -> dict[str, str]:
    return {_param_url(_BOJANO_HOST): _fix("bojano_sitemap.html")}


def test_bojano_carta_miss_ma_residenza_ok():
    carta = _risolvi(_BOJANO, _BOJANO_HOST, _pagine_bojano(), ServiceKey.CARTA_IDENTITA)
    residenza = _risolvi(_BOJANO, _BOJANO_HOST, _pagine_bojano(), ServiceKey.CAMBIO_RESIDENZA)
    assert carta.status is DataStatus.NOT_FOUND
    assert residenza.status is DataStatus.FULFILLED


# ── Archetipo F — Agnana, unescape + tributi assenti veri ───────────────────

_AGNANA = "080002"
_AGNANA_HOST = "comune.agnana.rc.it"


def _pagine_agnana() -> dict[str, str]:
    return {_param_url(_AGNANA_HOST): _fix("agnana_sitemap.html")}


def test_agnana_carta_unescape_confermata():
    r = _risolvi(_AGNANA, _AGNANA_HOST, _pagine_agnana(), ServiceKey.CARTA_IDENTITA)
    assert r.status is DataStatus.FULFILLED
    assert "identità" in r.service_references[0].title.lower()


def test_agnana_imu_tari_miss_onesti():
    # Solo canoni minori pubblicati: assenza VERA, non artefatto.
    imu = _risolvi(_AGNANA, _AGNANA_HOST, _pagine_agnana(), ServiceKey.TRIBUTI_IMU)
    tari = _risolvi(_AGNANA, _AGNANA_HOST, _pagine_agnana(), ServiceKey.TRIBUTI_TARI)
    assert imu.status is DataStatus.NOT_FOUND
    assert tari.status is DataStatus.NOT_FOUND


# ── host guard + gate di piattaforma ────────────────────────────────────────


def test_host_guard_scarta_anchor_off_host():
    host = "comune.esempio.it"
    sitemap = (
        "<html><body>"
        '<a href="https://evil.example/servizi/anagrafe_e_stato_civile/servizio_35.html">'
        "Anagrafe e stato civile - Cambio di residenza</a>"
        "</body></html>"
    )
    r = _risolvi("099001", host, {_param_url(host): sitemap}, ServiceKey.CAMBIO_RESIDENZA)
    # L'unico anchor è off-host → scartato (I-5) → 0 confermati → NOT_FOUND.
    assert r.status is DataStatus.NOT_FOUND


def test_sito_assente_not_supported():
    conn = _connector({})
    r = conn.retrieve(
        _request(istat="010002", service_key=ServiceKey.CARTA_IDENTITA),
        mappa=_mappa(istat="010002", host=None),
        esito=None,
    )
    assert r.status is DataStatus.NOT_SUPPORTED
    assert r.access_mode is AccessMode.UNAVAILABLE


def test_service_key_mancante_not_found():
    r = _risolvi(_AVEGNO, _AVEGNO_HOST, _pagine_avegno(), None)
    assert r.status is DataStatus.NOT_FOUND


def test_sitemap_muta_entrambe_le_firme_not_found():
    # Parameterless muta E nessuna home/en → sitemap None → NOT_FOUND onesto.
    r = _risolvi(_AVEGNO, _AVEGNO_HOST, {}, ServiceKey.CARTA_IDENTITA)
    assert r.status is DataStatus.NOT_FOUND
