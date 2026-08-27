"""Routing NLP dell'intento «responsabile/referente» dello sportello.

Il difetto misurato in prod (Albano/Ariccia): «chi è il responsabile
dell'anagrafe» non attivava il drill per-ufficio, perché il trigger richiedeva
o un «ufficio X» letterale (`_ufficio_chiesto`) o la parola «orari». Il
cittadino cadeva sull'URP muto (ramo coperto) o su nessuno sportello (ramo
fuori copertura), mai sull'ufficio dedotto dal topic.

`_richiesta_responsabile` è il marker additivo che chiude il buco: da solo
attiva il drill, che poi deduce l'ufficio DAL TOPIC (`ufficio_chiesto=""`),
senza toccare servizio, modulistica, informativa, né il routing di
orari/ufficio nominato — tutti su condizioni distinte. Questi test bloccano le
due regressioni simmetriche: che il marker NON scatti (buco riaperto) e che
scatti dove non deve (dirottamento di richieste non pertinenti).
"""

from __future__ import annotations

import pytest

from treasureiq.chat.respond import _richiesta_responsabile, _ufficio_chiesto


# --- Positivi: il cittadino chiede la persona/lo sportello di riferimento ---
@pytest.mark.parametrize(
    "messaggio",
    [
        "chi è il responsabile dell'anagrafe",
        "chi e il responsabile dei tributi",  # senza accento, come lo scrivono
        "chi sono i responsabili dell'ufficio tecnico",  # plurale
        "a chi mi rivolgo per il cambio di residenza",
        "a chi rivolgersi per un certificato",
        "chi si occupa delle pratiche edilizie",
        "qual è il referente dell'ufficio tributi",
        "cerco i referenti dei servizi sociali",  # plurale
        "mi serve il contatto dell'ufficio anagrafe",
        "contatto dell ufficio tributi",  # apostrofo perso dalla tastiera
    ],
)
def test_marker_responsabile_scatta_sulle_richieste_di_referente(messaggio):
    assert _richiesta_responsabile(messaggio.lower()) is True


# --- Negativi: richieste NON pertinenti non devono attivare il marker ---
#
# Sono le classi che il drill-responsabile non deve mai intercettare: servizio,
# modulistica, informativa pura, e le formulazioni che già hanno un loro
# routing (orari, ufficio nominato). Se una di queste iniziasse a matchare, il
# marker starebbe dirottando un intento che non gli appartiene.
@pytest.mark.parametrize(
    "messaggio",
    [
        "come rinnovo la carta d'identità",  # servizio/info
        "quanto pago di IMU",  # info tributi
        "dove scarico il modulo per la residenza",  # modulistica
        "modulo per l'accesso agli atti",  # modulistica
        "orari dell'ufficio anagrafe",  # routing «orari»/«ufficio» esistente
        "che orari ha l'ufficio tributi",  # idem
        "quali bandi sono aperti",  # bandi
        "vorrei un certificato di residenza",  # servizio
        "quanto costa la carta d'identità",  # info
    ],
)
def test_marker_responsabile_non_intercetta_richieste_non_pertinenti(messaggio):
    assert _richiesta_responsabile(messaggio.lower()) is False


def test_marker_parola_intera_non_pesca_sottostringhe():
    """`\\b` sulle parole singole: il marker non deve accendersi dentro un'altra
    parola. Nessun toponimo/servizio civico contiene «responsabile»/«referente»
    come sottostringa, ma il confine di parola resta la garanzia esplicita."""
    # confini di parola: «responsabilmente» (avverbio) NON è il sostantivo
    assert _richiesta_responsabile("gestisco tutto responsabilmente") is False


def test_marker_e_ortogonale_a_ufficio_chiesto():
    """I due segnali sono indipendenti e componibili: «responsabile» senza
    «ufficio X» attiva SOLO il marker (il topic dedurrà lo sportello); «ufficio
    tributi» senza referente attiva SOLO `_ufficio_chiesto`. «referente ufficio
    tributi» — il caso che già funzionava — li accende entrambi, e continua a
    funzionare via `_ufficio_chiesto` come prima."""
    solo_marker = "chi è il responsabile dell'anagrafe".lower()
    assert _richiesta_responsabile(solo_marker) is True
    assert _ufficio_chiesto(solo_marker) is None

    solo_ufficio = "orari ufficio tributi".lower()
    assert _richiesta_responsabile(solo_ufficio) is False
    assert _ufficio_chiesto(solo_ufficio) == "tributi"

    entrambi = "referente ufficio tributi".lower()
    assert _richiesta_responsabile(entrambi) is True
    assert _ufficio_chiesto(entrambi) == "tributi"
