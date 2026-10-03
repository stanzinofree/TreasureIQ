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
            "aderenza": 0.5,
            "base_misura": "modello_intero",
            "sezioni_esposte": "descrizione,come_fare",
            "impronta_declinazione": "sha256:abc",
        },
        measurement_id="sweep-2026-08-20",
        measured_at=datetime.now(timezone.utc),
    )

    assert ordinary.platform_id == "wp_design_comuni"
    assert ordinary.access_mode is AccessMode.MEDIATED
    assert ordinary.platform_compatibility.value == "partial"
    assert transparency.surface is Surface.TRANSPARENCY
    assert transparency.platform_id == "jcitygov"
    assert transparency.access_mode is AccessMode.MEDIATED


def test_only_complete_agid_api_is_direct() -> None:
    ordinary, _ = snapshots_from_sweep_row(
        {
            "codice_istat": "058003",
            "piattaforma": "standard-agid",
            "indirizzabilita": "api_uffici",
            "aderenza": 1.0,
            "base_misura": "modello_intero",
        },
        measurement_id="sweep-1",
        measured_at=datetime.now(timezone.utc),
    )

    assert ordinary.access_mode is AccessMode.DIRECT


def test_full_exposed_schema_is_not_direct() -> None:
    """100% of the boxes an API exposes is not the whole AgID model."""
    ordinary, _ = snapshots_from_sweep_row(
        {
            "codice_istat": "058003",
            "piattaforma": "wp_design_comuni",
            "indirizzabilita": "api_uffici",
            "aderenza": 1.0,
            "base_misura": "schema_esposto",
        },
        measurement_id="sweep-1",
        measured_at=datetime.now(timezone.utc),
    )

    assert ordinary.platform_compatibility.value == "partial"
    assert ordinary.access_mode is AccessMode.MEDIATED


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
