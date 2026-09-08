"""Golden tests per il facet-variante (Ramo 3, MVP TARI). Net-free.

Il facet-variante è un SECONDO asse resolve-time, ortogonale alla ServiceKey e
COMPONIBILE col facet-azione, al medesimo punto comune (``connettore_base.retrieve``).
Motivazione reale (corpus Sportello): la TARI si sdoppia in ``utenze.domestiche``
(casa) e ``utenze.non.domestiche`` (attività), *entrambe* con la stessa azione
(``dichiarazione``) — quindi il facet-azione da solo lascia ≥2 → NOT_FOUND, ed è
la variante a restringere la coppia a esattamente-uno.

Copre: recogniser (citizen text→variante) exactly-one-or-None e topic-scoped;
matcher candidato (title/slug→variante) con overlap ``non.domestiche``⊃``domestiche``
gestito, esclusione HARD di ``;domanda``, url-encoding; no-op fuori perimetro; e
l'integrazione end-to-end sul connettore Sportello con due schede TARI reali.

Non indebolisce mai I-1: 0 o ≥2 dopo il facet = NOT_FOUND onesto, nessun
fallback. Nessuna inferenza: un turno senza variante esplicita resta None → il
facet è inerte → gate storico.
"""

from __future__ import annotations

import pytest

from tests.test_sportello_service_connector import (
    _CODOGNO,
    _CODOGNO_HOST,
    _FetcherSportello,
    _mappa,
    _u,
)
from treasureiq.catalog.contracts import CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import DataRequest, DataStatus, FreshnessPolicy
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.facet_variante import (
    filtra_per_variante,
    variante_del_candidato,
)
from treasureiq.catalog.service_connectors.sportello_service import (
    SportelloServiceConnector,
)
from treasureiq.catalog.service_contracts import (
    AzioneServizio,
    ServiceKey,
    VarianteServizio,
)
from treasureiq.chat.service_key import riconosci_variante


# ── recogniser: citizen text → variante (TARI), exactly-one-or-None ──────────


@pytest.mark.parametrize(
    "message, atteso",
    [
        ("dichiarazione TARI per la mia abitazione", VarianteServizio.DOMESTICHE),
        ("tassa rifiuti di casa mia", VarianteServizio.DOMESTICHE),
        ("tari nuova casa dove abito", VarianteServizio.DOMESTICHE),
        ("dichiarazione rifiuti appartamento", VarianteServizio.DOMESTICHE),
        ("tassa rifiuti utenza domestica", VarianteServizio.DOMESTICHE),
        ("tari nucleo familiare", VarianteServizio.DOMESTICHE),
        ("tari per il mio negozio", VarianteServizio.NON_DOMESTICHE),
        ("tassa rifiuti della mia attività", VarianteServizio.NON_DOMESTICHE),
        ("tari azienda", VarianteServizio.NON_DOMESTICHE),
        ("tari utenza non domestica", VarianteServizio.NON_DOMESTICHE),
        ("dichiarazione rifiuti bar", VarianteServizio.NON_DOMESTICHE),
        ("tari partita iva", VarianteServizio.NON_DOMESTICHE),
        ("tari locale commerciale", VarianteServizio.NON_DOMESTICHE),
        # accenti: "attività"/"società" folded per matchare il lessico accent-free
        ("tari per la società", VarianteServizio.NON_DOMESTICHE),
    ],
)
def test_riconosce_variante_tari_singola(message, atteso):
    assert riconosci_variante(message, ServiceKey.TRIBUTI_TARI) is atteso


@pytest.mark.parametrize(
    "message",
    [
        "dichiarazione TARI",  # nessun marker variante → turno senza variante
        "devo pagare la tassa rifiuti",
        "informazioni tari",
        "",
        # ambiguo: casa + attività (home-business) → entrambe le famiglie sparano
        # → None (mai la più vicina); il gate ≥2 decide, il facet non restringe.
        "ho aperto un'attività in casa mia",
        "lavoro da casa con partita iva",
        "studio professionale nella mia abitazione",
        "negozio di famiglia",
        "bed and breakfast in casa",
    ],
)
def test_variante_none_quando_assente_o_ambigua(message):
    assert riconosci_variante(message, ServiceKey.TRIBUTI_TARI) is None


def test_non_domestica_non_conta_come_domestica():
    # Overlap lessicale: "non domestica" contiene "domestica". La negazione
    # sopprime la famiglia domestiche → resta solo non.domestiche (mai ambiguo).
    assert (
        riconosci_variante("tari utenza non domestica", ServiceKey.TRIBUTI_TARI)
        is VarianteServizio.NON_DOMESTICHE
    )


@pytest.mark.parametrize(
    "service_key",
    [ServiceKey.TRIBUTI_IMU, ServiceKey.CAMBIO_RESIDENZA, ServiceKey.CARTA_IDENTITA],
)
def test_variante_topic_scoped_none_fuori_tari(service_key):
    # Il lessico è topic-scoped: una key senza vocabolario variante non riconosce
    # nulla, anche se il testo contiene parole "casa"/"negozio" (MVP TARI-only).
    assert riconosci_variante("per la mia casa e il mio negozio", service_key) is None


# ── matcher candidato: title/slug → variante ────────────────────────────────


def _cand(native_id: str, title: str) -> ServiceCandidate:
    return ServiceCandidate(
        native_id=native_id,
        title=title,
        url="https://sportellotelematico.example.it/x",
    )


def test_candidato_domestiche_da_slug():
    c = _cand("s_italia:tassa.rifiuti;utenze.domestiche;dichiarazione", "Dichiarazione TARI domestiche")
    assert variante_del_candidato(c, ServiceKey.TRIBUTI_TARI) is VarianteServizio.DOMESTICHE


def test_candidato_non_domestiche_da_slug():
    c = _cand(
        "s_italia:tassa.rifiuti;utenze.non.domestiche;dichiarazione",
        "Dichiarazione TARI utenze non domestiche",
    )
    assert (
        variante_del_candidato(c, ServiceKey.TRIBUTI_TARI)
        is VarianteServizio.NON_DOMESTICHE
    )


def test_candidato_overlap_non_domestiche_non_e_ambiguo():
    # Il candidato non.domestiche contiene la substring "domestiche": l'anti-marker
    # impedisce il doppio-match → esattamente NON_DOMESTICHE, non None.
    c = _cand("s_italia:tassa.rifiuti;utenze.non.domestiche", "TARI non domestiche")
    assert (
        variante_del_candidato(c, ServiceKey.TRIBUTI_TARI)
        is VarianteServizio.NON_DOMESTICHE
    )


def test_candidato_senza_marker_e_variantless():
    c = _cand("s_italia:tassa.rifiuti;dichiarazione", "Dichiarazione TARI")
    assert variante_del_candidato(c, ServiceKey.TRIBUTI_TARI) is None


def test_candidato_key_non_scoped_none():
    # IMU non ha vocabolario variante → sempre None (no-op), anche con uno slug che
    # per assurdo portasse "domestiche".
    c = _cand("s_italia:imposta.municipale.unica;utenze.domestiche", "IMU")
    assert variante_del_candidato(c, ServiceKey.TRIBUTI_IMU) is None


def test_domanda_esclusa_hard():
    # ``;domanda`` è un launcher di modulo: il segmento dopo il marker è tagliato
    # prima dello scan → una variante che vi comparisse non trapela.
    c = _cand("s_italia:tassa.rifiuti;domanda;utenze.domestiche", "Istanza TARI online")
    assert variante_del_candidato(c, ServiceKey.TRIBUTI_TARI) is None


def test_slug_url_encoded_decodificato():
    c = _cand(
        "s_italia%3Atassa.rifiuti%3Butenze.non.domestiche%3Bdichiarazione",
        "TARI non domestiche",
    )
    assert (
        variante_del_candidato(c, ServiceKey.TRIBUTI_TARI)
        is VarianteServizio.NON_DOMESTICHE
    )


# ── filtra_per_variante: no-op fuori perimetro, restringe dentro ────────────


def _due_tari() -> tuple[ServiceCandidate, ...]:
    return (
        _cand("s_italia:tassa.rifiuti;utenze.domestiche;dichiarazione", "TARI domestiche"),
        _cand("s_italia:tassa.rifiuti;utenze.non.domestiche;dichiarazione", "TARI non domestiche"),
    )


def test_filtra_noop_senza_variante():
    due = _due_tari()
    assert filtra_per_variante(due, ServiceKey.TRIBUTI_TARI, None) == due


def test_filtra_noop_key_non_scoped():
    # IMU non è variant-scoped: nessun restringimento anche con variante presente.
    due = _due_tari()
    assert (
        filtra_per_variante(due, ServiceKey.TRIBUTI_IMU, VarianteServizio.DOMESTICHE)
        == due
    )


def test_filtra_restringe_a_uno():
    due = _due_tari()
    (solo,) = filtra_per_variante(
        due, ServiceKey.TRIBUTI_TARI, VarianteServizio.DOMESTICHE
    )
    assert "utenze.domestiche" in solo.native_id
    assert "non.domestiche" not in solo.native_id


def test_filtra_zero_survivor_senza_match():
    solo_dom = (
        _cand("s_italia:tassa.rifiuti;utenze.domestiche;dichiarazione", "TARI domestiche"),
    )
    assert (
        filtra_per_variante(
            solo_dom, ServiceKey.TRIBUTI_TARI, VarianteServizio.NON_DOMESTICHE
        )
        == ()
    )


# ── integrazione end-to-end sul connettore Sportello ────────────────────────

# Due schede TARI nazionali (domestiche + non.domestiche), stessa azione
# dichiarazione, motore Globo. Costruite inline (net-free): slug-token
# `tassa.rifiuti` per il pre-filtro, titolo che il recogniser conferma come TARI.
_CO_TARI_DOM = "/procedure%3As_italia%3Atassa.rifiuti%3Butenze.domestiche%3Bdichiarazione"
_CO_TARI_NON = "/procedure%3As_italia%3Atassa.rifiuti%3Butenze.non.domestiche%3Bdichiarazione"


def _pagina_tari(titolo: str) -> str:
    return (
        f"<!DOCTYPE html><html lang='it'><head>"
        f"<title>{titolo} | Comune di Codogno</title></head><body></body></html>"
    )


def _pagine_codogno_tari_utenze() -> dict[str, str]:
    sitemap = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        f"<url><loc>{_u(_CODOGNO_HOST, _CO_TARI_DOM)}</loc></url>"
        f"<url><loc>{_u(_CODOGNO_HOST, _CO_TARI_NON)}</loc></url>"
        "</urlset>"
    )
    return {
        _u(_CODOGNO_HOST, "/sitemap.xml"): sitemap,
        _u(_CODOGNO_HOST, _CO_TARI_DOM): _pagina_tari("Dichiarazione TARI utenze domestiche"),
        _u(_CODOGNO_HOST, _CO_TARI_NON): _pagina_tari("Dichiarazione TARI utenze non domestiche"),
    }


def _request_tari(
    *, variante: VarianteServizio | None, azione: AzioneServizio | None = None
) -> DataRequest:
    selection: dict[str, object] = {"service_key": ServiceKey.TRIBUTI_TARI.value}
    if azione is not None:
        selection["azione"] = azione.value
    if variante is not None:
        selection["variante"] = variante.value
    return DataRequest(
        request_id=f"t:{_CODOGNO}:variante-tari",
        source_id=_CODOGNO,
        surface=Surface.ORDINARY_DATA,
        capability=CAPABILITY_SERVICES,
        selection=selection,
        freshness=FreshnessPolicy(max_age_seconds=86_400),
        manifest_revision=1,
    )


def _risolvi_tari(
    *, variante: VarianteServizio | None, azione: AzioneServizio | None = None
):
    fetcher = _FetcherSportello(_pagine_codogno_tari_utenze())
    conn = SportelloServiceConnector(fetcher)
    return conn.retrieve(
        _request_tari(variante=variante, azione=azione),
        mappa=_mappa(istat=_CODOGNO, host=_CODOGNO_HOST),
        esito=None,
    )


def test_codogno_tari_domestiche_fulfilled():
    # I due TARI (domestiche + non.domestiche) sarebbero ≥2 → NOT_FOUND; con la
    # variante "domestiche" il turno risolve esattamente la scheda giusta.
    r = _risolvi_tari(variante=VarianteServizio.DOMESTICHE)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id.endswith("s_italia:tassa.rifiuti;utenze.domestiche;dichiarazione")


def test_codogno_tari_non_domestiche_fulfilled():
    r = _risolvi_tari(variante=VarianteServizio.NON_DOMESTICHE)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id.endswith(
        "s_italia:tassa.rifiuti;utenze.non.domestiche;dichiarazione"
    )


def test_codogno_tari_senza_variante_resta_not_found():
    # Nessuna variante nel turno → facet no-op → ≥2 → NOT_FOUND onesto (I-1,
    # invariato rispetto al pre-facet).
    r = _risolvi_tari(variante=None)
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()


def test_codogno_tari_variante_e_azione_compongono():
    # I due assi COMPONGONO al punto comune: azione=dichiarazione (no-op utile,
    # entrambi i candidati la offrono) + variante=domestiche → esattamente-1.
    r = _risolvi_tari(
        variante=VarianteServizio.DOMESTICHE, azione=AzioneServizio.DICHIARAZIONE
    )
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id.endswith("s_italia:tassa.rifiuti;utenze.domestiche;dichiarazione")


# ── singolo candidato: il facet DECIDE anche a cardinalità 1 (fail-closed) ───
# Regressione review PR #93: con UN solo confermato il ramo len==1 NON deve
# corto-circuitare il facet. Un candidato con variante OPPOSTA a quella chiesta
# è NOT_FOUND, non FULFILLED su una scheda che il cittadino non ha chiesto.


def _pagine_codogno_tari_solo_domestiche() -> dict[str, str]:
    sitemap = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        f"<url><loc>{_u(_CODOGNO_HOST, _CO_TARI_DOM)}</loc></url>"
        "</urlset>"
    )
    return {
        _u(_CODOGNO_HOST, "/sitemap.xml"): sitemap,
        _u(_CODOGNO_HOST, _CO_TARI_DOM): _pagina_tari("Dichiarazione TARI utenze domestiche"),
    }


def _risolvi_tari_solo_domestiche(*, variante: VarianteServizio | None):
    fetcher = _FetcherSportello(_pagine_codogno_tari_solo_domestiche())
    conn = SportelloServiceConnector(fetcher)
    return conn.retrieve(
        _request_tari(variante=variante),
        mappa=_mappa(istat=_CODOGNO, host=_CODOGNO_HOST),
        esito=None,
    )


def test_unico_candidato_variante_opposta_not_found():
    # Unico confermato = domestiche; cittadino chiede non_domestiche → il candidato
    # NON sopravvive al filtro → 0 → NOT_FOUND (mai FULFILLED sulla domestica).
    r = _risolvi_tari_solo_domestiche(variante=VarianteServizio.NON_DOMESTICHE)
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()


def test_unico_candidato_variante_corretta_fulfilled():
    # Unico confermato = domestiche; cittadino chiede domestiche → sopravvive → 1.
    r = _risolvi_tari_solo_domestiche(variante=VarianteServizio.DOMESTICHE)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id.endswith("s_italia:tassa.rifiuti;utenze.domestiche;dichiarazione")


def test_unico_candidato_senza_variante_resta_fulfilled():
    # Nessun discriminatore nel turno → facet no-op → percorso storico len==1 →
    # FULFILLED (comportamento invariato per chi non usa il facet).
    r = _risolvi_tari_solo_domestiche(variante=None)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id.endswith("s_italia:tassa.rifiuti;utenze.domestiche;dichiarazione")
