"""Che software gira sotto il portale di un comune.

Il censimento t0 misurava due assi: se il portale è indirizzabile e se l'orario
è recuperabile. Nessuno dei due dice *perché*. Un comune finito in `SOLO_HTML`
può essere un WordPress senza il tema giusto — a cui manca una riga di
configurazione — oppure un Liferay del 2014, che è un connettore nuovo da
scrivere. Sono due costi diversi di un ordine di grandezza, e finora
cadevano nella stessa casella.

Questo modulo separa il riconoscimento dalla rete: le funzioni qui dentro
ricevono ciò che il portale ha già risposto e non chiedono niente a nessuno.
Così la classificazione si testa su stringhe fissate, e una firma nuova si
aggiunge senza rifare un giro su ottomila server.

Ogni classificazione porta con sé la stringa che l'ha decisa. Un enum senza
prova è un'opinione con una faccia seria: se domani `wp_design_comuni` risulta
sovrastimato, si va a leggere `prova` e si capisce dove sbagliava la firma.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple

#: Quanto testo della home guardiamo. Il `<head>` sta nei primi kilobyte;
#: leggere tutta la pagina per trovare un meta tag costa banda a loro.
FINESTRA_HEAD = 8_192


class Piattaforma(str, Enum):
    """Le famiglie di portale, ordinate per quanto ci costa leggerle.

    Non è una tassonomia del web: è una tassonomia del *lavoro che resta*.
    Due CMS diversi che si leggono con lo stesso connettore starebbero nella
    stessa voce.
    """

    #: WordPress col tema Design Comuni Italia: `servizi` tipizzati, il caso
    #: che TreasureIQ già sa leggere. Costo di ingestione: zero codice nuovo.
    WP_DESIGN_COMUNI = "wp_design_comuni"
    #: WordPress senza quel tema. L'API REST c'è, il vocabolario dei servizi
    #: no: si legge, ma va mappato.
    WORDPRESS_GENERICO = "wordpress_generico"
    #: PeopleWeb di Siscom: ASP.NET WebForms col tema Bootstrap Italia. Non si
    #: dichiara da nessuna parte — né generator, né header, né nome del
    #: fornitore nel markup — ma espone due rotte fisse, `/Mappasito` e
    #: `/Datimonitoraggio`, e la mappa del sito elenca i servizi con un
    #: vocabolario di rotte stabile fra installazioni diverse. È leggibile
    #: quanto WordPress: solo, va letto in HTML invece che in JSON.
    PEOPLEWEB = "peopleweb"
    #: ComWeb di ePublic. Al contrario di PeopleWeb si dichiara nel `generator`,
    #: e pubblica un feed RSS per categoria — comprese `bandi-e-avvisi-di-gara`
    #: e `avvisi-novita`, che è materiale da rail agevolazione già impaginato.
    COMWEB = "comweb"
    #: Fornitori civici italiani che si dichiarano nel `generator`. Erano già
    #: distinguibili come "generator ignoto"; nominarli serve a contarli senza
    #: passare da un raggruppamento a mano.
    DOTNETNUKE = "dotnetnuke"
    FLEXCMP = "flexcmp"
    ISWEB = "isweb"
    CITYPAL = "citypal"
    #: Famiglie riconosciute dai segnali grezzi invece che da una
    #: dichiarazione. Vedi `da_impronta`: sono portali che non si presentano,
    #: identificati dalla forma di ciò che servono.
    #:
    #: `HGATE` prende il nome dall'header del server, non dal fornitore.
    #: L'accoppiata con le rotte `.hbl` fa pensare a un'azienda precisa, ma
    #: finché non è verificato il nome resta quello che abbiamo misurato:
    #: mettere in tabella il nome di un'azienda per inferenza è un'accusa,
    #: non una classificazione.
    HGATE = "hgate"
    OPENPA = "openpa"
    #: Municipium, di Maggioli. Non si dichiara nel `generator` ne' negli
    #: header, ma serve gli asset da `municipiumapp.it`: un host esterno, che
    #: le prime versioni di questa impronta non guardavano affatto — e per
    #: questo novecentotrentuno comuni, il gruppo piu' grande d'Italia, sono
    #: rimasti "non riconosciuti" per mezza giornata.
    MUNICIPIUM = "municipium"
    #: eGov (D-10): firmata dalla rotta `/EG0/EGS*.HBL` con querystring
    #: `en=eg###` — vista su Marino (RM), `en=eg176`. Il nome è quello della
    #: firma osservata (asset/rotta), non di un fornitore dichiarato: nessun
    #: `generator` né header la nomina.
    EGOV = "egov"
    #: Piattaforma Laravel col tema Bootstrap Italia, riconosciuta dalla rotta
    #: `/agenda-smart` che espone: verificata su otto comuni di cinque regioni
    #: diverse. Il nome e' quello della rotta, non del fornitore, che non si
    #: dichiara da nessuna parte.
    AGENDA_SMART = "agenda_smart"
    MAGNOLIA = "magnolia"
    COMUNIBOOTSTRAPITALIA = "comunibootstrapitalia"
    #: Non un fornitore: la piattaforma condivisa di una Regione, che ospita i
    #: portali dei propri comuni. Tenerla distinta conta, perché racconta il
    #: contrario di un portale disordinato — è il modello che funziona.
    REGIONE_FVG = "regione_fvg"
    REGIONE_VENETO = "regione_veneto"
    #: La Rete Civica di Lepida, societa' in-house della Regione
    #: Emilia-Romagna. Il nome non e' dedotto: `retecivica.lepida.it` risponde
    #: con lo stesso `nginx/1.18.0` dei comuni che la usano.
    RETE_CIVICA_LEPIDA = "rete_civica_lepida"
    #: Prodotto ASP.NET diffuso nel sud, riconosciuto dalla rotta
    #: `/pageobject/…` che espone. Il nome è quello della rotta, non del
    #: fornitore, che non abbiamo verificato: verificata è invece la rotta,
    #: che risponde su sei comuni su sei di tre regioni diverse.
    PAGEOBJECT = "pageobject"
    DRUPAL = "drupal"
    JOOMLA = "joomla"
    LIFERAY = "liferay"
    TYPO3 = "typo3"
    PLONE = "plone"
    #: Risponde, ma nessuna firma nota. È la voce che dice quanta strada
    #: resta: se cresce, servono firme nuove, non connettori nuovi.
    IGNOTA = "ignota"
    #: Non si è potuto guardare: DNS che non risolve, TLS rotto, timeout.
    #: Diverso da `IGNOTA`, e i due non vanno mai sommati.
    NON_MISURATA = "non_misurata"


class Firma(NamedTuple):
    """Una piattaforma riconosciuta, con la prova verbatim che l'ha decisa."""

    piattaforma: Piattaforma
    #: La stringa esatta letta dal portale: un header, un meta generator, un
    #: percorso che ha risposto. Troncata, mai riscritta.
    prova: str | None


#: `generator` come lo scrivono i CMS, in ordine di specificità. WordPress sta
#: in fondo di proposito: alcuni temi civici dichiarano sia WordPress sia il
#: proprio nome, e la firma più specifica deve vincere.
_GENERATOR: tuple[tuple[re.Pattern[str], Piattaforma], ...] = (
    (re.compile(r"\bDrupal\b", re.I), Piattaforma.DRUPAL),
    (re.compile(r"\bJoomla!?\b", re.I), Piattaforma.JOOMLA),
    (re.compile(r"\bLiferay\b", re.I), Piattaforma.LIFERAY),
    (re.compile(r"\bTYPO3\b", re.I), Piattaforma.TYPO3),
    (re.compile(r"\bComWeb\b", re.I), Piattaforma.COMWEB),
    (re.compile(r"\bDotNetNuke\b|\bDNN\b", re.I), Piattaforma.DOTNETNUKE),
    (re.compile(r"\bFlexCMP\b", re.I), Piattaforma.FLEXCMP),
    (re.compile(r"\bIsWeb\b", re.I), Piattaforma.ISWEB),
    (re.compile(r"\bCityPal\b", re.I), Piattaforma.CITYPAL),
    (re.compile(r"\bPlone\b", re.I), Piattaforma.PLONE),
    (re.compile(r"\bWordPress\b", re.I), Piattaforma.WORDPRESS_GENERICO),
)

#: Header che dichiarano il CMS senza che serva leggere una riga di HTML.
_HEADER_SPIA: tuple[tuple[str, re.Pattern[str], Piattaforma], ...] = (
    ("x-drupal-cache", re.compile(r".*"), Piattaforma.DRUPAL),
    ("x-drupal-dynamic-cache", re.compile(r".*"), Piattaforma.DRUPAL),
    ("x-generator", re.compile(r"\bDrupal\b", re.I), Piattaforma.DRUPAL),
    ("x-generator", re.compile(r"\bTYPO3\b", re.I), Piattaforma.TYPO3),
    ("x-lift-version", re.compile(r".*"), Piattaforma.LIFERAY),
    ("liferay-portal", re.compile(r".*"), Piattaforma.LIFERAY),
)

#: Host esterni che tradiscono il prodotto. Un portale puo' non nominarsi in
#: nessun tag e poi caricare i propri asset dal dominio del fornitore: quella
#: e' una firma involontaria, quindi affidabile.
_HOST_PRODOTTO: tuple[tuple[re.Pattern[str], Piattaforma], ...] = (
    (re.compile(r"municipiumapp\.it|\bmunicipium\b", re.I), Piattaforma.MUNICIPIUM),
)

#: Percorsi degli asset: la firma che resta quando il CMS non si dichiara.
#:
#: Misurato su portali veri: Albano Laziale non espone né `meta generator` né
#: il link all'API REST — le installazioni WordPress irrobustite li tolgono —
#: ma serve i fogli di stile da `/wp-content/`. Senza questo livello, un
#: comune che TreasureIQ *già legge* risultava `IGNOTA`, e la voce "quanta
#: strada resta" si gonfiava di portali che erano invece i più facili.
#:
#: Sono indizi più deboli di una dichiarazione esplicita, e per questo si
#: guardano dopo: un percorso può sopravvivere a una migrazione fra CMS. La
#: prova lo dice a chiare lettere, così chi rilegge sa cosa ha in mano.
_ASSET: tuple[tuple[re.Pattern[str], Piattaforma], ...] = (
    (re.compile(r"/wp-(?:content|includes)/", re.I), Piattaforma.WORDPRESS_GENERICO),
    (re.compile(r"drupal-settings-json|/sites/default/files/", re.I), Piattaforma.DRUPAL),
    (re.compile(r"/typo3(?:temp|conf)/", re.I), Piattaforma.TYPO3),
    (re.compile(r"\+\+plone\+\+|/\+\+resource\+\+", re.I), Piattaforma.PLONE),
    (re.compile(r"Liferay\.(?:ThemeDisplay|Portlet)|/o/frontend-", re.I), Piattaforma.LIFERAY),
    (re.compile(r"/media/jui/|/media/system/js/", re.I), Piattaforma.JOOMLA),
    (
        re.compile(r"/EG0/EGS\w+\.HBL\?[^\"']*\ben=eg\d{1,4}\b", re.I),
        Piattaforma.EGOV,
    ),
)

#: Quanto guardiamo per gli asset. Più larga di `FINESTRA_HEAD` perché i
#: riferimenti agli asset stanno sparsi nel corpo, non nel `<head>`; resta un
#: taglio perché su pagine da 240 KB scandire tutto non aggiunge segnale.
FINESTRA_ASSET = 40_000

#: PeopleWeb serve il tema Bootstrap Italia da percorsi con i backslash di
#: Windows, misti alle barre normali: `assets\\bootstrap-italia\\dist\\css/…`.
#: È una firma involontaria e per questo affidabile — nessuno la scrive per
#: farsi riconoscere, e sopravvive al fatto che il fornitore non si nomini mai.
_PEOPLEWEB = re.compile(r"bootstrap-italia-comuni[^\"']*\.css|assets\\bootstrap-italia", re.I)

_META_GENERATOR = re.compile(
    r"<meta[^>]+name=[\"']generator[\"'][^>]+content=[\"'](?P<v>[^\"']{1,120})",
    re.I,
)
#: WordPress si dichiara anche senza meta generator, con il link all'API REST.
_LINK_WP_API = re.compile(r"<link[^>]+https://api\.w\.org/", re.I)
_JSON_API_DRUPAL = re.compile(r"<link[^>]+/jsonapi[\"'/]", re.I)


#: Estensioni di pagina che tradiscono la tecnologia sotto anche quando il
#: portale non dice una parola: Camogli serve `EGSCHTST.HBL`, e quella `.HBL`
#: vale quanto un nome di fornitore per raggruppare chi gli somiglia.
_ESTENSIONE_ROTTA = re.compile(r"\.(aspx|php|jsp|hbl|cfm|asp|do)\b", re.I)

#: Directory di primo livello degli asset. Due portali dello stesso fornitore
#: le hanno identiche anche quando ogni altra traccia è stata tolta.
_DIR_ASSET = re.compile(r"""(?:src|href)=["']/?([A-Za-z0-9_.\\-]{2,24})[/\\]""")


def impronta_grezza(*, headers: dict[str, str], html: str) -> str | None:
    """I segnali che restano quando la piattaforma non si presenta.

    Metà dei comuni misurati non dichiara niente: né generator, né header di
    prodotto. Non sono però tutti diversi fra loro — sono pochi fornitori che
    non si firmano. Questa stringa è la chiave con cui si raggruppano più
    tardi, interrogando lo storico invece di rifare un giro sull'Italia.

    Deliberatamente grossolana e stabile: nomi di cookie, tecnologia del
    server, estensioni delle rotte, prime directory degli asset. Niente che
    cambi a ogni visita, perché due misure dello stesso portale a mesi di
    distanza devono produrre la stessa chiave o il raggruppamento si sbriciola.
    """
    minuscoli = {k.lower(): v for k, v in headers.items()}
    pezzi: list[str] = []

    server = minuscoli.get("server")
    if server:
        pezzi.append(f"server={server.split('(')[0].strip()[:40]}")

    biscotti = minuscoli.get("set-cookie", "")
    nomi = sorted({n.split("=")[0].strip()[:24] for n in biscotti.split(",") if "=" in n})
    if nomi:
        pezzi.append("cookie=" + "|".join(nomi[:3]))

    estensioni = sorted({m.group(1).lower() for m in _ESTENSIONE_ROTTA.finditer(html[:FINESTRA_ASSET])})
    if estensioni:
        pezzi.append("rotte=" + "|".join(estensioni[:3]))

    cartelle = sorted({m.group(1).lower() for m in _DIR_ASSET.finditer(html[:FINESTRA_ASSET])})
    scartabili = {"http:", "https:", "www.", "#", "javascript:"}
    utili = [c for c in cartelle if c not in scartabili][:4]
    if utili:
        pezzi.append("asset=" + "|".join(utili))

    return "; ".join(pezzi) or None


def _tronca(testo: str, massimo: int = 120) -> str:
    """La prova serve a capire, non ad archiviare la pagina."""
    pulito = " ".join(testo.split())
    return pulito if len(pulito) <= massimo else pulito[: massimo - 1] + "…"


def firma_da_risposta(*, headers: dict[str, str], html: str) -> Firma:
    """Riconosce la piattaforma da una sola risposta HTTP già in mano.

    Gli header vengono prima dell'HTML perché costano zero parsing e mentono
    di meno: un `x-drupal-cache` lo mette il server, un meta generator lo può
    aver lasciato un tema copiato da un altro comune.
    """
    minuscoli = {k.lower(): v for k, v in headers.items()}
    for nome, atteso, piattaforma in _HEADER_SPIA:
        valore = minuscoli.get(nome)
        if valore is not None and atteso.search(valore):
            return Firma(piattaforma, _tronca(f"{nome}: {valore}"))

    testa = html[:FINESTRA_HEAD]
    trovato = _META_GENERATOR.search(testa)
    dichiarato_ignoto: str | None = None
    if trovato:
        dichiarato = trovato.group("v")
        for atteso, piattaforma in _GENERATOR:
            if atteso.search(dichiarato):
                return Firma(piattaforma, _tronca(f"generator: {dichiarato}"))
        # Un generator che non riconosciamo è la cosa più preziosa che ci
        # possa capitare: è un fornitore che si presenta con nome e cognome e
        # che noi non conosciamo ancora. Buttarlo via — come faceva la prima
        # versione — trasformava ComWeb di ePublic, che si dichiara in chiaro
        # sulla home, in un anonimo `IGNOTA` indistinguibile da un portale
        # muto. Conservato qui, i fornitori nuovi si raggruppano da soli
        # interrogando lo storico, senza rifare un giro sull'Italia.
        dichiarato_ignoto = dichiarato

    if _LINK_WP_API.search(testa):
        return Firma(Piattaforma.WORDPRESS_GENERICO, "link rel=https://api.w.org/")
    if _JSON_API_DRUPAL.search(testa):
        return Firma(Piattaforma.DRUPAL, "link rel=jsonapi")

    corpo = html[:FINESTRA_ASSET]
    for atteso, piattaforma in _HOST_PRODOTTO:
        trovato_host = atteso.search(corpo)
        if trovato_host:
            return Firma(piattaforma, f"asset host: {_tronca(trovato_host.group(0), 40)}")

    trovato_peopleweb = _PEOPLEWEB.search(corpo)
    if trovato_peopleweb:
        return Firma(Piattaforma.PEOPLEWEB, f"asset: {_tronca(trovato_peopleweb.group(0), 60)}")

    for atteso, piattaforma in _ASSET:
        trovato_asset = atteso.search(corpo)
        if trovato_asset:
            return Firma(piattaforma, f"asset: {_tronca(trovato_asset.group(0), 60)}")

    if dichiarato_ignoto:
        return Firma(Piattaforma.IGNOTA, _tronca(f"generator ignoto: {dichiarato_ignoto}"))
    return Firma(Piattaforma.IGNOTA, None)


def raffina_wordpress(*, firma: Firma, tipi_noti: list[str], rest_base: str | None) -> Firma:
    """Distingue un WordPress civico da un WordPress qualunque.

    La differenza è tutta qui: il tema Design Comuni Italia pubblica un post
    type `servizio`, ed è quello che TreasureIQ sa già leggere. Senza,
    l'API REST c'è ma parla di articoli e pagine — leggibile, ma da mappare.

    Chi non è WordPress passa di qui senza essere toccato: la raffinazione non
    deve poter promuovere un Drupal per distrazione.
    """
    if firma.piattaforma is not Piattaforma.WORDPRESS_GENERICO:
        return firma
    civici = [t for t in tipi_noti if t in {"servizio", "servizi", "unita-organizzativa"}]
    if not civici:
        return firma
    prova = f"post type: {', '.join(sorted(civici))}"
    if rest_base:
        prova = f"{prova} (rest_base: {rest_base})"
    return Firma(Piattaforma.WP_DESIGN_COMUNI, _tronca(prova))


#: Regole di secondo passaggio: riconoscono una famiglia dai segnali grezzi
#: quando nessuna dichiarazione era presente.
#:
#: Sono volutamente ancorate a un token discriminante e non alla stringa
#: intera dell'impronta, perché la stringa contiene anche dettagli che
#: cambiano fra deployment (versione di nginx, un cookie in più) e ancorarcisi
#: spaccherebbe una famiglia sola in otto gruppi.
#:
#: Fuori da qui resta di proposito `node_modules`: si trova su 85 comuni in
#: Veneto e 70 in Emilia-Romagna e in nessun'altra regione d'Italia. Due
#: piattaforme regionali diverse che condividono una directory di build, non
#: un fornitore: dargli un nome solo inventerebbe un'azienda che non esiste.
_DA_IMPRONTA: tuple[tuple[str, Piattaforma], ...] = (
    ("server=hgate", Piattaforma.HGATE),
    ("argomenti|content|extension", Piattaforma.OPENPA),
    # Dopo OpenPA di proposito: entrambe hanno `argomenti` fra le directory, e
    # a distinguerle e' cio' che segue. Invertirle darebbe a OpenPA comuni che
    # non sono suoi.
    ("argomenti|bootstrap-italia", Piattaforma.AGENDA_SMART),
    (".imaging", Piattaforma.MAGNOLIA),
    ("dam|home", Piattaforma.MAGNOLIA),
    ("comunibootstrapitalia", Piattaforma.COMUNIBOOTSTRAPITALIA),
    ("|portals", Piattaforma.DOTNETNUKE),
)

#: Piattaforme regionali: stessa impronta *e* stessa regione. La regione fa
#: parte della regola perché l'impronta da sola è generica — `nginx` con una
#: directory `assets` non identifica niente. È la coincidenza fra le due che
#: la rende una firma.
_REGIONALI: tuple[tuple[str, str, Piattaforma], ...] = (
    ("server=nginx; rotte=php; asset=assets", "Friuli-Venezia Giulia", Piattaforma.REGIONE_FVG),
)

#: Famiglie che si riconoscono da più segnali insieme. Una condizione sola
#: qui sarebbe troppo larga — `Microsoft-IIS` da solo non identifica niente —
#: ed è la coincidenza dei tre a fare la firma.
_COMBINATE: tuple[tuple[tuple[str, ...], Piattaforma], ...] = (
    (("microsoft-iis", "aspx", "bootstrap-italia"), Piattaforma.PAGEOBJECT),
)

#: `node_modules` è una directory di build, non un fornitore: da sola non
#: dice niente. Ma si trova in due sole regioni d'Italia e in nessun'altra,
#: con vocabolari di rotte diversi fra loro — l'Emilia usa `/servizi` con
#: paginazione, il Veneto `/home` — quindi sono due piattaforme regionali
#: distinte, e la regione è ciò che le separa.
_REGIONALI_SU_TOKEN: tuple[tuple[str, str, Piattaforma], ...] = (
    ("node_modules", "Veneto", Piattaforma.REGIONE_VENETO),
    ("node_modules", "Emilia-Romagna", Piattaforma.RETE_CIVICA_LEPIDA),
)


def da_impronta(*, impronta: str | None, regione: str | None = None) -> Firma | None:
    """Riconosce una famiglia dai soli segnali grezzi, o niente.

    Secondo passaggio, non sostituto del primo: si applica solo a chi era
    rimasto `IGNOTA`. Un portale che si è dichiarato ha già detto cosa è, e
    una regola statistica non deve poter smentire una dichiarazione.

    Torna `None` invece di indovinare. Metà dei comuni italiani non si
    presenta, e la tentazione di allargare le regole finché il numero degli
    sconosciuti scende è esattamente il modo di ottenere una fotografia
    pulita e falsa.
    """
    if not impronta:
        return None
    minuscola = impronta.lower()
    for chiave, regione_attesa, piattaforma in _REGIONALI:
        if minuscola == chiave.lower() and regione == regione_attesa:
            return Firma(piattaforma, _tronca(f"impronta regionale: {impronta}"))
    for token, regione_attesa, piattaforma in _REGIONALI_SU_TOKEN:
        if token in minuscola and regione == regione_attesa:
            return Firma(piattaforma, _tronca(f"impronta regionale: {token} in {regione}"))
    for chiave, piattaforma in _DA_IMPRONTA:
        if chiave in minuscola:
            return Firma(piattaforma, _tronca(f"impronta: {chiave}"))
    for tutte, piattaforma in _COMBINATE:
        if all(x in minuscola for x in tutte):
            return Firma(piattaforma, _tronca("impronta: " + " + ".join(tutte)))
    return None
