from treasureiq.ingest.ipa import arricchisci_comuni


def test_shared_host_uses_name_and_province_before_assigning_ipa() -> None:
    comuni = [
        {
            "nome": "Basiano",
            "provincia": "MI",
            "sito": "https://www.unione.basianomasate.mi.it",
            "codice_ipa": "C_STALE",
        },
        {
            "nome": "Masate",
            "provincia": "MI",
            "sito": "https://www.unione.basianomasate.mi.it",
        },
    ]
    righe = [
        {
            "cod_amm": "C_BAS",
            "sito_istituzionale": "https://www.unione.basianomasate.mi.it",
            "Comune": "Basiano",
            "Provincia": "MI",
        },
        {
            "cod_amm": "C_MAS",
            "sito_istituzionale": "https://www.unione.basianomasate.mi.it",
            "Comune": "Masate",
            "Provincia": "MI",
        },
    ]

    matched, missing = arricchisci_comuni(comuni, righe)

    assert (matched, missing) == (2, 0)
    assert [comune["codice_ipa"] for comune in comuni] == ["C_BAS", "C_MAS"]
