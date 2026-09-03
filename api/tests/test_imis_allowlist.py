"""Guardia sul gate di promozione IMIS: allowlist authenticated_online +
validatore applicato a una ``ServiceReference`` (host, ISTAT, path, HTTPS, porta)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from treasureiq.catalog.imis_allowlist import (
    etichetta_delegata,
    motivo_rifiuto_auth_online,
    problemi_promozione,
)
from treasureiq.catalog.service_contracts import (
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceReference,
)

_COMUNE = "https://www.comune.vigolana.tn.it/Servizi/IMIS-on-line"
_DGE_VIGOLANA = "https://dgegovpa.it/Vigolana/login"


def _ref(*options: ServiceAccessOption, source_url: str = _COMUNE) -> ServiceReference:
    return ServiceReference(
        service_id="022236:openpa:1415",
        title="IMIS on line",
        source_url=source_url,
        options=tuple(options),
        discovered_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )


def _info(url: str = _COMUNE) -> ServiceAccessOption:
    return ServiceAccessOption(mode=ServiceAccessMode.INFORMATION, url=url, source_url=url)


def _auth(url: str) -> ServiceAccessOption:
    return ServiceAccessOption(
        mode=ServiceAccessMode.AUTHENTICATED_ONLINE, url=url, requires_authentication=True
    )


# --- etichetta_delegata (lookup host+ISTAT) --------------------------------

def test_imis_trentino_delega_globale():
    for istat in ("022236", "022097", "022001", "099999"):
        assert etichetta_delegata("consulenza.comunitrentini.tn.it", istat) == "IMIS_TRENTINO"


def test_dge_ammesso_solo_per_vigolana():
    assert etichetta_delegata("dgegovpa.it", "022236") == "DGE"
    for istat in ("022097", "022115", "022235", "022001"):
        assert etichetta_delegata("dgegovpa.it", istat) is None


def test_gisco_e_sconosciuti_mai_ammessi():
    for host in ("giscoservice.it", "imisimer.giscoservice.it", "esempio.it", ""):
        assert etichetta_delegata(host, "022236") is None


# --- motivo_rifiuto_auth_online (schema/porta/path) ------------------------

def test_dge_vigolana_url_ammesso():
    assert motivo_rifiuto_auth_online(_DGE_VIGOLANA, "022236") is None


def test_dge_rifiuta_altro_istat():
    assert motivo_rifiuto_auth_online(_DGE_VIGOLANA, "022097") is not None


def test_dge_rifiuta_path_diverso():
    # Stesso host, ISTAT ammesso, ma path di un tenant diverso: rifiutato.
    assert motivo_rifiuto_auth_online("https://dgegovpa.it/Imer/login", "022236") is not None
    assert motivo_rifiuto_auth_online("https://dgegovpa.it/Vigolana/admin", "022236") is not None


def test_rifiuta_non_https():
    assert motivo_rifiuto_auth_online("http://dgegovpa.it/Vigolana/login", "022236") is not None


def test_rifiuta_porta_non_standard():
    assert motivo_rifiuto_auth_online("https://dgegovpa.it:8443/Vigolana/login", "022236") is not None


def test_rifiuta_host_fuori_allowlist():
    assert motivo_rifiuto_auth_online("https://imisvigolana.giscoservice.it/", "022236") is not None


# --- problemi_promozione (integrazione su ServiceReference) ----------------

def test_reference_vigolana_ammissibile():
    ref = _ref(_info(), _auth(_DGE_VIGOLANA))
    assert problemi_promozione(ref, "022236") == []


def test_reference_vigolana_rifiutata_per_altro_istat():
    ref = _ref(_info(), _auth(_DGE_VIGOLANA))
    assert problemi_promozione(ref, "022097")  # DGE non ammesso per Imer


def test_reference_rifiuta_auth_su_gisco():
    ref = _ref(_info(), _auth("https://imisvigolana.giscoservice.it/"))
    assert problemi_promozione(ref, "022236")


def test_reference_rifiuta_prima_opzione_non_information():
    ref = _ref(_auth(_DGE_VIGOLANA), _info())
    assert any("INFORMATION" in p for p in problemi_promozione(ref, "022236"))


def test_reference_rifiuta_information_fuori_host_comune():
    ref = _ref(_info("https://altro-host.it/servizio"), _auth(_DGE_VIGOLANA))
    assert problemi_promozione(ref, "022236")


def test_reference_rifiuta_download_fuori_host_comune():
    dl = ServiceAccessOption(
        mode=ServiceAccessMode.DOWNLOAD, url="https://cdn-terzi.it/modulo.pdf"
    )
    ref = _ref(_info(), dl, _auth(_DGE_VIGOLANA))
    assert any("download" in p for p in problemi_promozione(ref, "022236"))


def test_reference_senza_opzioni_impossibile_da_costruire():
    # ServiceReference impone options min_length=1: il gate non riceve mai [].
    with pytest.raises(Exception):
        _ref()
