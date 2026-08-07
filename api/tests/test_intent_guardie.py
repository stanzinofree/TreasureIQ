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

import asyncio

import pytest

from treasureiq.chat.intent import (
    ChatIntent,
    ProfileSlots,
    QuestionKind,
    Topic,
    _confirm_comune_hint,
    _disabilita_dichiarata_nel_testo,
    extract_intent,
)


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


# --- D-47: contesto multi-turno --------------------------------------------
#
# «ci sono agevolazioni per la mensa ad Albano?» seguito da un turno che non
# nomina di nuovo ne' l'argomento ne' il comune deve comunque arrivare a
# un'intenzione completa, senza richiedere il comune una seconda volta. Il
# topic pero' non si eredita mai fidandosi solo del modello (D-47 hard rule):
# si eredita solo se le sue parole compaiono per davvero nella storia.


class _ProviderFinto:
    """Un `LLMProvider` finto: risponde in base a quale messaggio riconosce
    nel prompt (che include il turno da classificare, sempre in coda),
    cosi' il riestrazione dei turni passati (`_eredita_dal_contesto`) puo'
    essere testata senza un modello vero."""

    def __init__(self, risposte: dict[str, ChatIntent]):
        self._risposte = risposte

    async def aparse(self, *, system, user, output_model):
        for frammento, intent in self._risposte.items():
            if frammento in user:
                return intent
        return output_model(topic=Topic.SCONOSCIUTO)


def test_topic_si_eredita_solo_se_le_sue_parole_sono_nella_storia():
    """Corroborazione deterministica: nessun modello coinvolto."""
    from treasureiq.chat.respond import _topic_da_storia

    assert (
        _topic_da_storia(storia=["ci sono agevolazioni per la mensa ad Albano?"])
        == Topic.MENSA_SCOLASTICA
    )
    assert _topic_da_storia(storia=["buongiorno, avrei una domanda"]) is None


def test_il_turno_successivo_eredita_argomento_e_comune_senza_richiederlo():
    """«ci sono agevolazioni per la mensa ad Albano?» poi «e gli orari
    dell'ufficio?» — il secondo turno non nomina ne' la mensa ne' Albano, ma
    deve risolvere entrambi dalla storia, senza richiedere di nuovo il
    comune."""
    import asyncio

    from treasureiq.chat.respond import _eredita_dal_contesto

    primo_turno = "ci sono agevolazioni per la mensa ad Albano Laziale?"
    provider = _ProviderFinto(
        {primo_turno: ChatIntent(topic=Topic.MENSA_SCOLASTICA, comune_hint="Albano Laziale")}
    )

    ereditato = asyncio.run(
        _eredita_dal_contesto(
            intent=ChatIntent(topic=Topic.SCONOSCIUTO),
            messaggio="e gli orari dell'ufficio?",
            storia=[primo_turno],
            provider=provider,
        )
    )

    assert ereditato.topic is Topic.MENSA_SCOLASTICA
    assert ereditato.comune_hint == "Albano Laziale"


def test_le_cifre_non_si_ereditano_mai_dalla_storia():
    """Guardia: un'eta' detta due turni fa non deve attaccarsi in silenzio a
    una domanda di oggi che non la ripete."""
    import asyncio

    from treasureiq.chat.intent import ChatIntent, ProfileSlots, extract_intent

    turno_precedente = "ho 38 anni e vivo a Pergine"
    # Il modello finto simula proprio il difetto da cui ci si guarda: rilegge
    # l'eta' dal contesto anche se il messaggio corrente non la ripete.
    provider = _ProviderFinto(
        {
            turno_precedente: ChatIntent(
                topic=Topic.SOSTEGNO_UTENZE, slots=ProfileSlots(eta=38)
            )
        }
    )

    intent = asyncio.run(
        extract_intent(
            message="quali sono gli orari dell'ufficio anagrafe?",
            provider=provider,
            storia=[turno_precedente],
        )
    )

    assert intent.slots.eta is None


# --- D-52/D-53: profilo esteso (sesso, figlio disabile) --------------------


def test_sesso_dichiarato_esplicitamente_vince():
    """«sono una donna di 38 anni»: dichiarazione esplicita, non deduzione
    dal nome — il modello (finto qui) la mette in `slots.sesso`, e
    `_profile_from_slots` la passa intatta al profilo."""
    from treasureiq.chat.intent import ChatIntent, ProfileSlots, Topic
    from treasureiq.chat.respond import _profile_from_slots

    intent = ChatIntent(
        topic=Topic.SOSTEGNO_UTENZE, slots=ProfileSlots(sesso="f", eta=38)
    )
    profilo = _profile_from_slots(intent=intent, messaggio="sono una donna di 38 anni")
    assert profilo.sesso == "f"
    assert profilo.eta == 38


def test_sesso_dedotto_dal_nome_curato():
    """«ciao sono Alessia»: nessuna dichiarazione esplicita nello slot, ma il
    nome e' nella lista curata — deduzione a bassa confidenza, sempre
    correggibile nell'eco (mai un filtro nascosto)."""
    from treasureiq.chat.intent import ChatIntent, ProfileSlots, Topic
    from treasureiq.chat.nomi_genere import sesso_da_nome
    from treasureiq.chat.respond import _profile_from_slots

    assert sesso_da_nome("ciao sono Alessia, ho 38 anni") == "f"

    intent = ChatIntent(topic=Topic.SOSTEGNO_UTENZE, slots=ProfileSlots())
    profilo = _profile_from_slots(intent=intent, messaggio="ciao sono Alessia, ho 38 anni")
    assert profilo.sesso == "f"


def test_nome_fuori_lista_non_deduce_niente():
    """Un nome assente dalla lista curata resta `None`: nessun ripiego sul
    suffisso italiano."""
    from treasureiq.chat.nomi_genere import sesso_da_nome

    assert sesso_da_nome("ciao sono Zephyrion, ho 40 anni") is None


def test_nessuna_deduzione_dal_suffisso_andrea_nicola():
    """Andrea e Nicola sono nomi maschili che finiscono per "-a": la prova
    che questo modulo non usa il suffisso come scorciatoia."""
    from treasureiq.chat.nomi_genere import sesso_da_nome

    assert sesso_da_nome("sono Andrea, 40 anni") == "m"
    assert sesso_da_nome("sono Nicola, 40 anni") == "m"


def test_figlio_disabile_normalizza_disabilita_nucleo():
    """`figli_disabili > 0` implica `disabilita_nucleo=True`, normalizzato
    in `_profile_from_slots` (D-53), non nel motore."""
    from treasureiq.chat.intent import ChatIntent, ProfileSlots, Topic
    from treasureiq.chat.respond import _profile_from_slots

    intent = ChatIntent(
        topic=Topic.SOSTEGNO_UTENZE, slots=ProfileSlots(figli_disabili=1)
    )
    profilo = _profile_from_slots(intent=intent, messaggio="ho un figlio disabile")
    assert profilo.disabilita_nucleo is True
    assert profilo.figli_disabili == 1


def test_figlio_disabile_senza_eta_fa_partire_la_domanda_minore():
    """Dichiarato un figlio disabile senza dire se e' minorenne, la chat
    chiede — needs_clarification=True, analogo a `_quale_comune` — invece
    di assumere in silenzio."""
    import asyncio

    from treasureiq.chat import respond as respond_mod
    from treasureiq.chat.intent import ChatIntent, ProfileSlots, QuestionKind, Topic

    messaggio = "sono Alessia, 38 anni, famiglia di 4, figlio disabile, vivo ad Albano Laziale"
    provider = _ProviderFinto(
        {
            messaggio: ChatIntent(
                topic=Topic.SOSTEGNO_UTENZE,
                kind=QuestionKind.AGEVOLAZIONE,
                comune_hint="Albano Laziale",
                slots=ProfileSlots(
                    sesso="f",
                    eta=38,
                    nucleo_familiare=4,
                    disabilita_nucleo=True,
                ),
            )
        }
    )

    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: provider)
    try:
        answer = asyncio.run(
            respond_mod._componi_risposta(
                message=messaggio,
                profile=None,
                records=[],
            )
        )
    finally:
        monkeypatch.undo()

    assert answer.needs_clarification is True
    assert "minorenne" in answer.reply or "maggiorenne" in answer.reply


# --- D-55: categorie, tutte o una -------------------------------------------


def test_categoria_per_topic_e_totale():
    """Ogni `Topic` tranne `SCONOSCIUTO` deve avere una categoria: un topic
    dimenticato sparirebbe silenziosamente dalla modalita' 'tutte'."""
    from treasureiq.chat.categorie import CATEGORIA_PER_TOPIC
    from treasureiq.chat.intent import Topic

    attesi = set(Topic) - {Topic.SCONOSCIUTO}
    assert set(CATEGORIA_PER_TOPIC.keys()) == attesi


def test_categoria_richiesta_riconosce_tutte_e_le_tre_categorie():
    from treasureiq.chat.categorie import Categoria
    from treasureiq.chat.respond import _categoria_richiesta

    assert _categoria_richiesta("tutte") == "tutte"
    assert _categoria_richiesta("tutte le categorie per favore") == "tutte"
    assert _categoria_richiesta("utenze") is Categoria.UTENZE
    assert _categoria_richiesta("direi mezzi") is Categoria.MEZZI
    assert _categoria_richiesta("assegni") is Categoria.ASSEGNI


def test_categoria_richiesta_ignora_una_domanda_vera():
    """Una domanda vera che nomina 'mezzi' di sfuggita non e' la risposta
    alla domanda categoria — deve restare `None` e proseguire nel flusso a
    singolo topic."""
    from treasureiq.chat.respond import _categoria_richiesta

    assert (
        _categoria_richiesta("quali agevolazioni ci sono per i mezzi pubblici comunali?")
        is None
    )
    assert _categoria_richiesta("buongiorno, avrei una domanda") is None


def test_profilo_ricco_e_topic_sconosciuto_chiede_la_categoria():
    """D-55: turno AGEVOLAZIONE, profilo gia' ricco (>=2 slot anagrafici),
    topic sconosciuto/generico ('che bonus posso avere?') → la chat chiede
    tutte le categorie o una in particolare, invece del generico 'non ho
    capito'."""
    import asyncio

    from treasureiq.chat import respond as respond_mod
    from treasureiq.chat.intent import ChatIntent, ProfileSlots, QuestionKind, Topic

    messaggio = "che bonus posso avere?"
    provider = _ProviderFinto(
        {
            messaggio: ChatIntent(
                topic=Topic.SCONOSCIUTO,
                kind=QuestionKind.AGEVOLAZIONE,
                slots=ProfileSlots(eta=38, nucleo_familiare=4),
            )
        }
    )

    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: provider)
    try:
        answer = asyncio.run(
            respond_mod._componi_risposta(message=messaggio, profile=None, records=[])
        )
    finally:
        monkeypatch.undo()

    assert answer.needs_clarification is True
    assert answer.matches == []
    testo = answer.reply.lower()
    assert "categoria" in testo or "tutte" in testo
    assert "utenze" in testo and "mezzi" in testo and "assegni" in testo


def test_tutte_le_categorie_produce_match_multi_topic():
    """D-55: 'tutte' cerca su TUTTI i record del comune (stesso ranker
    dell'endpoint /api/opportunities), non su un solo topic — verificato sul
    seed Albano committato, dove i risultati devono coprire piu' di un
    topic."""
    import asyncio

    from treasureiq.api import load_opportunities
    from treasureiq.chat import respond as respond_mod
    from treasureiq.chat.intent import (
        AMBIGUOUS_ROLE_TOPICS,
        TOPIC_KEYWORDS,
        ChatIntent,
        QuestionKind,
        Topic,
    )
    from treasureiq.chat.respond import DEFAULT_COMUNE_ISTAT, _keyword_hit
    from treasureiq.schema import CitizenProfile

    messaggio = "tutte"
    provider = _ProviderFinto(
        {messaggio: ChatIntent(topic=Topic.SCONOSCIUTO, kind=QuestionKind.AGEVOLAZIONE)}
    )
    profilo = CitizenProfile(
        comune_istat=DEFAULT_COMUNE_ISTAT,
        comune_nome="Albano Laziale",
        eta=38,
        nucleo_familiare=4,
    )
    records = list(load_opportunities(DEFAULT_COMUNE_ISTAT))
    assert records, "il seed Albano committato non puo' essere vuoto"

    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: provider)
    try:
        answer = asyncio.run(
            respond_mod._componi_risposta(message=messaggio, profile=profilo, records=records)
        )
    finally:
        monkeypatch.undo()

    assert answer.needs_clarification is False
    assert len(answer.matches) >= 2

    def topic_dei(opportunity) -> set[Topic]:
        haystack = " ".join(
            p for p in (opportunity.title, opportunity.summary, opportunity.body) if p
        ).lower()
        trovati = set()
        for topic in Topic:
            if topic is Topic.SCONOSCIUTO:
                continue
            if _keyword_hit(haystack=haystack, keywords=TOPIC_KEYWORDS.get(topic, ())):
                trovati.add(topic)
        return trovati

    topics_coperti: set[Topic] = set()
    for match_result in answer.matches:
        topics_coperti |= topic_dei(match_result.opportunity)
    assert len(topics_coperti) >= 2


def test_categoria_scelta_filtra_ai_topic_della_categoria():
    """D-55: con una categoria scelta, i candidati si limitano ai `Topic` di
    quella categoria PRIMA del ranking — mai al topic singolo dell'ultimo
    turno e mai a tutto il comune."""
    import asyncio

    from treasureiq.api import load_opportunities
    from treasureiq.chat import respond as respond_mod
    from treasureiq.chat.categorie import Categoria, topics_di
    from treasureiq.chat.intent import TOPIC_KEYWORDS, ChatIntent, QuestionKind, Topic
    from treasureiq.chat.respond import DEFAULT_COMUNE_ISTAT, _keyword_hit
    from treasureiq.schema import CitizenProfile

    messaggio = "utenze"
    provider = _ProviderFinto(
        {messaggio: ChatIntent(topic=Topic.SCONOSCIUTO, kind=QuestionKind.AGEVOLAZIONE)}
    )
    profilo = CitizenProfile(
        comune_istat=DEFAULT_COMUNE_ISTAT,
        comune_nome="Albano Laziale",
        eta=38,
        nucleo_familiare=4,
    )
    records = list(load_opportunities(DEFAULT_COMUNE_ISTAT))

    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: provider)
    try:
        answer = asyncio.run(
            respond_mod._componi_risposta(message=messaggio, profile=profilo, records=records)
        )
    finally:
        monkeypatch.undo()

    topics_ammessi = set(topics_di(Categoria.UTENZE))
    for match_result in answer.matches:
        opportunity = match_result.opportunity
        haystack = " ".join(
            p for p in (opportunity.title, opportunity.summary, opportunity.body) if p
        ).lower()
        assert any(
            _keyword_hit(haystack=haystack, keywords=TOPIC_KEYWORDS.get(topic, ()))
            for topic in topics_ammessi
        ), f"'{opportunity.title}' non appartiene alla categoria utenze"


def test_sesso_non_si_eredita_mai_dalla_storia():
    """Come per eta'/isee: un sesso dichiarato due turni fa non deve
    attaccarsi in silenzio a un turno di oggi che non lo ripete."""
    import asyncio

    from treasureiq.chat.intent import ChatIntent, ProfileSlots, extract_intent

    turno_precedente = "sono una donna e vivo a Pergine"
    provider = _ProviderFinto(
        {
            turno_precedente: ChatIntent(
                topic=Topic.SOSTEGNO_UTENZE, slots=ProfileSlots(sesso="f")
            )
        }
    )

    intent = asyncio.run(
        extract_intent(
            message="quali sono gli orari dell'ufficio anagrafe?",
            provider=provider,
            storia=[turno_precedente],
        )
    )

    assert intent.slots.sesso is None


def test_eco_anonima_acc1_mostra_i_quattro_fatti_insieme():
    """REVISE round 1: `_profilo_capito` in chat anonima (senza cookie
    CIE/SPID) doveva restare senza `nucleo_familiare` — a differenza di
    eta'/sesso/disabilita_nucleo, non aveva un ripiego dal testo del
    messaggio. «ciao sono Alessia, 38 anni, famiglia di 4, figlio disabile»
    e' la frase letterale di acc1: i quattro fatti devono comparire tutti
    nella risposta, non solo tre su quattro."""
    from treasureiq.api import _profilo_capito

    messaggio = "ciao sono Alessia, 38 anni, famiglia di 4, figlio disabile"
    capito = _profilo_capito(answer=None, profile=None, message=messaggio)

    assert capito.sesso == "f"
    assert capito.sesso_dedotto is True
    assert capito.eta == 38
    assert capito.nucleo_familiare == 4
    assert capito.disabilita_nucleo is True


def test_eco_anonima_disabilita_propria_dal_testo():
    """`_profilo_capito` in chat anonima doveva mostrare la disabilita' del
    cittadino stesso quando la dichiara a voce: era l'unico slot anagrafico
    letto solo dal cookie, quindi per un anonimo restava sempre vuoto anche
    se `extract_intent` l'aveva colto. «ho 23 anni e sono disabile di san
    vito lo capo» e' la frase letterale del bug segnalato live: la disabilita'
    deve comparire nel profilo a lato, non solo l'eta'."""
    from treasureiq.api import _profilo_capito

    messaggio = "ho 23 anni e sono disabile di san vito lo capo, ho bonus?"
    capito = _profilo_capito(answer=None, profile=None, message=messaggio)

    assert capito.eta == 23
    assert capito.disabilita is True
    # la disabilita' propria non deve sconfinare nel nucleo (e' un'altra cosa)
    assert capito.disabilita_nucleo is None


def test_eco_anonima_disabilita_figlio_non_diventa_propria():
    """Il rovescio: «ho un figlio disabile» e' `disabilita_nucleo`, non la
    disabilita' del cittadino. La cessione di precedenza al check figlio in
    `_disabilita_dichiarata_nel_testo` non deve rompere questa distinzione."""
    from treasureiq.api import _profilo_capito

    messaggio = "sono Alessia, 38 anni, ho un figlio disabile"
    capito = _profilo_capito(answer=None, profile=None, message=messaggio)

    assert capito.disabilita_nucleo is True
    assert capito.disabilita is None


def test_cambio_persona_anonimo_riparte_da_profilo_pulito():
    """D-56, path anonimo: «e per mia madre...» non deve trascinare i dati
    della persona del turno precedente nel profilo del turno nuovo.

    Il test prova il meccanismo (strip carry-over in `extract_intent` +
    `_profile_from_slots` per turno), non lo assume: il provider finto
    simula il caso peggiore realistico, un modello che ripete pigramente
    il nucleo familiare del turno prima anche se il turno nuovo non lo
    ridichiara. Se questo test e' verde senza modifiche, il path anonimo
    resetta gia' da solo (B5)."""
    import asyncio

    from treasureiq.chat import respond as respond_mod
    from treasureiq.chat.intent import ChatIntent, ProfileSlots, QuestionKind, Topic, extract_intent

    turno1 = "sono Alessia, 38 anni, di Pergine, famiglia di 4, figlio disabile"
    turno2 = "e per mia madre, 78 anni, disabile, di San Vito lo Capo"

    # Solo il turno 2 viene fatto "interpretare" dal provider finto: il
    # turno 1 serve solo come `storia` (testo grezzo del cittadino), non va
    # ri-mandato al modello qui. Se comparisse anche come chiave del
    # provider finto, `frammento in user` lo troverebbe per primo (il suo
    # testo e' comunque dentro al prompt come storia) e la risposta del
    # turno 2 non verrebbe mai usata.
    provider = _ProviderFinto(
        {
            turno2: ChatIntent(
                topic=Topic.SOSTEGNO_UTENZE,
                kind=QuestionKind.AGEVOLAZIONE,
                comune_hint="San Vito lo Capo",
                # Il modello, qui, sbaglia e ripete ancora il nucleo del
                # turno precedente: e' esattamente cio' che lo strip
                # carry-over deve correggere prima che arrivi al profilo.
                # `disabilita` (non `disabilita_nucleo`, che parla di un
                # figlio) e' la disabilita' della madre stessa.
                slots=ProfileSlots(
                    sesso="f", eta=78, disabilita=True, nucleo_familiare=4
                ),
            ),
        }
    )

    intent2 = asyncio.run(
        extract_intent(message=turno2, provider=provider, storia=[turno1])
    )
    profilo2 = respond_mod._profile_from_slots(intent=intent2, messaggio=turno2)

    assert profilo2.eta == 78
    assert profilo2.disabilita is True
    assert profilo2.nucleo_familiare is None  # niente 4 del turno precedente


def test_cambio_persona_con_sessione_cie_spid_chiede_conferma_senza_azzerare():
    """D-56/R-LOGOUT: con un profilo di sessione (CIE/SPID, cookie) attivo,
    «per mia madre» + dati anagrafici nuovi non deve sostituire in silenzio
    il profilo della sessione. La chat chiede conferma (data_gap=
    "cambio_persona", needs_clarification=True) e NON chiama la dimenticanza
    da sola — lo spy sotto lo verifica esplicitamente."""
    import asyncio
    from unittest.mock import patch

    from treasureiq.chat import respond as respond_mod
    from treasureiq.chat.intent import ChatIntent, ProfileSlots, QuestionKind, Topic
    from treasureiq.schema import CitizenProfile

    messaggio = "e per mia madre, 78 anni, disabile, di San Vito lo Capo?"
    provider = _ProviderFinto(
        {
            messaggio: ChatIntent(
                topic=Topic.SOSTEGNO_UTENZE,
                kind=QuestionKind.AGEVOLAZIONE,
                comune_hint="San Vito lo Capo",
                slots=ProfileSlots(sesso="f", eta=78, disabilita_nucleo=True),
            )
        }
    )
    profilo_sessione = CitizenProfile(
        comune_istat="058091",
        comune_nome="Pergine Valsugana",
        eta=38,
        sesso="f",
    )

    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: provider)
    try:
        with patch(
            "treasureiq.api.dimentica_campo"
        ) as dimentica_spy:
            answer = asyncio.run(
                respond_mod._componi_risposta(
                    message=messaggio,
                    profile=profilo_sessione,
                    records=[],
                )
            )
            dimentica_spy.assert_not_called()
    finally:
        monkeypatch.undo()

    assert answer.needs_clarification is True
    assert answer.data_gap == "cambio_persona"
    assert answer.matches == []


# ---------------------------------------------------------------------------
# Guardie di determinismo NLP scoperte nel test live (San Vito Lo Capo):
# la disabilita' propria non estratta, e «ho bonus?» incollato a un topic.
# Il modello (qwen3:4b) sbaglia; le guardie deterministiche lo correggono.
# ---------------------------------------------------------------------------


class _ModelloFinto:
    """Restituisce l'intento che il modello *avrebbe* prodotto, per provare
    che le guardie deterministiche lo correggono a valle."""

    def __init__(self, intento: ChatIntent) -> None:
        self._intento = intento

    async def aparse(self, *, system, user, output_model):
        return self._intento


def _estrai(messaggio: str, intento: ChatIntent, storia=None) -> ChatIntent:
    return asyncio.run(
        extract_intent(
            message=messaggio,
            provider=_ModelloFinto(intento),
            storia=storia,
        )
    )


def test_disabilita_propria_e_marcata_dal_testo():
    assert _disabilita_dichiarata_nel_testo("ho 23 anni e sono disabile") is True
    assert _disabilita_dichiarata_nel_testo("ho una disabilità certificata") is True
    # «mio figlio disabile» e' il nucleo, non il cittadino: non deve scattare.
    assert _disabilita_dichiarata_nel_testo("mio figlio è disabile") is False


def test_disabilita_propria_recuperata_anche_a_turno_singolo():
    """Il difetto vero, dal test live: «ho 23 anni e sono disabile...» usciva
    con disabilita' persa, senza storia da incolpare."""
    modello_la_manca = ChatIntent(
        topic=Topic.SCONOSCIUTO,
        kind=QuestionKind.AGEVOLAZIONE,
        slots=ProfileSlots(eta=23, disabilita=None),
    )
    intento = _estrai(
        "ho 23 anni e sono disabile di san vito lo capo, ho bonus?",
        modello_la_manca,
    )
    assert intento.slots.disabilita is True


def test_disabilita_non_si_trascina_su_altra_persona():
    """Turno nuovo senza «sono disabile»: se il modello la eredita dal turno
    precedente, la guardia la toglie (D-56)."""
    modello_la_eredita = ChatIntent(
        topic=Topic.SCONOSCIUTO,
        kind=QuestionKind.AGEVOLAZIONE,
        slots=ProfileSlots(eta=80, disabilita=True),
    )
    intento = _estrai(
        "e per mio padre che ha 80 anni?",
        modello_la_eredita,
        storia=["turno precedente su un'altra persona"],
    )
    assert intento.slots.disabilita is None


def test_bonus_generico_torna_a_sconosciuto():
    """«ho bonus?» senza categoria: il modello lo incolla a sostegno_utenze,
    la guardia riporta a SCONOSCIUTO cosi' parte la domanda-categoria (D-55)."""
    modello_inventa = ChatIntent(
        topic=Topic.SOSTEGNO_UTENZE,
        kind=QuestionKind.AGEVOLAZIONE,
        slots=ProfileSlots(eta=23),
    )
    intento = _estrai("ho 23 anni e sono disabile, ho bonus?", modello_inventa)
    assert intento.topic is Topic.SCONOSCIUTO
    assert intento.kind is QuestionKind.AGEVOLAZIONE


def test_bonus_ancorato_a_categoria_non_viene_toccato():
    """«bonus per le bollette» nomina la categoria: resta sostegno_utenze."""
    modello_giusto = ChatIntent(
        topic=Topic.SOSTEGNO_UTENZE,
        kind=QuestionKind.AGEVOLAZIONE,
        slots=ProfileSlots(),
    )
    intento = _estrai("c'è un bonus per le bollette?", modello_giusto)
    assert intento.topic is Topic.SOSTEGNO_UTENZE
