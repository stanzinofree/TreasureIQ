"""Transport-error classification in the bootstrap connector entrypoint."""

from __future__ import annotations

import httpx

import treasureiq.connettore as connettore_mod
from treasureiq import registro_cli
from treasureiq.sonda_live import ComuneNoto


def test_timeout_di_connessione_e_classificato_come_rete_non_raggiungibile(monkeypatch):
    monkeypatch.setattr(registro_cli, "comune_per_codice", lambda _istat: None)

    def timeout(*_args, **_kwargs):
        raise httpx.ConnectTimeout("connessione scaduta")

    monkeypatch.setattr(registro_cli, "leggi_connettore", timeout)
    stato, _ = registro_cli._scansiona_uno("007017")
    assert stato == "rete_non_raggiungibile"


def test_home_5xx_e_classificata_come_rete_non_raggiungibile(tmp_path, monkeypatch):
    comune = ComuneNoto(
        codice_istat="081015",
        nome="Partanna",
        provincia="TP",
        regione="Sicilia",
        sito="www.comune.partanna.tp.it",
    )

    class Sonda500:
        def __init__(self, *, timeout: float = 8.0) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def risposta(self, url: str) -> httpx.Response:
            return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(registro_cli, "comune_per_codice", lambda _istat: comune)
    monkeypatch.setattr(connettore_mod, "comune_per_codice", lambda _istat: comune)
    monkeypatch.setattr(connettore_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(connettore_mod, "_Sonda", Sonda500)
    monkeypatch.setattr(connettore_mod, "mappa_connettore", lambda _istat: None)

    stato, _ = registro_cli._scansiona_uno(comune.codice_istat)
    assert stato == "rete_non_raggiungibile"
