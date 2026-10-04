"""Fase 2C — verdetto unico di aderenza per (comune, connettore).

`fondi_aderenza` fonde il `CheckResult` uniforme (riconoscimento + drift +
fingerprint) con una copertura misurata opzionale in un solo verdetto,
famiglia-agnostico. Questi test fissano la regola del `verdetto`: la copertura è
la misura, il riconoscimento la sblocca, il drift la invalida.
"""
from __future__ import annotations

from datetime import datetime, timezone

from treasureiq.catalog.aderenza import Aderenza, coverage_da_misura, fondi_aderenza
from treasureiq.catalog.checks import CheckResult, CheckStatus
from treasureiq.catalog.contracts import Surface


def _check(
    *, status: CheckStatus, coverage=None, recognition=None,
    platform="wordpress_agid", connector_id="entrypoint_confirmation",
    fingerprint="sha256:abc",
) -> CheckResult:
    return CheckResult(
        source_id="058003", surface=Surface.TRANSPARENCY, status=status,
        source_health=True, recognition_score=recognition, coverage_score=coverage,
        connector_id=connector_id, fingerprint=fingerprint,
        identity={"platform": platform},
        checked_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )


# --- coverage_da_misura: legge la forma uniforme del censimento ---

def test_coverage_legge_aderenza():
    assert coverage_da_misura({"aderenza": 0.68, "scheda_campione": "x"}) == 0.68


def test_coverage_none_su_nota_misura():
    # Nessuna scheda letta: solo nota_misura, niente chiave aderenza → non misurata.
    assert coverage_da_misura({"nota_misura": "indice_senza_schede"}) is None


def test_coverage_none_su_vuoto():
    assert coverage_da_misura(None) is None
    assert coverage_da_misura({}) is None


def test_coverage_clampa_e_ignora_bool():
    assert coverage_da_misura({"aderenza": 1.4}) == 1.0
    assert coverage_da_misura({"aderenza": -0.2}) == 0.0
    # True è un int in Python: non deve passare per una copertura.
    assert coverage_da_misura({"aderenza": True}) is None


# --- fondi_aderenza: la regola del verdetto ---

def test_riconosciuto_con_copertura_verdetto_e_la_copertura():
    check = _check(status=CheckStatus.OK, recognition=1.0)
    result = fondi_aderenza(check, coverage=0.68)
    assert isinstance(result, Aderenza)
    assert result.status is CheckStatus.OK
    assert result.difforme is False
    assert result.coverage_score == 0.68
    assert result.verdetto == 0.68
    # connettore = motore/plugin, piattaforma = ciò che il riconoscimento ha
    # visto: due chiavi distinte, non collassate.
    assert result.connettore == "entrypoint_confirmation"
    assert result.piattaforma == "wordpress_agid"
    assert result.source_id == "058003"
    assert result.fingerprint == "sha256:abc"


def test_drift_azzera_il_verdetto_ma_tiene_la_copertura():
    # DIFFORME: la copertura è misurata contro un contratto che non vale più.
    # recognition positivo di proposito: è il *drift* a dover azzerare il
    # verdetto, non l'assenza di riconoscimento.
    check = _check(status=CheckStatus.DIFFORME, recognition=1.0)
    result = fondi_aderenza(check, coverage=0.68)
    assert result.difforme is True
    assert result.coverage_score == 0.68
    assert result.verdetto is None


def test_non_riconosciuto_niente_verdetto():
    check = _check(status=CheckStatus.MANUAL_REVIEW, recognition=0.0)
    result = fondi_aderenza(check, coverage=0.5)
    assert result.difforme is False
    assert result.verdetto is None


def test_riconosciuto_senza_copertura_verdetto_none():
    # Riconosciuto e vivo, ma la copertura non è stata misurata: onesto None,
    # non uno zero — è il caso odierno del path confirmation.
    check = _check(status=CheckStatus.OK, recognition=1.0, coverage=None)
    result = fondi_aderenza(check)  # nessuna copertura fornita
    assert result.coverage_score is None
    assert result.verdetto is None


def test_ok_senza_recognition_score_non_sblocca_il_verdetto():
    # Uno stato OK NON basta a sbloccare la coverage: serve un recognition_score
    # positivo. Un OK con recognition None (es. SOURCE_IDENTITY) più una coverage
    # non deve produrre un verdetto — la recognition sblocca la coverage.
    check = _check(status=CheckStatus.OK, recognition=None)
    result = fondi_aderenza(check, coverage=0.7)
    assert result.recognition_score is None
    assert result.coverage_score == 0.7
    assert result.verdetto is None


def test_copertura_fornita_ha_precedenza_su_quella_del_check():
    check = _check(status=CheckStatus.OK, recognition=1.0, coverage=0.2)
    result = fondi_aderenza(check, coverage=0.9)
    assert result.coverage_score == 0.9
    assert result.verdetto == 0.9


def test_famiglia_non_wp_stessa_regola(monkeypatch):
    # Gate Fase 2: l'aderedenza si calcola anche fuori da WordPress. La fusione
    # è famiglia-agnostica — cambia solo la stringa piattaforma e la misura, che
    # per ComWeb arriva dalla scheda HTML generica del censimento.
    misura_comweb = {"aderenza": 0.68, "scheda_campione": "https://x/it-it/servizi/y"}
    coverage = coverage_da_misura(misura_comweb)
    check = _check(status=CheckStatus.OK, recognition=1.0, platform="comweb",
                   connector_id="entrypoint_confirmation")
    result = fondi_aderenza(check, coverage=coverage)
    assert result.piattaforma == "comweb"
    assert result.connettore == "entrypoint_confirmation"
    assert result.coverage_score == 0.68
    assert result.verdetto == 0.68


def test_connettore_e_connector_id_piattaforma_none_se_assente():
    check = _check(status=CheckStatus.OK, recognition=1.0, platform=None,
                   connector_id="filodiretto_sp")
    result = fondi_aderenza(check, coverage=0.5)
    assert result.connettore == "filodiretto_sp"
    assert result.piattaforma is None


# --- census coverage fused with any connector's recognition -------------

from datetime import datetime as _dt, timezone as _tz

from treasureiq.catalog.aderenza import check_da_riconoscimento, stessa_famiglia
from treasureiq.catalog.contracts import Surface as _Surface
from treasureiq.catalog.recognition import RecognitionResult


def _riconoscimento(*, piattaforma: str | None = "comweb", score: float = 0.998, coverage: float | None = None):
    return RecognitionResult(
        source_id="001081",
        surface=_Surface.ORDINARY_DATA,
        platform_id=piattaforma,
        connector_id="comweb_base",
        connector_version="1.0.0",
        fingerprint_version="1.0",
        recognition_score=score,
        coverage_score=coverage,
        checked_at=_dt(2026, 10, 3, tzinfo=_tz.utc),
    )


def test_copertura_su_modello_intero_diventa_verdetto() -> None:
    aderenza = fondi_aderenza(
        check_da_riconoscimento(_riconoscimento()),
        coverage=0.818, coverage_base="modello_intero", coverage_misurata_il="2026-08-20",
    )
    assert aderenza.verdetto == 0.818
    assert aderenza.coverage_base == "modello_intero"
    assert aderenza.coverage_misurata_il == "2026-08-20"
    assert aderenza.piattaforma == "comweb"


def test_copertura_su_schema_esposto_registrata_senza_verdetto() -> None:
    """User decision: 100% of the exposed boxes is recorded, not a verdict."""
    aderenza = fondi_aderenza(
        check_da_riconoscimento(_riconoscimento(piattaforma="wordpress_generico")),
        coverage=1.0, coverage_base="schema_esposto",
    )
    assert aderenza.coverage_score == 1.0
    assert aderenza.coverage_base == "schema_esposto"
    assert aderenza.verdetto is None


def test_copertura_capability_del_riconoscimento_non_e_il_verdetto() -> None:
    """The recognition's own coverage (capabilities recovered) is another
    measure: without a census coverage there is no verdict, not a zero."""
    aderenza = fondi_aderenza(check_da_riconoscimento(_riconoscimento(coverage=0.0)))
    assert aderenza.coverage_score is None
    assert aderenza.verdetto is None


def test_riconoscimento_senza_piattaforma_non_sblocca() -> None:
    check = check_da_riconoscimento(_riconoscimento(piattaforma=None, score=0.0))
    aderenza = fondi_aderenza(check, coverage=1.0, coverage_base="modello_intero")
    assert aderenza.verdetto is None


def test_stessa_famiglia_censimento_riconoscimento() -> None:
    assert stessa_famiglia("peopleweb", "openweb")
    assert stessa_famiglia("peopleweb", "peopleweb")
    assert stessa_famiglia("wp_design_comuni", "wordpress_agid")
    assert stessa_famiglia("comweb", "comweb")
    assert not stessa_famiglia("comweb", "peopleweb")
    assert not stessa_famiglia("regione_veneto", "wordpress_agid")
    assert not stessa_famiglia(None, "comweb")
