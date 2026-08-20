"""Test sull'estrazione della prova.

Tutti i casi qui sotto sono difetti realmente occorsi durante la costruzione
del censimento, non ipotesi: ognuno ha prodotto, su un portale vero, una
citazione sbagliata che sarebbe finita davanti a un cittadino. Restano scritti
perché la citazione è l'unica cosa che autorizza TreasureIQ a mostrare un
orario, e un difetto lì non si vede — la risposta continua ad avere l'aria di
essere precisa.
"""

from __future__ import annotations

from pathlib import Path

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
    """Il limite anonimo è per indirizzo quando non esiste una sessione."""
    from treasureiq import api
    from fastapi import HTTPException

    monkeypatch.setattr(api, "LIMITE_MODELLO", 1)
    api._chiamate_modello.clear()

    class Richiesta:
        cookies = {}
        client = type("c", (), {"host": "203.0.113.7"})()

    api.limita_modello(Richiesta())
    with pytest.raises(HTTPException) as errore:
        api.limita_modello(Richiesta())
    assert errore.value.status_code == 429


# --- Amministrazione Trasparente: firme + discovery (ciclo 16, brief B3) ---
#
# Le fixture qui sotto vengono dallo spike B1 (`.kapi/spike-at.md`): ogni
# firma testata corrisponde a un campione reale, non a un'ipotesi.

_FIXTURE_AT = Path(__file__).parent / "fixtures" / "at"


def _leggi_fixture_at(nome: str) -> str:
    return (_FIXTURE_AT / nome).read_text(encoding="utf-8")


def test_classifica_risposta_isweb_su_pagina_at():
    """Barletta e Prato: stesso CMS (`IsWeb, il cms`) su due comuni diversi.
    La firma è già nella batteria BASE (`_GENERATOR`): qui si verifica solo
    che riconosca anche l'HTML della pagina AT, non della home."""
    from treasureiq.ingest.piattaforma import Piattaforma, classifica_risposta

    for nome_fixture in ("barletta_isweb_head.html", "prato_isweb_head.html"):
        html = _leggi_fixture_at(nome_fixture)
        esito = classifica_risposta(headers={}, html=html)
        assert esito.vincitore.piattaforma == Piattaforma.ISWEB


def test_classifica_risposta_halley_trasparenza():
    """Delebio: `var ente = "c<ISTAT>"` + asset `/km/design-web-toolkit/`
    insieme sono il fingerprint Halley "zf", non uno dei due da solo."""
    from treasureiq.ingest.piattaforma import Piattaforma, classifica_risposta

    html = _leggi_fixture_at("delebio_halley_zf_head.html")
    esito = classifica_risposta(headers={}, html=html)
    assert esito.vincitore.piattaforma == Piattaforma.HALLEY_TRASPARENZA


def test_classifica_risposta_halley_ente_da_solo_non_basta():
    """`var ente = "c<ISTAT>"` da solo (senza /km/design-web-toolkit/) non è
    prova sufficiente — mitiga il rischio mono-campione: 1 solo segnale può
    comparire per coincidenza in un CMS diverso da Halley."""
    from treasureiq.ingest.piattaforma import Piattaforma, classifica_risposta

    html = '<html><head></head><body><script>var ente = "c012345";</script></body></html>'
    esito = classifica_risposta(headers={}, html=html)
    assert esito.vincitore.piattaforma != Piattaforma.HALLEY_TRASPARENZA


def test_classifica_risposta_halley_kamaleonte_da_solo_non_basta():
    """`/km/design-web-toolkit/` da solo (senza `var ente = "c<ISTAT>"`) non è
    prova sufficiente — stesso motivo del test gemello sopra: serve la
    congiunzione dei due segnali, non un asset path isolato."""
    from treasureiq.ingest.piattaforma import Piattaforma, classifica_risposta

    html = '<html><head><link href="/km/design-web-toolkit/style.css"></head><body></body></html>'
    esito = classifica_risposta(headers={}, html=html)
    assert esito.vincitore.piattaforma != Piattaforma.HALLEY_TRASPARENZA


def test_classifica_risposta_wp_amm_trasp():
    """Neive: il tema design-comuni-wordpress-theme marca l'archivio AT con
    la classe `post-type-archive-amm_trasp` sul `<body>`."""
    from treasureiq.ingest.piattaforma import Piattaforma, classifica_risposta

    html = _leggi_fixture_at("neive_wp_amm_trasp_head.html")
    esito = classifica_risposta(headers={}, html=html)
    assert esito.vincitore.piattaforma == Piattaforma.WP_AMM_TRASP


def test_classifica_risposta_jcitygov():
    """Peveragno: il SaaS AT indipendente si riconosce dal dominio
    `trasparenza-valutazione-merito.it`, cross-famiglia rispetto al CMS
    di base (qui WordPress; a Chieri/Grugliasco è Municipium)."""
    from treasureiq.ingest.piattaforma import Piattaforma, classifica_risposta

    html = _leggi_fixture_at("peveragno_jcitygov_head.html")
    esito = classifica_risposta(headers={}, html=html)
    assert esito.vincitore.piattaforma == Piattaforma.JCITYGOV


def test_scopri_url_at_delebio_segue_la_landing_locale():
    """Delebio: l'unico candidato nella home è l'ancora con etichetta
    "Amministrazione trasparente" (in `alt`/`title` dell'icona, non nel
    testo diretto dell'ancora) verso la landing locale Halley."""
    from treasureiq.ingest import censimento

    html_home = _leggi_fixture_at("delebio_home_head.html")
    url = censimento.scopri_url_at(html_home, "https://www.comune.delebio.so.it")
    assert url == "https://www.comune.delebio.so.it/amministrazione/trasparenza/trasparenza.html"


def test_scopri_url_at_peveragno_preferisce_il_link_corrente():
    """Peveragno ha DUE ancore etichettate "Amministrazione Trasparente":
    quella corrente (jcitygov, "dal 24/11/2025") e quella scaduta (WP
    nativo `/amm_trasp/`, "fino al 23/11/2025"). La prima in ordine di
    documento è quella corrente — e vince, non un terzo distrattore
    (`amministrazionetrasparente.aspx` di Maggioli, etichettato "ANAC -
    Contratti pubblici", che non deve intercettare nulla)."""
    from treasureiq.ingest import censimento

    html_home = _leggi_fixture_at("peveragno_home_at_links.html")
    url = censimento.scopri_url_at(html_home, "https://comune.peveragno.cn.it")
    assert url == "https://peveragno.trasparenza-valutazione-merito.it/web/trasparenza/trasparenza"


def test_scopri_url_at_shell_angular_nessun_link_e_non_trovata():
    """SIAMO/Publisys: la home è uno shell Angular senza href
    server-rendered. Nessuna ancora in nessuna priorità → `None`, non un
    URL indovinato sul pattern di un'altra piattaforma."""
    from treasureiq.ingest import censimento

    html_shell = (
        '<html><body><app-root ng-version="16.2.0"></app-root>'
        '<script src="/main.js"></script></body></html>'
    )
    url = censimento.scopri_url_at(html_shell, "https://comune.esempio.it")
    assert url is None


def test_scopri_pagina_at_shell_angular_ritorna_non_trovata():
    """L'esito pubblico per SIAMO/Publisys: `NON_TROVATA` onesto, nessun
    fetch tentato (nessun URL da cui farlo)."""
    from treasureiq.ingest import censimento
    from treasureiq.ingest.piattaforma import Piattaforma

    html_shell = "<html><body><app-root></app-root></body></html>"
    esito = censimento.scopri_pagina_at(html_home=html_shell, base="https://comune.esempio.it")
    assert esito.piattaforma_at == Piattaforma.NON_TROVATA
    assert esito.at_url is None
    assert esito.piattaforma_at_prova is None
    assert esito.firme_scattate == []


class _RispostaAtFinta:
    """Doppio finto di `httpx.Response` in streaming, quanto basta per
    `_fetch_at_guardato`: `.url`, `.status_code`, `.headers`, `.iter_bytes()`
    e il protocollo di context manager di `client.stream(...)`."""

    def __init__(self, *, url: str, status_code: int = 200, corpo: bytes = b""):
        self.url = url
        self.status_code = status_code
        self.headers: dict = {}
        self._corpo = corpo

    def iter_bytes(self):
        yield self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _ClientAtFinto:
    """Sostituisce `httpx.Client` nei test di `_fetch_at_guardato`: niente
    rete reale. Una nuova istanza viene creata a OGNI hop (stessa cosa che fa
    il codice vero), quindi qui si consuma una risposta finta da una coda —
    non un singolo oggetto riusato per tutti gli hop."""

    def __init__(self, risposta: "_RispostaAtFinta"):
        self._risposta = risposta

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, metodo, url):
        return self._risposta


def _client_at_finto_in_coda(risposte: list["_RispostaAtFinta"]):
    """Fabbrica per `censimento.httpx.Client`: ogni chiamata (un hop) estrae
    la prossima risposta finta dalla coda, nell'ordine in cui il codice le
    richiederebbe davvero."""

    def _fabbrica(**kw):
        return _ClientAtFinto(risposte.pop(0))

    return _fabbrica


def _dns_finto(ip_per_host: dict[str, str] | None = None, *, ip_fisso: str | None = None):
    """Fabbrica per `host_guard.socket.getaddrinfo`: mai una query DNS
    reale nei test. `ip_fisso` risponde lo stesso IP per qualunque host;
    `ip_per_host` fa risolvere host diversi a IP diversi (per simulare un
    DNS che cambia risposta tra un hop e il successivo)."""

    def _getaddrinfo(host, port):
        ip = ip_per_host[host] if ip_per_host else ip_fisso
        return [(2, 1, 6, "", (ip, 0))]

    return _getaddrinfo


def _dns_sequenza_finta(ip_per_chiamata: list[str]):
    """Come `_dns_finto`, ma risponde IP diversi a chiamate successive sullo
    STESSO host — serve a provare che il check IP viene rieseguito a ogni
    hop, non solo una tantum sulla prima risoluzione."""
    sequenza = iter(ip_per_chiamata)

    def _getaddrinfo(host, port):
        return [(2, 1, 6, "", (next(sequenza), 0))]

    return _getaddrinfo


def test_fetch_at_guardato_hostname_risolve_a_ip_metadata_e_bloccato(monkeypatch):
    """BLOCKER SSRF: l'host nell'URL è testualmente pubblico
    (`trasparenza.comune-deface.it`), ma il suo DNS (sotto controllo di chi
    ha compromesso il comune) risolve a `169.254.169.254`, l'IP metadata dei
    provider cloud. Il vecchio guard controllava solo se l'URL contenesse
    già un IP letterale: qui il DNS deve essere risolto e ogni IP validato
    PRIMA del connect. Nessuna richiesta HTTP deve nemmeno partire."""
    from treasureiq.ingest import censimento
    from treasureiq.ingest import host_guard

    monkeypatch.setattr(
        host_guard.socket, "getaddrinfo", _dns_finto(ip_fisso="169.254.169.254")
    )

    def _client_non_deve_essere_chiamato(**kw):
        raise AssertionError("non deve tentare la rete se l'host risolve a IP non sicuro")

    monkeypatch.setattr(censimento.httpx, "Client", _client_non_deve_essere_chiamato)

    esito = censimento._fetch_at_guardato("https://trasparenza.comune-deface.it/pagina")
    assert esito is None


def test_fetch_at_guardato_redirect_verso_ip_interno_e_bloccato(monkeypatch):
    """Il redirect resta sullo STESSO host (quindi il check di identità host
    non basterebbe a bloccarlo): fra il primo hop e il secondo il DNS
    dell'host risolve a un IP diverso, interno. Il check IP deve essere
    rieseguito a ogni hop e bloccare il secondo, non fidarsi della
    risoluzione fatta per il primo."""
    from treasureiq.ingest import censimento
    from treasureiq.ingest import host_guard

    host = "trasparenza.comune-deface.it"
    redirect = _RispostaAtFinta(url=f"https://{host}/step1", status_code=302, corpo=b"")
    redirect.headers = {"location": f"https://{host}/step2"}
    monkeypatch.setattr(censimento.httpx, "Client", _client_at_finto_in_coda([redirect]))
    monkeypatch.setattr(
        host_guard.socket,
        "getaddrinfo",
        _dns_sequenza_finta(["93.184.216.34", "169.254.169.254"]),
    )

    esito = censimento._fetch_at_guardato(f"https://{host}/step1")
    assert esito is None


def test_fetch_at_guardato_redirect_fuori_host_e_scartato(monkeypatch):
    """Guardia sull'identità dell'host (complementare al check IP, non un
    suo sostituto): l'URL richiesto sta su
    `trasparenza-valutazione-merito.it`, il redirect (302 + `Location`) porta
    a un host completamente diverso — mai seguito, anche se quel secondo
    host risolvesse a un IP pubblico innocuo."""
    from treasureiq.ingest import censimento
    from treasureiq.ingest import host_guard

    redirect = _RispostaAtFinta(
        url="https://peveragno.trasparenza-valutazione-merito.it/web/trasparenza/trasparenza",
        status_code=302,
        corpo=b"",
    )
    redirect.headers = {"location": "https://host-esterno-inatteso.example.com/phishing"}
    monkeypatch.setattr(censimento.httpx, "Client", _client_at_finto_in_coda([redirect]))
    monkeypatch.setattr(
        host_guard.socket, "getaddrinfo", _dns_finto(ip_fisso="93.184.216.34")
    )

    esito = censimento._fetch_at_guardato(
        "https://peveragno.trasparenza-valutazione-merito.it/web/trasparenza/trasparenza"
    )
    assert esito is None


def test_fetch_at_guardato_scarta_schema_non_http():
    """Uno schema diverso da http/https (qui `javascript:`) va scartato
    prima di qualunque tentativo di rete o risoluzione DNS."""
    from treasureiq.ingest import censimento

    assert censimento._fetch_at_guardato("javascript:alert(1)") is None


def test_fetch_at_guardato_scarta_ip_privato():
    """Un URL che punta letteralmente a un IP privato è scartato dalla
    stessa validazione IP della risoluzione DNS (qui non c'è nemmeno un
    hostname da risolvere: `socket.getaddrinfo` su un IP letterale lo
    ritorna tale e quale, senza query di rete)."""
    from treasureiq.ingest import censimento

    assert censimento._fetch_at_guardato("http://127.0.0.1/trasparenza") is None
    assert censimento._fetch_at_guardato("http://10.0.0.5/trasparenza") is None


def test_fetch_at_guardato_accetta_stesso_host_e_classifica(monkeypatch):
    """Percorso felice: DNS a IP pubblico, nessun redirect fuori host, la
    pagina scaricata è quella Halley di Delebio — `scopri_pagina_at` la
    classifica con la stessa batteria BASE, e l'URL torna verificato, non
    indovinato."""
    from treasureiq.ingest import censimento
    from treasureiq.ingest import host_guard
    from treasureiq.ingest.piattaforma import Piattaforma

    html_at = _leggi_fixture_at("delebio_halley_zf_head.html")
    url_at = "https://www.comune.delebio.so.it/amministrazione/trasparenza/trasparenza.html"
    risposta = _RispostaAtFinta(url=url_at, status_code=200, corpo=html_at.encode("utf-8"))
    monkeypatch.setattr(censimento.httpx, "Client", _client_at_finto_in_coda([risposta]))
    monkeypatch.setattr(
        host_guard.socket, "getaddrinfo", _dns_finto(ip_fisso="93.184.216.34")
    )
    html_home = _leggi_fixture_at("delebio_home_head.html")

    esito = censimento.scopri_pagina_at(html_home=html_home, base="https://www.comune.delebio.so.it")

    assert esito.piattaforma_at == Piattaforma.HALLEY_TRASPARENZA
    assert esito.at_url == url_at
    assert esito.piattaforma_at_prova is not None
    assert esito.firme_scattate


def test_impronta_infila_la_discovery_at_nella_riga(monkeypatch):
    """Ciclo 16: `_impronta` deve vedere l'AT su OGNI comune misurato, non
    solo dentro `leggi_connettore`. Qui mockiamo solo `_fetch_at_guardato`
    (il fetch guardato SSRF della pagina AT) — la home arriva da una `sonda`
    finta minimale, senza toccare rete o `httpx.Client` reale: dimostra che
    `scopri_pagina_at` viene chiamato con la stessa home già scaricata
    (`resp.text`/`base`), non un secondo fetch."""
    from treasureiq.ingest import censimento
    from treasureiq.ingest.piattaforma import Piattaforma

    html_at = _leggi_fixture_at("neive_wp_amm_trasp_head.html")
    url_at = "https://comune.esempio.it/amministrazione-trasparente/"
    html_home = (
        "<html><body>"
        '<a href="/amministrazione-trasparente/">Amministrazione Trasparente</a>'
        "</body></html>"
    )

    chiamate_at = []

    def _fetch_finto(url: str, *, timeout: float = 8.0):
        chiamate_at.append(url)
        return {}, html_at

    monkeypatch.setattr(censimento, "_fetch_at_guardato", _fetch_finto)

    class _RispostaFinta:
        text = html_home
        headers: dict = {}
        status_code = 200
        url = "https://comune.esempio.it"

    class _SondaFinta:
        richieste = 1

        def risposta(self, url: str):
            return _RispostaFinta()

    esito = censimento._impronta(sonda=_SondaFinta(), base="https://comune.esempio.it")

    # Un solo fetch AT (nessun doppio-fetch della home): la sonda finta non
    # viene interrogata una seconda volta per l'AT, solo _fetch_at_guardato.
    assert chiamate_at == [url_at]
    assert esito["piattaforma_at"] == Piattaforma.WP_AMM_TRASP.value
    assert esito["at_url"] == url_at
    assert esito["piattaforma_at_prova"] is not None
    assert esito["firme_scattate"]

    campione = censimento.EsitoCensimento(
        codice_istat="000000",
        nome="Comune di Esempio",
        sito="https://comune.esempio.it",
        indirizzabilita=censimento.Indirizzabilita.SOLO_HTML,
        recuperabilita=censimento.RecuperabilitaOrari.NON_TENTATO,
        **esito,
    )
    assert campione.piattaforma_at == Piattaforma.WP_AMM_TRASP.value
    assert campione.at_url == url_at


def test_impronta_registra_non_trovata_onestamente(monkeypatch):
    """Nessun link AT nella home → `NON_TROVATA` senza alcun fetch, e il
    valore vincitore va comunque registrato (onestà D-16): mai `None` per
    convenienza quando la sonda non ha semplicemente misurato nulla."""
    from treasureiq.ingest import censimento
    from treasureiq.ingest.piattaforma import Piattaforma

    def _fetch_mai_chiamato(url: str, *, timeout: float = 8.0):
        raise AssertionError("nessun link AT nella home: _fetch_at_guardato non va invocato")

    monkeypatch.setattr(censimento, "_fetch_at_guardato", _fetch_mai_chiamato)

    class _RispostaFinta:
        text = "<html><body>nessun link qui</body></html>"
        headers: dict = {}
        status_code = 200
        url = "https://comune.esempio.it"

    class _SondaFinta:
        richieste = 1

        def risposta(self, url: str):
            return _RispostaFinta()

    esito = censimento._impronta(sonda=_SondaFinta(), base="https://comune.esempio.it")

    assert esito["piattaforma_at"] == Piattaforma.NON_TROVATA.value
    assert esito["at_url"] is None
