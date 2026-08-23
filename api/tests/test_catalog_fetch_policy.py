"""Fase 2D-ii — politica di fetch: backoff, rate-limit, budget per dominio.

Decisioni pure su un `now` iniettato: si testa il *quanto aspettare* e il
*quando rifiutare* senza dormire.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from treasureiq.catalog.fetch_policy import (
    BudgetDominio,
    LimitatoreDominio,
    PoliticaFetch,
    backoff_secondi,
    dominio_di,
)

_T0 = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)


# --- dominio_di: chiave di dominio normalizzata ---

def test_dominio_normalizza_www_porta_e_case():
    assert dominio_di("https://WWW.Comune.It:8443/x") == "comune.it"
    assert dominio_di("https://comune.it/y") == "comune.it"
    assert dominio_di("https://user@comune.it/z") == "comune.it"


def test_www_e_non_www_stesso_dominio_nel_budget():
    b = BudgetDominio(massimo=1)
    b.consuma("https://www.comune.it/a")
    # Stesso host senza www: budget già esaurito, non un secondo conteggio.
    assert b.disponibile("https://comune.it/b") is False


# --- backoff esponenziale ---

def test_backoff_zero_fallimenti_zero_attesa():
    assert backoff_secondi(0) == 0.0


def test_backoff_cresce_e_si_ferma_al_cap():
    assert backoff_secondi(1, base=60, fattore=2, cap=3600) == 60
    assert backoff_secondi(2, base=60, fattore=2, cap=3600) == 120
    assert backoff_secondi(3, base=60, fattore=2, cap=3600) == 240
    # Oltre il cap resta al cap.
    assert backoff_secondi(20, base=60, fattore=2, cap=3600) == 3600


# --- rate-limit per dominio ---

def test_limitatore_primo_colpo_senza_attesa():
    lim = LimitatoreDominio(intervallo_minimo_s=1.0)
    assert lim.attesa("https://comune.it/a", _T0) == 0.0


def test_limitatore_impone_intervallo():
    lim = LimitatoreDominio(intervallo_minimo_s=2.0)
    lim.registra("https://comune.it/a", _T0)
    # 0.5s dopo: deve aspettare i 1.5s residui.
    attesa = lim.attesa("https://comune.it/b", _T0 + timedelta(seconds=0.5))
    assert attesa == 1.5
    # Passato l'intervallo: niente attesa.
    assert lim.attesa("https://comune.it/c", _T0 + timedelta(seconds=2)) == 0.0


def test_limitatore_domini_diversi_indipendenti():
    lim = LimitatoreDominio(intervallo_minimo_s=5.0)
    lim.registra("https://comune-a.it/x", _T0)
    # Un altro dominio non è vincolato dal primo.
    assert lim.attesa("https://comune-b.it/y", _T0) == 0.0


# --- budget per dominio ---

def test_budget_esaurisce_e_rimanente():
    b = BudgetDominio(massimo=2)
    assert b.rimanente("https://comune.it/a") == 2
    b.consuma("https://comune.it/a")
    b.consuma("https://comune.it/b")
    assert b.disponibile("https://comune.it/c") is False
    assert b.rimanente("https://comune.it/c") == 0


# --- budget a finestra scorrevole (Slice 5, D-S5-9) ---


def test_budget_finestra_reset_dopo_scadenza():
    # Un budget di processo senza reset resterebbe bloccato per sempre; con la
    # finestra il conteggio del dominio si azzera trascorsi finestra_s secondi.
    b = BudgetDominio(massimo=2, finestra_s=100.0)
    url = "https://comune.it/a"
    b.consuma(url, _T0)
    b.consuma(url, _T0)
    assert b.disponibile(url, _T0) is False
    # Dentro la finestra: ancora esaurito.
    assert b.disponibile(url, _T0 + timedelta(seconds=50)) is False
    # Scaduta la finestra: budget di NUOVO disponibile per quel dominio.
    assert b.disponibile(url, _T0 + timedelta(seconds=100)) is True
    assert b.rimanente(url, _T0 + timedelta(seconds=100)) == 2


def test_budget_finestra_per_dominio_isolata():
    b = BudgetDominio(massimo=1, finestra_s=100.0)
    b.consuma("https://a.it/x", _T0)
    # Il reset del dominio A non tocca il dominio B (finestra per-dominio).
    assert b.disponibile("https://b.it/y", _T0) is True
    # A torna disponibile solo alla sua scadenza.
    assert b.disponibile("https://a.it/z", _T0 + timedelta(seconds=100)) is True


def test_budget_senza_finestra_non_resetta_mai():
    # finestra_s=None mantiene la semantica per-passata dello sweep: nessun reset,
    # anche passando un now molto avanti.
    b = BudgetDominio(massimo=1)
    b.consuma("https://comune.it/a", _T0)
    assert b.disponibile("https://comune.it/b", _T0 + timedelta(days=365)) is False


def test_budget_finestra_deve_essere_positiva():
    for cattiva in (0.0, -1.0):
        try:
            BudgetDominio(massimo=1, finestra_s=cattiva)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("finestra <= 0 deve sollevare")


def test_budget_minimo_uno():
    try:
        BudgetDominio(massimo=0)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("budget 0 deve sollevare")


# --- PoliticaFetch: la decisione fusa ---

def test_politica_budget_esaurito_rifiuta():
    p = PoliticaFetch(massimo_per_dominio=1, intervallo_minimo_s=1.0)
    p.registra("https://comune.it/a", _T0)
    d = p.decidi("https://comune.it/b", _T0 + timedelta(seconds=10))
    assert d.consentito is False
    assert d.motivo == "budget_esaurito"


def test_politica_attesa_e_il_massimo_fra_ratelimit_e_backoff():
    p = PoliticaFetch(
        massimo_per_dominio=50, intervallo_minimo_s=2.0,
        backoff_base_s=60.0, backoff_cap_s=3600.0,
    )
    p.registra("https://comune.it/a", _T0)
    # Subito dopo: rate-limit vuole 2s, ma 1 fallimento vuole 60s → vince 60.
    d = p.decidi(
        "https://comune.it/b", _T0 + timedelta(seconds=0.1),
        fallimenti_consecutivi=1,
    )
    assert d.consentito is True
    assert d.attesa_s == 60.0


def test_politica_senza_vincoli_consente_subito():
    p = PoliticaFetch(massimo_per_dominio=50, intervallo_minimo_s=1.0)
    d = p.decidi("https://comune.it/a", _T0)
    assert d.consentito is True
    assert d.attesa_s == 0.0
    assert d.motivo == "ok"
