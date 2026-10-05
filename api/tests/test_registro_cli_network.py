"""Transport-error classification in the bootstrap connector entrypoint."""

from __future__ import annotations

import httpx

from treasureiq import registro_cli


def test_timeout_di_connessione_e_classificato_come_rete_non_raggiungibile(monkeypatch):
    monkeypatch.setattr(registro_cli, "comune_per_codice", lambda _istat: None)

    def timeout(*_args, **_kwargs):
        raise httpx.ConnectTimeout("connessione scaduta")

    monkeypatch.setattr(registro_cli, "leggi_connettore", timeout)
    stato, _ = registro_cli._scansiona_uno("007017")
    assert stato == "rete_non_raggiungibile"
