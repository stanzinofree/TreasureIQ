"""Golden tests per il facet-azione (Ramo 3, MVP IMU/tributi). Net-free.

Il facet è un asse ACTION ortogonale alla ServiceKey: applicato al punto comune
(``connettore_base.retrieve``) restringe ≥2 confermati *facetabili* a
esattamente-uno quando il turno porta un'azione, senza mai indebolire I-1 (0 o ≥2
dopo il facet = NOT_FOUND onesto, nessun fallback). Verità di terra reale: su
Codogno l'IMU nazionale ha due schede distinte (dichiarazione + pagamento) →
oggi ≥2 → NOT_FOUND; col facet, "dichiarazione"/"pagamento" nel messaggio le
separano.

Copre: recogniser (citizen text→azione), matcher candidato (title/slug→azione)
con esclusione HARD di ``;domanda``, no-op del facet fuori perimetro, e
l'integrazione end-to-end sul connettore Sportello riusando l'harness reale.
"""

from __future__ import annotations

import pytest

from tests.test_sportello_service_connector import (
    _CODOGNO,
    _CODOGNO_HOST,
    _FetcherSportello,
    _mappa,
    _pagine_codogno_ambiguo,
    _u,
)
from treasureiq.catalog.contracts import CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import DataRequest, DataStatus, FreshnessPolicy
from treasureiq.catalog.service_connectors.base import ServiceCandidate
from treasureiq.catalog.service_connectors.facet_azione import (
    azione_del_candidato,
    filtra_per_azione,
)
from treasureiq.catalog.service_connectors.sportello_service import (
    SportelloServiceConnector,
)
from treasureiq.catalog.service_contracts import AzioneServizio, ServiceKey
from treasureiq.chat.service_key import riconosci_azione


# ── recogniser: citizen text → azione ───────────────────────────────────────


@pytest.mark.parametrize(
    "message, atteso",
    [
        ("vorrei pagare l'IMU", AzioneServizio.PAGAMENTO),
        ("pago l'IMU", AzioneServizio.PAGAMENTO),
        ("come faccio il pagamento IMU", AzioneServizio.PAGAMENTO),
        ("versamento IMU", AzioneServizio.PAGAMENTO),
        ("devo pagare con l'F24", AzioneServizio.PAGAMENTO),
        ("dichiarazione IMU", AzioneServizio.DICHIARAZIONE),
        ("dichiaro l'IMU", AzioneServizio.DICHIARAZIONE),
        ("denuncia IMU", AzioneServizio.DICHIARAZIONE),
    ],
)
def test_riconosce_azione_singola(message, atteso):
    assert riconosci_azione(message) is atteso


@pytest.mark.parametrize(
    "message",
    [
        "IMU",  # nessun marker → turno senza azione
        "informazioni sull'IMU",
        "",
        # ambiguo: due azioni distinte nello stesso messaggio → None (mai la più
        # vicina); il gate ≥2 decide, il facet non restringe.
        "voglio pagare e fare la dichiarazione IMU",
    ],
)
def test_azione_none_quando_assente_o_ambigua(message):
    assert riconosci_azione(message) is None


# ── matcher candidato: title/slug → azione ──────────────────────────────────


def _cand(native_id: str, title: str) -> ServiceCandidate:
    return ServiceCandidate(
        native_id=native_id,
        title=title,
        url="https://sportellotelematico.example.it/x",
    )


def test_candidato_dichiarazione_da_slug_e_titolo():
    c = _cand("s_italia:imposta.municipale.unica;dichiarazione", "Dichiarazione IMU")
    assert azione_del_candidato(c) is AzioneServizio.DICHIARAZIONE


def test_candidato_pagamento_da_slug_e_titolo():
    c = _cand(
        "s_italia:imposta.municipale.unica;pagamento",
        "Pagamento dell'imposta municipale propria (IMU)",
    )
    assert azione_del_candidato(c) is AzioneServizio.PAGAMENTO


def test_candidato_senza_marker_e_actionless():
    c = _cand("s_italia:imposta.municipale.unica", "IMU")
    assert azione_del_candidato(c) is None


def test_domanda_esclusa_hard():
    # ``;domanda`` è un launcher di modulo, NON un'azione: il segmento dopo il
    # marker viene tagliato prima dello scan → il candidato resta actionless
    # anche se un token vi comparisse. Qui il titolo non porta azione.
    c = _cand("s_italia:imposta.municipale.unica;domanda", "Istanza IMU online")
    assert azione_del_candidato(c) is None


def test_domanda_non_maschera_pagamento_reale():
    # Un candidato che offre davvero pagamento resta pagamento: il taglio
    # ``;domanda`` non tocca il resto (qui il titolo porta il marker).
    c = _cand("s_italia:imposta.municipale.unica;domanda", "Pagamento IMU")
    assert azione_del_candidato(c) is AzioneServizio.PAGAMENTO


def test_slug_url_encoded_decodificato():
    # native_id può arrivare URL-encoded (%3A=:, %3B=;): il matcher decodifica.
    c = _cand("s_italia%3Aimposta.municipale.unica%3Bpagamento", "Pagamento IMU")
    assert azione_del_candidato(c) is AzioneServizio.PAGAMENTO


# ── filtra_per_azione: no-op fuori perimetro, restringe dentro ──────────────


def _due_imu() -> tuple[ServiceCandidate, ...]:
    return (
        _cand("s_italia:imposta.municipale.unica;dichiarazione", "Dichiarazione IMU"),
        _cand("s_italia:imposta.municipale.unica;pagamento", "Pagamento IMU"),
    )


def test_filtra_noop_senza_azione():
    due = _due_imu()
    assert filtra_per_azione(due, ServiceKey.TRIBUTI_IMU, None) == due


def test_filtra_noop_key_non_facetabile():
    # TARI non è in _FACET_KEYS (MVP IMU-only): nessun restringimento anche con
    # azione presente → i ≥2 restano ≥2 → gate storico → NOT_FOUND.
    due = _due_imu()
    assert filtra_per_azione(due, ServiceKey.TRIBUTI_TARI, AzioneServizio.PAGAMENTO) == due


def test_filtra_restringe_a_uno():
    due = _due_imu()
    (solo,) = filtra_per_azione(due, ServiceKey.TRIBUTI_IMU, AzioneServizio.PAGAMENTO)
    assert "pagamento" in solo.native_id


def test_filtra_zero_survivor_senza_match():
    # Azione senza candidato corrispondente → 0 survivor (mai un ripiego): il
    # chiamante cade nel gate ≥2 → NOT_FOUND.
    solo_dich = (
        _cand("s_italia:imposta.municipale.unica;dichiarazione", "Dichiarazione IMU"),
    )
    assert filtra_per_azione(solo_dich, ServiceKey.TRIBUTI_IMU, AzioneServizio.PAGAMENTO) == ()


# ── integrazione end-to-end sul connettore Sportello ────────────────────────


def _request(*, istat: str, azione: AzioneServizio | None) -> DataRequest:
    selection: dict[str, object] = {"service_key": ServiceKey.TRIBUTI_IMU.value}
    if azione is not None:
        selection["azione"] = azione.value
    return DataRequest(
        request_id=f"t:{istat}:facet",
        source_id=istat,
        surface=Surface.ORDINARY_DATA,
        capability=CAPABILITY_SERVICES,
        selection=selection,
        freshness=FreshnessPolicy(max_age_seconds=86_400),
        manifest_revision=1,
    )


def _risolvi_azione(azione: AzioneServizio | None):
    fetcher = _FetcherSportello(_pagine_codogno_ambiguo())
    conn = SportelloServiceConnector(fetcher)
    return conn.retrieve(
        _request(istat=_CODOGNO, azione=azione),
        mappa=_mappa(istat=_CODOGNO, host=_CODOGNO_HOST),
        esito=None,
    )


def test_codogno_imu_dichiarazione_fulfilled():
    # I due IMU (dichiarazione + pagamento) sarebbero ≥2 → NOT_FOUND; col facet
    # "dichiarazione" il turno risolve esattamente la scheda giusta.
    r = _risolvi_azione(AzioneServizio.DICHIARAZIONE)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    # id da ns:slug (I-2), scheda dichiarazione.
    assert ref.service_id.endswith("s_italia:imposta.municipale.unica;dichiarazione")


def test_codogno_imu_pagamento_fulfilled():
    r = _risolvi_azione(AzioneServizio.PAGAMENTO)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id.endswith("s_italia:imposta.municipale.unica;pagamento")


def test_codogno_imu_senza_azione_resta_not_found():
    # Nessuna azione nel turno → facet no-op → ≥2 → NOT_FOUND onesto (invariato
    # rispetto al comportamento pre-facet, I-1).
    r = _risolvi_azione(None)
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()


# ── guard end-to-end: TARI non è facetabile (MVP IMU-only) ──────────────────

# Due schede TARI nazionali (pagamento + dichiarazione), stesso motore Globo,
# costruite inline (net-free, nessuna fixture su disco): slug-token `tassa.rifiuti`
# per il pre-filtro, titolo che il recogniser conferma come TARI. Il titolo
# "Pagamento TARI" porta pure il marker-azione: se TARI fosse facetabile il facet
# lo promuoverebbe — è proprio ciò che il guard deve impedire.
_CO_TARI_PAG = "/procedure%3As_italia%3Atassa.rifiuti%3Bpagamento"
_CO_TARI_DIC = "/procedure%3As_italia%3Atassa.rifiuti%3Bdichiarazione"


def _pagina_tari(titolo: str) -> str:
    return f"<!DOCTYPE html><html lang='it'><head><title>{titolo} | Comune di Codogno</title></head><body></body></html>"


def _pagine_codogno_tari_ambiguo() -> dict[str, str]:
    sitemap = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        f"<url><loc>{_u(_CODOGNO_HOST, _CO_TARI_PAG)}</loc></url>"
        f"<url><loc>{_u(_CODOGNO_HOST, _CO_TARI_DIC)}</loc></url>"
        "</urlset>"
    )
    return {
        _u(_CODOGNO_HOST, "/sitemap.xml"): sitemap,
        _u(_CODOGNO_HOST, _CO_TARI_PAG): _pagina_tari("Pagamento TARI"),
        _u(_CODOGNO_HOST, _CO_TARI_DIC): _pagina_tari("Dichiarazione TARI"),
    }


def _request_tari(*, azione: AzioneServizio | None) -> DataRequest:
    selection: dict[str, object] = {"service_key": ServiceKey.TRIBUTI_TARI.value}
    if azione is not None:
        selection["azione"] = azione.value
    return DataRequest(
        request_id=f"t:{_CODOGNO}:facet-tari",
        source_id=_CODOGNO,
        surface=Surface.ORDINARY_DATA,
        capability=CAPABILITY_SERVICES,
        selection=selection,
        freshness=FreshnessPolicy(max_age_seconds=86_400),
        manifest_revision=1,
    )


# ── OpenPA: facet decisivo su una famiglia che AMMETTE disambiguazione ───────

# OpenPA è l'unico connettore con _AMMETTE_DISAMBIGUAZIONE=True: senza facet, ≥2
# IMU confermati → DISAMBIGUATION. Col facet applicabile (IMU + azione) il facet
# DECIDE da solo — esattamente-1 → FULFILLED, 0 o ≥2 → NOT_FOUND — e NON ripiega
# MAI a mostrare i confermati non ristretti. Regressione del 🔴 della review.

from tests.test_openpa_imis_tributi_imu import (  # noqa: E402
    StubFetcher as _OpenPAStub,
)
from tests.test_openpa_imis_tributi_imu import (  # noqa: E402
    _ISTAT as _OPENPA_ISTAT,
)
from tests.test_openpa_imis_tributi_imu import (  # noqa: E402
    _cand as _openpa_cand,
)
from tests.test_openpa_imis_tributi_imu import (  # noqa: E402
    _conn as _openpa_conn,
)
from tests.test_openpa_imis_tributi_imu import (  # noqa: E402
    _mappa as _openpa_mappa,
)


def _request_openpa(*, azione: AzioneServizio | None) -> DataRequest:
    selection: dict[str, object] = {"service_key": ServiceKey.TRIBUTI_IMU.value}
    if azione is not None:
        selection["azione"] = azione.value
    return DataRequest(
        request_id="r-openpa-facet",
        source_id=_OPENPA_ISTAT,
        surface=Surface.ORDINARY_DATA,
        capability=CAPABILITY_SERVICES,
        selection=selection,
        freshness=FreshnessPolicy(max_age_seconds=86_400),
        manifest_revision=1,
    )


def _risolvi_openpa(candidati, *, azione):
    conn = _openpa_conn(_OpenPAStub(candidati=candidati))
    return conn.retrieve(_request_openpa(azione=azione), mappa=_openpa_mappa(), esito=None)


# Due public_service IMU distinti per azione (entrambi confermano IMU via titolo).
_PAG = _openpa_cand(701, "Pagamento IMU", "/Servizi/Pagamento-IMU", "public_service")
_DIC = _openpa_cand(702, "Dichiarazione IMU", "/Servizi/Dichiarazione-IMU", "public_service")


def test_openpa_baseline_due_imu_senza_azione_disambigua():
    # Percorso storico invariato: senza azione, ≥2 IMU → DISAMBIGUATION (OpenPA
    # ammette la scelta). È la baseline che il facet NON deve alterare.
    r = _risolvi_openpa((_PAG, _DIC), azione=None)
    assert r.status is DataStatus.DISAMBIGUATION


def test_openpa_imu_azione_esattamente_uno_fulfilled():
    # Facet applicabile, ristretti=1 → FULFILLED (non disambigua).
    r = _risolvi_openpa((_PAG, _DIC), azione=AzioneServizio.PAGAMENTO)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id.endswith(":openpa:701")  # id da native_id (I-2), scheda pagamento


def test_openpa_imu_azione_zero_match_not_found_mai_disambigua():
    # ristretti=0 (nessun candidato offre pagamento) → NOT_FOUND, MAI la
    # disambiguazione dei confermati non ristretti (contratto MVP).
    dic2 = _openpa_cand(703, "Dichiarazione acconto IMU", "/Servizi/Dich-2", "public_service")
    r = _risolvi_openpa((_DIC, dic2), azione=AzioneServizio.PAGAMENTO)
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()


def test_openpa_imu_azione_multipli_match_not_found_mai_disambigua():
    # ristretti≥2 (due candidati offrono pagamento) → NOT_FOUND, MAI DISAMBIGUATION.
    pag2 = _openpa_cand(704, "Pagamento acconto IMU", "/Servizi/Pag-2", "public_service")
    r = _risolvi_openpa((_PAG, pag2), azione=AzioneServizio.PAGAMENTO)
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()


def test_openpa_imu_unico_candidato_azione_opposta_not_found():
    # Regressione review PR #93: UN solo confermato (dichiarazione) con azione
    # richiesta OPPOSTA (pagamento) → il facet DECIDE anche a cardinalità 1 →
    # 0 sopravvissuti → NOT_FOUND. Il ramo len==1 NON deve corto-circuitare il
    # facet promuovendo la scheda dichiarazione che il cittadino non ha chiesto.
    r = _risolvi_openpa((_DIC,), azione=AzioneServizio.PAGAMENTO)
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()


def test_openpa_imu_unico_candidato_azione_corretta_fulfilled():
    # Speculare: unico confermato (pagamento) con azione corretta → sopravvive → 1
    # → FULFILLED sulla scheda giusta.
    r = _risolvi_openpa((_PAG,), azione=AzioneServizio.PAGAMENTO)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id.endswith(":openpa:701")


def test_openpa_imu_unico_candidato_senza_azione_fulfilled():
    # Facet no-op (nessuna azione) → percorso storico len==1 → FULFILLED
    # (comportamento invariato per chi non usa il facet).
    r = _risolvi_openpa((_PAG,), azione=None)
    assert r.status is DataStatus.FULFILLED
    (ref,) = r.service_references
    assert ref.service_id.endswith(":openpa:701")


def test_tari_con_pagamento_non_promuove_resta_not_found():
    # Guard end-to-end al punto comune: TARI ∉ _FACET_KEYS → filtra_per_azione è
    # no-op anche con azione=pagamento presente → i due TARI restano ≥2 → gate
    # storico → NOT_FOUND. Nessuna promozione indebita del candidato "Pagamento
    # TARI", che pure porterebbe il marker-azione.
    fetcher = _FetcherSportello(_pagine_codogno_tari_ambiguo())
    conn = SportelloServiceConnector(fetcher)
    r = conn.retrieve(
        _request_tari(azione=AzioneServizio.PAGAMENTO),
        mappa=_mappa(istat=_CODOGNO, host=_CODOGNO_HOST),
        esito=None,
    )
    assert r.status is DataStatus.NOT_FOUND
    assert r.service_references == ()
