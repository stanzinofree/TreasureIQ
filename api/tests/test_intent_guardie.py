"""Test sulla guardia che scarta un comune che il cittadino non ha nominato.

Difetto reale: alla domanda «orari ufficio anagrafe Camposampiero» il modello
ha restituito `comune_hint="Albano Laziale"` — il comune scritto nel proprio
system prompt, non nella frase del cittadino. La risposta che ne seguiva
mostrava l'ufficio di Albano, il suo telefono e i suoi orari a qualcuno che
chiedeva di un comune a 500 km. Nessuno dei passaggi successivi poteva
accorgersene: trattano tutti `comune_hint` come una cosa che il cittadino ha
detto.
"""

from __future__ import annotations

import pytest

from treasureiq.chat.intent import _confirm_comune_hint


def conferma(messaggio: str, hint: str | None) -> str | None:
    return _confirm_comune_hint(message=messaggio, hint=hint)


def test_scarta_il_comune_inventato_dal_modello():
    assert conferma("orari ufficio anagrafe Camposampiero", "Albano Laziale") is None


def test_tiene_il_comune_che_il_cittadino_ha_scritto():
    assert conferma("orari anagrafe Arquata Scrivia", "Arquata Scrivia") == "Arquata Scrivia"


def test_mezzo_nome_non_conferma_il_nome_intero():
    """«Reggio» da solo non prova che il cittadino intendesse Reggio Emilia:
    mezzo nome è il modo in cui si finisce nel comune sbagliato."""
    assert conferma("vivo a Reggio", "Reggio Emilia") is None


def test_accenti_e_maiuscole_non_contano():
    assert conferma("sono di forli", "Forlì") == "Forlì"
    assert conferma("Sono di ALBANO LAZIALE", "Albano Laziale") == "Albano Laziale"


def test_la_punteggiatura_non_impedisce_la_conferma():
    assert conferma("abito a Trento, e volevo sapere gli orari", "Trento") == "Trento"


def test_non_inventa_mai_un_comune():
    """La guardia può solo togliere, mai aggiungere."""
    assert conferma("abito a Trento", None) is None


@pytest.mark.parametrize("hint", ["", "   "])
def test_hint_vuoto_e_come_assente(hint: str):
    assert conferma("una domanda qualsiasi", hint) is None
