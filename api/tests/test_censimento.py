"""Test sull'estrazione della prova.

Tutti i casi qui sotto sono difetti realmente occorsi durante la costruzione
del censimento, non ipotesi: ognuno ha prodotto, su un portale vero, una
citazione sbagliata che sarebbe finita davanti a un cittadino. Restano scritti
perché la citazione è l'unica cosa che autorizza TreasureIQ a mostrare un
orario, e un difetto lì non si vede — la risposta continua ad avere l'aria di
essere precisa.
"""

from __future__ import annotations

import pytest

from treasureiq.ingest.censimento import ORARIO_RE, _cita


def cita(testo: str) -> str | None:
    trovato = ORARIO_RE.search(testo)
    return _cita(testo, trovato) if trovato else None


def test_intervallo_completo_non_solo_apertura():
    """La prima versione citava «Venerdì: 08.30», leggibile come "chiude alle
    8:30". Una citazione troncata è peggio di nessuna citazione."""
    assert cita("Venerdì: 08.30 - 12.30.") == "Venerdì: 08.30 - 12.30"


def test_orario_settimanale_intero():
    """Fermarsi alla prima riga direbbe che l'ufficio apre solo il lunedì."""
    testo = "Orari lunedì 15.00 - 17.30, martedì 9.00 - 12.00, sabato 9.00 - 11.30."
    citazione = cita(testo)
    assert "15.00 - 17.30" in citazione
    assert "9.00 - 11.30" in citazione


def test_il_centralino_non_e_un_orario():
    """`60.04` dentro «+39.0143.60.04.05» ha la forma di un'ora e stava a
    poche decine di caratteri da «sabato»: finiva dentro la citazione."""
    citazione = cita("Orari sabato 9.00 - 11.30 Telefono +39.0143.60.04.05")
    assert "+39" not in citazione
    assert citazione.endswith("11.30")


def test_un_giorno_senza_ora_non_e_un_orario():
    """"lunedì" da solo compare in mezzo mondo."""
    assert cita("Il consiglio si riunisce il lunedì in sala consiliare.") is None


def test_una_ora_senza_giorno_non_e_un_orario():
    assert cita("Il contributo ammonta a 12.50 euro per nucleo.") is None


def test_la_citazione_parte_dall_etichetta_non_dall_indirizzo():
    """Senza l'ancoraggio, metà della prova era l'indirizzo del municipio."""
    testo = "Sede Via Fabbri, 10 26030 Tornata (CR) Orari di apertura martedì 9.00 - 12.30"
    citazione = cita(testo)
    assert "Fabbri" not in citazione
    # Il taglio si dichiara: una citazione accorciata che non lo dice finge di
    # essere completa.
    assert citazione == "[…] Orari di apertura martedì 9.00 - 12.30"


def test_i_campi_in_fila_non_sono_una_frase():
    """Le schede AGID possono non contenere un solo punto fermo: senza `|`
    come confine l'espansione partiva dall'inizio della pagina e tagliava via
    proprio l'orario."""
    testo = "Contatti | Piazza della Costituente 1 | Email: urp@x.it | ORARIO Lunedì: 08.30 - 11.00"
    citazione = cita(testo)
    assert "Piazza" not in citazione
    assert "08.30 - 11.00" in citazione


def test_una_tabella_piu_lunga_della_citazione_dichiara_il_taglio():
    """Difetto reale, Villanova di Camposampiero: l'anagrafe apre lunedì 9-10
    per le CIE e 10-13 per tutto il resto, e citare la sola prima riga è
    verbatim e insieme falso — chi legge capisce che alle dieci chiude."""
    testo = (
        "Orari di ricevimento | Lunedì - 09:00-10:00 – Carta Identità Elettronica "
        "(su appuntamento) | Lunedì - 10:00-13:00 – Altre pratiche | Martedì - "
        "9:00-10:00 – Carta Identità | Mercoledì: CHIUSO | Giovedì - 9:00-13:00"
    )
    citazione = cita(testo)
    assert "10:00-13:00" in citazione, "la seconda fascia dello stesso giorno deve entrare"
    assert "Mercoledì: CHIUSO" in citazione, "e le chiusure fanno parte dell'orario"


def test_una_tabella_troppo_lunga_dichiara_il_taglio():
    """Quando la settimana non sta nella citazione, il marcatore è l'unica
    cosa che impedisce a un estratto di spacciarsi per l'orario completo."""
    righe = " | ".join(
        f"{giorno} - 09:00-13:00 e 14:00-18:00 – sportello al pubblico"
        for giorno in ("Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato")
    )
    citazione = cita(f"Orari di ricevimento | {righe}")
    assert citazione.endswith("[…]")
    assert len(citazione) <= 260


def test_niente_taglio_dichiarato_quando_non_c_e_altro():
    """Il marcatore deve comparire solo quando è vero: metterlo sempre lo
    renderebbe rumore e smetterebbe di voler dire qualcosa."""
    assert not cita("Orari lunedì 9.00 - 12.00. Sede in via Roma.").endswith("[…]")


@pytest.mark.parametrize(
    "testo, atteso",
    [
        ("Apertura lunedì dalle 9:00 alle 13:00.", "9:00"),
        # Come lo scrive mezza Italia, e come lo scrive Castro (LE): senza
        # l'«ore» opzionale la citazione si fermava all'apertura.
        ("Dal lunedì al venerdì: dalle ore 9:00 alle ore 12:00.", "12:00"),
        ("Ricevimento del pubblico mercoledì 9.00-13.00 e 14.00-16.00.", "14.00-16.00"),
    ],
)
def test_formati_diversi_della_stessa_cosa(testo: str, atteso: str):
    assert atteso in cita(testo)


def test_sonda_non_cancella_la_query_string(monkeypatch):
    """`params={}` non è "nessun parametro": httpx lo legge come "la query è
    questa" e cancella quella dell'URL.

    Il difetto era invisibile e caro: `Servizi?ID=130875` diventava `Servizi`,
    la sonda leggeva l'indice al posto della scheda, e l'aderenza di PeopleWeb
    risultava non misurabile su 35 comuni le cui schede erano perfettamente
    leggibili.
    """
    from treasureiq.ingest import censimento

    chiamate: list[tuple] = []

    class FintoClient:
        def get(self, url, **kwargs):
            chiamate.append((url, kwargs))

            class R:
                status_code = 200
                text = "ok"
                url = "x"

                def raise_for_status(self):
                    return None

            return R()

        def close(self):
            return None

    sonda = censimento._Sonda.__new__(censimento._Sonda)
    sonda._client = FintoClient()
    sonda.richieste = 0
    sonda.raggiungibile = None

    sonda.testo("https://esempio.it/Servizi?ID=1")
    assert "params" not in chiamate[-1][1], "senza parametri httpx non deve ricevere params"

    sonda.testo("https://esempio.it/altro")
    assert "params" not in chiamate[-1][1]


def test_censisci_molti_salva_a_blocchi(monkeypatch):
    """Su scala nazionale la raccolta dura un'ora: tenere tutto in memoria fino
    alla fine significa che un'interruzione butta via migliaia di misure, cioè
    migliaia di portali pubblici interrogati per niente.

    Il blocco parziale in coda deve essere salvato anche quando non raggiunge
    la soglia, altrimenti gli ultimi comuni sparirebbero in silenzio — il tipo
    di perdita che non lascia traccia in nessun log.
    """
    from treasureiq.ingest import censimento

    def finto(*, codice_istat, nome, sito, leggi_pagina, misura_piattaforma, misura_aderenza, regione=None, ipa_noto=None):
        return censimento.EsitoCensimento(
            codice_istat=codice_istat,
            nome=nome,
            sito=sito,
            indirizzabilita=censimento.Indirizzabilita.SOLO_HTML,
            recuperabilita=censimento.RecuperabilitaOrari.NON_TENTATO,
        )

    monkeypatch.setattr(censimento, "censisci_comune", finto)
    comuni = [{"codice_istat": f"{i:06d}", "nome": f"C{i}", "sito": "x.it"} for i in range(7)]
    blocchi: list[int] = []

    esiti = censimento.censisci_molti(
        comuni,
        leggi_pagina=False,
        lavoratori=2,
        salva=lambda blocco: blocchi.append(len(blocco)),
        ogni=3,
    )

    assert len(esiti) == 7
    assert sum(blocchi) == 7, "ogni esito deve essere passato al salvataggio una volta sola"
    assert blocchi == [3, 3, 1], "il resto in coda va salvato anche se sotto soglia"


def test_meta_refresh_riconosciuto_come_cartello():
    """Sessantacinque comuni campani risultavano senza alcuna firma: la loro
    home e' un documento di 179 byte con dentro
    `<meta http-equiv="refresh" content="0;URL=/sito/">`.

    Non e' un redirect HTTP, quindi `follow_redirects` non lo segue, e la
    sonda leggeva il cartello concludendo che il portale non dichiarasse
    niente — una diagnosi sbagliata su portali perfettamente normali.
    """
    from treasureiq.ingest.censimento import _segui_meta_refresh

    stub = '<html><head><meta http-equiv="refresh" content="0;URL=https://x.it/sito/"></head></html>'
    assert _segui_meta_refresh(sonda=None, base="https://x.it", corpo=stub) == "https://x.it/sito/"

    relativo = '<meta http-equiv="Refresh" content="0; url=/sito/">'
    assert _segui_meta_refresh(sonda=None, base="https://x.it/", corpo=relativo) == "https://x.it/sito/"


def test_pagina_vera_non_viene_scambiata_per_un_cartello():
    """Una pagina lunga con dentro un meta refresh (una redirezione dopo N
    secondi, un avviso) e' un portale, non un cartello: seguirla porterebbe
    la sonda via dal contenuto che stava gia' leggendo."""
    from treasureiq.ingest.censimento import _segui_meta_refresh

    lunga = '<meta http-equiv="refresh" content="30;URL=/altro">' + ("<p>contenuto</p>" * 400)
    assert _segui_meta_refresh(sonda=None, base="https://x.it", corpo=lunga) is None


def test_corpo_myportal_usa_oggetti_per_le_tassonomie():  # noqa: D401
    """L'API MyPortal rifiuta con 400 se i quattro campi di tassonomia
    arrivano come liste invece che come oggetti.

    Un dizionario vuoto e una lista vuota si stampano quasi uguali quando si
    ispeziona una cattura di rete, ed e' cosi' che abbiamo sbagliato la prima
    volta: il test fissa la forma, che l'occhio non distingue.
    """
    from treasureiq.ingest.myportal import corpo_ricerca

    corpo = corpo_ricerca("rer_schedaservizio")
    for campo in (
        "taxonomiesMust",
        "taxonomiesShould",
        "extraTaxonomiesMust",
        "extraTaxonomiesShould",
    ):
        assert isinstance(corpo[campo], dict), campo
    assert isinstance(corpo["orderBy"], list)
    assert corpo["types"] == ["rer_schedaservizio"]


def test_tipi_candidati_ordina_per_specificita_e_scarta_i_falsi():
    """Su Abano Terme il primo candidato per specificita' rende zero e il
    secondo novantadue: la scelta va misurata, non dedotta.

    Qui si fissa solo l'ordinamento e l'esclusione dei tipi che contengono la
    parola ma descrivono altro — `atti_opere_servizi_forniture` non e' un
    catalogo di servizi al cittadino.
    """
    from treasureiq.ingest.myportal import tipi_candidati

    payload = {
        "status": "ok",
        "entities": [
            {"name": "Allegato", "type": "rve_allegato"},
            {"name": "Atti opere", "type": "AT_myp_atti_opere_servizi_forniture"},
            {"name": "Servizio PNRR", "type": "pnrr_service"},
            {"name": "Scheda servizio", "type": "rer_schedaservizio"},
        ],
    }
    assert tipi_candidati(payload) == ["rer_schedaservizio", "pnrr_service"]
    assert tipi_candidati({"status": "ok", "entities": []}) == []
    assert tipi_candidati(None) == []


def test_codice_ipa_normalizzato_in_maiuscolo():
    """IndicePA distribuisce i codici in minuscolo, MyPortal risponde solo al
    maiuscolo — e al minuscolo risponde `200` con zero contenuti invece di un
    errore. Un comune che pubblica 53 servizi risulterebbe vuoto."""
    from treasureiq.ingest.myportal import normalizza_ipa

    assert normalizza_ipa("c_a138") == "C_A138"
    assert normalizza_ipa("  C_a138 ") == "C_A138"
    assert normalizza_ipa(None) is None
    assert normalizza_ipa("") is None


def test_limite_modello_ferma_il_ciclo_e_dice_quando_riprovare(monkeypatch):
    """`/api/chat` invoca un modello, quindi ogni richiesta costa denaro: senza
    limite chiunque conosca l'URL trasforma quel costo in un problema nostro.

    Il `Retry-After` non e' cortesia formale — senza, un client automatico
    riprova subito e trasforma il limite in un ciclo piu' stretto.
    """
    from fastapi import HTTPException

    from treasureiq import api

    monkeypatch.setattr(api, "LIMITE_MODELLO", 2)
    monkeypatch.setattr(api, "FINESTRA_MODELLO", 60)
    api._chiamate_modello.clear()

    class FintaRichiesta:
        cookies: dict = {}

        class client:
            host = "203.0.113.7"

    richiesta = FintaRichiesta()
    api.limita_modello(richiesta)
    api.limita_modello(richiesta)

    try:
        api.limita_modello(richiesta)
    except HTTPException as errore:
        assert errore.status_code == 429
        assert int(errore.headers["Retry-After"]) > 0
    else:
        raise AssertionError("la terza chiamata doveva essere respinta")


def test_limite_modello_separa_i_chiamanti(monkeypatch):
    """Limitare per solo IP punirebbe piu' persone dietro lo stesso ufficio o
    la stessa rete mobile: la sessione, quando c'e', viene prima."""
    from treasureiq import api

    monkeypatch.setattr(api, "LIMITE_MODELLO", 1)
    api._chiamate_modello.clear()

    class Richiesta:
        def __init__(self, cookie):
            self.cookies = {api.SESSION_COOKIE: cookie} if cookie else {}
            self.client = type("c", (), {"host": "203.0.113.7"})()

    api.limita_modello(Richiesta("alice"))
    # Un'altra sessione dallo stesso indirizzo non deve essere bloccata.
    api.limita_modello(Richiesta("bruno"))
