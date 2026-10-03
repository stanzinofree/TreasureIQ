from datetime import datetime, timezone

from treasureiq.catalog import SnapshotStore, Surface
from treasureiq.catalog.sweep_bridge import snapshots_from_sweep_row
from treasureiq.catalog.sweep_import import persist_sweep_snapshots


def test_sweep_import_persists_both_surfaces(monkeypatch, tmp_path) -> None:
    snapshots = snapshots_from_sweep_row(
        {
            "codice_istat": "058003",
            "piattaforma": "wp_design_comuni",
            "piattaforma_at": "jcitygov",
            "indirizzabilita": "api_uffici",
            "aderenza": 0.5,
        },
        measurement_id="sweep-1",
        measured_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "treasureiq.catalog.sweep_bridge.snapshots_from_sweep_db",
        lambda *args, **kwargs: snapshots,
    )
    # The importer imports the function into its module at import time.
    monkeypatch.setattr(
        "treasureiq.catalog.sweep_import.snapshots_from_sweep_db",
        lambda *args, **kwargs: snapshots,
    )

    paths = persist_sweep_snapshots(
        tmp_path / "storico.db",
        store=SnapshotStore(tmp_path / "catalog"),
        codice_istat="058003",
        measurement_id="sweep-1",
        measured_at=datetime.now(timezone.utc),
    )

    assert len(paths) == 2
    assert SnapshotStore(tmp_path / "catalog").latest_municipality(
        "058003", Surface.TRANSPARENCY
    ) is not None


# --- producer -> consumer: the real censimento summary through the bridge ---

from treasureiq.catalog.contracts import AgidCompatibility, CapabilityStatus, SectionStatus
from treasureiq.ingest.censimento import _riassumi
from treasureiq.ingest.modello_agid import SchedaAgid, SezioneAgid

_SCHEDA = "https://www.comune.example.it/servizi/carta-identita/"


def _riga_da_scheda(scheda: SchedaAgid) -> dict:
    """A portale_snapshot row as the census writes it for one sample page."""
    return {
        "codice_istat": "058003",
        "piattaforma": "wp_design_comuni",
        "indirizzabilita": "api_uffici",
        **_riassumi(scheda, _SCHEDA),
    }


def _ordinaria(riga: dict):
    ordinaria, _ = snapshots_from_sweep_row(
        riga, measurement_id="sweep-1", measured_at=datetime.now(timezone.utc)
    )
    return ordinaria


def test_schema_esposto_al_completo_resta_parziale_e_conserva_la_base() -> None:
    """100% of the boxes the API exposes is not the whole AgID model, and
    reading one service page proves nothing about offices or contacts."""
    esposte = frozenset({SezioneAgid.DESCRIZIONE, SezioneAgid.COME_FARE})
    scheda = SchedaAgid(
        declinazione="wp_design_comuni",
        sezioni={SezioneAgid.DESCRIZIONE: "x", SezioneAgid.COME_FARE: "y"},
        non_riconosciute=[],
        esposte=esposte,
    )
    riga = _riga_da_scheda(scheda)
    assert riga["aderenza"] == 1.0 and riga["base_misura"] == "schema_esposto"

    snap = _ordinaria(riga)
    assert snap.platform_compatibility is AgidCompatibility.PARTIAL
    assert snap.municipality_adoption["services"] is SectionStatus.PRESENT
    assert snap.municipality_adoption["offices"] is SectionStatus.UNKNOWN
    assert snap.municipality_adoption["contacts"] is SectionStatus.UNKNOWN
    assert snap.capabilities["services"] is CapabilityStatus.UNKNOWN
    assert snap.measurement_evidence["base_misura"] == "schema_esposto"
    assert snap.measurement_evidence["aderenza"] == "1.0"
    assert snap.measurement_evidence["sezioni_esposte"] == "descrizione,come_fare"
    assert snap.measurement_evidence["sezioni_dichiarate"] == "descrizione,come_fare"
    assert snap.measurement_evidence["scheda_campione"] == _SCHEDA
    assert "modello intero" in snap.measurement_evidence["nota_misura"]


def test_modello_intero_compilato_e_compatibile() -> None:
    scheda = SchedaAgid(
        declinazione="generica",
        sezioni={sezione: "x" for sezione in SezioneAgid},
        non_riconosciute=[],
    )
    riga = _riga_da_scheda(scheda)
    assert riga["aderenza"] == 1.0 and riga["base_misura"] == "modello_intero"
    assert _ordinaria(riga).platform_compatibility is AgidCompatibility.COMPATIBLE


def test_modello_intero_parziale_e_parziale() -> None:
    scheda = SchedaAgid(
        declinazione="generica",
        sezioni={SezioneAgid.DESCRIZIONE: "x", SezioneAgid.COME_FARE: "y"},
        non_riconosciute=[],
    )
    snap = _ordinaria(_riga_da_scheda(scheda))
    assert snap.platform_compatibility is AgidCompatibility.PARTIAL
    assert snap.measurement_evidence["base_misura"] == "modello_intero"


def test_riga_senza_misura_resta_ignota_e_senza_prove() -> None:
    snap = _ordinaria({"codice_istat": "058003", "piattaforma": "comweb"})
    assert snap.platform_compatibility is AgidCompatibility.UNKNOWN
    assert snap.municipality_adoption["services"] is SectionStatus.UNKNOWN
    assert snap.measurement_evidence == {}
