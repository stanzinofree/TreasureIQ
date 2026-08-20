from datetime import datetime, timezone

from treasureiq.catalog import AccessMode, Surface
from treasureiq.catalog.sweep_bridge import snapshots_from_sweep_row


def test_sweep_row_becomes_two_contract_snapshots() -> None:
    ordinary, transparency = snapshots_from_sweep_row(
        {
            "codice_istat": "058003",
            "piattaforma": "wp_design_comuni",
            "piattaforma_at": "jcitygov",
            "url_finale": "https://comune.example",
            "at_url": "https://at.example",
            "indirizzabilita": "api_uffici",
            "aderenza": 50,
            "sezioni_esposte": "services,offices",
            "impronta_declinazione": "sha256:abc",
        },
        measurement_id="sweep-2026-08-20",
        measured_at=datetime.now(timezone.utc),
    )

    assert ordinary.platform_id == "wp_design_comuni"
    assert ordinary.access_mode is AccessMode.DIRECT
    assert ordinary.platform_compatibility.value == "partial"
    assert transparency.surface is Surface.TRANSPARENCY
    assert transparency.platform_id == "jcitygov"
    assert transparency.access_mode is AccessMode.MEDIATED


def test_sweep_unknowns_do_not_become_negative_assertions() -> None:
    ordinary, transparency = snapshots_from_sweep_row(
        {
            "codice_istat": "058003",
            "piattaforma": "ignota",
            "piattaforma_at": "",
            "indirizzabilita": "irraggiungibile",
            "aderenza": None,
        },
        measurement_id="sweep-1",
        measured_at=datetime.now(timezone.utc),
    )

    assert ordinary.platform_id is None
    assert ordinary.access_mode is AccessMode.UNAVAILABLE
    assert transparency.platform_id is None
    assert transparency.access_mode is AccessMode.UNAVAILABLE
