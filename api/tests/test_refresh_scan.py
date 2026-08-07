"""D-S6: refresh-on-search. Un comune riconosciuto con scan mancante o
stantio (>6gg) fa partire un refresh in background e lo segnala nel campo
`scan` della risposta chat; uno fresco serve la cache senza sondare di nuovo.

`build_chat_answer` ha TRE punti di uscita (W-1, dal plan-check): i due rami
fuori-copertura (nominato non censito; comune coperto ma senza match che
risulta comunque indirizzabile) e il `return` finale del ramo comune coperto
con match. Il campo `scan` deve arrivare da tutti e tre — qui si copre il
ramo coperto-con-match e uno dei due rami fuori-copertura, come da VERIFY del
brief B6. Nessuna rete: ogni sonda live e' monkeypatchata.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from treasureiq.chat import respond
from treasureiq.chat.intent import QuestionKind, Topic
from treasureiq.chat.respond import Connettore, DEFAULT_COMUNE_ISTAT, build_chat_answer

CIAMPINO_ISTAT = "058118"  # noto (`sonda_live`) ma non censito (`load_enti`): fuori copertura.


def _risposta_finta(*, data_gap: str | None = None) -> "respond.ChatAnswer":
    return respond.ChatAnswer(
        reply="Ecco quello che ho trovato.",
        topic=Topic.SCONOSCIUTO,
        kind=QuestionKind.AGEVOLAZIONE,
        data_gap=data_gap,
        needs_clarification=False,
        matches=[],
        spid_required=False,
        spid_reason=None,
    )


def _muta_sonde_fuori_copertura(monkeypatch: pytest.MonkeyPatch, *, connettore: Connettore | None) -> None:
    """Fa tacere ogni sonda dal vivo del ramo fuori-copertura (nessuna rete)."""
    monkeypatch.setattr(respond, "_componi_risposta", lambda **_k: asyncio.sleep(0, result=_risposta_finta()))
    monkeypatch.setattr(respond, "_prova_live", lambda *, risposta, comune, message: risposta)
    monkeypatch.setattr(respond, "sonda_connettore", lambda _codice: connettore)
    monkeypatch.setattr(respond, "_numeri_utili_al_volo", lambda _codice: None)
    monkeypatch.setattr(
        respond,
        "_premessa_fuori_copertura",
        lambda nominato, risposta, connettore, *, ha_scheda_laterale: "Attenzione: fuori copertura.",
    )


def _spia_refresh(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    chiamate: list[str] = []
    monkeypatch.setattr(
        respond, "_avvia_refresh_in_background", lambda codice_istat: chiamate.append(codice_istat)
    )
    return chiamate


# --- Ramo comune-coperto-con-match (il `return` finale) -------------------


def test_scan_stantio_su_comune_coperto_avvia_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(respond, "_componi_risposta", lambda **_k: asyncio.sleep(0, result=_risposta_finta()))
    chiamate = _spia_refresh(monkeypatch)
    monkeypatch.setattr(respond, "carica_scansione", lambda _codice: SimpleNamespace(scansionato_il="2020-01-01T00:00:00+00:00"))
    monkeypatch.setattr(respond, "scansione_stantia", lambda _record, **_k: True)

    risposta = asyncio.run(
        build_chat_answer(
            message="quali agevolazioni ci sono per la mensa?",
            profile=None,
            records=[],
            comune_istat=DEFAULT_COMUNE_ISTAT,
            comune_coperto=True,
        )
    )

    assert risposta.scan is not None
    assert risposta.scan.stato == "aggiornamento_in_corso"
    assert risposta.scan.ultimo_scan == "2020-01-01T00:00:00+00:00"
    assert chiamate == [DEFAULT_COMUNE_ISTAT]


def test_scan_fresco_su_comune_coperto_non_avvia_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(respond, "_componi_risposta", lambda **_k: asyncio.sleep(0, result=_risposta_finta()))
    chiamate = _spia_refresh(monkeypatch)
    monkeypatch.setattr(respond, "carica_scansione", lambda _codice: SimpleNamespace(scansionato_il="2026-08-06T09:00:00+00:00"))
    monkeypatch.setattr(respond, "scansione_stantia", lambda _record, **_k: False)

    risposta = asyncio.run(
        build_chat_answer(
            message="quali agevolazioni ci sono per la mensa?",
            profile=None,
            records=[],
            comune_istat=DEFAULT_COMUNE_ISTAT,
            comune_coperto=True,
        )
    )

    assert risposta.scan is not None
    assert risposta.scan.stato == "fresco"
    assert risposta.scan.ultimo_scan == "2026-08-06T09:00:00+00:00"
    assert chiamate == []


# --- Ramo fuori-copertura (nominato non censito) ---------------------------


def test_scan_assente_su_comune_fuori_copertura_avvia_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    _muta_sonde_fuori_copertura(monkeypatch, connettore=None)
    chiamate = _spia_refresh(monkeypatch)
    monkeypatch.setattr(respond, "carica_scansione", lambda _codice: None)
    monkeypatch.setattr(respond, "scansione_stantia", lambda _record, **_k: True)

    risposta = asyncio.run(
        build_chat_answer(
            message="Vivo a Ciampino, ci sono bonus per l'asilo?",
            profile=None,
            records=[],
            comune_istat=None,
            comune_coperto=True,
        )
    )

    assert risposta.scan is not None
    assert risposta.scan.stato == "aggiornamento_in_corso"
    assert risposta.scan.ultimo_scan is None
    assert chiamate == [CIAMPINO_ISTAT]
