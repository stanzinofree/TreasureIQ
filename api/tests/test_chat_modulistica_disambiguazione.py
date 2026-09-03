"""Ramo 3 — chat wiring dei rami DISAMBIGUATION e SELEZIONE (contratto ≥2).

Fissa il comportamento della chat quando il resolver ritorna una
``DisambiguazioneServizi`` (≥2 confermati, contratto universale) e il turno di
selezione successivo. Net-free: i due seam del handler — la mappa in cache e il
resolver/selettore — sono stubbati a livello di modulo.

Invarianti:
  * ≥2 → ``ChatAnswer.servizi_ambigui`` con voci raggruppate per intento,
    ``needs_clarification=True``, ``data_gap="servizio_ambiguo"``, nessuna
    scheda risolta (``info is None``): si espone la scelta, non si elegge;
  * il testo di ``reply`` è FISSO (D-07): titoli/URL solo nei campi strutturati;
  * selezione di un ``service_id`` noto → scheda risolta (helper fulfilled),
    ``seleziona_servizio`` chiamato con quell'id opaco;
  * selezione di un ``service_id`` ignoto → resolver torna ``None`` → miss URP.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from treasureiq.catalog.contracts import ConnectorRef
from treasureiq.catalog.service_contracts import (
    DisambiguazioneServizi,
    ResolvedService,
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceKey,
    ServiceReference,
)
from treasureiq.chat import respond
from treasureiq.chat.respond import (
    ServizioScelto,
    _modulistica_selezione,
    _risposta_modulistica,
)
from treasureiq.mappa_connettore import MappaConnettore

ISTAT = "022018"  # Bocenago (OpenPA-Trentino, famiglia IMIS)
WHEN = datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc)
BASE_URL = "https://www.comune.bocenago.tn.it"
CONN = ConnectorRef(name="openpa_service", version="1")


def _mappa(*, piattaforma_id: str | None = "openpa") -> MappaConnettore:
    return MappaConnettore(
        codice_istat=ISTAT,
        nome="Bocenago",
        sito=BASE_URL,
        sondato_il="2026-09-02T09:00:00+00:00",
        piattaforma_id=piattaforma_id,
    )


def _ref(service_id: str, title: str) -> ServiceReference:
    """Reference LEGGERA (solo INFORMATION), come le emette il ramo ≥2."""
    url = f"{BASE_URL}/servizi/{service_id.split(':')[-1]}"
    return ServiceReference(
        service_id=service_id,
        title=title,
        source_url=url,
        options=(
            ServiceAccessOption(
                mode=ServiceAccessMode.INFORMATION, url=url, source_url=url
            ),
        ),
        provider_platform="openpa",
        discovered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


# Tre servizi IMIS distinti, come sul dato reale di Bocenago (calcolatore,
# domanda di agevolazione, pagina informativa dei valori aree).
_REF_CALC = _ref(f"{ISTAT}:openpa:869", "Calcolatore IMIS")
_REF_AGEV = _ref(f"{ISTAT}:openpa:417", "Domanda di agevolazione tributaria (IMIS)")
_REF_INFO = _ref(f"{ISTAT}:openpa:414", "IMIS Valori aree fabbricabili 2019")


def _disambiguazione() -> DisambiguazioneServizi:
    return DisambiguazioneServizi(
        references=(_REF_CALC, _REF_AGEV, _REF_INFO),
        retrieved_at=WHEN,
        connector=CONN,
    )


def _resolved(reference: ServiceReference) -> ResolvedService:
    return ResolvedService(
        reference=reference, retrieved_at=WHEN, from_cache=False, connector=CONN
    )


@pytest.fixture
def mappa_in_cache(monkeypatch):
    stato = {"mappa": _mappa()}
    monkeypatch.setattr(
        "treasureiq.mappa_connettore._da_cache", lambda _istat: stato["mappa"]
    )
    return stato


def _run(coro):
    return asyncio.run(coro)


# -- ramo ≥2 → ServiziAmbigui -----------------------------------------------


def test_ge2_espone_scelta_raggruppata(monkeypatch, mappa_in_cache):
    monkeypatch.setattr(
        respond, "risolvi_o_disambigua", lambda request, **kw: _disambiguazione()
    )
    ans = _run(
        _risposta_modulistica(
            message="come pago l'IMU", profile=None, comune_istat=ISTAT
        )
    )
    assert ans.servizi_ambigui is not None
    assert ans.needs_clarification is True
    assert ans.data_gap == "servizio_ambiguo"
    assert ans.info is None  # nessuna scheda risolta: si sceglie, non si elegge
    sa = ans.servizi_ambigui
    assert sa.service_key == ServiceKey.TRIBUTI_IMU.value

    # Ogni reference compare una volta sola, nessuna persa.
    ids = {v.service_id for g in sa.gruppi for v in g.voci}
    assert ids == {_REF_CALC.service_id, _REF_AGEV.service_id, _REF_INFO.service_id}

    # Raggruppate per intento, in ordine d'enum: CALCOLATORE prima di
    # AGEVOLAZIONE prima di ALTRO_INFORMAZIONI.
    intenti = [g.intento for g in sa.gruppi]
    assert intenti == ["calcolatore", "agevolazione", "altro_informazioni"]
    # Ogni gruppo ha un'etichetta umana non vuota.
    assert all(g.etichetta for g in sa.gruppi)


def test_ge2_reply_fisso_niente_titoli_in_prosa(monkeypatch, mappa_in_cache):
    monkeypatch.setattr(
        respond, "risolvi_o_disambigua", lambda request, **kw: _disambiguazione()
    )
    ans = _run(
        _risposta_modulistica(
            message="come pago l'IMU", profile=None, comune_istat=ISTAT
        )
    )
    # D-07: titoli e URL viaggiano nei campi strutturati, mai interpolati.
    assert "Calcolatore" not in ans.reply
    assert "http" not in ans.reply
    assert "Bocenago" in ans.reply  # il solo nome comune è ammesso


# -- turno di selezione ------------------------------------------------------


def test_selezione_id_noto_risolve_scheda(monkeypatch, mappa_in_cache):
    visti = {}

    def _seleziona(request, *, mappa, service_id, **kw):
        visti["service_id"] = service_id
        visti["service_key"] = request.selection.get("service_key")
        return _resolved(_REF_CALC)

    monkeypatch.setattr(respond, "seleziona_servizio", _seleziona)
    scelta = ServizioScelto(
        service_id=_REF_CALC.service_id, service_key=ServiceKey.TRIBUTI_IMU.value
    )
    ans = _run(
        _modulistica_selezione(
            servizio_scelto=scelta, target_istat=ISTAT, nominato=None
        )
    )
    # Scheda risolta dal ramo fulfilled condiviso.
    assert ans.info is not None
    assert ans.info.service is not None
    assert ans.needs_clarification is False
    assert ans.servizi_ambigui is None
    # L'id opaco e la chiave del turno arrivano intatti al selettore.
    assert visti["service_id"] == _REF_CALC.service_id
    assert visti["service_key"] == ServiceKey.TRIBUTI_IMU.value


def test_selezione_id_ignoto_miss_urp(monkeypatch, mappa_in_cache):
    # Il selettore rifiuta un id fuori dall'insieme del turno → None → miss URP.
    monkeypatch.setattr(
        respond, "seleziona_servizio", lambda request, **kw: None
    )
    scelta = ServizioScelto(
        service_id="022018:openpa:99999", service_key=ServiceKey.TRIBUTI_IMU.value
    )
    ans = _run(
        _modulistica_selezione(
            servizio_scelto=scelta, target_istat=ISTAT, nominato=None
        )
    )
    assert ans.info is None
    assert ans.servizi_ambigui is None
    assert ans.data_gap == "not_verified"  # miss onesto URP
    assert "URP" in ans.reply


def test_selezione_service_key_malformata_miss_urp(monkeypatch, mappa_in_cache):
    # Una chiave fuori vocabolario (echo corrotto) è malformata: miss onesto,
    # mai il vicino — e il selettore non viene nemmeno chiamato.
    chiamato = {"n": 0}

    def _seleziona(request, **kw):
        chiamato["n"] += 1
        return _resolved(_REF_CALC)

    monkeypatch.setattr(respond, "seleziona_servizio", _seleziona)
    scelta = ServizioScelto(
        service_id=_REF_CALC.service_id, service_key="non_esiste"
    )
    ans = _run(
        _modulistica_selezione(
            servizio_scelto=scelta, target_istat=ISTAT, nominato=None
        )
    )
    assert ans.data_gap == "not_verified"
    assert chiamato["n"] == 0


def test_selezione_mappa_assente_miss_urp(monkeypatch):
    # Senza mappa in cache per il comune: miss onesto URP, nessun fetch.
    monkeypatch.setattr(
        "treasureiq.mappa_connettore._da_cache", lambda _istat: None
    )
    chiamato = {"n": 0}
    monkeypatch.setattr(
        respond,
        "seleziona_servizio",
        lambda *a, **kw: chiamato.__setitem__("n", chiamato["n"] + 1),
    )
    scelta = ServizioScelto(
        service_id=_REF_CALC.service_id, service_key=ServiceKey.TRIBUTI_IMU.value
    )
    ans = _run(
        _modulistica_selezione(
            servizio_scelto=scelta, target_istat=ISTAT, nominato=None
        )
    )
    assert ans.data_gap == "not_verified"
    assert chiamato["n"] == 0
