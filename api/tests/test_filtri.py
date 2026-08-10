"""Test del modulo deterministico `treasureiq.chat.filtri` (ciclo 11, B2).

Riusa i testi di `corpus_filtri.py` (B1) dove il caso e' pertinente a
`filtri.py`, ma con l'atteso CORRETTO che B2 deve produrre — non quello
"attuale" che il corpus congela per `intent.py`/`respond.py` di produzione
(vedi il docstring di `CasoTesto`: quel dizionario descrive lo stato di
oggi, non una wishlist). I casi `oggi_non_colto=True` del corpus sono
esattamente il gap che questo modulo chiude.

`filtri.py` e' innestato in produzione dal B3: questi test lo esercitano
in isolamento, senza dover passare da `intent.py`/`respond.py`/`api.py`.
"""

from __future__ import annotations

from treasureiq.chat.filtri import (
    Filtro,
    FiltroChiave,
    accumula_filtri,
    dichiarazione_figli_senza_numero,
    negazioni_esplicite,
    riconosci_filtri,
)


def _di(filtri: list[Filtro], chiave: FiltroChiave) -> list[Filtro]:
    return [f for f in filtri if f.chiave is chiave]


def _valori(filtri: list[Filtro], chiave: FiltroChiave) -> list:
    return [f.valore for f in _di(filtri, chiave)]


# -- A1: ogni filtro con sorgente="testo" ha uno span verbatim ---------------


def test_ogni_filtro_ha_span_verbatim_nel_testo():
    frasi = [
        "ho 67 anni",
        "ISEE 9.360",
        "isee 9.360,50",
        "ISEE di 9360 euro",
        "siamo in 4",
        "due figli minorenni",
        "sono disabile",
        "figlio disabile",
        "sono disoccupato da un anno",
        "sono di monte rotondo",
        "ci sono bandi per la mobilità?",
    ]
    for frase in frasi:
        for filtro in riconosci_filtri(frase):
            assert filtro.sorgente == "testo"
            assert filtro.span is not None, f"{filtro.chiave} senza span su {frase!r}"
            assert filtro.span.testo == frase[filtro.span.inizio : filtro.span.fine]
            assert filtro.span.testo in frase


def test_forma_non_riconosciuta_non_produce_filtri_inventati():
    # A12: nessuna delle frasi seguenti contiene evidenza testuale per il
    # rispettivo slot -> lista vuota, mai un valore indovinato.
    assert riconosci_filtri("isee basso") == []
    assert riconosci_filtri("in famiglia siamo in tanti") == []
    assert riconosci_filtri("ho due figli") == []  # niente qualificatore minor/piccol
    assert riconosci_filtri("civico 140 anni luce") == []  # eta' oltre 130, scartata


# -- A2: negazione -> zero filtri attivi -------------------------------------


def test_negazione_figli_minori_zero_filtri_attivi():
    assert _valori(riconosci_filtri("non ho figli minori"), FiltroChiave.FIGLI_MINORI) == []


def test_negazione_disabilita_zero_filtri_attivi():
    assert _valori(riconosci_filtri("non sono disabile"), FiltroChiave.DISABILITA) == []


def test_negazione_con_cue_senza_e_privo_di():
    assert _valori(riconosci_filtri("senza figli minori"), FiltroChiave.FIGLI_MINORI) == []
    assert _valori(riconosci_filtri("privo di disabilità"), FiltroChiave.DISABILITA) == []


def test_senza_negazione_il_filtro_resta_attivo():
    # Il regex non scatta nemmeno oggi su questa forma (nessun qualificatore
    # minor/piccol adiacente): zero filtri, ma non a causa della negazione.
    assert riconosci_filtri("mia figlia è maggiorenne") == []
    # Caso positivo di controllo: senza negazione, il filtro c'e'.
    assert _valori(riconosci_filtri("sono disabile"), FiltroChiave.DISABILITA) == [True]


def test_negazione_di_uno_stato_non_aborta_il_riconoscimento_di_un_altro():
    # "non sono disoccupato" e' negato -> non deve emettere disoccupato,
    # ma NON deve nemmeno abortire il riconoscimento di "sono pensionato"
    # che segue nella stessa frase.
    filtri = riconosci_filtri("non sono disoccupato, sono pensionato")
    assert _valori(filtri, FiltroChiave.EMPLOYMENT_STATUS) == ["pensionato"]


def test_negazione_figlio_disabile_non_aborta_disabilita_propria():
    # "non ho figli disabili" e' negato -> DISABILITA_NUCLEO non deve
    # emettere, ma il riconoscimento deve comunque cadere sul check della
    # disabilita' propria del cittadino che segue.
    filtri = riconosci_filtri("non ho figli disabili ma io sono disabile")
    assert _valori(filtri, FiltroChiave.DISABILITA) == [True]
    assert _valori(filtri, FiltroChiave.DISABILITA_NUCLEO) == []


# -- A3: nessun comune spurio (toponimi che sono anche parole comuni) -------


def test_minori_da_solo_non_risolve_al_comune_minori():
    assert _valori(riconosci_filtri("minori"), FiltroChiave.COMUNE) == []


def test_minori_dentro_frase_reale_non_risolve_al_comune():
    assert _valori(riconosci_filtri("ho due figli minori"), FiltroChiave.COMUNE) == []


def test_bolletta_della_luce_non_risolve_a_un_comune_con_della():
    assert _valori(riconosci_filtri("bolletta della luce"), FiltroChiave.COMUNE) == []


def test_comune_scritto_spezzato_monte_rotondo():
    for frase in ("monte rotondo", "sono di monte rotondo", "vivo a monte rotondo da anni"):
        filtri = _di(riconosci_filtri(frase), FiltroChiave.COMUNE)
        assert len(filtri) == 1, frase
        assert filtri[0].span.testo.lower() == "monte rotondo"


def test_comune_ambiguo_non_sceglie_a_caso():
    # Pergine Valsugana (TN) vs Laterina Pergine Valdarno (AR): resta
    # ambiguo, D-54 chiede invece di indovinare -> nessun filtro comune.
    assert _valori(riconosci_filtri("sono di pergine"), FiltroChiave.COMUNE) == []
    # "gorla" aggancia Gorla Maggiore E Gorla Minore dopo aver tolto
    # "minore" (stoplist): due candidati reali, ancora ambiguo.
    assert _valori(riconosci_filtri("gorla minore"), FiltroChiave.COMUNE) == []


# -- A4: forme numeriche, incluso il fix del bug 9360 -> 936.0 --------------


def test_isee_bug_9360_fixato_con_di_e_euro():
    assert _valori(riconosci_filtri("ISEE di 9360 euro"), FiltroChiave.ISEE) == [9360.0]


def test_isee_bug_9360_fixato_senza_di():
    assert _valori(riconosci_filtri("ISEE 9360"), FiltroChiave.ISEE) == [9360.0]


def test_isee_con_separatore_migliaia():
    assert _valori(riconosci_filtri("ISEE 9.360"), FiltroChiave.ISEE) == [9360.0]


def test_isee_con_centesimi():
    assert _valori(riconosci_filtri("isee 9.360,50"), FiltroChiave.ISEE) == [9360.5]


def test_isee_notazione_k_con_parola_chiave():
    assert _valori(riconosci_filtri("il mio isee è 9k"), FiltroChiave.ISEE) == [9000.0]


def test_isee_numero_a_parole_con_parola_chiave():
    assert _valori(riconosci_filtri("isee novemila euro"), FiltroChiave.ISEE) == [9000.0]


def test_reddito_mila_come_isee():
    assert _valori(riconosci_filtri("reddito 15 mila"), FiltroChiave.ISEE) == [15000.0]


def test_numero_nudo_senza_parola_chiave_non_e_isee():
    # A12: "novemila euro"/"9k" da soli, senza 'isee'/'reddito' vicino, sono
    # ambigui (potrebbero essere qualunque importo) -> nessun filtro.
    assert riconosci_filtri("novemila euro") == []
    assert riconosci_filtri("9k") == []


def test_eta_semplice_e_soglia_anziano():
    filtri = riconosci_filtri("ho 67 anni")
    assert _valori(filtri, FiltroChiave.ETA) == [67]
    assert _valori(filtri, FiltroChiave.ANZIANO) == [True]


def test_eta_sotto_soglia_anziano_non_scatta():
    filtri = riconosci_filtri("ho 38 anni e sono di pergine")
    assert _valori(filtri, FiltroChiave.ETA) == [38]
    assert _valori(filtri, FiltroChiave.ANZIANO) == []


def test_nucleo_familiare_siamo_in_n():
    assert _valori(riconosci_filtri("siamo in 4"), FiltroChiave.NUCLEO_FAMILIARE) == [4]


def test_nucleo_familiare_famiglia_di_n():
    assert _valori(riconosci_filtri("famiglia di 6"), FiltroChiave.NUCLEO_FAMILIARE) == [6]


def test_figli_minori_numero_a_parole():
    assert _valori(riconosci_filtri("due figli minorenni"), FiltroChiave.FIGLI_MINORI) == [2]


def test_figli_minori_default_a_uno_senza_conteggio():
    assert _valori(riconosci_filtri("ho figli minori"), FiltroChiave.FIGLI_MINORI) == [1]


def test_figli_minori_due_figli_minori_regress_a4():
    # A4 esistente: non deve regredire dopo l'estensione bambino/bimbo (ciclo 11).
    assert _valori(riconosci_filtri("due figli minori"), FiltroChiave.FIGLI_MINORI) == [2]


def test_figli_minori_bambino_di_n_anni_ciclo11_bug_b():
    filtri = riconosci_filtri("un bambino di 4 anni disabile")
    assert _valori(filtri, FiltroChiave.FIGLI_MINORI) == [1]


def test_figli_minori_due_bambini_ciclo11_bug_b():
    assert _valori(riconosci_filtri("ho due bambini"), FiltroChiave.FIGLI_MINORI) == [2]


def test_figli_minori_eta_multipla_con_e():
    filtri = riconosci_filtri("ho due figli di 4 e 9 anni")
    assert _valori(filtri, FiltroChiave.FIGLI_MINORI) == [2]
    assert _valori(filtri, FiltroChiave.ETA) == []


def test_figli_minori_eta_multipla_senza_conteggio():
    assert _valori(riconosci_filtri("figli di 4 e 9 anni"), FiltroChiave.FIGLI_MINORI) == [1]


def test_figli_minori_eta_multipla_tutti_maggiorenni():
    assert _valori(riconosci_filtri("due figli di 20 e 25 anni"), FiltroChiave.FIGLI_MINORI) == []


def test_figli_minori_eta_multipla_tre_eta_con_virgola():
    filtri = riconosci_filtri("un figlio di 10, 14 e 16 anni")
    assert _valori(filtri, FiltroChiave.FIGLI_MINORI) == [1]


def test_figli_minori_eta_singola_regressione():
    assert _valori(riconosci_filtri("figlio di 4 anni"), FiltroChiave.FIGLI_MINORI) == [1]


# -- disabilita' propria vs figlio (R-8/D-53), degrado onesto --------------


def test_disabilita_propria():
    filtri = riconosci_filtri("sono disabile")
    assert _valori(filtri, FiltroChiave.DISABILITA) == [True]
    assert _di(filtri, FiltroChiave.DISABILITA_NUCLEO) == []


def test_disabilita_del_figlio_cede_il_passo():
    filtri = riconosci_filtri("mia figlia con disabilità")
    assert _valori(filtri, FiltroChiave.DISABILITA_NUCLEO) == [True]
    assert _di(filtri, FiltroChiave.DISABILITA) == []


def test_disabilitato_non_e_disabile_confine_di_parola():
    filtri = riconosci_filtri("sono disabilitato il servizio")
    assert _di(filtri, FiltroChiave.DISABILITA) == []
    assert _di(filtri, FiltroChiave.DISABILITA_NUCLEO) == []


def test_disabilita_negazione_regress_ciclo11():
    assert _valori(riconosci_filtri("non sono disabile"), FiltroChiave.DISABILITA) == []
    assert _valori(riconosci_filtri("non sono disabile"), FiltroChiave.DISABILITA_NUCLEO) == []


def test_disabilita_bambino_di_n_anni_e_del_figlio_non_del_cittadino_ciclo11_bug_a():
    # «un bambino di 4 anni disabile»: i marcatori contigui esistenti ("figlio
    # disabile") non lo prendono. Deve comunque attribuirsi al FIGLIO
    # (DISABILITA_NUCLEO), mai al cittadino (DISABILITA).
    filtri = riconosci_filtri("un bambino di 4 anni disabile")
    assert _valori(filtri, FiltroChiave.DISABILITA_NUCLEO) == [True]
    assert _di(filtri, FiltroChiave.DISABILITA) == []


def test_disabilita_frase_bisceglie_ciclo11_regressione_committente():
    # Frase di prova del committente: eta' del CITTADINO (58), non del
    # bambino (4); disabilita' del bambino (nucleo), non del cittadino.
    frase = (
        "ciao, sono di bisceglie, ho 58 anni e un bambino di 4 anni "
        "disabile, c'è un contributo per l'asilo?"
    )
    filtri = riconosci_filtri(frase)
    assert _valori(filtri, FiltroChiave.ETA) == [58]
    assert _valori(filtri, FiltroChiave.FIGLI_MINORI) == [1]
    assert _valori(filtri, FiltroChiave.DISABILITA_NUCLEO) == [True]
    assert _di(filtri, FiltroChiave.DISABILITA) == []
    assert _valori(filtri, FiltroChiave.COMUNE) == ["110003"]


# -- employment: A10, riconoscimento esplicito che oggi manca in produzione -


def test_employment_disoccupato_riconosciuto():
    assert _valori(riconosci_filtri("sono disoccupato da un anno"), FiltroChiave.EMPLOYMENT_STATUS) == [
        "disoccupato"
    ]


def test_employment_pensionato_riconosciuto():
    assert _valori(riconosci_filtri("sono pensionato"), FiltroChiave.EMPLOYMENT_STATUS) == ["pensionato"]


# -- tema: solo quando ricostruibile come sottostringa verbatim -------------


def test_tema_bandi_riconosciuto_con_span():
    filtri = _di(riconosci_filtri("ci sono bandi per la mobilità?"), FiltroChiave.TEMA)
    assert len(filtri) == 1
    assert "mobilit" in filtri[0].valore.lower()
    assert filtri[0].span.testo in "ci sono bandi per la mobilità?"


def test_tema_assente_senza_keyword_bandi():
    assert riconosci_filtri("ci sono agevolazioni per anziani?") == [] or _di(
        riconosci_filtri("ci sono agevolazioni per anziani?"), FiltroChiave.TEMA
    ) == []


# -- import pulito e stabilita' su input degenere ---------------------------


def test_import_pulito():
    from treasureiq.chat.filtri import riconosci_filtri as rf  # noqa: F401


def test_testo_vuoto_non_produce_filtri_ne_eccezioni():
    assert riconosci_filtri("") == []
    assert riconosci_filtri(None) == []  # type: ignore[arg-type]


# -- accumula_filtri: sopravvivenza multi-turno (ciclo 12/A1) ----------------


def test_accumula_filtri_sopravvive_a_un_turno_neutro():
    storia = ["ho 2 figli minorenni"]
    message = "e per la mensa scolastica?"
    accumulati = accumula_filtri(storia, message, frozenset())
    assert FiltroChiave.FIGLI_MINORI in accumulati
    assert accumulati[FiltroChiave.FIGLI_MINORI].valore == riconosci_filtri(storia[0])[0].valore


def test_accumula_filtri_negazione_successiva_fa_cadere_il_filtro():
    storia = ["sono disabile"]
    message = "non sono disabile"
    accumulati = accumula_filtri(storia, message, frozenset())
    assert FiltroChiave.DISABILITA not in accumulati


def test_accumula_filtri_filtri_esclusi_vince_sulla_storia():
    storia = ["ho 2 figli minorenni"]
    message = "quali bonus ci sono?"
    accumulati = accumula_filtri(storia, message, frozenset({FiltroChiave.FIGLI_MINORI}))
    assert FiltroChiave.FIGLI_MINORI not in accumulati


def test_accumula_filtri_e_idempotente_e_ordine_stabile():
    storia = ["ho 2 figli minorenni", "sono disabile", "e per la mensa?"]
    message = "quali bandi ci sono?"
    prima = accumula_filtri(storia, message, frozenset())
    seconda = accumula_filtri(storia, message, frozenset())
    assert {k: v.valore for k, v in prima.items()} == {k: v.valore for k, v in seconda.items()}
    assert FiltroChiave.FIGLI_MINORI in prima
    assert FiltroChiave.DISABILITA in prima


def test_accumula_filtri_turno_successivo_sovrascrive_lo_stesso_filtro():
    storia = ["ho 2 figli minorenni"]
    message = "in realta' ho 3 figli minorenni"
    accumulati = accumula_filtri(storia, message, frozenset())
    assert accumulati[FiltroChiave.FIGLI_MINORI].valore == riconosci_filtri(message)[0].valore


# -- negazioni_esplicite -----------------------------------------------------


def test_negazioni_esplicite_rileva_disabilita_negata():
    assert FiltroChiave.DISABILITA in negazioni_esplicite("non sono disabile")


def test_negazioni_esplicite_muta_senza_evidenza_testuale():
    assert negazioni_esplicite("quali bandi ci sono?") == set()
    assert negazioni_esplicite("") == set()


# -- dichiarazione_figli_senza_numero ----------------------------------------


def test_dichiarazione_figli_senza_numero_vera_su_dichiarazione_incompleta():
    assert dichiarazione_figli_senza_numero("ho dei figli") is True


def test_dichiarazione_figli_senza_numero_falsa_se_gia_riconosciuto():
    assert dichiarazione_figli_senza_numero("ho 2 figli minorenni") is False


def test_dichiarazione_figli_senza_numero_falsa_su_negazione():
    assert dichiarazione_figli_senza_numero("non ho figli") is False
