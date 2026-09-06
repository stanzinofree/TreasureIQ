"""Golden tests per il connettore-servizio Lepida/MyPortal (ER).

Net-free: la rete è dietro un transport stub che serve fixture **costruite** dal
contratto osservabile degli endpoint GET reali di due comuni ER (Anzola
dell'Emilia, Zola Predosa) — cfr. le intestazioni nelle fixture. Due livelli,
come per HGATE/ComWeb:

- ``_LepidaDiscovery`` — home→IPA (``codice_ipa``/``normalizza_ipa``),
  default-types→tipi servizio (``tipi_candidati``), un GET di elenco per tipo
  (``url_elenco``/``leggi_pagina``), mapping voce→``ServiceCandidate``, host guard;
- ``LepidaServiceConnector`` — il contratto ``retrieve`` condiviso cablato alla
  discovery reale: exactly-one-o-NOT_FOUND, ambiguità ≥2 come miss onesto (I-1),
  nessuna policy per-chiave propria (i titoli ER confermano la key direttamente).

Il gate di piattaforma tiene fuori ogni variante MyPortal non ER (Veneto
incluso): qui non compare, per costruzione.
"""

from __future__ import annotations

import json
from pathlib import Path

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, AccessMode, Surface
from treasureiq.catalog.data_contracts import DataRequest, DataStatus, FreshnessPolicy
from treasureiq.catalog.service_connectors.lepida_service import (
    LepidaServiceConnector,
    _LepidaDiscovery,
)
from treasureiq.catalog.service_contracts import ServiceAccessMode, ServiceKey
from treasureiq.ingest import myportal
from treasureiq.mappa_connettore import AssetServizi, MappaConnettore

_FIXTURES = Path(__file__).parent / "fixtures" / "rete_civica_lepida"
_LIMITE = LepidaServiceConnector._LIMITE_RICERCA
_TIPO = "rer_schedaservizio"


def _txt(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


def _obj(nome: str) -> object:
    return json.loads(_txt(nome))


# ── doubles ──────────────────────────────────────────────────────────────────


class _StubTransport:
    """Serve HTML (``leggi_pagina``) e JSON già decodificato (``scarica_json``)
    per-URL; registra cosa è stato fetchato."""

    def __init__(self, pagine: dict[str, str], json_map: dict[str, object]) -> None:
        self._pagine = pagine
        self._json = json_map
        self.letti: list[str] = []

    def leggi_pagina(self, *, url, official_host):
        self.letti.append(url)
        return self._pagine.get(url)

    def scarica_json(self, *, url, host_atteso):
        self.letti.append(url)
        return self._json.get(url)


class _FetcherLepida:
    """``_LepidaDiscovery`` reale su transport stub → un ``ServiceFetcher``."""

    def __init__(self, pagine: dict[str, str], json_map: dict[str, object]) -> None:
        self.transport = _StubTransport(pagine, json_map)
        self._discovery = _LepidaDiscovery()

    def scopri_servizi(self, *, base_url, term, limit):
        return self._discovery.scopri_servizi(
            self.transport, base_url=base_url, term=term, limit=limit
        )

    def leggi_pagina(self, *, url, official_host):
        return self.transport.leggi_pagina(url=url, official_host=official_host)


def _mappa(*, istat: str, host: str | None) -> MappaConnettore:
    # MyPortal non espone il CPT WP-REST: esposto=False, il gate non ne dipende.
    return MappaConnettore(
        codice_istat=istat,
        nome="Comune",
        sito=host,
        sondato_il="2026-09-06T00:00:00+00:00",
        piattaforma_id="rete_civica_lepida",
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


def _pagine_e_json(base: str, ipa: str, home_fix: str, content_fix: str):
    """La mappa fetch per un comune: home + default-types + elenco schedaservizio,
    più la pagina-scheda (shell) per ogni canonical del content."""
    pagine = {base: _txt(home_fix)}
    json_map = {
        myportal.url_tipi(base, ipa): _obj("default_types.json"),
        myportal.url_elenco(base, ipa, _TIPO, quanti=_LIMITE): _obj(content_fix),
    }
    # La pagina-scheda di ogni candidato (shell SPA) → _opzioni legge INFORMATION.
    for voce in _obj(content_fix)["page"]["entities"]:
        can = voce["attributes"]["sys_canonical_url"]
        pagine[base + can] = _txt("scheda_shell.html")
    return pagine, json_map


def _connector(pagine, json_map) -> LepidaServiceConnector:
    return LepidaServiceConnector(_FetcherLepida(pagine, json_map))


def _risolvi(istat, host, base, ipa, home_fix, content_fix, service_key):
    pagine, json_map = _pagine_e_json(base, ipa, home_fix, content_fix)
    conn = _connector(pagine, json_map)
    return conn.retrieve(
        _request(istat=istat, service_key=service_key),
        mappa=_mappa(istat=istat, host=host),
        esito=None,
    )


# ── Anzola dell'Emilia (037001) ──────────────────────────────────────────────

_ANZOLA = "037001"
_ANZOLA_HOST = "www.comune.anzoladellemilia.bo.it"
_ANZOLA_BASE = f"https://{_ANZOLA_HOST}"
_ANZOLA_IPA = "C_A324"


def _anzola(service_key):
    return _risolvi(
        _ANZOLA, _ANZOLA_HOST, _ANZOLA_BASE, _ANZOLA_IPA,
        "anzola_home.html", "anzola_content.json", service_key,
    )


# ── supports() — barriera di piattaforma ─────────────────────────────────────


def test_supports_solo_rete_civica_lepida():
    conn = _connector({}, {})
    req = _request(istat=_ANZOLA, service_key=ServiceKey.CARTA_IDENTITA)
    assert conn.supports(req, platform_id="rete_civica_lepida") is True
    # Le altre varianti MyPortal / famiglie NON sono servite qui.
    assert conn.supports(req, platform_id="regione_veneto") is False
    assert conn.supports(req, platform_id="wordpress_agid") is False
    assert conn.supports(req, platform_id="hgate") is False


def test_supports_solo_capability_servizi():
    conn = _connector({}, {})
    req = _request(istat=_ANZOLA, service_key=ServiceKey.CARTA_IDENTITA, capability="uffici")
    assert conn.supports(req, platform_id="rete_civica_lepida") is False


# ── positivi (exactly-one → FULFILLED) ───────────────────────────────────────


def test_anzola_cambio_residenza_fulfilled():
    r = _anzola(ServiceKey.CAMBIO_RESIDENZA)
    assert r.status is DataStatus.FULFILLED
    assert r.access_mode is AccessMode.MEDIATED
    (ref,) = r.service_references
    # id = sourceId nativo, MAI dal titolo (I-2); prefisso lepida.
    assert ref.service_id == f"{_ANZOLA}:lepida:674f036adbae62009a6bad28"
    assert ref.provider_platform == "lepida"
    assert str(ref.source_url).endswith(
        "/servizi/anagrafe-e-stato-civile/cambio-di-residenza-iscrizione-in-anagrafe"
    )


def test_anzola_carta_identita_confermata_pur_con_punteggiatura_strippata():
    # MyPortal serve i titoli senza punteggiatura ("Carta didentita elettronica
    # CIE"): il recogniser condiviso conferma comunque CARTA_IDENTITA.
    r = _anzola(ServiceKey.CARTA_IDENTITA)
    assert r.status is DataStatus.FULFILLED
    assert r.service_references[0].service_id == f"{_ANZOLA}:lepida:673b6877b67fc80097c5da05"


def test_anzola_information_option_da_shell_spa():
    # La pagina-scheda è un guscio SPA: unica opzione INFORMATION (= la pagina),
    # nessun DOWNLOAD/AUTHENTICATED_ONLINE fabbricato.
    r = _anzola(ServiceKey.CAMBIO_RESIDENZA)
    (ref,) = r.service_references
    modi = [o.mode for o in ref.options]
    assert modi == [ServiceAccessMode.INFORMATION]
    info = ref.options[0]
    assert str(info.url) == str(ref.source_url)


# ── ambiguità (≥2 → NOT_FOUND, I-1) ──────────────────────────────────────────


def test_anzola_accesso_atti_ambiguo_not_found():
    # Due schede "accesso agli atti" (anagrafe + ufficio tecnico) → ≥2 confermati
    # → NOT_FOUND: la scelta è di un livello superiore, mai implicita qui.
    r = _anzola(ServiceKey.ACCESSO_ATTI)
    assert r.status is DataStatus.NOT_FOUND
    assert r.access_mode is AccessMode.MEDIATED
    assert r.service_references == ()


# ── miss onesto (0 → NOT_FOUND) ──────────────────────────────────────────────


def test_anzola_tari_miss_onesto():
    # Nessuna scheda TARI nel catalogo di questo comune → 0 confermati.
    r = _anzola(ServiceKey.TRIBUTI_TARI)
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()


# ── discovery: forma dei fetch (home + types + un elenco) ─────────────────────


def test_discovery_tre_fetch_home_tipi_elenco():
    pagine, json_map = _pagine_e_json(
        _ANZOLA_BASE, _ANZOLA_IPA, "anzola_home.html", "anzola_content.json"
    )
    fetcher = _FetcherLepida(pagine, json_map)
    conn = LepidaServiceConnector(fetcher)
    conn.retrieve(
        _request(istat=_ANZOLA, service_key=ServiceKey.CAMBIO_RESIDENZA),
        mappa=_mappa(istat=_ANZOLA, host=_ANZOLA_HOST),
        esito=None,
    )
    letti = fetcher.transport.letti
    assert _ANZOLA_BASE in letti  # home (per l'IPA)
    assert myportal.url_tipi(_ANZOLA_BASE, _ANZOLA_IPA) in letti  # default-types
    assert myportal.url_elenco(_ANZOLA_BASE, _ANZOLA_IPA, _TIPO, quanti=_LIMITE) in letti
    # Un solo tipo-servizio nel default-types → un solo elenco (nessun fan-out).
    elenchi = [u for u in letti if "/api/content?" in u]
    assert len(elenchi) == 1


# ── Zola Predosa (037060) ────────────────────────────────────────────────────

_ZOLA = "037060"
_ZOLA_HOST = "www.comune.zolapredosa.bo.it"
_ZOLA_BASE = f"https://{_ZOLA_HOST}"
_ZOLA_IPA = "C_M185"


def _zola(service_key):
    return _risolvi(
        _ZOLA, _ZOLA_HOST, _ZOLA_BASE, _ZOLA_IPA,
        "zola_home.html", "zola_content.json", service_key,
    )


def test_zola_imu_e_tari_fulfilled():
    imu = _zola(ServiceKey.TRIBUTI_IMU)
    tari = _zola(ServiceKey.TRIBUTI_TARI)
    assert imu.status is DataStatus.FULFILLED
    assert tari.status is DataStatus.FULFILLED
    assert imu.service_references[0].service_id == f"{_ZOLA}:lepida:66d9bc224347260099881e0a"
    assert tari.service_references[0].service_id == f"{_ZOLA}:lepida:66e22003149ce5009bb5b3b8"


def test_zola_stato_civile_scheda_singola_fulfilled():
    # Un'unica scheda conferma STATO_CIVILE ("Separazione o divorzio davanti
    # all'ufficiale di stato civile") → FULFILLED, senza aggregazione di categoria.
    r = _zola(ServiceKey.STATO_CIVILE)
    assert r.status is DataStatus.FULFILLED
    assert r.service_references[0].service_id == f"{_ZOLA}:lepida:66e21576149ce5009bb5b14a"


def test_zola_carta_ambigua_not_found():
    # Due carte d'identità (elettronica + cartacea) → ≥2 → NOT_FOUND (I-1).
    r = _zola(ServiceKey.CARTA_IDENTITA)
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()


# ── host guard + degradi ─────────────────────────────────────────────────────


def test_host_guard_scarta_canonical_off_host():
    # Una voce con canonical assoluto verso un host esterno → resa assoluta
    # off-host → scartata (I-5) → 0 confermati → NOT_FOUND. Nessun URL esterno
    # diventa mai source_url.
    base, host, ipa = "https://comune.esempio.it", "comune.esempio.it", "C_X999"
    content = {
        "status": "ok",
        "page": {"index": 1, "entitiesCount": 1, "entities": [{
            "sourceId": "abc123",
            "name": "Cambio di residenza",
            "parent": "/Servizi/Anagrafe e stato civile",
            "attributes": {"sys_canonical_url": "https://evil.example/servizi/x/cambio-residenza"},
        }]},
    }
    pagine = {base: '<html><body>C_X999</body></html>'}
    json_map = {
        myportal.url_tipi(base, ipa): _obj("default_types.json"),
        myportal.url_elenco(base, ipa, _TIPO, quanti=_LIMITE): content,
    }
    conn = _connector(pagine, json_map)
    r = conn.retrieve(
        _request(istat="099001", service_key=ServiceKey.CAMBIO_RESIDENZA),
        mappa=_mappa(istat="099001", host=host),
        esito=None,
    )
    assert r.status is DataStatus.NOT_FOUND


def test_sito_assente_not_supported():
    conn = _connector({}, {})
    r = conn.retrieve(
        _request(istat=_ANZOLA, service_key=ServiceKey.CARTA_IDENTITA),
        mappa=_mappa(istat=_ANZOLA, host=None),
        esito=None,
    )
    assert r.status is DataStatus.NOT_SUPPORTED
    assert r.access_mode is AccessMode.UNAVAILABLE


def test_home_muta_not_found():
    # Home non servita → nessun IPA ricavabile → discovery vuota → NOT_FOUND.
    conn = _connector({}, {})
    r = conn.retrieve(
        _request(istat=_ANZOLA, service_key=ServiceKey.CARTA_IDENTITA),
        mappa=_mappa(istat=_ANZOLA, host=_ANZOLA_HOST),
        esito=None,
    )
    assert r.status is DataStatus.NOT_FOUND


def test_home_senza_ipa_not_found():
    # Home raggiungibile ma senza codice IPA → comune non indirizzabile per questa
    # via: NOT_FOUND onesto, non un catalogo inventato.
    pagine = {_ANZOLA_BASE: "<html><body>nessun codice qui</body></html>"}
    conn = _connector(pagine, {})
    r = conn.retrieve(
        _request(istat=_ANZOLA, service_key=ServiceKey.CARTA_IDENTITA),
        mappa=_mappa(istat=_ANZOLA, host=_ANZOLA_HOST),
        esito=None,
    )
    assert r.status is DataStatus.NOT_FOUND


def test_service_key_mancante_not_found():
    r = _anzola(None)
    assert r.status is DataStatus.NOT_FOUND
