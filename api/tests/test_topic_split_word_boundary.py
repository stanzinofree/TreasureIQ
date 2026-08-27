"""Topic-split del drill: match a PAROLA INTERA per i pezzi del topic.

`_ufficio_connettore_pertinente` spezza `topic.value` su «_» e cerca i pezzi nei
nomi d'ufficio. Con il match a sottostringa, «atti» (da `accesso_atti`) pescava
«Attività Produttive - SUAP» — falso positivo osservato in prod su Pomezia: un
intento di accesso agli atti mostrava l'ufficio SUAP (viola «senza uffici
inventati», D-04).

Il fix: i pezzi del topic matchano a confine di parola (`_parola_intera`), così
«atti» ⊄ «attività». L'ufficio nominato dal cittadino e «disabilita» restano a
sottostringa (radici d'Area, es. «finanziari» in «…finanziarie»). Questi test
bloccano le regressioni simmetriche: il falso match che riappare e i match
legittimi (SUAP, anagrafe, parola-intera «atti») che si perdono.
"""

from __future__ import annotations

from treasureiq.chat.intent import Topic
from treasureiq.chat.respond import _parola_intera, _ufficio_connettore_pertinente
from treasureiq.connettore import UfficioConnettore


def _ufficio(nome: str) -> UfficioConnettore:
    return UfficioConnettore(
        nome=nome,
        url="https://example.comune.it/uo/" + nome[:8],
        source_typed=False,
        letto_il="2026-08-27T00:00:00+00:00",
    )


# Set d'uffici in stile Pomezia (Municipium non mappato → drill normale):
# c'è «Attività Produttive - SUAP», NON un ufficio «atti».
def _uffici_pomezia() -> list[UfficioConnettore]:
    return [
        _ufficio("Attività Produttive - SUAP"),
        _ufficio("Area I – Programmazione e Controllo attività economiche e finanziarie"),
        _ufficio("Servizio Anagrafe"),
    ]


# --- Il bug: «atti» ⊄ «attività» ---


def test_accesso_atti_non_pesca_attivita_produttive():
    """Accesso agli atti ≠ Attività Produttive: nessun ufficio dimostrabile →
    fallback onesto, non l'ufficio SUAP sbagliato."""
    ufficio, ambigui = _ufficio_connettore_pertinente(
        _uffici_pomezia(), ufficio_chiesto=None, topic=Topic.ACCESSO_ATTI
    )
    assert ufficio is None
    assert ambigui == []


def test_atti_non_matcha_attivita_a_livello_helper():
    """La primitiva: «atti» come parola intera non è dentro «attività»."""
    assert not _parola_intera("atti", "attività produttive - suap")
    assert not _parola_intera("atti", "area i – attività economiche e finanziarie")


def test_atti_matcha_ufficio_atti_vero():
    """Un ufficio che nomina davvero gli «atti» come parola intera resta
    agganciabile: il fix stringe il match, non lo spegne."""
    uffici = [
        _ufficio("Ufficio Atti e Notifiche"),
        _ufficio("Attività Produttive - SUAP"),
    ]
    ufficio, ambigui = _ufficio_connettore_pertinente(
        uffici, ufficio_chiesto=None, topic=Topic.ACCESSO_ATTI
    )
    assert ufficio is not None
    assert ufficio.nome == "Ufficio Atti e Notifiche"
    assert ambigui == []


# --- I match legittimi di «attività»/SUAP restano funzionanti ---


def test_suap_imprese_aggancia_sportello_suap():
    """Topic `suap_imprese` → pezzo «suap» a parola intera aggancia
    «Attività Produttive - SUAP»."""
    ufficio, ambigui = _ufficio_connettore_pertinente(
        _uffici_pomezia(), ufficio_chiesto=None, topic=Topic.SUAP_IMPRESE
    )
    assert ufficio is not None
    assert ufficio.nome == "Attività Produttive - SUAP"
    assert ambigui == []


def test_commercio_via_sinonimo_aggancia_suap():
    """Ufficio nominato «commercio» → sinonimi-radice (commerci/attivita
    produttive/suap) agganciano ancora lo sportello Attività Produttive."""
    ufficio, ambigui = _ufficio_connettore_pertinente(
        _uffici_pomezia(), ufficio_chiesto="commercio", topic=Topic.SCONOSCIUTO
    )
    assert ufficio is not None
    assert ufficio.nome == "Attività Produttive - SUAP"
    assert ambigui == []


# --- Regressioni di contorno: la parola intera non stringe i casi normali ---


def test_anagrafe_parola_intera_aggancia_servizio_anagrafe():
    """Il pezzo «anagrafe» a parola intera aggancia «Servizio Anagrafe»: il
    drill normale per anagrafe non regredisce."""
    ufficio, ambigui = _ufficio_connettore_pertinente(
        _uffici_pomezia(), ufficio_chiesto=None, topic=Topic.ANAGRAFE_CARTA_IDENTITA
    )
    assert ufficio is not None
    assert ufficio.nome == "Servizio Anagrafe"
    assert ambigui == []


def test_ufficio_chiesto_resta_a_sottostringa_radice_area():
    """L'ufficio nominato dal cittadino resta a sottostringa: «finanziari»
    (radice) deve agganciare «…finanziarie», che la parola intera perderebbe."""
    ufficio, ambigui = _ufficio_connettore_pertinente(
        _uffici_pomezia(), ufficio_chiesto="finanziari", topic=Topic.SCONOSCIUTO
    )
    assert ufficio is not None
    assert ufficio.nome.startswith("Area I")
    assert ambigui == []


def test_parola_intera_helper_positivi():
    """Confini legittimi: inizio/fine token, trattini e spazi come confine."""
    assert _parola_intera("suap", "attività produttive - suap")
    assert _parola_intera("anagrafe", "servizio anagrafe")
    assert _parola_intera("polizia", "area iii - polizia locale")
