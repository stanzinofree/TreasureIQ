"""Topic BANDI end-to-end lato chat (B3, bandi-live-agid, WAVE 2-bis).

`treasureiq.bandi_live.bandi_arricchiti` (B2, gia' atterrato) sonda dal vivo
Amministrazione Trasparente e non e' toccato qui: viene sempre mockato con
`mock.patch` sul modulo REALE (`treasureiq.bandi_live.bandi_arricchiti`),
esattamente come lo chiamera' `respond.py` — se qui si patchasse un nome
importato con un `from ... import`, il mock non intercetterebbe nulla.

Copre due cose distinte:
1. Routing dell'intento: "bandi"/"avviso pubblico"/"graduatoria" -> BANDI, ma
   "bandi per i mezzi pubblici" resta TRASPORTO_PUBBLICO (la guardia che
   prima di B3 non esisteva affatto — era solo un commento sull'enum). Le
   trappole gia' presidiate su comune (bolletta, minori) restano intatte.
2. Il ramo di risposta: testo FISSO non-LLM per ciascun esito di
   `BandiLiveEsito`, mai una cifra nel testo — criteri/importi viaggiano solo
   nel payload strutturato `ChatAnswer.bandi_live` — e degradazione onesta se
   la sonda solleva.
"""

from __future__ import annotations

import asyncio
from unittest import mock

from treasureiq.bandi_live import BandiLiveEsito, BandoArricchito
from treasureiq.chat import respond as respond_mod
from treasureiq.chat.intent import (
    ChatIntent,
    QuestionKind,
    Topic,
    _e_bando_di_trasporto_pubblico,
    extract_intent,
)
from treasureiq.schema import CitizenProfile, Opportunity


class _ModelloFinto:
    """Restituisce l'intento che il modello *avrebbe* prodotto, cosi' le
    guardie deterministiche si possono provare a valle senza un modello vero
    (stesso idioma di `test_intent_guardie.py`)."""

    def __init__(self, intento: ChatIntent) -> None:
        self._intento = intento

    async def aparse(self, *, system, user, output_model):
        return self._intento


def _estrai(messaggio: str, intento: ChatIntent, storia=None) -> ChatIntent:
    return asyncio.run(
        extract_intent(message=messaggio, provider=_ModelloFinto(intento), storia=storia)
    )


# --- 1. Routing dell'intento -------------------------------------------------


def test_che_bandi_ci_sono_risolve_bandi():
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)
    intento = _estrai("che bandi ci sono?", modello)
    assert intento.topic is Topic.BANDI


def test_avvisi_pubblici_del_comune_risolve_bandi():
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)
    intento = _estrai("avvisi pubblici del comune", modello)
    assert intento.topic is Topic.BANDI


def test_guardia_bandi_trasporto_pubblico():
    """«bandi per i mezzi pubblici» nomina "bandi" ma parla di abbonamenti al
    TPL: anche se il modello (qui finto) sceglie BANDI, la guardia deve
    riportarlo a TRASPORTO_PUBBLICO."""
    modello_sbaglia = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)
    intento = _estrai("bandi per i mezzi pubblici", modello_sbaglia)
    assert intento.topic is Topic.TRASPORTO_PUBBLICO

    intento2 = _estrai("bandi trasporto pubblico", modello_sbaglia)
    assert intento2.topic is Topic.TRASPORTO_PUBBLICO


def test_guardia_bandi_trasporto_non_scatta_senza_le_due_parole():
    """Un vero BANDI, senza parole di trasporto pubblico nel testo, non deve
    essere toccato dalla guardia."""
    assert _e_bando_di_trasporto_pubblico("che bandi ci sono?") is False
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)
    intento = _estrai("che bandi ci sono in comune?", modello)
    assert intento.topic is Topic.BANDI


def test_trappola_bolletta_intatta():
    """La trappola gia' presidiata su sostegno_utenze non deve muoversi con
    l'aggiunta di BANDI al catalogo."""
    modello = ChatIntent(topic=Topic.SOSTEGNO_UTENZE, kind=QuestionKind.AGEVOLAZIONE)
    intento = _estrai("ho la bolletta troppo alta", modello)
    assert intento.topic is Topic.SOSTEGNO_UTENZE
    assert _e_bando_di_trasporto_pubblico("ho la bolletta troppo alta") is False


def test_trappola_minori_intatta_nella_ricerca_comuni():
    """«minori» (i bambini) non deve risolvere al comune Minori (SA) neanche
    in una frase che nomina anche "bandi"."""
    from treasureiq.chat.respond import _comuni_candidati

    candidati = _comuni_candidati("che bandi ci sono per i minori disabili?")
    nomi = {c.nome for c in candidati}
    assert "Minori" not in nomi


# --- 2. Il ramo di risposta ---------------------------------------------------


def _bando(titolo: str) -> BandoArricchito:
    return BandoArricchito(
        opportunity=Opportunity.model_construct(title=titolo),
        scadenza=None,
        scadenza_verificata=False,
    )


def _profilo_albano() -> CitizenProfile:
    return CitizenProfile(
        comune_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
    )


def _componi(messaggio: str, intento: ChatIntent, *, profile=None, comune_istat=None):
    provider = _ModelloFinto(intento)
    with mock.patch.object(respond_mod, "load_provider", lambda **_: provider):
        return asyncio.run(
            respond_mod._componi_risposta(
                message=messaggio,
                profile=profile,
                records=[],
                comune_istat=comune_istat,
            )
        )


def test_ramo_coperto_con_bandi_usa_il_comune_del_profilo_non_il_testo():
    """Il profilo ha gia' un comune (Albano): anche se il testo nominasse un
    comune diverso, la sonda deve girare sul comune del profilo (memoria
    «ricerca live cieca al comune di profilo»)."""
    esito = BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="coperto_con_bandi",
        gradino="cpt",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[_bando("Avviso pubblico contributi 2026")],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch(
        "treasureiq.bandi_live.bandi_arricchiti", return_value=esito
    ) as sonda:
        answer = _componi(
            "che bandi ci sono a Roma?",
            modello,
            profile=_profilo_albano(),
        )

    sonda.assert_called_once_with(respond_mod.DEFAULT_COMUNE_ISTAT)
    assert answer.topic is Topic.BANDI
    assert "Amministrazione Trasparente" in answer.reply
    assert respond_mod.DEFAULT_COMUNE_NOME in answer.reply
    assert "2026-08-08T09:30:00+00:00" in answer.reply
    # Il payload strutturato porta i bandi, il testo no.
    assert answer.bandi_live is esito
    assert answer.bandi_live.bandi[0].opportunity.title == "Avviso pubblico contributi 2026"


def test_ramo_coperto_senza_bandi_ha_variante_di_testo():
    esito = BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="coperto_senza_bandi",
        gradino="pages",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        answer = _componi("che bandi ci sono?", modello, profile=_profilo_albano())

    assert "Amministrazione Trasparente" in answer.reply
    assert "nessun bando" in answer.reply.lower()
    assert answer.bandi_live.bandi == []


def test_ramo_non_coperto_e_testo_advocacy():
    esito = BandiLiveEsito(
        codice_istat="999999",
        comune_nome="Comune Fuori Copertura",
        esito="non_coperto",
        gradino=None,
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)
    profilo = CitizenProfile(comune_istat="999999", comune_nome="Comune Fuori Copertura")

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        answer = _componi("che bandi ci sono?", modello, profile=profilo)

    testo = answer.reply.lower()
    assert "non pubblica" in testo or "apertura" in testo
    assert "amministrazione trasparente" not in testo
    assert answer.data_gap is not None


def test_bandi_live_giu_da_risposta_degradata_onesta():
    """La sonda solleva (portale irraggiungibile): nessuna eccezione deve
    arrivare al cittadino."""
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch(
        "treasureiq.bandi_live.bandi_arricchiti", side_effect=RuntimeError("portale giu'")
    ):
        answer = _componi("che bandi ci sono?", modello, profile=_profilo_albano())

    assert answer.topic is Topic.BANDI
    assert answer.bandi_live is None
    assert answer.reply  # una frase, non un'eccezione propagata


def test_bandi_senza_riscontro_testuale_non_chiama_la_sonda():
    """Guardia difensiva (memoria «topic del modello serve riscontro»): se il
    modello etichetta BANDI ma il testo non lo sostiene, la sonda di rete non
    deve partire."""
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti") as sonda:
        _componi("buongiorno, avrei una domanda", modello, profile=_profilo_albano())

    sonda.assert_not_called()


# --- 3. Zero regressione sui topic esistenti ---------------------------------


def test_topic_esistente_non_passa_dal_ramo_bandi():
    """Un topic gia' esistente (SOSTEGNO_UTENZE) non deve mai svegliare la
    sonda bandi-live: il ramo BANDI e' condizionato sul topic, non un
    fallback generico."""
    modello = ChatIntent(topic=Topic.SOSTEGNO_UTENZE, kind=QuestionKind.AGEVOLAZIONE)

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti") as sonda:
        answer = _componi("ho la bolletta troppo alta", modello, profile=_profilo_albano())

    sonda.assert_not_called()
    assert answer.topic is Topic.SOSTEGNO_UTENZE


def test_categoria_per_topic_include_bandi():
    """`Topic.BANDI` deve avere una categoria come ogni altro topic (stesso
    invariante di `test_categoria_per_topic_e_totale`), altrimenti sparirebbe
    silenziosamente dalla modalita' 'tutte' (D-55)."""
    from treasureiq.chat.categorie import CATEGORIA_PER_TOPIC

    assert Topic.BANDI in CATEGORIA_PER_TOPIC
