from treasureiq.chat.intent import (
    ChatIntent,
    ChatRecognitionContract,
    Topic,
    build_recognition_contract,
)


def test_contract_unifica_intent_filtri_e_contesto():
    contract = build_recognition_contract(
        message="Sono di Albano Laziale, ho due figli minori e chiedo la mensa",
        intent=ChatIntent(topic=Topic.MENSA_SCOLASTICA, comune_hint="Albano Laziale"),
        storia=["cerco un servizio per la scuola"],
    )

    assert isinstance(contract, ChatRecognitionContract)
    assert contract.version == "v1"
    assert contract.context_turns == 1
    assert contract.municipality_explicit is True
    assert "figli_minori" in contract.filter_keys


def test_contract_non_fa_entrare_filtri_dalla_storia():
    contract = build_recognition_contract(
        message="e per la mensa?",
        intent=ChatIntent(topic=Topic.MENSA_SCOLASTICA),
        storia=["ho due figli minori"],
    )

    assert contract.filter_keys == ()
    assert contract.context_turns == 1
