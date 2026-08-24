"""Step 2 dello sweep di catalogo servizi: run reale, ma net-free nei test.

Due matrici, zero rete e zero scritture fuori da `tmp_path`:

- **P1–P6** — il seam probe-mappa guardato (`mappa_connettore(..., esecutore=)`
  + `_LettoreEsecutore`), esercitato con un `EsecutoreFetch` finto che inietta
  le combinazioni `consentito`/`fetched` senza toccare la rete: cache hit senza
  rete, cache miss con probe guardata, host non autorizzato, budget esaurito,
  scrittura atomica della mappa, risoluzione solo dopo una mappa valida.
- **sweep** — sei simulazioni su `_esegui_service_catalog`/
  `_risolvi_comune_servizi` (cache hit, live, miss, probe fallita → senza_mappa,
  budget → blocco, ripresa da cache), più il gate del campione e la resilienza
  a un errore per-comune, con i seam iniettati via monkeypatch.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from treasureiq import mappa_connettore as mc
from treasureiq import sweep_worker
from treasureiq.catalog.fetch_runtime import EsitoFetch
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.mappa_connettore import (
    MAX_BYTES_PROBE,
    MappaConnettore,
    ProbeBudgetEsaurito,
    ProbeFallita,
)
from treasureiq.sonda_live import ComuneNoto

N_CHIAVI = len(tuple(ServiceKey))


# --------------------------------------------------------------------------- #
# Finti condivisi
# --------------------------------------------------------------------------- #


class FakeEsecutore:
    """`EsecutoreFetch` finto: mappa ogni url a un esito, net-free, e registra
    le chiamate con i loro kwargs (host_atteso/max_bytes/timeout).

    `esito` è "ok" (200 html), "muto" (interrogato ma nullo: host fuori atteso o
    non-200) o "budget" (politica ha rifiutato), oppure un callable(url)->str.
    """

    def __init__(self, esito):
        self._esito = esito
        self.chiamate: list[tuple[str, dict]] = []

    def esegui(self, url, **kwargs):
        self.chiamate.append((url, kwargs))
        stato = self._esito(url) if callable(self._esito) else self._esito
        if stato == "budget":
            return EsitoFetch(consentito=False, fetched=None, motivo="budget")
        if stato == "muto":
            return EsitoFetch(consentito=True, fetched=None, motivo="muto")
        headers = {"content-type": "text/html"}
        corpo = b"<html><body>ok</body></html>"
        return EsitoFetch(consentito=True, fetched=(headers, corpo, url), motivo="ok")


@pytest.fixture
def comune_finto(monkeypatch, tmp_path):
    """Un comune noto con sito, cache-mappa isolata in `tmp_path`."""
    monkeypatch.setattr(mc, "LIVE_DIR", tmp_path)
    comune = ComuneNoto(
        codice_istat="099999",
        nome="Comunetest",
        provincia="XX",
        regione="Test",
        sito="https://comune.test.it",
    )
    monkeypatch.setattr(mc, "comune_per_codice", lambda codice: comune)
    return comune, tmp_path


# --------------------------------------------------------------------------- #
# P1–P6: seam probe-mappa guardato
# --------------------------------------------------------------------------- #


def test_p1_cache_hit_senza_rete(comune_finto):
    """Cache-mappa calda → nessun fetch: l'executor non è mai chiamato."""
    comune, tmp = comune_finto
    percorso = tmp / "mappa-connettore" / f"{comune.codice_istat}.json"
    percorso.parent.mkdir(parents=True)
    voce = MappaConnettore(
        codice_istat=comune.codice_istat,
        nome=comune.nome,
        sito=comune.sito,
        sondato_il=datetime.now(timezone.utc).isoformat(),
    )
    percorso.write_text(voce.model_dump_json(), "utf-8")

    fake = FakeEsecutore("budget")  # se toccasse la rete, il run fallirebbe
    mappa = mc.mappa_connettore(comune.codice_istat, esecutore=fake)

    assert mappa is not None
    assert mappa.codice_istat == comune.codice_istat
    assert fake.chiamate == []  # executor mai chiamato: cache-first vero


def test_p2_cache_miss_probe_guardata(comune_finto):
    """Cache miss → probe live, ma ogni fetch passa dall'executor guardato."""
    comune, _tmp = comune_finto
    fake = FakeEsecutore("ok")
    mappa = mc.mappa_connettore(comune.codice_istat, esecutore=fake)

    assert mappa is not None
    assert mappa.sito == comune.sito
    assert not mappa.servizi.esposto  # nessuna superficie REST dal fake
    assert fake.chiamate, "la probe deve passare dall'executor guardato"
    _url, kwargs = fake.chiamate[0]
    assert kwargs["host_atteso"] == "comune.test.it"
    assert kwargs["max_bytes"] == MAX_BYTES_PROBE


def test_p3_host_non_autorizzato_miss_senza_mappa(comune_finto):
    """Home muta/host fuori atteso → `ProbeFallita`, nessuna mappa scritta."""
    comune, tmp = comune_finto
    fake = FakeEsecutore("muto")  # fetch_guardato ritorna None fuori host
    with pytest.raises(ProbeFallita):
        mc.mappa_connettore(comune.codice_istat, esecutore=fake)
    assert not (tmp / "mappa-connettore" / f"{comune.codice_istat}.json").exists()


def test_p4_budget_esaurito_miss_senza_mappa(comune_finto):
    """Budget dominio esaurito → `ProbeBudgetEsaurito`, nessuna mappa scritta."""
    comune, tmp = comune_finto
    fake = FakeEsecutore("budget")
    with pytest.raises(ProbeBudgetEsaurito):
        mc.mappa_connettore(comune.codice_istat, esecutore=fake)
    assert not (tmp / "mappa-connettore" / f"{comune.codice_istat}.json").exists()


def test_p5_scrittura_atomica_mappa(comune_finto):
    """Probe riuscita → mappa valida su disco, nessun `.tmp` residuo."""
    comune, tmp = comune_finto
    fake = FakeEsecutore("ok")
    mc.mappa_connettore(comune.codice_istat, esecutore=fake)

    dir_mappa = tmp / "mappa-connettore"
    percorso = dir_mappa / f"{comune.codice_istat}.json"
    assert percorso.exists()
    MappaConnettore.model_validate_json(percorso.read_text("utf-8"))
    assert list(dir_mappa.glob("*.tmp")) == []  # la replace atomica ha ripulito


def test_p6_risoluzione_solo_dopo_mappa_valida(monkeypatch):
    """`_esito_chiave`: mappa `None` → nessuna risoluzione tentata."""
    chiamate: list[tuple] = []

    def fake_resolve(*a, **k):
        chiamate.append((a, k))
        return SimpleNamespace(from_cache=True)

    monkeypatch.setattr(sweep_worker, "resolve_service_with_meta", fake_resolve)
    fresh = sweep_worker.FreshnessPolicy(max_age_seconds=86400)

    esito = sweep_worker._esito_chiave(
        ServiceKey.CARTA_IDENTITA, "099999", None, "wordpress_agid", object(), fresh
    )
    assert esito == "senza_mappa"
    assert chiamate == []  # senza mappa non si risolve

    esito = sweep_worker._esito_chiave(
        ServiceKey.CARTA_IDENTITA, "099999", object(), "wordpress_agid", object(), fresh
    )
    assert esito == "da_cache"
    assert len(chiamate) == 1  # con mappa valida, risoluzione tentata


# --------------------------------------------------------------------------- #
# Simulazioni sweep: _esegui_service_catalog / _risolvi_comune_servizi
# --------------------------------------------------------------------------- #


@pytest.fixture
def sweep_env(monkeypatch, tmp_path):
    """Seam sweep iniettati: metriche in `tmp_path`, registry/executor finti."""
    monkeypatch.setattr(sweep_worker, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(
        sweep_worker, "leggi_registro",
        lambda codice: SimpleNamespace(piattaforma="wordpress_agid"),
    )
    monkeypatch.setattr(sweep_worker, "default_service_registry", lambda esecutore: object())
    monkeypatch.setattr(sweep_worker, "_nuovo_esecutore", lambda config: object())
    return tmp_path


def _config(tmp_path):
    return sweep_worker.WorkerConfig(
        db=tmp_path / "storico.db", mode="service_catalog", dry_run=False, execute=True
    )


def _metriche(tmp_path):
    percorso = tmp_path / "service-catalog-metriche" / "ultimo.json"
    return json.loads(percorso.read_text("utf-8"))


def test_sweep_lotto_fuori_campione_rifiutato(sweep_env):
    """Difesa in profondità: un lotto non ⊆ campione pinnato è rifiutato."""
    exit_code = sweep_worker.run_batch(_config(sweep_env), ["999999"])
    assert exit_code == sweep_worker.EXIT_SERVICE_REAL_NOT_READY


def test_sweep_cache_hit(sweep_env, monkeypatch):
    """Mappa da cache → nessuna probe live; chiavi tutte `da_cache`."""
    monkeypatch.setattr(sweep_worker, "_mappa_da_cache", lambda codice: object())

    def boom(*a, **k):
        raise AssertionError("probe live non deve partire su cache hit")

    monkeypatch.setattr(sweep_worker, "mappa_connettore", boom)
    monkeypatch.setattr(
        sweep_worker, "resolve_service_with_meta",
        lambda *a, **k: SimpleNamespace(from_cache=True),
    )

    exit_code = sweep_worker.run_batch(_config(sweep_env), ["001001"])
    assert exit_code == 0
    m = _metriche(sweep_env)
    assert m["probe"]["comuni_da_cache_mappa"] == 1
    assert m["probe"]["comuni_probati_live"] == 0
    assert m["esito_chiavi"]["da_cache"] == N_CHIAVI
    assert m["comuni_completati"] == 1


def test_sweep_live_success(sweep_env, monkeypatch):
    """Cache miss → probe live riuscita; chiavi tutte `risolto_live`."""
    monkeypatch.setattr(sweep_worker, "_mappa_da_cache", lambda codice: None)
    monkeypatch.setattr(
        sweep_worker, "mappa_connettore", lambda codice, esecutore=None: object()
    )
    monkeypatch.setattr(
        sweep_worker, "resolve_service_with_meta",
        lambda *a, **k: SimpleNamespace(from_cache=False),
    )

    exit_code = sweep_worker.run_batch(_config(sweep_env), ["001001"])
    assert exit_code == 0
    m = _metriche(sweep_env)
    assert m["probe"]["comuni_probati_live"] == 1
    assert m["probe"]["comuni_da_cache_mappa"] == 0
    assert m["probe"]["probe_fallite"] == 0
    assert m["esito_chiavi"]["risolto_live"] == N_CHIAVI


def test_sweep_miss(sweep_env, monkeypatch):
    """Mappa valida ma servizio non risolvibile → `miss` onesto, no crash."""
    monkeypatch.setattr(sweep_worker, "_mappa_da_cache", lambda codice: object())
    monkeypatch.setattr(sweep_worker, "resolve_service_with_meta", lambda *a, **k: None)

    exit_code = sweep_worker.run_batch(_config(sweep_env), ["001001"])
    assert exit_code == 0
    m = _metriche(sweep_env)
    assert m["esito_chiavi"]["miss"] == N_CHIAVI


def test_sweep_probe_fallita_senza_mappa(sweep_env, monkeypatch):
    """Probe fallita → `senza_mappa` per tutte le chiavi, nessuna risoluzione."""
    monkeypatch.setattr(sweep_worker, "_mappa_da_cache", lambda codice: None)

    def probe_fallita(codice, esecutore=None):
        raise ProbeFallita(codice)

    monkeypatch.setattr(sweep_worker, "mappa_connettore", probe_fallita)

    def boom_resolve(*a, **k):
        raise AssertionError("nessuna risoluzione senza mappa valida")

    monkeypatch.setattr(sweep_worker, "resolve_service_with_meta", boom_resolve)

    exit_code = sweep_worker.run_batch(_config(sweep_env), ["001001"])
    assert exit_code == 0
    m = _metriche(sweep_env)
    assert m["probe"]["probe_fallite"] == 1
    assert m["probe"]["comuni_probati_live"] == 1
    assert m["esito_chiavi"]["senza_mappa"] == N_CHIAVI


def test_sweep_budget_blocca_run(sweep_env, monkeypatch):
    """Budget esaurito sulla probe → run fermato, nessuna risoluzione speculativa."""
    monkeypatch.setattr(sweep_worker, "_mappa_da_cache", lambda codice: None)

    def budget(codice, esecutore=None):
        raise ProbeBudgetEsaurito(codice)

    monkeypatch.setattr(sweep_worker, "mappa_connettore", budget)

    exit_code = sweep_worker.run_batch(_config(sweep_env), ["001001", "002007"])
    assert exit_code == sweep_worker.EXIT_SERVICE_BUDGET_BLOCKED
    m = _metriche(sweep_env)
    assert m["budget_esaurito"] is True
    assert m["comuni_completati"] == 0  # il comune bloccato non conta come fatto
    esiti = [r.get("esito_comune") for r in m["per_comune"]]
    assert esiti == ["budget_bloccato"]  # secondo comune mai toccato


def test_sweep_ripresa_da_cache(sweep_env, monkeypatch):
    """Interruzione a metà lotto (budget) → ripresa completa dalla cache-mappa."""
    lotto = ["001001", "002007"]
    stato = {"cache": {}}

    def cache_peek(codice):
        return stato["cache"].get(codice)

    monkeypatch.setattr(sweep_worker, "_mappa_da_cache", cache_peek)

    def probe(codice, esecutore=None):
        if codice == "002007":
            raise ProbeBudgetEsaurito(codice)
        stato["cache"][codice] = object()  # la probe scalda la cache
        return stato["cache"][codice]

    monkeypatch.setattr(sweep_worker, "mappa_connettore", probe)
    monkeypatch.setattr(
        sweep_worker, "resolve_service_with_meta",
        lambda *a, **k: SimpleNamespace(from_cache=False),
    )

    # Primo giro: 001001 live ok, 002007 budget → run fermato.
    exit_code = sweep_worker.run_batch(_config(sweep_env), lotto)
    assert exit_code == sweep_worker.EXIT_SERVICE_BUDGET_BLOCKED
    assert _metriche(sweep_env)["comuni_completati"] == 1

    # Ripresa: cache calda per 001001, budget ora concede 002007.
    stato["cache"]["002007"] = object()
    monkeypatch.setattr(
        sweep_worker, "resolve_service_with_meta",
        lambda *a, **k: SimpleNamespace(from_cache=True),
    )
    exit_code = sweep_worker.run_batch(_config(sweep_env), lotto)
    assert exit_code == 0
    m = _metriche(sweep_env)
    assert m["comuni_completati"] == 2
    assert m["probe"]["comuni_da_cache_mappa"] == 2  # nessuna riprobatura
    assert m["probe"]["comuni_probati_live"] == 0


def test_sweep_errore_non_blocca_lotto(sweep_env, monkeypatch):
    """Un errore per-comune conta come errore ma non ferma il lotto."""
    monkeypatch.setattr(sweep_worker, "_mappa_da_cache", lambda codice: object())

    def resolve(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(sweep_worker, "resolve_service_with_meta", resolve)

    exit_code = sweep_worker.run_batch(_config(sweep_env), ["001001", "002007"])
    assert exit_code == sweep_worker.EXIT_SERVICE_PARTIAL_ERRORS
    m = _metriche(sweep_env)
    assert m["esito_comuni"]["errore"] == 2
    assert m["comuni_completati"] == 2
