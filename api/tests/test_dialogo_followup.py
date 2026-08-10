"""Ciclo 12 (B1, follow-up-slot): TIQ chiede il pezzo mancante, mai bloccante.

Contratto congelato (A1/A2/B1): `ChatIn.chiarimento_atteso` /
`ChatOut.chiarimento` sono lo stesso enum chiuso
`Literal["figli_quanti", "disabile_minorenne"] | None`. Il follow-up e'
ADDITIVO — la risposta di merito resta intera, la domanda si accoda in
coda a `reply` — e MAX UNA per turno (D-04). Il trigger legge solo il
messaggio del turno corrente (AM-1): una dichiarazione ignorata non viene
rincorsa ai turni dopo, ed e' esattamente il caso (d) qui sotto.

Stesso idioma di `test_chat_filtri_proiezione.py`: nessuna rete, il
provider LLM e' mockato con un `ChatIntent` gia' pronto (Topic.SCONOSCIUTO
basta — questi turni non nominano nessun comune, quindi `build_chat_answer`
non tenta risoluzione di comune/connettore/scan live).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from treasureiq.api import app
from treasureiq.chat import respond as respond_mod
from treasureiq.chat.intent import ChatIntent, Topic


class _ModelloFinto:
    """Nessuna rete: l'intento e' gia' quello che il modello avrebbe letto."""

    def __init__(self, intento: ChatIntent) -> None:
        self._intento = intento

    async def aparse(self, *, system, user, output_model):
        return self._intento


def _monta_client(monkeypatch) -> TestClient:
    provider = _ModelloFinto(ChatIntent(topic=Topic.SCONOSCIUTO))
    monkeypatch.setattr(respond_mod, "load_provider", lambda **_: provider)
    return TestClient(app)


def test_a_dichiarazione_figli_senza_numero_chiede_quanti(monkeypatch) -> None:
    """(a) 'ho dei figli' senza numero -> risposta di merito + follow-up."""
    client = _monta_client(monkeypatch)

    risposta = client.post("/api/chat", json={"message": "ho dei figli"})

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["chiarimento"] == "figli_quanti"
    # Additivo (D-04): la risposta di merito non e' stata sostituita dalla
    # sola domanda, la domanda si e' accodata.
    assert corpo["reply"], "reply vuota: il follow-up ha sostituito la risposta invece di accodarsi"


def test_b_risposta_secca_al_follow_up_riempie_lo_slot_senza_richiedere(monkeypatch) -> None:
    """(b) 'due, di 4 e 9 anni' con chiarimento_atteso='figli_quanti' -> figli_minori=2, nessun nuovo chiarimento."""
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat",
        json={"message": "due, di 4 e 9 anni", "chiarimento_atteso": "figli_quanti"},
    )

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["profilo_capito"]["figli_minori"] == 2, corpo["profilo_capito"]
    assert corpo["chiarimento"] is None, "lo slot appena risolto non deve essere richiesto di nuovo"


def test_c_numero_gia_dichiarato_non_chiede_nulla(monkeypatch) -> None:
    """(c) 'ho 2 figli minorenni' -> il numero e' gia' noto, nessun follow-up (regressione anti-nag)."""
    client = _monta_client(monkeypatch)

    risposta = client.post("/api/chat", json={"message": "ho 2 figli minorenni"})

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["chiarimento"] is None, corpo
    assert corpo["profilo_capito"]["figli_minori"] == 2, corpo["profilo_capito"]


def test_d_dichiarazione_solo_in_storia_non_viene_rincorsa(monkeypatch) -> None:
    """(d) AM-1: 'ho figli' vive solo in `storia`, il messaggio corrente e' neutro -> nessuna domanda."""
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat",
        json={
            "message": "che aiuti ci sono per la mensa?",
            "history": [
                {"role": "user", "content": "ho figli"},
                {"role": "assistant", "content": "ok"},
            ],
        },
    )

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["chiarimento"] is None, (
        "AM-1 violato: il trigger ha letto la dichiarazione dalla sola storia, "
        f"non dal messaggio corrente ({corpo['chiarimento']!r})"
    )


def test_e_disabilita_dichiarata_chiede_se_minorenne(monkeypatch) -> None:
    """(e1) disabilita' dichiarata, stato-minorenne ignoto -> chiarimento='disabile_minorenne'."""
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat", json={"message": "in famiglia c'e' una persona con disabilita'"}
    )

    assert risposta.status_code == 200, risposta.text
    assert risposta.json()["chiarimento"] == "disabile_minorenne"


def test_e_nessuna_disabilita_dichiarata_non_chiede_nulla(monkeypatch) -> None:
    """(e2) D-03: mai proattivo. Nessuna disabilita' dichiarata -> chiarimento=None."""
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat", json={"message": "che aiuti ci sono per i trasporti?"}
    )

    assert risposta.status_code == 200, risposta.text
    assert risposta.json()["chiarimento"] is None


def test_f_al_massimo_un_chiarimento_per_turno_priorita_figli(monkeypatch) -> None:
    """(f) D-04: entrambi i trigger scattano nello stesso turno -> ne vince UNO solo."""
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat", json={"message": "ho figli e sono anche disabile"}
    )

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    # Un solo campo puo' portare un solo valore: verifichiamo che sia
    # esattamente il trigger a priorita' piu' alta (figli_quanti), non
    # 'disabile_minorenne' e non entrambi accodati alla cieca.
    assert corpo["chiarimento"] == "figli_quanti", corpo


# -- gap-closure: "famiglia"/"nucleo" generica, nessuno slot concreto --------
#
# Vincolo duro del committente: la domanda di questo ramo non nomina MAI la
# disabilita' — TIQ non la introduce prima che sia il cittadino a nominarla.


def test_g_famiglia_generica_senza_slot_concreto_chiede_composizione(monkeypatch) -> None:
    """(a) 'famiglia' nominata genericamente, nessun figlio/nucleo/disabilita' noto
    -> chiarimento='composizione_famiglia', risposta di merito presente, e la
    domanda non nomina la disabilita'."""
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat", json={"message": "cosa mi spetta con la mia famiglia?"}
    )

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["chiarimento"] == "composizione_famiglia", corpo
    assert corpo["reply"], "reply vuota: il follow-up ha sostituito la risposta invece di accodarsi"
    assert "disab" not in corpo["reply"].lower(), (
        "vincolo duro violato: la domanda su composizione_famiglia nomina la disabilita'"
    )


def test_h_risposta_a_composizione_famiglia_riempie_lo_slot_senza_richiedere(monkeypatch) -> None:
    """(b) 'ho due figli minorenni, di 4 e 9 anni' con chiarimento_atteso=
    'composizione_famiglia' -> figli_minori=2, nessun nuovo chiarimento (la
    risposta scorre nel riconoscimento normale, nessun resolver dedicato serve)."""
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat",
        json={
            "message": "ho due figli minorenni, di 4 e 9 anni",
            "chiarimento_atteso": "composizione_famiglia",
        },
    )

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["profilo_capito"]["figli_minori"] == 2, corpo["profilo_capito"]
    assert corpo["chiarimento"] is None, "lo slot appena risolto non deve essere richiesto di nuovo"


def test_i_ho_figli_e_famiglia_vince_priorita_figli_quanti(monkeypatch) -> None:
    """(c) 'ho figli' insieme a 'famiglia' nello stesso messaggio -> vince
    'figli_quanti' (priorita' piu' alta), non 'composizione_famiglia' (D-04)."""
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat", json={"message": "ho figli, cosa spetta alla mia famiglia?"}
    )

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["chiarimento"] == "figli_quanti", corpo


def test_j_famiglia_di_n_e_concreta_non_chiede_composizione(monkeypatch) -> None:
    """(d) 'famiglia di 4' e' un NUCLEO_FAMILIARE concreto (letto da
    `riconosci_filtri`), non un caso generico -> nessuna domanda su
    composizione_famiglia."""
    client = _monta_client(monkeypatch)

    risposta = client.post("/api/chat", json={"message": "siamo una famiglia di 4"})

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["profilo_capito"]["nucleo_familiare"] == 4, corpo["profilo_capito"]
    assert corpo["chiarimento"] is None, corpo


def test_k_famiglia_solo_in_storia_non_viene_rincorsa(monkeypatch) -> None:
    """(e) AM-1: 'famiglia' vive solo in `storia`, il messaggio corrente e'
    neutro -> nessuna domanda su composizione_famiglia."""
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat",
        json={
            "message": "che aiuti ci sono per i trasporti?",
            "history": [
                {"role": "user", "content": "cosa spetta alla mia famiglia?"},
                {"role": "assistant", "content": "ok"},
            ],
        },
    )

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["chiarimento"] is None, (
        "AM-1 violato: il trigger ha letto 'famiglia' dalla sola storia, "
        f"non dal messaggio corrente ({corpo['chiarimento']!r})"
    )


def test_l_domanda_composizione_famiglia_non_nomina_mai_la_disabilita() -> None:
    """(f) Vincolo duro dedicato: ogni variante deterministica della domanda
    di composizione_famiglia e' priva di qualunque riferimento a disabilita'."""
    for domanda in respond_mod._DOMANDA_COMPOSIZIONE_FAMIGLIA:
        assert "disab" not in domanda.lower(), domanda


def test_m_risposta_secca_senza_figli_non_leaka_eta_dei_figli_come_anagrafica(monkeypatch) -> None:
    """(g) Ciclo12/B-seam: 'Due, di 4 e 9 anni' (senza la parola "figli") con
    chiarimento_atteso='figli_quanti' -> figli_minori=2, NESSUN filtro `eta`
    (l'eta' dei figli non deve leakare come eta' anagrafica del cittadino)."""
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat",
        json={
            "message": "Due, di 4 e 9 anni",
            "chiarimento_atteso": "figli_quanti",
            "history": [
                {"role": "user", "content": "Ho figli"},
                {"role": "assistant", "content": "Quanti figli hai?"},
            ],
        },
    )

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["profilo_capito"]["figli_minori"] == 2, corpo["profilo_capito"]
    assert corpo["profilo_capito"]["eta"] is None, (
        "seam bug: l'eta' del figlio e' leakata come eta' anagrafica del cittadino "
        f"({corpo['profilo_capito']})"
    )
    chiavi_filtri = {f["chiave"] for f in corpo["filtri"]}
    assert "eta" not in chiavi_filtri, corpo["filtri"]


def test_n_risposta_con_figli_non_leaka_eta_come_anagrafica_non_regressione(monkeypatch) -> None:
    """(h) Guardia di non-regressione: 'ho due figli di 4 e 9 anni' (con la
    parola "figli", chiarimento_atteso='composizione_famiglia') non leakava
    gia' prima del fix (`_FIGLIO_ETA_RE` la esclude) -> resta senza `eta`."""
    client = _monta_client(monkeypatch)

    risposta = client.post(
        "/api/chat",
        json={
            "message": "ho due figli di 4 e 9 anni",
            "chiarimento_atteso": "composizione_famiglia",
        },
    )

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["profilo_capito"]["figli_minori"] == 2, corpo["profilo_capito"]
    chiavi_filtri = {f["chiave"] for f in corpo["filtri"]}
    assert "eta" not in chiavi_filtri, corpo["filtri"]


def test_o_eta_anagrafica_vera_senza_chiarimento_atteso_non_viene_soppressa(monkeypatch) -> None:
    """(i) Guardia: senza un chiarimento sui figli in corso, un'eta' vera
    dichiarata dal cittadino ('ho 67 anni') resta un filtro `eta` a tutti gli
    effetti — la soppressione e' scoped al contesto figli, non generale."""
    client = _monta_client(monkeypatch)

    risposta = client.post("/api/chat", json={"message": "ho 67 anni"})

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["profilo_capito"]["eta"] == 67, corpo["profilo_capito"]
    chiavi_filtri = {f["chiave"] for f in corpo["filtri"]}
    assert "eta" in chiavi_filtri, corpo["filtri"]
