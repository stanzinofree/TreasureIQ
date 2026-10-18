"""The AT snapshot is a read-only fallback for portals without CPT REST."""

from treasureiq import api
from treasureiq.connettore import AmministrazioneTrasparente, BandoAT, EsitoConnettore


def test_bandi_route_falls_back_to_cached_at_snapshot(monkeypatch):
    monkeypatch.setattr(api, "bandi_criteri", lambda _istat: [])
    monkeypatch.setattr(
        api,
        "_da_store_raw",
        lambda _istat: EsitoConnettore(
            codice_istat="058118",
            piattaforma="wordpress_generico",
            letto_il="2026-10-18T00:00:00+00:00",
            amministrazione_trasparente=AmministrazioneTrasparente(
                bandi_attivi=[BandoAT(titolo="Avviso verificato", url="https://ciampino.example/avviso")]
            ),
        ),
    )

    assert api.bandi_criteri_route("058118") == [
        api.Bando(titolo="Avviso verificato", url="https://ciampino.example/avviso", data="")
    ]
