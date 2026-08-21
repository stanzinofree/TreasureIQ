from datetime import datetime, timezone

from treasureiq.catalog import (
    AuthenticationMethod,
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceReference,
    Surface,
    request_from_recognition,
    service_portal_request,
)
from treasureiq.catalog.planner import build_query_plan
from treasureiq.chat.intent import (
    ChatIntent,
    ChatRecognitionContract,
    QuestionKind,
    Topic,
)


def test_base_reference_can_expose_download_and_authenticated_paths() -> None:
    reference = ServiceReference(
        service_id="cambio_residenza",
        title="Cambio di residenza",
        source_url="https://comune.example.it/modulistica",
        provider_platform="urbi",
        discovered_from=Surface.ORDINARY_DATA,
        discovered_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        options=(
            ServiceAccessOption(
                mode=ServiceAccessMode.DOWNLOAD,
                url="https://comune.example.it/modulo.pdf",
                source_url="https://comune.example.it/modulistica",
            ),
            ServiceAccessOption(
                mode=ServiceAccessMode.AUTHENTICATED_ONLINE,
                url="https://cloud.example.it/urbi/servizio",
                provider="urbi",
                authentication=(AuthenticationMethod.SPID, AuthenticationMethod.CIE),
                requires_authentication=True,
                source_url="https://comune.example.it/modulistica",
            ),
        ),
    )

    assert reference.discovered_from is Surface.ORDINARY_DATA
    assert reference.options[1].requires_authentication is True
    assert reference.options[1].automatable is False


def test_service_portal_request_is_a_separate_deterministic_route() -> None:
    request = service_portal_request(
        source_id="058003",
        service_id="cambio_residenza",
    )
    plan = build_query_plan(request)

    assert request.surface is Surface.SERVICE_PORTAL
    assert request.selection == {"service_id": "cambio_residenza"}
    assert all(step.surface is Surface.SERVICE_PORTAL for step in plan.steps)
    assert request.request_id == "chat:058003:service_portal:cambio_residenza"


def test_recognition_can_route_to_service_portal_only_with_explicit_override() -> None:
    recognition = ChatRecognitionContract(
        message="come cambio residenza?",
        intent=ChatIntent(
            topic=Topic.ANAGRAFE_CARTA_IDENTITA,
            kind=QuestionKind.INFORMAZIONE,
            comune_hint="Albano Laziale",
        ),
    )

    request = request_from_recognition(
        recognition,
        source_id="058003",
        capability_override="authenticated_service",
        surface_override=Surface.SERVICE_PORTAL,
    )

    assert request.surface is Surface.SERVICE_PORTAL
    assert request.capability == "authenticated_service"
