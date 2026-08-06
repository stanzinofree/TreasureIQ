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


def test_radice_aggancia_il_plurale_che_il_cittadino_scrive():
    """«asili nido» non conteneva la chiave «asilo», «agevolazioni» non
    conteneva «agevolazione» — e il cittadino scrive al plurale molto piu'
    spesso di quanto scriva al singolare."""
    from treasureiq.chat.respond import _keyword_hit

    assert _keyword_hit(haystack="cerco asili nido comunali", keywords=("asilo",))
    assert _keyword_hit(haystack="quali agevolazioni ci sono", keywords=("agevolazione",))
    assert _keyword_hit(haystack="contributi per le famiglie", keywords=("contributo",))


def test_la_radice_non_smonta_le_distinzioni_che_contano():
    """Le confusioni che questa funzione esiste per evitare devono
    sopravvivere al confronto per radice.

    `tari` sta a `tar` come `tariffa` sta a `tariff`, e `tributi` sta a `trib`
    come `contributi` sta a `contrib`: restano parole diverse. Se un giorno lo
    stemmer cambiasse comportamento, questo test cade prima che cada un
    cittadino sulla risposta sbagliata.
    """
    from treasureiq.chat.respond import _keyword_hit

    assert not _keyword_hit(haystack="qual e' la tariffa dello scuolabus", keywords=("tari",))
    assert not _keyword_hit(haystack="ci sono contributi per il nido", keywords=("tributi",))


def test_le_radici_troppo_corte_non_agganciano():
    """Sotto le tre lettere una radice non distingue piu' niente: «di», «un» e
    «al» aggancerebbero qualunque frase."""
    from treasureiq.chat.respond import _radici

    assert "di" not in _radici("di un al")


def test_le_opportunita_scadute_non_arrivano_al_cittadino():
    """Un bando scaduto non e' un'informazione incompleta: e' un falso positivo
    che fa perdere tempo a chi ne ha meno.

    Chi legge «Voucher asilo nido 2025» non ha modo di sapere, dalla scheda,
    che il termine e' passato otto mesi fa.
    """
    from datetime import date, timedelta

    from treasureiq.chat.respond import _senza_scadute
    from treasureiq.schema import Opportunity

    def finta(nome, scadenza):
        return Opportunity.model_construct(title=nome, deadline=scadenza)

    ieri = date.today() - timedelta(days=1)
    domani = date.today() + timedelta(days=1)
    tenute = _senza_scadute(
        [finta("scaduto", ieri), finta("aperto", domani), finta("senza scadenza", None)]
    )
    assert [o.title for o in tenute] == ["aperto", "senza scadenza"]


def test_senza_scadenza_si_mostra_lo_stesso():
    """Scadenza assente vuol dire due cose diverse — sempre aperto, oppure non
    pubblicata. Nel dubbio si mostra: nascondere qualcosa che potrebbe
    spettare e' un danno peggiore che mostrare qualcosa di incerto."""
    from treasureiq.chat.respond import _senza_scadute
    from treasureiq.schema import Opportunity

    senza = Opportunity.model_construct(title="sempre aperto", deadline=None)
    assert _senza_scadute([senza]) == [senza]


def test_eta_e_isee_letti_dal_testo_senza_modello():
    """«ho 38 anni» restava fuori dal profilo, e la scheda continuava a
    chiedere l'eta' alla persona che l'aveva appena scritta.

    E' la stessa regola che vale per le soglie nei verdetti: le cifre non le
    produce il modello — qui vale anche in ingresso.
    """
    from treasureiq.chat.intent import slot_dal_testo

    assert slot_dal_testo("ho 38 anni e sono di pergine")["eta"] == 38
    assert slot_dal_testo("sono un 38enne")["eta"] == 38
    assert slot_dal_testo("isee 12.000 euro")["isee"] == 12000.0
    assert slot_dal_testo("il mio isee e' 9.360,50")["isee"] == 9360.50


def test_numeri_che_non_sono_eta_restano_fuori():
    """Oltre i 130 non e' un'eta': e' un importo o un numero civico finito
    accanto alla parola sbagliata."""
    from treasureiq.chat.intent import slot_dal_testo

    assert "eta" not in slot_dal_testo("ho 999 anni")
    assert slot_dal_testo("nessun numero qui") == {}


def test_anno_passato_nel_titolo_va_in_fondo_non_via():
    """Il comune non pubblica la scadenza, quindi dire che il bando e' chiuso
    sarebbe una deduzione nostra. Ma «Voucher asilo nido 2025» in agosto 2026
    non e' una proposta seria da mettere per prima.

    L'anno si legge, non si indovina: e' la differenza fra riferire cio' che
    il comune ha pubblicato e concludere qualcosa al posto suo.
    """
    from treasureiq.chat.respond import _senza_scadute
    from treasureiq.schema import Opportunity

    vecchio = Opportunity.model_construct(title="Voucher asilo nido 2025", deadline=None)
    nuovo = Opportunity.model_construct(title="Voucher conciliazione 2026", deadline=None)
    senza_anno = Opportunity.model_construct(title="Contributo affitto", deadline=None)

    ordinate = _senza_scadute([vecchio, nuovo, senza_anno])
    assert ordinate[-1] is vecchio, "l'anno passato va in fondo"
    assert len(ordinate) == 3, "in fondo, non via: la scadenza non e' pubblicata"


def test_misura_regionale_di_un_altra_regione_non_arriva():
    """A Malvagna (Sicilia) veniva offerta un'agevolazione della Regione Lazio.

    E' lo stesso errore del comune sbagliato con un'etichetta piu' grande
    davanti: informazioni di un altro territorio, presentate come proprie.
    """
    from treasureiq.chat.respond import _senza_regioni_altrui
    from treasureiq.schema import Livello, Opportunity

    lazio = Opportunity.model_construct(title="SIRGAT", livello=Livello.REGIONALE, regione="Lazio")
    nazionale = Opportunity.model_construct(title="Bonus", livello=Livello.NAZIONALE, regione=None)
    comunale = Opportunity.model_construct(title="Nido", livello=Livello.COMUNALE, regione=None)

    tenute = _senza_regioni_altrui([lazio, nazionale, comunale], regione="Sicilia")
    assert [o.title for o in tenute] == ["Bonus", "Nido"]

    # Nel Lazio la stessa misura resta.
    assert lazio in _senza_regioni_altrui([lazio], regione="Lazio")


def test_regione_sconosciuta_non_nasconde_niente():
    """Nascondere una misura che potrebbe spettare e' peggio che mostrarne una
    che non riguarda: l'ente che la pubblica e' scritto sulla scheda."""
    from treasureiq.chat.respond import _senza_regioni_altrui
    from treasureiq.schema import Livello, Opportunity

    lazio = Opportunity.model_construct(title="SIRGAT", livello=Livello.REGIONALE, regione="Lazio")
    assert _senza_regioni_altrui([lazio], regione=None) == [lazio]
