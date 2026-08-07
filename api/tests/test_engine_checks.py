"""_check_sesso e _check_disabilita_nucleo (D-52, D-53).

Entrambi neutri per costruzione: senza un requisito esplicito nella fonte
(`Requirements.sesso` / `disabilita_nucleo_required`), non producono mai un
blocco — qual che sia il profilo del cittadino. Sul dataset di oggi solo 6
record su 736 portano uno di questi requisiti (R-DATA): il resto del
seed deve attraversare questi due check senza che il verdetto cambi.
"""

from __future__ import annotations

from treasureiq.match.engine import CriterionState, _check_disabilita_nucleo, _check_sesso
from treasureiq.schema import CitizenProfile, Requirements


def profilo(**kwargs) -> CitizenProfile:
    return CitizenProfile(**kwargs)


# --- _check_sesso -----------------------------------------------------------


def test_check_sesso_neutro_senza_requisito():
    """Nessun requisito nella fonte: nessun blocco, qualunque sia il profilo."""
    req = Requirements()
    assert _check_sesso(req, profilo()).state is CriterionState.UNKNOWN_SOURCE
    assert _check_sesso(req, profilo(sesso="f")).state is CriterionState.UNKNOWN_SOURCE
    assert _check_sesso(req, profilo(sesso="m")).state is CriterionState.UNKNOWN_SOURCE


def test_check_sesso_unknown_profile_quando_richiesto_ma_non_dichiarato():
    req = Requirements(sesso="f")
    risultato = _check_sesso(req, profilo())
    assert risultato.state is CriterionState.UNKNOWN_PROFILE


def test_check_sesso_match():
    req = Requirements(sesso="f")
    risultato = _check_sesso(req, profilo(sesso="f"))
    assert risultato.state is CriterionState.MET


def test_check_sesso_mismatch():
    req = Requirements(sesso="f")
    risultato = _check_sesso(req, profilo(sesso="m"))
    assert risultato.state is CriterionState.NOT_MET
    assert risultato.blocks


# --- _check_disabilita_nucleo ------------------------------------------------


def test_check_disabilita_nucleo_neutro_senza_requisito():
    req = Requirements()
    assert _check_disabilita_nucleo(req, profilo()).state is CriterionState.UNKNOWN_SOURCE
    assert (
        _check_disabilita_nucleo(req, profilo(disabilita_nucleo=True)).state
        is CriterionState.UNKNOWN_SOURCE
    )


def test_check_disabilita_nucleo_unknown_profile():
    req = Requirements(disabilita_nucleo_required=True)
    risultato = _check_disabilita_nucleo(req, profilo())
    assert risultato.state is CriterionState.UNKNOWN_PROFILE


def test_check_disabilita_nucleo_match():
    req = Requirements(disabilita_nucleo_required=True)
    risultato = _check_disabilita_nucleo(req, profilo(disabilita_nucleo=True))
    assert risultato.state is CriterionState.MET


def test_check_disabilita_nucleo_mismatch():
    req = Requirements(disabilita_nucleo_required=True)
    risultato = _check_disabilita_nucleo(req, profilo(disabilita_nucleo=False))
    assert risultato.state is CriterionState.NOT_MET
    assert risultato.blocks
