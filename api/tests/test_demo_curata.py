from pathlib import Path

import treasureiq.api as api
from treasureiq.ingest.__main__ import SOURCES


def test_albano_non_e_piu_una_demo_curata() -> None:
    assert "058003" not in api.COMUNI
    assert all(source["codice_istat"] != "058003" for source in SOURCES)
    assert not (Path(__file__).resolve().parents[2] / "data" / "seed" / "albano_058003.json").exists()
