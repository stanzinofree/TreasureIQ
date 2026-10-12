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
            "des_amm": "Comune di Basiano",
            "sito_istituzionale": "https://www.unione.basianomasate.mi.it",
            "Comune": "Basiano",
            "Provincia": "MI",
        },
        {
            "cod_amm": "C_MAS",
            "des_amm": "Comune di Masate",
            "sito_istituzionale": "https://www.unione.basianomasate.mi.it",
            "Comune": "Masate",
            "Provincia": "MI",
        },
    ]

    matched, missing = arricchisci_comuni(comuni, righe)

    assert (matched, missing) == (2, 0)
    assert [comune["codice_ipa"] for comune in comuni] == ["C_BAS", "C_MAS"]


def test_non_municipal_ipa_row_never_identifies_a_comune() -> None:
    comuni = [{"nome": "Basiano", "provincia": "MI"}]
    righe = [
        {
            "cod_amm": "ULCBM_2",
            "des_amm": "Unione Lombarda Dei Comuni di Basiano e Masate",
            "Comune": "Basiano",
            "Provincia": "MI",
        }
    ]

    matched, missing = arricchisci_comuni(comuni, righe)

    assert (matched, missing) == (0, 1)
    assert "codice_ipa" not in comuni[0]
