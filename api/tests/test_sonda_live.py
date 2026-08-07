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

from treasureiq.sonda_live import risolvi_comune


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
