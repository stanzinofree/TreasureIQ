from treasureiq.catalog import build_query_plan, request_from_recognition
from treasureiq.chat.intent import (
    ChatIntent,
    ChatRecognitionContract,
    QuestionKind,
    Topic,
)


def _contract(topic: Topic, kind: QuestionKind = QuestionKind.INFORMAZIONE):
    return ChatRecognitionContract(
        message="domanda",
        intent=ChatIntent(topic=topic, kind=kind),
        filter_keys=("isee",),
    )


def test_recognition_to_query_request_is_deterministic():
    request = request_from_recognition(_contract(Topic.BANDI), source_id="058003")

    assert request.surface.value == "transparency"
    assert request.capability == "notices"
    assert request.filters == {"keys": ["isee"]}
    assert build_query_plan(request).steps[0].capability == "notices"


def test_agevolazione_uses_opportunities_without_model():
    request = request_from_recognition(
        _contract(Topic.MENSA_SCOLASTICA, QuestionKind.AGEVOLAZIONE),
        source_id="058003",
    )

    assert request.surface.value == "ordinary_data"
    assert request.capability == "opportunities"
