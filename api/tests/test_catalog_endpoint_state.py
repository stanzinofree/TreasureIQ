"""Fase 2D-i — stato persistente per (comune, superficie, entrypoint).

`transiziona` è la transizione pura guidata dal `CheckResult`: fissa qui le tre
regole che una singola foto non dà — durata dello stato (`da` scatta solo al
cambio), fallimenti di rete consecutivi (solo UNAVAILABLE, per il backoff),
ultimo esito buono.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from treasureiq.catalog.checks import CheckResult, CheckStatus
from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.endpoint_state import (
    EndpointState,
    stato_iniziale,
    transiziona,
)

_URL = "https://comune.example.it/amministrazione-trasparente"
_T0 = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)


def _check(status: CheckStatus, *, at: datetime) -> CheckResult:
    return CheckResult(
        source_id="058003", surface=Surface.TRANSPARENCY, status=status,
        source_health=status is CheckStatus.OK, checked_at=at,
    )


def test_stato_iniziale_ok():
    stato = stato_iniziale(_check(CheckStatus.OK, at=_T0), entrypoint_url=_URL)
    assert stato.status is CheckStatus.OK
    assert stato.ok_consecutivi == 1
    assert stato.fallimenti_consecutivi == 0
    assert stato.da == _T0
    assert stato.ultimo_ok_il == _T0
    assert stato.entrypoint_url == _URL


def test_stato_iniziale_unavailable_conta_il_fallimento():
    stato = stato_iniziale(
        _check(CheckStatus.UNAVAILABLE, at=_T0), entrypoint_url=_URL
    )
    assert stato.fallimenti_consecutivi == 1
    assert stato.ok_consecutivi == 0
    assert stato.ultimo_ok_il is None


def test_ricontrollo_stesso_stato_non_riazzera_la_durata():
    s0 = stato_iniziale(_check(CheckStatus.OK, at=_T0), entrypoint_url=_URL)
    t1 = _T0 + timedelta(hours=1)
    s1 = transiziona(s0, _check(CheckStatus.OK, at=t1))
    # Stesso stato: `da` resta l'inizio, ma i contatori e l'ultimo controllo avanzano.
    assert s1.da == _T0
    assert s1.ultimo_controllo_il == t1
    assert s1.ok_consecutivi == 2
    assert s1.ultimo_ok_il == t1


def test_cambio_stato_fa_scattare_da():
    s0 = stato_iniziale(_check(CheckStatus.OK, at=_T0), entrypoint_url=_URL)
    t1 = _T0 + timedelta(hours=1)
    s1 = transiziona(s0, _check(CheckStatus.DIFFORME, at=t1))
    assert s1.status is CheckStatus.DIFFORME
    assert s1.da == t1  # lo stato è cambiato: la durata riparte
    assert s1.ok_consecutivi == 0
    # DIFFORME non è un guasto di rete: nessun backoff.
    assert s1.fallimenti_consecutivi == 0
    # L'ultimo OK resta memorizzato anche se ora è difforme.
    assert s1.ultimo_ok_il == _T0


def test_fallimenti_di_rete_si_accumulano():
    s = stato_iniziale(_check(CheckStatus.UNAVAILABLE, at=_T0), entrypoint_url=_URL)
    for i in range(1, 4):
        s = transiziona(s, _check(CheckStatus.UNAVAILABLE, at=_T0 + timedelta(hours=i)))
    assert s.fallimenti_consecutivi == 4
    # Stesso stato per tutta la serie: `da` non si muove.
    assert s.da == _T0


def test_un_ok_azzera_i_fallimenti():
    s = stato_iniziale(_check(CheckStatus.UNAVAILABLE, at=_T0), entrypoint_url=_URL)
    s = transiziona(s, _check(CheckStatus.UNAVAILABLE, at=_T0 + timedelta(hours=1)))
    assert s.fallimenti_consecutivi == 2
    s = transiziona(s, _check(CheckStatus.OK, at=_T0 + timedelta(hours=2)))
    assert s.fallimenti_consecutivi == 0
    assert s.ok_consecutivi == 1


def test_difforme_azzera_gli_ok_ma_non_e_un_guasto():
    s = stato_iniziale(_check(CheckStatus.OK, at=_T0), entrypoint_url=_URL)
    s = transiziona(s, _check(CheckStatus.OK, at=_T0 + timedelta(hours=1)))
    assert s.ok_consecutivi == 2
    s = transiziona(s, _check(CheckStatus.DIFFORME, at=_T0 + timedelta(hours=2)))
    assert s.ok_consecutivi == 0
    assert s.fallimenti_consecutivi == 0


def test_stato_e_immutabile():
    s0 = stato_iniziale(_check(CheckStatus.OK, at=_T0), entrypoint_url=_URL)
    s1 = transiziona(s0, _check(CheckStatus.UNAVAILABLE, at=_T0 + timedelta(hours=1)))
    # model_copy non muta l'originale (modello frozen).
    assert s0.status is CheckStatus.OK
    assert s0.fallimenti_consecutivi == 0
    assert s1.status is CheckStatus.UNAVAILABLE
    assert isinstance(s1, EndpointState)
