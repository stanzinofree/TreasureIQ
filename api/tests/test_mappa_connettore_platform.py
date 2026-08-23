from datetime import datetime, timezone

from treasureiq.mappa_connettore import MappaConnettore, _piattaforma_da_home


class _RispostaFinta:
    """Sta per la risposta della home già scaricata (headers + testo)."""

    def __init__(self, *, testo: str, headers: dict | None = None) -> None:
        self.text = testo
        self.headers = headers or {}


def test_sonda_popola_piattaforma_da_home() -> None:
    # Gli asset /wp-content/ bastano a riconoscere la famiglia WordPress: è la
    # stessa firma del censimento, così il piattaforma_id scritto in mappa è
    # esattamente l'id su cui il registry dei connettori seleziona (Albano reale).
    home = _RispostaFinta(
        testo='<html><head><link rel="stylesheet" href="/wp-content/themes/x/s.css"></head>'
    )
    assert (
        _piattaforma_da_home(
            home, source_id="058003", entrypoint_url="https://comune.example"
        )
        == "wordpress_generico"
    )


def test_home_ignota_niente_piattaforma() -> None:
    # Nessun marcatore → piattaforma ignota → None: il resolver cadrà nel miss
    # onesto invece di agganciare una famiglia a caso (mai un connettore inventato).
    home = _RispostaFinta(testo="<html><body>solo testo civico</body></html>")
    assert (
        _piattaforma_da_home(
            home, source_id="058003", entrypoint_url="https://comune.example"
        )
        is None
    )


def test_home_muta_niente_piattaforma() -> None:
    # Una risposta senza .text/.headers non deve sollevare: piattaforma None.
    class _Muta:
        pass

    assert (
        _piattaforma_da_home(
            _Muta(), source_id="058003", entrypoint_url="https://comune.example"
        )
        is None
    )


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
