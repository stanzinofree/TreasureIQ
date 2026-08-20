from datetime import datetime, timezone

from treasureiq.mappa_connettore import MappaConnettore


def test_mappa_keeps_main_and_transparency_platforms_separate() -> None:
    mappa = MappaConnettore(
        codice_istat="058003",
        nome="Albano",
        sito="https://comune.example",
        sondato_il=datetime.now(timezone.utc).isoformat(),
        piattaforma_id="wordpress_agid",
        piattaforma_at_id="halley_at",
    )

    assert mappa.piattaforma_id == "wordpress_agid"
    assert mappa.piattaforma_at_id == "halley_at"
