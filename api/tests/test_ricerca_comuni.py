"""Test sulla ricerca da cui il cittadino sceglie il proprio comune.

Scegliere serve a produrre un `codice_istat`, che è l'unica forma di questo
dato che non ha omonimi, non dipende dalla grafia e non può essere inventata
da un modello. Perché la scelta funzioni, però, l'elenco deve contenere quello
che la persona sta cercando: una tendina che non trova «comune di Roma» spinge
di nuovo verso la deduzione, cioè verso i difetti che la scelta esiste per
chiudere.
"""

from __future__ import annotations

import pytest

from treasureiq.sonda_live import cerca_comuni, comune_per_codice


def nomi(query: str) -> list[str]:
    return [c.nome for c in cerca_comuni(query)]


def test_il_modo_normale_di_nominare_un_comune():
    """«comune di X» è come parla la gente, e nessun nome ISTAT contiene la
    parola «comune»: senza ripulire il prefisso la ricerca dava zero."""
    assert "Camposampiero" in nomi("comune di Camposampiero")
    assert "Torino" in nomi("città di Torino")


def test_la_corrispondenza_esatta_viene_prima():
    assert nomi("Roma")[0] == "Roma"
    assert nomi("Castro")[0] == "Castro"


def test_gli_omonimi_ci_sono_tutti_e_due():
    """È il punto della tendina: Castro sta in Puglia e in Lombardia, e chi
    sceglie deve poter dire quale — non riceverne uno a caso."""
    castri = [c for c in cerca_comuni("Castro") if c.nome == "Castro"]
    assert {c.provincia for c in castri} == {"BG", "LE"}


def test_roma_c_e_anche_se_non_ne_conosciamo_il_portale():
    """Nasconderla farebbe sembrare l'elenco incompleto. Il fatto che di Roma
    non abbiamo il sito è un'assenza da dichiarare, non da mascherare."""
    roma = next(c for c in cerca_comuni("Roma") if c.nome == "Roma")
    assert roma.codice_istat == "058091"
    assert roma.sito is None


def test_una_ricerca_troppo_corta_non_restituisce_mezza_italia():
    assert cerca_comuni("a") == []


def test_un_nome_che_non_e_un_comune_non_trova_niente():
    """Zero risultati significa «questo non è un comune italiano», non
    «comune non coperto»: l'elenco ISTAT è completo."""
    assert cerca_comuni("Vattelapesca") == []


def test_il_codice_e_la_via_che_non_sbaglia():
    comune = comune_per_codice("028019")
    assert comune is not None
    assert comune.nome == "Camposampiero"


@pytest.mark.parametrize("codice", [None, "", "999999"])
def test_un_codice_inesistente_non_inventa_un_comune(codice):
    assert comune_per_codice(codice) is None
