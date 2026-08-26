"""Filtro OpenPA-local titolo/classe (`_filtra_candidati`) — blast-radius net-free.

Copre la policy OpenPA-local aggiunta a ``openpa_service.py`` SENZA toccare il
recogniser condiviso (`riconosci_service_key`) né i contratti base:

  - Layer 0  ``_MARCATORI_NEGATIVI``  (es. "taxi" per le chiavi anagrafiche)
  - Layer B  ``_STOPLIST_DETRITO`` + ``_DETRITO_RX``  (detrito amministrativo)
  - Layer A  priorità classe: un solo ``public_service`` vince su document/output
  - short-circuit ``len(matched) <= 1``: un match solitario non viene MAI scartato
    (è ciò che protegge i 39 golden).

Il test golden riproduce la pipeline di produzione per il caso mono-sito OpenPA
(filtro → recogniser → gate esattamente-1, I-1) sui 39 casi confermati dalla
baseline congelata, e asserisce che restino confermati sullo stesso native_id.
"""
from __future__ import annotations

import json
import os

import pytest

from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.openpa_service import (
    _DETRITO_RX,
    _MARCATORI_NEGATIVI,
    _STOPLIST_DETRITO,
    OpenPAServiceConnector,
    _e_detrito,
)
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.chat.service_key import riconosci_service_key

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "openpa_golden_campione.json"
)

# Net-free: il fetcher non viene usato (chiamiamo _filtra_candidati direttamente).
_CONN = OpenPAServiceConnector(fetcher=object())


def _cands(hits: list[dict]) -> tuple[ServiceCandidate, ...]:
    out = []
    for h in hits:
        try:
            out.append(
                ServiceCandidate(
                    native_id=str(h["id"]),
                    title=h["title"],
                    url=h["url"],
                    native_class=h.get("classIdentifier"),
                )
            )
        except Exception:
            # Un hit non costruibile (es. titolo vuoto) non diventa candidato in
            # produzione: il parser eZ lo scarta allo stesso modo. Mirror onesto.
            continue
    return tuple(out)


def _resolve(hits: list[dict], key: ServiceKey):
    """Rispecchia la produzione per OpenPA mono-sito: filtro → recogniser → gate."""
    filtrati = _CONN._filtra_candidati(_cands(hits), key)
    conf = [c for c in filtrati if riconosci_service_key(c.title) is key]
    if len(conf) == 1:
        return "confermato", conf[0]
    return ("vuoto" if not conf else "ambiguo"), None


# --------------------------------------------------------------------------- #
# (d) Golden: i 39 casi confermati dalla baseline restano invariati.
# --------------------------------------------------------------------------- #
def _golden_cases() -> list[dict]:
    with open(_FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def test_golden_fixture_ha_39_casi() -> None:
    assert len(_golden_cases()) == 39


@pytest.mark.parametrize(
    "caso",
    _golden_cases(),
    ids=[f"{c['comune']}-{c['key']}" for c in _golden_cases()],
)
def test_golden_39_restano_confermati_stesso_id(caso: dict) -> None:
    """Nessuna regressione: ogni caso confermato pre-filtro resta confermato,
    e punta allo stesso native_id (I-1 non deve mai perdere il match solitario)."""
    esito, cand = _resolve(caso["hits"], ServiceKey[caso["key"]])
    assert esito == "confermato", f"{caso['comune']}/{caso['key']} → {esito}"
    assert cand is not None
    assert cand.native_id == caso["expected_native_id"]


# --------------------------------------------------------------------------- #
# (c) Ogni termine della stoplist e ogni token della regex → detrito.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("termine", _STOPLIST_DETRITO)
def test_stoplist_ogni_substring_e_detrito(termine: str) -> None:
    # substring: basta contenerlo, in un titolo altrimenti plausibile.
    assert _e_detrito(f"Comune di Roma {termine} anno 2026") is True


@pytest.mark.parametrize("token", ["ruolo", "det", "delib", "imp"])
def test_regex_ogni_token_di_confine_e_detrito(token: str) -> None:
    # token di confine di parola (\b): isolato è detrito.
    assert _e_detrito(f"Elenco {token} 2026") is True


def test_regex_token_dentro_parola_non_e_detrito() -> None:
    # \b evita i falsi positivi dentro parole legittime.
    assert _e_detrito("Detrazione IMU prima casa") is False  # "det" non isolato
    assert _e_detrito("Impegno civico del cittadino") is False  # "imp" non isolato


def test_titolo_servizio_pulito_non_e_detrito() -> None:
    for buono in (
        "Cambio di residenza",
        "Carta d'Identità Elettronica (CIE)",
        "Richiesta di accesso agli atti",
        "TARI - Tassa sui rifiuti",
        "Pagare l'IMU",
    ):
        assert _e_detrito(buono) is False, buono


# --------------------------------------------------------------------------- #
# (c) "registri" e "taxi": i 2 falsi positivi egregi restano esclusi.
# --------------------------------------------------------------------------- #
def test_registro_e_detrito_escluso() -> None:
    # Maddaloni: "Registro di accesso agli atti" = il registro/log, non il servizio.
    assert _e_detrito("Registro di accesso agli atti") is True


def _c(nid, title, cls):
    # url plausibile mono-sito OpenPA; lo schema conta per la validazione pydantic.
    return ServiceCandidate(
        native_id=str(nid),
        title=title,
        url=f"https://www.comune.esempio.it/x/{nid}",
        native_class=cls,
    )


def test_taxi_marcatore_negativo_su_anagrafe() -> None:
    """Verona: 'residenza taxi' (licenza taxi) NON deve confermare CAMBIO_RESIDENZA.
    Il marcatore negativo per-chiave lo rimuove prima del gate."""
    key = ServiceKey.CAMBIO_RESIDENZA
    cands = (
        _c(1, "Cambio di residenza", "public_service"),
        _c(2, "Procedure per cambio residenza taxi", "public_service"),
    )
    filtrati = _CONN._filtra_candidati(cands, key)
    titoli = {c.title for c in filtrati}
    assert "Procedure per cambio residenza taxi" not in titoli
    # e con il taxi rimosso resta un solo servizio anagrafico → confermabile.
    assert "Cambio di residenza" in titoli


def test_marcatori_negativi_registrati_sulle_chiavi_anagrafiche() -> None:
    # guardia: le chiavi con marcatore "taxi" sono esattamente quelle anagrafiche.
    assert set(_MARCATORI_NEGATIVI) == {
        ServiceKey.CAMBIO_RESIDENZA,
        ServiceKey.STATO_CIVILE,
        ServiceKey.ACCESSO_ATTI,
    }
    for chiave in _MARCATORI_NEGATIVI:
        assert "taxi" in _MARCATORI_NEGATIVI[chiave]


# --------------------------------------------------------------------------- #
# Short-circuit len(matched)<=1: un match solitario detrito NON va scartato.
# --------------------------------------------------------------------------- #
def test_match_solitario_non_scartato_anche_se_detrito() -> None:
    """Se il recogniser matcha UN SOLO candidato, quello passa comunque: il
    detrito/priorità agisce solo per disambiguare ≥2 match (protegge i 39)."""
    key = ServiceKey.TRIBUTI_IMU
    # un solo candidato IMU, per giunta document "istanza rimborso": deve restare.
    cands = (
        _c(1, "IMU istanza rimborso", "document"),
        _c(2, "Ufficio Protocollo", "public_service"),  # non matcha IMU
    )
    filtrati = _CONN._filtra_candidati(cands, key)
    conf = [c for c in filtrati if riconosci_service_key(c.title) is key]
    assert [c.native_id for c in conf] == ["1"]


# --------------------------------------------------------------------------- #
# (Layer A) Priorità classe: un solo public_service vince su document/output.
# --------------------------------------------------------------------------- #
def test_priorita_public_service_su_document_e_output() -> None:
    key = ServiceKey.TRIBUTI_TARI
    cands = (
        _c(1, "TARI - Tassa sui rifiuti", "public_service"),
        _c(2, "TARI modulo dichiarazione", "document"),
        _c(3, "TARI esito pratica", "output"),
    )
    filtrati = _CONN._filtra_candidati(cands, key)
    # tre match recogniser, nessuno detrito → vince l'unico public_service.
    assert [c.native_id for c in filtrati] == ["1"]


def test_debris_riduce_a_uno_prima_della_priorita() -> None:
    key = ServiceKey.TRIBUTI_IMU
    cands = (
        _c(1, "IMU - Imposta Municipale Propria", "public_service"),
        _c(2, "Regolamento IMU 2026", "document"),  # detrito → fuori
        _c(3, "Delibera aliquote IMU", "output"),  # detrito → fuori
    )
    filtrati = _CONN._filtra_candidati(cands, key)
    assert [c.native_id for c in filtrati] == ["1"]


def test_due_public_service_veri_restano_ambigui() -> None:
    """Se sopravvivono ≥2 public_service non-detrito, il filtro NON inventa un
    vincitore: il gate a valle darà NOT_FOUND (I-1)."""
    key = ServiceKey.CAMBIO_RESIDENZA
    cands = (
        _c(1, "Cambio di residenza", "public_service"),
        _c(2, "Cambio di residenza online", "public_service"),
    )
    filtrati = _CONN._filtra_candidati(cands, key)
    conf = [c for c in filtrati if riconosci_service_key(c.title) is key]
    assert len(conf) == 2  # ambiguo, non confermato


def test_classi_fuori_allow_list_scartate() -> None:
    """article/channel/online_contact_point non entrano mai nei candidati."""
    key = ServiceKey.STATO_CIVILE
    cands = (
        _c(1, "Certificato di stato civile", "public_service"),
        _c(2, "Notizia: nuovi orari stato civile", "article"),
        _c(3, "Contatta ufficio stato civile", "online_contact_point"),
    )
    filtrati = _CONN._filtra_candidati(cands, key)
    assert [c.native_id for c in filtrati] == ["1"]
