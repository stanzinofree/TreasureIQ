"""Test sul riconoscimento del comune nominato da un cittadino.

Sbagliare qui non produce una risposta mancante: produce una risposta
sbagliata con l'aria di essere giusta — l'orario di un comune presentato a chi
vive in un altro. È lo stesso rischio che R-18 registra per le pagine trovate
sul web, sul lato del riconoscimento invece che su quello della fonte.

Nessuno di questi test tocca la rete: verificano `risolvi_comune`, che legge
solo `data/comuni-istat.json`.
"""

from __future__ import annotations

import pytest

from treasureiq.sonda_live import _tel_valido, risolvi_comune


def nome_di(hint: str) -> str | None:
    comune = risolvi_comune(hint)
    return comune.nome if comune else None


def test_riconosce_un_comune_nominato_da_solo():
    assert nome_di("Trento") == "Trento"


def test_riconosce_un_comune_dentro_una_frase():
    assert nome_di("abito a Trento e vorrei sapere gli orari") == "Trento"


def test_san_marino_non_e_marino():
    """Difetto reale: «San Marino» risolveva a Marino (RM), e un cittadino di
    uno stato estero si vedeva rispondere coi dati dei Castelli Romani."""
    assert nome_di("San Marino") is None


def test_ma_marino_da_solo_resta_marino():
    """La guardia sui prefissi non deve mangiare il comune vero."""
    assert nome_di("vivo a Marino") == "Marino"


def test_un_prefisso_non_blocca_il_nome_completo():
    assert nome_di("San Giovanni Rotondo") == "San Giovanni Rotondo"


def test_il_nome_ufficiale_e_quello_parlato_cadono_insieme():
    """ISTAT scrive «Reggio nell'Emilia», un cittadino scrive «Reggio Emilia»."""
    assert nome_di("sono di Reggio Emilia") == nome_di("Reggio nell'Emilia")
    assert nome_di("sono di Reggio Emilia") is not None


def test_un_nome_una_parola_scritto_spezzato_si_riconosce():
    """Difetto reale: «monte rotondo» (due parole) non combaciava con
    «Monterotondo» (una parola nell'indice), e il comune attivo sbagliato
    restava. La chiave compatta recupera il nome intero concatenato."""
    assert nome_di("l'ufficio anagrafe del comune di monte rotondo") == "Monterotondo"
    assert nome_di("vivo a San Remo") == "Sanremo"


def test_la_chiave_compatta_non_scavalca_la_guardia_sui_prefissi():
    """«San Marino» resta None anche con la chiave compatta: «sanmarino» non è
    un comune italiano nell'indice, e la finestra «marino» è guardata dal
    prefisso che la precede."""
    assert nome_di("San Marino") is None


def test_fra_omonimi_non_si_indovina():
    """Castro sta in Puglia e in Lombardia. Sceglierne uno significa dare a
    metà di quei cittadini le informazioni dell'altra metà: si chiede."""
    assert nome_di("Castro") is None


@pytest.mark.parametrize("hint", ["", "   ", None, "Vattelapesca", "vorrei un aiuto"])
def test_niente_da_riconoscere(hint):
    assert risolvi_comune(hint) is None


def test_il_comune_riconosciuto_porta_con_se_il_proprio_sito():
    """Senza sito la sonda live non ha dove andare: è il campo che collega il
    riconoscimento alla lettura."""
    comune = risolvi_comune("Albano Laziale")
    assert comune is not None
    assert comune.codice_istat == "058003"
    assert comune.sito


# --- _tel_valido: sintassi telefono italiano ---------------------------------
# Lo scraping pesca sequenze storpiate (prefisso ripetuto, cifre monche) che
# sotto il vecchio minimo di 6 cifre finivano in card come un centralino finto.
# Meglio telefono «assente» che un numero che non si può comporre.


@pytest.mark.parametrize(
    "grezzo",
    [
        "06 6710 1234",  # centralino Roma con spazi -> 0667101234, 10 cifre
        "081 5601111",  # fisso Napoli, 10 cifre
        "0110010101",  # fisso Torino, 10 cifre
        "3331234567",  # cellulare
        "055 27681",  # fisso Firenze corto ma valido, 8 cifre
        "+39 06 69820000",  # prefisso internazionale +39
        "0039 011 1234567",  # prefisso 0039
        "39 3331234567",  # 39 + cellulare (12 cifre)
    ],
)
def test_accetta_numeri_italiani_componibili(grezzo):
    """Fisso (0 + area 1-9) o cellulare (3), 8-11 cifre nazionali, con o senza
    prefisso internazionale italiano."""
    assert _tel_valido(grezzo) is True


@pytest.mark.parametrize(
    "grezzo",
    [
        "055055",  # prefisso Firenze ripetuto: 6 cifre, garbage da scraping
        "00975370487",  # 11 cifre ma inizia con 00: non è area italiana valida
        "123456",  # troppo corto e non inizia per 0/3
        "1234567890",  # 10 cifre ma inizia per 1: né fisso né cellulare
        "000000000",  # zeri: 0 seguito da 0 -> area 00 non esiste
        "",  # vuoto
        "abc",  # nessuna cifra
        "20123456789",  # 11 cifre ma inizia per 2
    ],
)
def test_scarta_numeri_non_componibili(grezzo):
    """Chi non rispetta lo schema è scartato: la riga telefono resta assente."""
    assert _tel_valido(grezzo) is False
