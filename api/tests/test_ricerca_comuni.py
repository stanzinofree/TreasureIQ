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


# --- D-54: disambiguazione nella chat (parola-nel-nome, non solo prima parola) ---
#
# `_comuni_candidati` (treasureiq.chat.respond) è la funzione che il turno di
# chat usa per capire QUANTI comuni sono compatibili col messaggio, prima di
# decidere se chiedere quale. Il bug misurato: confrontando solo la prima
# parola del nome, «pergine» risolveva sempre e solo a Pergine Valsugana (mai
# ambiguo) e «pergine valdarno» ci risolveva ANCORA, perché "valdarno" non è
# la prima parola di "Laterina Pergine Valdarno" e quindi non contava mai.


class _ProviderFinto:
    """Un `LLMProvider` finto: non deve mai vedere le CIFRE del comune, solo
    servire da riempitivo perché `build_chat_answer` chiede un `ChatIntent`
    prima di poter emettere la domanda di disambiguazione."""

    async def aparse(self, *, system, user, output_model):
        from treasureiq.chat.intent import Topic

        return output_model(topic=Topic.SCONOSCIUTO)


def test_pergine_da_solo_e_ambiguo_due_candidati():
    """Prima del fix non era mai ambiguo: risolveva sempre a Valsugana."""
    from treasureiq.chat.respond import _comuni_candidati

    candidati = _comuni_candidati("vivo a Pergine")
    nomi_trovati = {c.nome for c in candidati}
    assert len(candidati) == 2
    assert "Pergine Valsugana" in nomi_trovati
    assert "Laterina Pergine Valdarno" in nomi_trovati


def test_pergine_valdarno_risolve_al_comune_giusto():
    """Prima del fix «pergine valdarno» risolveva ANCORA a Pergine Valsugana:
    solo la prima parola del nome contava, e "valdarno" non lo è mai."""
    from treasureiq.chat.respond import _comuni_candidati

    candidati = _comuni_candidati("sono di pergine valdarno")
    assert len(candidati) == 1
    assert candidati[0].nome == "Laterina Pergine Valdarno"
    assert candidati[0].codice_istat == "051042"


def test_san_vito_lo_capo_risolve_esatto_senza_domanda():
    from treasureiq.chat.respond import _comuni_candidati

    candidati = _comuni_candidati("sono di San Vito lo Capo")
    assert len(candidati) == 1
    assert candidati[0].codice_istat == "081020"


def test_laterina_risolve_esatto_senza_domanda():
    from treasureiq.chat.respond import _comuni_candidati

    candidati = _comuni_candidati("sono di Laterina")
    assert len(candidati) == 1
    assert candidati[0].codice_istat == "051042"


def test_nessun_comune_nominato_non_produce_candidati():
    from treasureiq.chat.respond import _comuni_candidati

    assert _comuni_candidati("che orari ha l'ufficio anagrafe?") == []


def test_pergine_fa_partire_la_domanda_di_disambiguazione(monkeypatch):
    """`_quale_comune` esisteva già ma era dead code: nessun chiamante la
    invocava, quindi l'ambiguità spariva silenziosamente dentro
    `_comune_nominato` (tornava `None`, come "nessun comune nominato").

    `load_provider` è mockato per non dipendere da Ollama in CI: la domanda
    di disambiguazione deve poter partire anche se il modello non è
    raggiungibile, perché nasce dal confronto coi 7.896 comuni ISTAT, non
    da una classificazione del modello.
    """
    import asyncio

    from treasureiq.chat import respond as respond_mod

    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: _ProviderFinto())

    risposta = asyncio.run(
        respond_mod.build_chat_answer(
            message="vivo a Pergine, che agevolazioni ci sono per la mensa?",
            profile=None,
            records=[],
        )
    )

    assert risposta.data_gap == "comune_ambiguo"
    assert risposta.needs_clarification is True
    assert "Pergine Valsugana" in risposta.reply
    assert "Laterina Pergine Valdarno" in risposta.reply


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
