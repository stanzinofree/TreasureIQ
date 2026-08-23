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
from datetime import datetime, timezone
from unittest import mock

import pytest

from treasureiq.bandi_live import BandiLiveEsito, BandoArricchito
from treasureiq.catalog import AccessMode as CatalogAccessMode, DataStatus, Surface
from treasureiq.catalog.contracts import CAPABILITY_NOTICES
from treasureiq.chat import respond as respond_mod
from treasureiq.chat.intent import (
    ChatIntent,
    ProfileSlots,
    QuestionKind,
    Topic,
    _e_bando_di_trasporto_pubblico,
    extract_intent,
)
from treasureiq.schema import (
    CitizenProfile,
    Opportunity,
    Requirements,
    Source,
    TargetGroup,
)


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


_ORA_ISO = datetime.now(timezone.utc).isoformat()  # live-read timestamp (fresh)


def _fake_source(titolo: str) -> Source:
    """Minimal but complete Source — real `bandi_arricchiti` always sets id +
    source, so the notices projection (Ramo 2) relies on them being present."""
    return Source(
        ente="Comune di Test",
        connector="bandi_live_test",
        url=f"https://example.test/bando/{abs(hash(titolo)) % 10_000}",
        fetched_at=datetime(2026, 8, 23, 6, 0, tzinfo=timezone.utc),
        raw_hash="testhash",
    )


def _bando(titolo: str, *, tipo=None) -> BandoArricchito:
    return BandoArricchito(
        opportunity=Opportunity.model_construct(
            id=titolo, title=titolo, source=_fake_source(titolo)
        ),
        scadenza=None,
        scadenza_verificata=False,
        tipo=tipo,
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


def test_gradino_alberatura_e_tipo_bando_arrivano_su_chat_answer():
    """KAPI 8 (bandi-alberatura, B2): `gradino="alberatura"` e il campo
    `tipo` di ogni `BandoArricchito` devono attraversare `respond.py` intatti
    fino a `ChatAnswer.bandi_live` — stesso punto dove L-3 (ciclo 7) e' stato
    rotto da un campo non proiettato. Qui il payload e' lo STESSO oggetto
    (`is esito`), quindi provare l'identita' e i suoi campi basta a
    dimostrare che nulla lo ricompone o lo tronca lungo la strada."""
    esito = BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="coperto_con_bandi",
        gradino="alberatura",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[
            _bando("Contributo affitto", tipo="agevolazione"),
            _bando("Concorso pubblico istruttore", tipo="concorso"),
        ],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        answer = _componi(
            "che bandi ci sono?",
            modello,
            profile=_profilo_albano(),
        )

    assert answer.bandi_live is esito
    assert answer.bandi_live.gradino == "alberatura"
    assert [b.tipo for b in answer.bandi_live.bandi] == ["agevolazione", "concorso"]


def test_primo_turno_senza_profilo_usa_il_comune_nominato_nel_testo():
    """Regressione bug Andrea: «vivo a Benevento, ci sono bandi?» al primo
    turno — nessun profilo ancora, nessun `comune_istat` dal client. Senza il
    ripiego su `_comune_nominato` la sonda cadeva sul default (Albano) e
    leggeva il comune sbagliato. Il profilo resta la prima precedenza (test
    sopra); il testo entra SOLO quando non c'e' ne' profilo ne' scelta."""
    benevento_istat = "062008"
    esito = BandiLiveEsito(
        codice_istat=benevento_istat,
        comune_nome="Benevento",
        esito="coperto_con_bandi",
        gradino="pages",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[_bando("Contributo affitto 2026")],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch(
        "treasureiq.bandi_live.bandi_arricchiti", return_value=esito
    ) as sonda:
        answer = _componi(
            "ciao sono Andrea, vivo a Benevento, ci sono bandi a cui posso accedere?",
            modello,
            profile=None,
            comune_istat=None,
        )

    sonda.assert_called_once_with(benevento_istat)
    assert answer.bandi_live is esito


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


# --- 2-bis. Ranking morbido per profilo (bug Andrea #2) ----------------------


def _bando_req(
    titolo: str,
    *,
    targets=None,
    figli_minori_required=None,
    disabilita_required=None,
    eta_min=None,
    eta_max=None,
) -> BandoArricchito:
    opp = Opportunity.model_construct(
        id=titolo,
        title=titolo,
        source=_fake_source(titolo),
        targets=targets or [],
        summary=None,
        requirements=Requirements(
            figli_minori_required=figli_minori_required,
            disabilita_required=disabilita_required,
            eta_min=eta_min,
            eta_max=eta_max,
        ),
    )
    return BandoArricchito(opportunity=opp, scadenza=None, scadenza_verificata=False)


@pytest.mark.parametrize(
    "testo, atteso",
    [
        ("sono vedovo con 2 figli minorenni, vivo a Benevento", 2),
        ("ho due figli minori", 2),
        ("un figlio minore", 1),
        ("ho figli piccoli", 1),
        ("ho due figli grandi", None),  # adulti: non contano
        ("ho 3 figli maggiorenni", None),
    ],
)
def test_slot_figli_minori_letto_dal_testo_non_dal_modello(testo, atteso):
    """La regex sul testo riempie `figli_minori` senza dipendere dall'LLM
    (che su Ollama spesso non popola lo slot) — e ignora i figli adulti."""
    from treasureiq.chat.intent import slot_dal_testo

    assert slot_dal_testo(testo).get("figli_minori") == atteso


def test_ordina_bandi_porta_in_cima_quelli_che_risuonano_e_non_esclude():
    """Un profilo con 2 figli minori porta il bando figli-minori in cima e lo
    marca `consigliato`, ma NESSUN bando sparisce (ordina, non esclude)."""
    generico = _bando_req("Avviso generico contributi")
    minori = _bando_req(
        "Contributo per famiglie con figli minori",
        targets=[TargetGroup.MINORI],
        figli_minori_required=True,
    )
    profilo = CitizenProfile(figli_minori=2)

    ordinati, c_e_ranking = respond_mod._ordina_bandi_per_profilo(
        [generico, minori], profilo
    )

    assert c_e_ranking is True
    assert len(ordinati) == 2  # niente esclusione
    assert ordinati[0].opportunity.title == "Contributo per famiglie con figli minori"
    assert ordinati[0].consigliato is True
    assert ordinati[1].consigliato is False


def test_ordina_bandi_senza_profilo_o_senza_riscontro_lascia_intatto():
    bandi = [_bando_req("Avviso A"), _bando_req("Avviso B")]

    intatto_no_profilo, r1 = respond_mod._ordina_bandi_per_profilo(bandi, None)
    assert intatto_no_profilo is bandi and r1 is False

    # Profilo che non risuona con nessun requisito: nessun ranking, nessuna
    # bugia di ordinamento — lista intatta.
    intatto_no_match, r2 = respond_mod._ordina_bandi_per_profilo(
        bandi, CitizenProfile(eta=54)
    )
    assert intatto_no_match is bandi and r2 is False


def test_ramo_bandi_ordina_e_dichiara_ranking_indicativo_non_verdetto():
    """Integrazione: Andrea (2 figli minori, primo turno senza profilo) — il
    ramo bandi ricava il profilo dal testo, ordina, e il testo dichiara
    l'ordinamento come indicativo, non un verdetto."""
    esito = BandiLiveEsito(
        codice_istat="062008",
        comune_nome="Benevento",
        esito="coperto_con_bandi",
        gradino="pages",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[
            _bando_req("Avviso pubblico generico 2026"),
            _bando_req(
                "Sostegno alle famiglie con figli minori",
                targets=[TargetGroup.MINORI],
                figli_minori_required=True,
            ),
        ],
    )
    # In produzione i figli minori li estrae il modello (Ollama) negli slot;
    # qui il modello è finto, quindi popoliamo lo slot come farebbe l'LLM.
    modello = ChatIntent(
        topic=Topic.BANDI,
        kind=QuestionKind.INFORMAZIONE,
        slots=ProfileSlots(figli_minori=2),
    )

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        answer = _componi(
            "sono vedovo con 2 figli minorenni, vivo a Benevento, ci sono bandi?",
            modello,
            profile=None,
        )

    titoli = [b.opportunity.title for b in answer.bandi_live.bandi]
    assert titoli[0] == "Sostegno alle famiglie con figli minori"
    assert answer.bandi_live.bandi[0].consigliato is True
    assert "non un verdetto" in answer.reply.lower()


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


# --- 4. Filtro conversazionale per tema (KAPI 9, bandi-conversazionale) -----


@pytest.mark.parametrize(
    "messaggio, atteso",
    [
        ("ci sono bandi per la mobilità?", "mobilità"),
        ("ci sono bandi?", None),
        ("bandi", None),
        ("avviso pubblico per la mobilità", "mobilità"),
        # Connettivo ("della") e stopword ("ci", "sono") tolti: resta solo il
        # tema, non l'intera coda di frase.
        ("ci sono bandi della mobilità?", "mobilità"),
        # Tema multi-parola: entrambi i token restano (≤3 parole).
        ("ci sono bandi per i servizi sociali?", "servizi sociali"),
        # Frase libera di presentazione: la coda dopo «bandi» è tutta
        # filler/verbi-domanda → nessun tema, nessun filtro fantasma.
        (
            "ciao sono Andrea, vivo a Benevento, ci sono bandi a cui posso accedere?",
            None,
        ),
        # BLOCKER review: saluto + nome + comune PRECEDONO la keyword «bandi»,
        # quindi la coda è vuota → None. Nome proprio mai scambiato per tema.
        ("Ciao, sono Andrea, vivo a Benevento, avete bandi?", None),
    ],
)
def test_estrai_tema(messaggio, atteso):
    assert respond_mod._estrai_tema(messaggio) == atteso


def test_estrai_tema_non_include_il_nome_del_comune():
    """Il comune nominato («Benevento») non deve mai finire nel tema — lo
    riconosce la stessa `_comune_nominato` usata per il routing (R-9)."""
    assert (
        respond_mod._estrai_tema("ci sono bandi a Benevento per la mobilità?")
        == "mobilità"
    )


def test_risposta_bandi_partiziona_per_tema_senza_perdere_bandi():
    """3 bandi, 1 solo titolo parla di mobilità: quello va marcato
    `corrisponde=True` e in cima; gli altri due `corrisponde=False` ma
    restano nell'esito — il filtro evidenzia, non esclude (A1/A6)."""
    esito = BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="coperto_con_bandi",
        gradino="cpt",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[
            _bando("Avviso pubblico contributi affitto"),
            _bando("Bando per la mobilità sostenibile"),
            _bando("Concorso pubblico istruttore"),
        ],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        answer = _componi(
            "ci sono bandi per la mobilità?", modello, profile=_profilo_albano()
        )

    bandi = answer.bandi_live.bandi
    assert len(bandi) == 3  # nessuno perso (A6)
    assert bandi[0].opportunity.title == "Bando per la mobilità sostenibile"
    assert bandi[0].corrisponde is True
    assert [b.corrisponde for b in bandi[1:]] == [False, False]
    assert answer.bandi_live.tema == "mobilità"
    # L'esito e' una copia per-richiesta: l'oggetto cache condiviso non e'
    # mai mutato (`bandi[0]` originale nell'esito passato al mock resta con
    # `corrisponde=None`).
    assert esito.bandi[1].corrisponde is None


def test_notices_databatch_arriva_su_chatanswer_neutro():
    """Ramo 2 slice 2: il DataBatch `notices` viaggia in `ChatAnswer.data_batches`
    con record CANONICI — nessun campo di presentazione, e nell'ordine NEUTRO
    dell'acquisizione, non quello riordinato per tema dalla chat.

    La presentazione (tema, corrisponde, riordino) resta in `bandi_live`.
    """
    esito = BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="coperto_con_bandi",
        gradino="cpt",
        verificato_il=_ORA_ISO,
        bandi=[
            _bando("Avviso pubblico contributi affitto"),
            _bando("Bando per la mobilità sostenibile"),
            _bando("Concorso pubblico istruttore"),
        ],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        answer = _componi(
            "ci sono bandi per la mobilità?", modello, profile=_profilo_albano()
        )

    # presentazione: bandi_live e' riordinato (mobilità in cima) + tema settato
    assert answer.bandi_live.bandi[0].opportunity.title.startswith("Bando per la mob")
    assert answer.bandi_live.tema == "mobilità"

    # contratto v1: un DataBatch notices canonico
    assert len(answer.data_batches) == 1
    batch = answer.data_batches[0]
    assert batch.capability == CAPABILITY_NOTICES
    assert batch.surface is Surface.TRANSPARENCY
    assert batch.access_mode is CatalogAccessMode.MEDIATED
    assert batch.status is DataStatus.FULFILLED
    assert answer.selected_data_batch is batch
    assert answer.query_plan is not None
    # access level propagated to the answer, not hidden in the batch
    assert answer.access_mode == "mediated"

    # ordine NEUTRO: il batch conserva l'ordine d'acquisizione, non il riordino
    assert [r["title"] for r in batch.records] == [
        "Avviso pubblico contributi affitto",
        "Bando per la mobilità sostenibile",
        "Concorso pubblico istruttore",
    ]
    # record canonici: nessun campo di presentazione
    for r in batch.records:
        assert "consigliato" not in r
        assert "corrisponde" not in r
        assert "tema" not in r


def test_notices_databatch_coperto_senza_bandi_e_mediated_empty():
    """coperto_senza_bandi raggiunge ChatAnswer come MEDIATED+EMPTY: fonte letta
    e vuota, non un buco di copertura."""
    esito = BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="coperto_senza_bandi",
        gradino="cpt",
        verificato_il=_ORA_ISO,
        bandi=[],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        answer = _componi("ci sono bandi?", modello, profile=_profilo_albano())

    assert len(answer.data_batches) == 1
    batch = answer.data_batches[0]
    assert batch.access_mode is CatalogAccessMode.MEDIATED
    assert batch.status is DataStatus.EMPTY
    assert batch.records == ()
    # source read, just empty -> still mediated on the answer, never unavailable
    assert answer.access_mode == "mediated"


def test_risposta_bandi_template_con_un_solo_match():
    esito = BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="coperto_con_bandi",
        gradino="cpt",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[
            _bando("Avviso pubblico contributi affitto"),
            _bando("Bando per la mobilità sostenibile"),
        ],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        answer = _componi(
            "ci sono bandi per la mobilità?", modello, profile=_profilo_albano()
        )

    assert answer.reply.startswith(
        f"Ho cercato «mobilità» tra i bandi di {respond_mod.DEFAULT_COMUNE_NOME}: "
        "1 corrisponde."
    )


def test_risposta_bandi_template_con_piu_match():
    esito = BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="coperto_con_bandi",
        gradino="cpt",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[
            _bando("Bando per la mobilità sostenibile"),
            _bando("Contributo mobilità elettrica"),
        ],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        answer = _componi(
            "ci sono bandi per la mobilità?", modello, profile=_profilo_albano()
        )

    assert answer.reply.startswith(
        f"Ho cercato «mobilità» tra i bandi di {respond_mod.DEFAULT_COMUNE_NOME}: "
        "2 corrispondono."
    )


def test_risposta_bandi_template_zero_match():
    esito = BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="coperto_con_bandi",
        gradino="cpt",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[
            _bando("Avviso pubblico contributi affitto"),
            _bando("Concorso pubblico istruttore"),
        ],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        answer = _componi(
            "ci sono bandi per la mobilità?", modello, profile=_profilo_albano()
        )

    assert answer.reply == (
        "Nessun bando corrisponde a «mobilità»; te li mostro tutti (2)."
    )
    assert answer.bandi_live.tema == "mobilità"
    assert all(b.corrisponde is False for b in answer.bandi_live.bandi)


def test_risposta_bandi_senza_tema_reply_identica_a_prima_del_ciclo():
    """A3/D-07: senza tema estratto, la reply resta byte-identica al
    comportamento precedente a questo ciclo, e `tema`/`corrisponde` restano
    `None` su tutta la riga."""
    esito = BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="coperto_con_bandi",
        gradino="cpt",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[_bando("Avviso pubblico contributi 2026")],
    )
    modello = ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        answer = _componi("che bandi ci sono?", modello, profile=_profilo_albano())

    assert answer.reply == (
        "Ho letto ora la sezione Amministrazione Trasparente di "
        f"{respond_mod.DEFAULT_COMUNE_NOME}. Verificato il 2026-08-08T09:30:00+00:00."
    )
    assert answer.bandi_live.tema is None
    assert all(b.corrisponde is None for b in answer.bandi_live.bandi)


# --- 3. Scansione bandi additiva su sinonimo civico (KAPI 11, gap-closure) --
#
# Decisione committente: «Aggiungi bandi», non un reroute. Un messaggio
# agevolazione con un sinonimo civico (agevolazione/contributo/sovvenzione/
# sussidio/bonus/incentivo) deve ALTRESI' popolare `ChatAnswer.bandi_live`
# senza toccare il testo della risposta agevolazione. «aiuto/aiuti» resta
# fuori dal set (troppo generico) e NON deve accendere la scansione.


def _risposta_agevolazione_finta(*, bandi_live=None) -> "respond_mod.ChatAnswer":
    return respond_mod.ChatAnswer(
        reply="Ecco le agevolazioni che ho trovato per te.",
        topic=Topic.SOSTEGNO_UTENZE,
        kind=QuestionKind.AGEVOLAZIONE,
        data_gap=None,
        needs_clarification=False,
        matches=[],
        spid_required=False,
        spid_reason=None,
        bandi_live=bandi_live,
    )


def _esito_bandi_coperto(*, con_bandi: bool = True) -> BandiLiveEsito:
    return BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="coperto_con_bandi" if con_bandi else "coperto_senza_bandi",
        gradino="cpt",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[_bando("Avviso pubblico contributi 2026")] if con_bandi else [],
    )


def test_helper_sinonimo_e_comune_noto_allega_bandi_live():
    esito = _esito_bandi_coperto()
    with mock.patch(
        "treasureiq.bandi_live.bandi_arricchiti", return_value=esito
    ) as sonda:
        risposta = asyncio.run(
            respond_mod._forse_aggiungi_bandi_live(
                _risposta_agevolazione_finta(),
                codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
                message="che contributo posso avere per l'affitto?",
            )
        )

    sonda.assert_called_once_with(respond_mod.DEFAULT_COMUNE_ISTAT)
    assert risposta.bandi_live is esito
    # Ramo agevolazione INTATTO: stesso testo, stesso topic/kind.
    assert risposta.reply == "Ecco le agevolazioni che ho trovato per te."
    assert risposta.topic is Topic.SOSTEGNO_UTENZE


@pytest.mark.parametrize(
    "messaggio",
    [
        "posso avere un bonus per l'affitto?",
        "c'e' una sovvenzione per la mia attivita'?",
    ],
)
def test_helper_altri_sinonimi_civici_allegano_bandi_live(messaggio):
    esito = _esito_bandi_coperto()
    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        risposta = asyncio.run(
            respond_mod._forse_aggiungi_bandi_live(
                _risposta_agevolazione_finta(),
                codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
                message=messaggio,
            )
        )

    assert risposta.bandi_live is esito


def test_helper_coperto_senza_bandi_e_esito_onesto_non_rumore():
    """Zero bandi trovati e' l'esito ONESTO di una ricerca appena fatta
    (memoria «Fonte Nuova non ha nulla da recuperare»): si allega comunque."""
    esito = _esito_bandi_coperto(con_bandi=False)
    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        risposta = asyncio.run(
            respond_mod._forse_aggiungi_bandi_live(
                _risposta_agevolazione_finta(),
                codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
                message="c'e' qualche sussidio per la mensa?",
            )
        )

    assert risposta.bandi_live is esito
    assert risposta.bandi_live.esito == "coperto_senza_bandi"


def test_helper_solo_aiuto_non_accende_la_scansione():
    """«aiuto/aiuti» e' escluso di proposito dal set (troppo generico): la
    sonda di rete non deve nemmeno partire."""
    with mock.patch("treasureiq.bandi_live.bandi_arricchiti") as sonda:
        risposta = asyncio.run(
            respond_mod._forse_aggiungi_bandi_live(
                _risposta_agevolazione_finta(),
                codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
                message="ho bisogno di aiuto, puoi darmi una mano con gli aiuti disponibili?",
            )
        )

    sonda.assert_not_called()
    assert risposta.bandi_live is None


def test_helper_senza_sinonimo_non_tocca_la_risposta():
    with mock.patch("treasureiq.bandi_live.bandi_arricchiti") as sonda:
        risposta = asyncio.run(
            respond_mod._forse_aggiungi_bandi_live(
                _risposta_agevolazione_finta(),
                codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
                message="quanto costa l'asilo nido?",
            )
        )

    sonda.assert_not_called()
    assert risposta.bandi_live is None


def test_helper_comune_ignoto_non_accende_la_scansione():
    with mock.patch("treasureiq.bandi_live.bandi_arricchiti") as sonda:
        risposta = asyncio.run(
            respond_mod._forse_aggiungi_bandi_live(
                _risposta_agevolazione_finta(),
                codice_istat=None,
                message="che bonus posso avere?",
            )
        )

    sonda.assert_not_called()
    assert risposta.bandi_live is None


def test_helper_ramo_bandi_gia_popolato_e_no_op():
    """Il ramo Topic.BANDI popola gia' da se' `bandi_live`: l'helper non deve
    fare una seconda scansione."""
    esito_gia_presente = _esito_bandi_coperto()
    with mock.patch("treasureiq.bandi_live.bandi_arricchiti") as sonda:
        risposta = asyncio.run(
            respond_mod._forse_aggiungi_bandi_live(
                _risposta_agevolazione_finta(bandi_live=esito_gia_presente),
                codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
                message="che bonus posso avere?",
            )
        )

    sonda.assert_not_called()
    assert risposta.bandi_live is esito_gia_presente


def test_helper_non_coperto_non_allega_rumore():
    esito = BandiLiveEsito(
        codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
        comune_nome=respond_mod.DEFAULT_COMUNE_NOME,
        esito="non_coperto",
        gradino=None,
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[],
    )
    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        risposta = asyncio.run(
            respond_mod._forse_aggiungi_bandi_live(
                _risposta_agevolazione_finta(),
                codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
                message="che bonus posso avere?",
            )
        )

    assert risposta.bandi_live is None


def test_helper_degradazione_onesta_su_eccezione():
    """La sonda solleva: la risposta agevolazione torna INTATTA, mai una
    500 al cittadino (degradazione onesta, D-07)."""
    originale = _risposta_agevolazione_finta()
    with mock.patch(
        "treasureiq.bandi_live.bandi_arricchiti",
        side_effect=RuntimeError("portale giu'"),
    ):
        risposta = asyncio.run(
            respond_mod._forse_aggiungi_bandi_live(
                originale,
                codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
                message="che bonus posso avere?",
            )
        )

    assert risposta.bandi_live is None
    assert risposta.reply == originale.reply
    assert risposta is originale or risposta == originale


def test_helper_non_inietta_cifre_nel_testo():
    """D-07: il testo della risposta agevolazione non deve MAI ricevere
    cifre/dettagli del bando — quelli viaggiano solo in `bandi_live`."""
    esito = _esito_bandi_coperto()
    with mock.patch("treasureiq.bandi_live.bandi_arricchiti", return_value=esito):
        risposta = asyncio.run(
            respond_mod._forse_aggiungi_bandi_live(
                _risposta_agevolazione_finta(),
                codice_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
                message="che contributo posso avere?",
            )
        )

    assert risposta.reply == "Ecco le agevolazioni che ho trovato per te."
    assert "Avviso pubblico contributi 2026" not in risposta.reply


# --- 3-bis. Wiring nei return terminali di build_chat_answer -----------------


def test_build_chat_answer_ramo_coperto_allega_bandi_live_su_sinonimo(monkeypatch):
    """Integrazione: il return finale del ramo comune-coperto (C) deve
    passare dal helper additivo — nessun edit a `_componi_risposta`, solo il
    `replace` finale in `build_chat_answer`."""
    monkeypatch.setattr(
        respond_mod,
        "_componi_risposta",
        lambda **_k: asyncio.sleep(0, result=_risposta_agevolazione_finta()),
    )
    esito = _esito_bandi_coperto()

    with mock.patch(
        "treasureiq.bandi_live.bandi_arricchiti", return_value=esito
    ) as sonda:
        answer = asyncio.run(
            respond_mod.build_chat_answer(
                message="che contributo posso avere per l'affitto?",
                profile=None,
                records=[],
                comune_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
                comune_coperto=True,
            )
        )

    sonda.assert_called_once_with(respond_mod.DEFAULT_COMUNE_ISTAT)
    assert answer.topic is Topic.SOSTEGNO_UTENZE  # ramo agevolazione INTATTO
    assert answer.reply == "Ecco le agevolazioni che ho trovato per te."
    assert answer.bandi_live is esito


def test_build_chat_answer_senza_sinonimo_non_chiama_la_sonda(monkeypatch):
    """Comportamento invariato: nessun sinonimo civico, nessuna scansione."""
    monkeypatch.setattr(
        respond_mod,
        "_componi_risposta",
        lambda **_k: asyncio.sleep(0, result=_risposta_agevolazione_finta()),
    )

    with mock.patch("treasureiq.bandi_live.bandi_arricchiti") as sonda:
        answer = asyncio.run(
            respond_mod.build_chat_answer(
                message="quanto costa l'asilo nido?",
                profile=None,
                records=[],
                comune_istat=respond_mod.DEFAULT_COMUNE_ISTAT,
                comune_coperto=True,
            )
        )

    sonda.assert_not_called()
    assert answer.bandi_live is None


# 3-ter. Regressione bug Bisceglie->Albano: la scansione bandi segue il comune
#        del cittadino anche quando arriva SOLO via `comune_istat` (comune noto
#        ma non ingerito) e non e' nominato nel testo del turno.


def test_build_chat_answer_bandi_comune_noto_non_ingerito_non_ripiega_su_albano():
    """Bug committente (Bisceglie): chattando su un comune noto ma non ingerito,
    «vedi i bandi» mostrava i bandi di Albano. Il ramo fuori-copertura di
    `build_chat_answer` passa `comune_istat=None` a `_componi_risposta` (per non
    contaminare records/naming agevolazione) ma conosce il comune via
    `nominato`: deve instradare la scansione bandi la', non sul DEFAULT Albano.
    Il comune non e' nel testo (`che bandi ci sono?`) ne' nel profilo: la sola
    via e' `comune_bandi_istat`."""
    bisceglie_istat = "110003"
    # Presupposto del ramo: comune noto ma NON ingerito (fuori da load_enti).
    assert bisceglie_istat not in respond_mod.load_enti()
    esito = BandiLiveEsito(
        codice_istat=bisceglie_istat,
        comune_nome="Bisceglie",
        esito="coperto_con_bandi",
        gradino="cpt",
        verificato_il="2026-08-08T09:30:00+00:00",
        bandi=[_bando("Avviso pubblico 2026")],
    )
    provider = _ModelloFinto(
        ChatIntent(topic=Topic.BANDI, kind=QuestionKind.INFORMAZIONE)
    )
    with mock.patch.object(
        respond_mod, "load_provider", lambda **_: provider
    ), mock.patch(
        "treasureiq.bandi_live.bandi_arricchiti", return_value=esito
    ) as sonda:
        answer = asyncio.run(
            respond_mod.build_chat_answer(
                message="che bandi ci sono?",
                profile=None,
                records=[],
                comune_istat=bisceglie_istat,
                comune_coperto=False,
            )
        )

    # La sonda ha scansionato Bisceglie, mai il DEFAULT Albano.
    sonda.assert_called_once_with(bisceglie_istat)
    assert sonda.call_args.args[0] != respond_mod.DEFAULT_COMUNE_ISTAT
    assert answer.bandi_live is not None
    assert answer.bandi_live.codice_istat == bisceglie_istat
