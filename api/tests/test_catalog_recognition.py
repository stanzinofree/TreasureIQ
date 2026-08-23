from datetime import datetime, timezone

from treasureiq.catalog import (
    ConnectorVersionManifest,
    FingerprintEvidence,
    RecognitionAction,
    RecognitionResult,
    ResweepPolicy,
    Surface,
    action_for_recognition,
    score_evidence,
)
from treasureiq.catalog.checks import CheckStatus, source_identity_check


def test_weighted_evidence_is_deterministic() -> None:
    evidence = (
        FingerprintEvidence(
            key="rest", description="REST endpoint", matched=True, weight=0.7
        ),
        FingerprintEvidence(
            key="theme", description="AgID theme", matched=False, weight=0.3
        ),
    )
    assert score_evidence(evidence) == 0.7


def test_recognition_result_keeps_connector_and_fingerprint_versions() -> None:
    result = RecognitionResult(
        source_id="058003",
        surface=Surface.ORDINARY_DATA,
        platform_id="wordpress_agid",
        connector_id="wordpress_agid_base",
        connector_version="1.2.0",
        fingerprint_version="1.0",
        recognition_score=0.95,
        checked_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
    )
    assert result.connector_version == "1.2.0"
    assert result.fingerprint_version == "1.0"


def test_policy_requests_targeted_work_for_version_changes() -> None:
    policy = ResweepPolicy()
    assert action_for_recognition(score=0.95, policy=policy) is RecognitionAction.KEEP
    assert action_for_recognition(
        score=0.95, policy=policy, fingerprint_changed=True
    ) is RecognitionAction.REDISCOVER
    assert action_for_recognition(
        score=0.95, policy=policy, connector_minor_changed=True
    ) is RecognitionAction.CONFIRM
    assert action_for_recognition(
        score=0.95, policy=policy, connector_major_changed=True
    ) is RecognitionAction.REDISCOVER
    assert action_for_recognition(score=0.50, policy=policy) is RecognitionAction.MANUAL_REVIEW


def test_manifest_is_versioned_per_surface() -> None:
    manifest = ConnectorVersionManifest(
        connector_id="wordpress_agid_base",
        version="1.2.0",
        contract_version="catalog.v1",
        fingerprint_version="1.0",
        surfaces=(Surface.ORDINARY_DATA,),
        platforms=("wordpress_agid",),
    )
    assert manifest.platforms == ("wordpress_agid",)


def test_source_identity_check_is_independent_from_connector() -> None:
    class Response:
        status_code = 200
        url = "https://comune.example.it/"

    result = source_identity_check(
        source_id="058003",
        declared_url="https://comune.example.it",
        response=Response(),
        identity={
            "nome": "Comune", "codice_ipa": "C_X", "pec": None,
            "indirizzo": None, "logo": False,
        },
        checked_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
    )
    assert result.surface is Surface.SOURCE_IDENTITY
    assert result.status is CheckStatus.DEGRADED
    assert result.source_health is True
