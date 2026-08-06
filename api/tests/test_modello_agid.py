"""Test sul lettore del modello AgID.

L'aderenza è un numero che finiamo per pubblicare accanto al nome di
un'azienda. Deve quindi sbagliare per difetto e mai per eccesso: un lettore
generoso regalerebbe conformità a chi non ce l'ha, ed è il tipo di errore che
non si scopre mai guardando i grafici.
"""

from __future__ import annotations

from treasureiq.ingest.modello_agid import (
    COMWEB,
    GENERICA,
    PEOPLEWEB,
    SezioneAgid,
    declinazione_per,
    leggi_scheda,
)

PEOPLEWEB_HTML = """
<h3>Accesso agli atti</h3>
<h4>A chi è rivolto</h4><p>A tutti i cittadini maggiorenni.</p>
<h4>Descrizione</h4><p>Richiesta di copia di atti amministrativi.</p>
<h4>Come fare</h4><p>Presentare istanza allo sportello.</p>
<h4>Cosa serve</h4><p>Documento di identità e marca da bollo.</p>
<h4>Cosa si ottiene</h4><p>Copia dell'atto richiesto.</p>
<h4>Tempi e scadenze</h4><p>Trenta giorni dalla presentazione.</p>
<h4>Quanto costa</h4><p>Diritti di segreteria 25,00 euro.</p>
<h4>Accedi al servizio</h4><p>Sportello URP.</p>
<h4>Condizioni di servizio</h4><p>Vedi regolamento comunale.</p>
<h4>Documenti e Allegati</h4><p>Modulo di richiesta.</p>
<h4>Contatti</h4><p>urp@comune.example.it</p>
"""


def test_peopleweb_espone_il_modello_intero():
    scheda = leggi_scheda(PEOPLEWEB_HTML, declinazione=PEOPLEWEB)
    assert scheda.aderenza == 1.0
    assert scheda.critiche_mancanti == frozenset()
    assert "marca da bollo" in scheda.sezioni[SezioneAgid.COSA_SERVE]


def test_una_scheda_fuori_modello_resta_in_fondo():
    """Non tutte le pagine sotto `/servizi` sono schede di servizio: alcune
    sono pagine informative, e su quelle il modello non c'è.

    Misurare la pagina sbagliata è il modo più facile di calunniare un
    fornitore — è successo davvero, e per questo l'aderenza va letta come
    media su più comuni e mai su una pagina sola.
    """
    html = "<h2>Scheda del servizio</h2><p>Pago PA</p><h3>Contatti</h3><p>protocollo@x.it</p>"
    scheda = leggi_scheda(html, declinazione=COMWEB)
    assert scheda.sezioni.keys() == {SezioneAgid.CONTATTI}
    assert round(scheda.aderenza, 3) == round(1 / len(SezioneAgid), 3)
    assert SezioneAgid.TEMPI_E_SCADENZE in scheda.critiche_mancanti


def test_una_sezione_vuota_non_conta_come_esposta():
    """Il titolo senza contenuto è il modo più comune di sembrare conformi."""
    html = "<h4>Tempi e scadenze</h4><h4>Contatti</h4><p>urp@x.it</p>"
    scheda = leggi_scheda(html, declinazione=PEOPLEWEB)
    assert SezioneAgid.TEMPI_E_SCADENZE not in scheda.sezioni
    assert SezioneAgid.CONTATTI in scheda.sezioni


def test_etichetta_simile_non_vale_come_sezione():
    """`Documenti necessari per il rinnovo` non è la sezione `Documenti`.

    Con un confronto per sottostringa due sezioni diverse collasserebbero in
    una, e l'aderenza salirebbe proprio dove il portale è più confuso.
    """
    html = "<h4>Documenti necessari per il rinnovo della carta</h4><p>Foto tessera.</p>"
    scheda = leggi_scheda(html, declinazione=PEOPLEWEB)
    assert scheda.sezioni == {}
    assert any("documenti necessari" in x for x in scheda.non_riconosciute)


def test_accenti_e_punteggiatura_non_cambiano_la_sezione():
    varianti = ["A chi è rivolto", "A CHI E' RIVOLTO", "A chi è rivolto?"]
    for etichetta in varianti:
        scheda = leggi_scheda(f"<h4>{etichetta}</h4><p>Ai residenti.</p>", declinazione=PEOPLEWEB)
        assert SezioneAgid.A_CHI_E_RIVOLTO in scheda.sezioni, etichetta


def test_le_intestazioni_ignote_restano_come_candidate():
    """Quello che oggi non riconosciamo è l'elenco delle etichette da
    aggiungere domani, non spazzatura da buttare."""
    html = "<h4>A chi è destinato il beneficio</h4><p>Alle famiglie.</p>"
    scheda = leggi_scheda(html, declinazione=PEOPLEWEB)
    assert scheda.non_riconosciute == ["a chi e destinato il beneficio"]


def test_impronta_cambia_con_la_forma_non_col_testo():
    """L'impronta sostituisce il numero di versione che nessuno pubblica:
    deve muoversi quando il fornitore cambia struttura, e stare ferma quando
    un comune riscrive il contenuto di una sezione."""
    a = leggi_scheda(PEOPLEWEB_HTML, declinazione=PEOPLEWEB)
    riscritto = PEOPLEWEB_HTML.replace("Trenta giorni", "Sessanta giorni lavorativi")
    b = leggi_scheda(riscritto, declinazione=PEOPLEWEB)
    assert a.impronta == b.impronta

    senza_scadenze = PEOPLEWEB_HTML.replace("<h4>Tempi e scadenze</h4>", "<h4>Altro</h4>")
    c = leggi_scheda(senza_scadenze, declinazione=PEOPLEWEB)
    assert c.impronta != a.impronta


def test_declinazione_ignota_ricade_sulla_generica():
    """Un fornitore mai visto va misurato lo stesso: è così che si scopre se
    valga la pena scrivergli una declinazione su misura."""
    assert declinazione_per("fornitore_mai_visto") is GENERICA
    assert declinazione_per("peopleweb") is PEOPLEWEB


CMB2_ALBANO = {
    "_dci_servizio_box_cosa_serve": {
        "_dci_servizio_cosa_serve_introduzione": "<p>ISEE non superiore a 20.000,00</p>",
        "_dci_servizio_cosa_serve_list": "",
    },
    "_dci_servizio_box_accedi_servizio": {
        "_dci_servizio_vincoli": "",
        "_dci_servizio_canale_digitale_link": "https://esempio.it/domanda",
    },
    # Box previsto dal tema e lasciato interamente vuoto dal comune.
    "_dci_servizio_box_tempi_e_scadenze": {"_dci_servizio_tempi": ""},
}


def test_campi_tipizzati_separano_esposto_da_compilato():
    """La distinzione che solo i campi tipizzati permettono: una sezione
    prevista dal tema e lasciata vuota dal comune.

    Senza, la colpa finirebbe sul fornitore, che invece il campo l'ha
    costruito. La misura resta a livello di box: `_dci_servizio_vincoli` vuoto
    dentro un box che ha il link compilato non si vede qui, e infatti la
    scoperta su Albano vive nel connettore di ingestione, che scende al campo.
    """
    from treasureiq.ingest.modello_agid import leggi_scheda_cmb2

    scheda = leggi_scheda_cmb2(CMB2_ALBANO)
    assert SezioneAgid.COSA_SERVE in scheda.sezioni
    assert scheda.esposte is not None
    assert SezioneAgid.ACCEDI_AL_SERVIZIO in scheda.esposte
    # Prevista dallo schema, lasciata vuota: né riempita, né inventata.
    assert SezioneAgid.TEMPI_E_SCADENZE in scheda.dichiarate_vuote
    assert SezioneAgid.TEMPI_E_SCADENZE not in scheda.sezioni


def test_lettura_html_non_puo_dire_cosa_e_dichiarato():
    """Su HTML la distinzione non esiste, e fingerla attribuirebbe una colpa
    a caso fra fornitore e comune."""
    scheda = leggi_scheda(PEOPLEWEB_HTML, declinazione=PEOPLEWEB)
    assert scheda.esposte is None
    assert scheda.dichiarate_vuote == frozenset()


def test_campo_con_solo_markup_non_conta_come_compilato():
    from treasureiq.ingest.modello_agid import leggi_scheda_cmb2

    scheda = leggi_scheda_cmb2({"_dci_servizio_box_come_fare": {"x": "<p><br></p>"}})
    assert scheda.sezioni == {}
    assert scheda.esposte == frozenset({SezioneAgid.COME_FARE})


def test_vincoli_distingue_assente_da_vuoto():
    """`assente` e' una scelta del fornitore, `vuoto` una del comune.

    Sommarli darebbe la colpa a chi non ce l'ha: un comune su una piattaforma
    che il campo non lo prevede non puo' pubblicare i requisiti nemmeno
    volendo.
    """
    from treasureiq.ingest.modello_agid import (
        VINCOLI_ASSENTE,
        VINCOLI_COMPILATO,
        VINCOLI_VUOTO,
        stato_vincoli,
    )

    assert stato_vincoli({"pnrr_constraints": "ISEE sotto 20.000"}) == VINCOLI_COMPILATO
    assert stato_vincoli({"sys_vincoli": ""}) == VINCOLI_VUOTO
    assert stato_vincoli({"pnrr_costs": "gratuito"}) == VINCOLI_ASSENTE
    assert stato_vincoli({}) == VINCOLI_ASSENTE


def test_vincoli_trovati_anche_annidati_nei_box():
    """Il tema WordPress annida i campi: `_dci_servizio_vincoli` vive dentro
    `_dci_servizio_box_accedi_servizio`. Fermarsi al primo livello direbbe
    `assente` per un campo che c'e' — ed e' esattamente il caso di Albano."""
    from treasureiq.ingest.modello_agid import VINCOLI_VUOTO, stato_vincoli

    cmb2 = {
        "_dci_servizio_box_accedi_servizio": {
            "_dci_servizio_vincoli": "",
            "_dci_servizio_canale_digitale_link": "https://x.it",
        }
    }
    assert stato_vincoli(cmb2) == VINCOLI_VUOTO


def test_markup_vuoto_non_conta_come_requisito_pubblicato():
    from treasureiq.ingest.modello_agid import VINCOLI_VUOTO, stato_vincoli

    assert stato_vincoli({"sys_vincoli": "<p><br></p>"}) == VINCOLI_VUOTO
