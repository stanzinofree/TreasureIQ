"""Censimento dell'apertura: quanti comuni sanno dirti quando sono aperti.

Questo modulo non ingerisce niente. Misura, comune per comune, due cose
distinte — e tenerle distinte è il punto:

**Asse A, indirizzabilità.** Il portale espone l'elenco dei propri uffici in
una forma leggibile da un programma? È una domanda a cui si risponde con una
chiamata sola, quindi si può porre a tutta l'Italia.

**Asse B, recuperabilità.** L'orario dello sportello URP è recuperabile, e da
dove? Costa un fetch in più e una lettura, quindi si pone a un campione.

La distanza fra i due assi è la misura vera. Il sondaggio del 4 agosto 2026 su
Albano Laziale e Fonte Nuova — i due comuni del seed che espongono un'API —
l'ha mostrata in modo netto: il post type AGID `unita_organizzativa` c'è su
entrambi e restituisce l'ufficio (41 uffici su Albano, URP compreso), ma il
record del singolo ufficio porta solo `title`, `slug`, `link` e la tassonomia.
Nessun `content`, nessun `meta`, nessun `acf`. **L'orario nell'API non c'è.**
Sta nell'HTML della pagina, in prosa, come nel 2009.

È lo stesso silenzio che `integration.py` documenta per IPA, che registra il
canale istituzionale e non l'orario del banco. Due registri pubblici diversi,
lo stesso dato mancante: non è la svista di un comune, è come è fatto il
modello. Un censimento che desse un numero solo nasconderebbe proprio questo.

Tre scelte deliberate.

*Deterministico.* Nessun modello gira qui. Gli orari si riconoscono con un
lessico chiuso (giorni della settimana più un'ora vicina) e quello che viene
trovato è riportato **alla lettera** come prova. Un censimento è una misura, e
una misura che cambia a ogni esecuzione non è una misura — al contrario
dell'ingestione, che non è riproducibile e non pretende di esserlo.

*Parsimonioso* (D-22). Al massimo tre richieste per comune, un timeout corto,
niente concorrenza sullo stesso host. Dall'altra parte ci sono server piccoli,
non un CDN: misurare quanto sono aperti non è una buona ragione per METTERLI
sotto pressione.

*Onesto sull'assenza* (D-16). "Non trovato" e "non tentato" sono due esiti
diversi e restano due valori diversi. Un comune irraggiungibile il giorno del
censimento non è un comune chiuso: è un comune non misurato, e va contato fra
i non misurati.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, Field

from treasureiq.ingest.base import USER_AGENT
from treasureiq.ingest.host_guard import fetch_guardato, host_senza_www
from treasureiq.ingest.modello_agid import (
    PREFISSO_MYPORTAL,
    stato_vincoli,
    SezioneAgid,
    declinazione_per,
    leggi_scheda,
    leggi_scheda_campi,
    leggi_scheda_cmb2,
)
from treasureiq.ingest.myportal import (
    alias_pnrr,
    campi_scheda,
    codice_ipa,
    normalizza_ipa,
    leggi_pagina as leggi_pagina_myportal,
    tipi_candidati,
    url_elenco,
    url_tipi,
    usa_modello_pnrr,
)
from treasureiq.ingest.piattaforma import (
    ClassificaFirme,
    FirmaScattata,
    Piattaforma,
    classifica_risposta,
    da_impronta,
    firma_da_risposta,
    impronta_grezza,
)
from treasureiq.ingest.wp_comuni import strip_html

logger = logging.getLogger(__name__)


#: I `rest_base` sotto cui il modello AGID pubblica gli uffici. Vocabolario
#: chiuso e ordinato: il primo è quello misurato sul campo (Albano, Fonte
#: Nuova), gli altri sono varianti di trattino/plurale che gli stessi temi
#: usano. Provarne una manciata in ordine costa una richiesta in più solo ai
#: comuni che non espongono niente — che sono esattamente quelli su cui il
#: censimento deve essere generoso prima di dire "no".
REST_BASE_UFFICI: tuple[str, ...] = (
    "unita_organizzative",
    "unita-organizzative",
    "unita_organizzativa",
    "uffici",
)

#: Come si chiama l'URP quando ha un nome invece di una sigla. Serve a
#: scegliere UN ufficio fra i quaranta di un comune, non a decidere se il
#: comune è aperto: se nessun titolo somiglia a un URP il censimento lo dice,
#: non ripiega su un ufficio a caso.
URP_RE = re.compile(
    r"\b(u\.?r\.?p\.?|relazioni\s+con\s+il\s+pubblico|sportello\s+al\s+cittadino"
    r"|informa\s*citt|anagrafe)\b",
    re.IGNORECASE,
)

_GIORNI = (
    r"luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica"
)
#: Un'ora, e non un pezzo di qualcos'altro. I lookaround distinguono "12.30"
#: da "60.04" dentro "+39.0143.60.04.05": senza, un numero di telefono a poche
#: decine di caratteri da un giorno della settimana diventa un orario di
#: apertura e finisce nella citazione che il cittadino legge come prova.
#:
#: Il lookahead rifiuta la cifra e il punto-seguito-da-cifra, non il punto in
#: sé: vietare ogni punto successivo — come faceva la prima versione — buttava
#: via ogni orario a fine frase, cioè «Venerdì: 08.30 - 12.30.», che è il modo
#: normale di scriverli.
_ORA = r"(?<![\d.])\d{1,2}[:.]\d{2}(?!\d)(?!\.\d)"

#: Un giorno della settimana e, entro poche decine di caratteri, un'ora. Né
#: l'uno né l'altra da soli: "lunedì" compare in mezzo mondo e "9:00" pure.
#: È la coincidenza dei due a fare un orario di sportello.
#:
#: Le ore successive fanno parte della stessa cattura, e non è un dettaglio.
#: La prima versione si fermava alla prima ora e produceva la prova
#: «Venerdì: 08.30» da una pagina che diceva «08.30 - 12.30»: verbatim, e
#: leggibile come "chiude alle 8:30". Una citazione troncata è peggio di
#: nessuna citazione, perché ha l'aspetto della precisione.
ORARIO_RE = re.compile(
    # I separatori includono "e" e la virgola perché un ufficio con due turni
    # li scrive così — «mercoledì 9.00-13.00 e 14.00-16.00» — e fermarsi al
    # primo turno pubblicherebbe metà orario. Il punto NON è un separatore:
    # è ciò che impedisce a «9.00-13.00. Costo 12.50 euro» di diventare un
    # orario che chiude alle 12.50.
    # «ore» è opzionale fra il separatore e l'ora perché mezza Italia scrive
    # «dalle ore 9:00 alle ore 12:00», e senza questo la citazione si fermava
    # all'apertura — di nuovo un orario che sembra dire "chiude alle 9".
    rf"(?:{_GIORNI})\b.{{0,120}}?\b{_ORA}"
    rf"(?:\s*(?:[-–—/]|alle|ed?|,)\s*(?:ore\s*)?{_ORA})*",
    re.IGNORECASE | re.DOTALL,
)

#: Confine di citazione. Discrimina lo spazio, non la cifra: il punto di
#: "08.30" è seguito da un numero e quindi non chiude niente, mentre quello
#: di "12.30. Telefono" chiude. Guardare la cifra *precedente* — come faceva
#: la prima versione — rendeva inchiudibile ogni frase che finisce con un
#: orario, cioè esattamente tutte quelle che ci interessano, e la citazione
#: si portava dietro il centralino.
#:
#: `|` e a capo contano quanto la punteggiatura perché le schede AGID non
#: sono prosa: sono campi in fila, e una pagina d'ufficio può non contenere
#: un solo punto fermo. Senza questi confini l'espansione partiva dall'inizio
#: della pagina.
_FINE_FRASE = re.compile(r"[.;!?](?=\s|$)|[|\n•]")

#: Quanti uffici leggere da un portale. Un comune ne pubblica decine; per
#: trovare l'URP ne bastano molti meno, e il tetto tiene la richiesta piccola.
MAX_UFFICI = 100

#: Caratteri di pagina letti prima di cercare un orario. Oltre questa soglia
#: si è già dentro il piè di pagina.
MAX_CARATTERI_PAGINA = 60_000

#: Prova estratta alla lettera, tagliata a una lunghezza citabile.
MAX_CITAZIONE = 240

#: Quanto contorno tenere a sinistra dell'orario quando la citazione va
#: accorciata. Serve a non lasciare un orario senza il soggetto — "08.30 -
#: 12.30" da solo non dice di quale ufficio parla.
_CONTORNO = 60

#: L'etichetta con cui una pagina annuncia i propri orari. Quando ce n'è una
#: poco prima dell'orario, la citazione parte da lì: senza, il contorno
#: pescava quello che capitava a stare a sinistra — «Via Fabbri,10 26030
#: Tornata (CR) Orari di apertura martedì…», dove metà della prova è
#: l'indirizzo. La prova è ciò che il cittadino legge per controllarci.
_ETICHETTA_ORARI = re.compile(
    r"\b(orari(?:o)?(?:\s+(?:di\s+)?(?:apertura|al\s+pubblico|per\s+il\s+pubblico|sportello))?"
    r"|apertura\s+al\s+pubblico|ricevimento(?:\s+del\s+pubblico)?)\b",
    re.IGNORECASE,
)

#: Quanto indietro cercare quell'etichetta. Oltre, non sta più annunciando
#: questo orario: sta annunciando qualcos'altro.
_RAGGIO_ETICHETTA = 140

#: Distanza massima fra due righe dello stesso orario settimanale. Oltre
#: questa, la pagina sta parlando di un altro ufficio o di un'altra cosa, e
#: unirle in una citazione sola le farebbe sembrare la stessa tabella.
#:
#: Ottanta e non quaranta perché le righe portano spesso la causale accanto
#: all'orario — «Lunedì 09:00-10:00 – Carta Identità Elettronica (su
#: appuntamento) | Lunedì 10:00-13:00 – Altre pratiche» — e a quaranta la
#: citazione si fermava alla prima riga, dicendo che l'ufficio chiude alle
#: dieci quando chiude alle tredici.
_SALTO_MASSIMO = 80

#: Quanto lontano guardare, dopo la fine della citazione, per capire se la
#: pagina continua a elencare orari. Serve solo a dichiarare il taglio, mai
#: ad allungare la citazione.
_ORIZZONTE_CONTINUAZIONE = 400


class Indirizzabilita(str, Enum):
    """Asse A — il portale sa dirti quali uffici ha?"""

    API_UFFICI = "api_uffici"
    """L'elenco degli uffici arriva da un'API, in una forma indirizzabile."""

    SOLO_HTML = "solo_html"
    """Il sito risponde, ma nessuna API degli uffici: c'è solo da leggere."""

    IRRAGGIUNGIBILE = "irraggiungibile"
    """Non ha risposto. Non misurato — non è la stessa cosa di chiuso."""


class RecuperabilitaOrari(str, Enum):
    """Asse B — e sa dirti quando quegli uffici sono aperti?"""

    CAMPO_TIPIZZATO = "campo_tipizzato"
    """L'orario è in un campo dell'API. Il caso migliore, e il più raro."""

    PROSA = "prosa"
    """L'orario c'è, ma dentro il testo della pagina: va estratto."""

    ASSENTE = "assente"
    """Cercato sulla pagina dell'ufficio giusto, non trovato."""

    URP_NON_TROVATO = "urp_non_trovato"
    """L'elenco uffici c'è, ma nessuno somiglia a un URP. Non è un'assenza
    di orari: è un'assenza dell'ufficio a cui chiederli, e nel conteggio
    del T0 sta da un'altra parte."""

    NON_TENTATO = "non_tentato"
    """Non si è arrivati a cercarlo. Va contato a parte, mai come assenza."""


class EsitoCensimento(BaseModel):
    """La misura di un comune, con dentro la prova e la data.

    Ogni campo che non è stato misurato resta `None`: un censimento che
    riempie i buchi con zeri misura la propria fantasia.
    """

    codice_istat: str
    nome: str
    sito: str | None
    indirizzabilita: Indirizzabilita
    recuperabilita: RecuperabilitaOrari
    #: Il `rest_base` che ha risposto, così la misura si può rifare identica.
    rest_base: str | None = None
    uffici_trovati: int | None = None
    ufficio_scelto: str | None = None
    ufficio_url: str | None = None
    #: L'orario come sta scritto sulla fonte, verbatim. Senza questo la
    #: misura è un'opinione con un enum davanti.
    citazione_orari: str | None = None
    #: Asse C: che software gira sotto. `NON_MISURATA` quando non si è
    #: guardato — diverso da `IGNOTA`, che vuol dire "guardato e non
    #: riconosciuto". I due non vanno mai sommati.
    piattaforma: Piattaforma = Piattaforma.NON_MISURATA
    #: La stringa verbatim che ha deciso l'asse C.
    piattaforma_prova: str | None = None
    #: L'header `Server`, quando c'è.
    server: str | None = None
    #: I segnali grossolani con cui si raggruppano i portali che non si
    #: dichiarano: metà dei comuni misurati. Vedi `piattaforma.impronta_grezza`.
    impronta_grezza: str | None = None
    #: Dove si è finiti davvero dopo i redirect, e come. Un comune che
    #: dichiara `http://` e atterra su `https://` è già una misura di
    #: modernizzazione, e va letta senza doverla rifare.
    url_finale: str | None = None
    https_ok: bool | None = None
    stato_http: int | None = None
    #: Quanti servizi pubblica il catalogo. Sommato su tutti i comuni con
    #: un'API dà il volume esatto di un seed ricorrente, non una stima.
    n_servizi: int | None = None
    #: Quanto del modello AgID espone il portale, misurato su una scheda vera.
    aderenza: float | None = None
    sezioni_esposte: str | None = None
    #: Le sezioni che lo schema del fornitore prevede, riempite o no. Solo
    #: dove i campi sono tipizzati; altrove resta `None`, mai dedotta.
    sezioni_dichiarate: str | None = None
    #: Contro quale denominatore è calcolata l'aderenza.
    base_misura: str | None = None
    #: Il codice IPA letto dalla home. Serve a indirizzare l'API di MyPortal
    #: senza una richiesta di scoperta.
    codice_ipa: str | None = None
    #: Se il campo dei requisiti di accesso esiste, e se e' compilato.
    #: `assente` e' una scelta del fornitore, `vuoto` una del comune.
    vincoli: str | None = None
    #: Chi ha deciso la piattaforma: la sonda, o una regola applicata dopo.
    classificato_da: str | None = None
    #: Perché una misura manca, quando manca. Tiene i nostri limiti fuori dai
    #: numeri dei fornitori.
    nota_misura: str | None = None
    #: Sostituisce il numero di versione che nessun fornitore pubblica.
    impronta_declinazione: str | None = None
    #: La scheda su cui l'aderenza è stata misurata, per poterla riaprire.
    scheda_campione: str | None = None
    #: Data del contenuto più recente: separa un portale vivo da una vetrina
    #: che ha l'API e non aggiorna dal 2019.
    ultimo_contenuto: date | None = None
    richieste: int = 0
    secondi: float | None = None
    errore: str | None = None
    misurato_il: date = Field(default_factory=lambda: datetime.now(timezone.utc).date())
    #: Ciclo 16 — amministrazione-trasparente, non il portale principale.
    #: Popolati SOLO dal valore reale che `scopri_pagina_at` ritorna dai byte
    #: scaricati: `non_trovata`/`ignota` sono copertura onesta e restano tali,
    #: mai indovinati per convenienza.
    piattaforma_at: str | None = None
    piattaforma_at_prova: str | None = None
    at_url: str | None = None
    #: Diagnostica dei runner-up della batteria di firme AT, come lista di
    #: dict pronta per `json.dumps` (stessa forma di `RigaPortale`).
    firme_scattate: list[dict] | None = None


def _cita(testo: str, trovato: re.Match[str]) -> str:
    """La frase che contiene l'orario, non il pezzo che il regex ha agganciato.

    Il regex trova il punto; la prova è la frase intorno. Espandere fino ai
    confini di frase è ciò che rende la citazione ricontrollabile da una
    persona che apre la pagina: deve poterci leggere la stessa cosa, non un
    frammento che va interpretato. Se la frase è più lunga del tetto, si
    taglia all'ultimo spazio e si segna il taglio — una citazione accorciata
    lo deve dichiarare, altrimenti finge di essere completa.
    """
    precedenti = list(_FINE_FRASE.finditer(testo, 0, trovato.start()))
    naturale_inizio = precedenti[-1].end() if precedenti else 0

    # Un orario settimanale sono più occorrenze di fila ("lunedì … martedì a
    # venerdì … sabato …"): la citazione le tiene tutte, perché fermarsi alla
    # prima direbbe al cittadino che l'ufficio apre solo il lunedì. Si smette
    # quando la prossima è lontana, cioè quando la pagina ha smesso di parlare
    # di orari e ha cominciato a parlare d'altro.
    naturale_fine = fine = trovato.end()
    while (seguente := ORARIO_RE.search(testo, fine)) is not None:
        if seguente.start() - fine > _SALTO_MASSIMO:
            break
        naturale_fine = fine = seguente.end()

    inizio = naturale_inizio

    # Se poco prima dell'orario la pagina lo annuncia ("Orari di apertura"),
    # la citazione parte da lì: è l'inizio che sceglierebbe una persona.
    etichette = list(
        _ETICHETTA_ORARI.finditer(
            testo, max(naturale_inizio, trovato.start() - _RAGGIO_ETICHETTA), trovato.start()
        )
    )
    if etichette:
        inizio = etichette[-1].start()

    if fine - inizio > MAX_CITAZIONE:
        # L'orario è la prova: si accorcia il contorno, mai lui. Tagliare da
        # sinistra a lunghezza fissa — come faceva la versione precedente — su
        # una scheda AGID senza punti fermi mangiava proprio l'orario e
        # lasciava in citazione l'indirizzo e il centralino.
        inizio = max(inizio, trovato.start() - _CONTORNO)
        fine = max(trovato.end(), min(fine, inizio + MAX_CITAZIONE))
        # Al confine di parola: tagliare a lunghezza fissa spezzava un orario
        # a metà — «Martedì - 13:00-14 […]» — che ha l'aria di un dato rotto
        # invece che di una citazione accorciata.
        spazio = testo.rfind(" ", trovato.end(), fine)
        if spazio > 0:
            fine = spazio

    # La pagina continua a elencare orari oltre dove ci siamo fermati? Allora
    # la citazione è parziale e lo deve dire. È il caso di Villanova di
    # Camposampiero, dove l'anagrafe apre lunedì 9-10 per le CIE e 10-13 per
    # tutto il resto: citare la sola prima riga è verbatim e insieme falso,
    # perché chi legge capisce che alle dieci chiude. Non si allunga la
    # citazione per coprire l'intera tabella — si ammette che c'è dell'altro e
    # si lascia il link alla fonte, che è l'unica cosa completa per davvero.
    continua = ORARIO_RE.search(testo, fine, fine + _ORIZZONTE_CONTINUAZIONE) is not None

    prefisso = "[…] " if inizio > naturale_inizio else ""
    suffisso = " […]" if continua or fine < naturale_fine else ""
    return f"{prefisso}{testo[inizio:fine].strip()}{suffisso}"


def _normalizza_sito(sito: str | None) -> str | None:
    """L'URL come lo scrive IPA (`www.comune.x.it`) non è un URL."""
    if not sito or not sito.strip():
        return None
    grezzo = sito.strip()
    if "//" not in grezzo:
        grezzo = f"https://{grezzo}"
    parti = urlsplit(grezzo)
    if not parti.hostname:
        return None
    return f"{parti.scheme}://{parti.netloc}".rstrip("/")


class _Sonda:
    """Le richieste HTTP di un censimento, contate.

    Contarle non è contabilità interna: `EsitoCensimento.richieste` finisce
    nel risultato, così chiunque rifaccia la misura sa quanto è costata al
    portale dall'altra parte.
    """

    def __init__(self, *, timeout: float = 12.0) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        self.richieste = 0
        #: Il portale ha risposto qualcosa, fosse anche un 404? `None` finché
        #: non si è provato. Contare le richieste *inviate* — come faceva la
        #: prima versione — dichiarava raggiungibile anche un host che non
        #: risolve, e faceva sparire gli irraggiungibili dal censimento
        #: mettendoli fra i misurati. Un 404 è una risposta; un DNS che non
        #: risolve è un comune non misurato, e i due non vanno sommati.
        self.raggiungibile: bool | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> _Sonda:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, url: str, **params: object) -> httpx.Response:
        self.richieste += 1
        try:
            # `params={}` non è "nessun parametro": httpx lo interpreta come
            # "la query è questa", e cancella quella già presente nell'URL.
            # `Servizi?ID=130875` diventava `Servizi`, cioè l'indice — e
            # l'aderenza di PeopleWeb risultava non misurabile su 35 comuni
            # mentre le schede erano lì e si leggevano benissimo.
            resp = self._client.get(url, params=params) if params else self._client.get(url)
        except httpx.RequestError:
            if self.raggiungibile is None:
                self.raggiungibile = False
            raise
        self.raggiungibile = True
        resp.raise_for_status()
        return resp

    def risposta(self, url: str) -> httpx.Response:
        """Una risposta grezza, tenuta anche quando lo stato non è 2xx.

        Serve al riconoscimento della piattaforma: un portale che risponde 403
        o 404 alla home ha comunque header che lo dichiarano, e buttare via
        quella risposta perché lo stato non piace significherebbe classificare
        `IGNOTA` un comune che si era presentato.
        """
        self.richieste += 1
        resp = self._client.get(url)
        self.raggiungibile = True
        return resp

    def posta(self, url: str, corpo: dict) -> object:
        """Una POST che torna JSON. MyPortal cerca solo così."""
        self.richieste += 1
        resp = self._client.post(url, json=corpo)
        self.raggiungibile = True
        resp.raise_for_status()
        return resp.json()

    def json_con_header(self, url: str, **params: object) -> tuple[object, httpx.Headers]:
        """JSON più header: WordPress conta il catalogo in `X-WP-Total`."""
        resp = self._get(url, **params)
        return resp.json(), resp.headers

    def json(self, url: str, **params: object) -> object:
        return self._get(url, **params).json()

    def testo(self, url: str) -> str:
        return self._get(url).text


#: Cap streaming sul download della pagina AT: mai in RAM oltre questa
#: soglia, connessione interrotta al superamento (stesso spirito di
#: `registro.MAX_HOME_BYTES`). Il download stesso passa da
#: `host_guard.fetch_guardato` (B5, ciclo16): questo modulo fissa solo il
#: cap, non la guardia SSRF.
MAX_AT_PAGINA_BYTES = 1_000_000

#: L'etichetta che il comune mostra al cittadino vince sul semplice indizio
#: nell'URL: su Peveragno distingue il link corrente (jcitygov, "dal
#: 24/11/2025") da quello scaduto (WP nativo, "fino al 23/11/2025"), ed è la
#: ragione per cui l'ordine di priorità comincia da qui e non dall'href.
_ETICHETTA_AT = re.compile(r"amministrazione\s+trasparente", re.I)
_HREF_JCITYGOV = re.compile(r"trasparenza-valutazione-merito\.it", re.I)
_HREF_AMM_TRASP = re.compile(r"amm_trasp", re.I)
_HREF_TRASPARENZA = re.compile(r"trasparenza", re.I)

#: Un blocco `<a href="...">...</a>`, contenuto incluso: l'etichetta AT vive
#: spesso in un `alt`/`title` di un `<img>` annidato o in un `<p>` figlio,
#: non nel testo diretto dell'ancora, quindi si guarda tutto il blocco.
_ANCORA_HREF = re.compile(r'<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)


def scopri_url_at(html_home: str, base: str) -> str | None:
    """Trova l'URL della pagina Amministrazione Trasparente nella home già
    scaricata (D-16: mai un fetch aggiuntivo solo per cercare il link).

    Scansiona le ancore in ordine di documento e le raggruppa per priorità
    (etichetta esplicita, poi host jcitygov, poi `amm_trasp`, poi
    `trasparenza` generico); il primo candidato della priorità più alta
    vince. Nessuna ancora in nessuna priorità → `None`, mai un URL
    indovinato.
    """
    per_priorita: list[list[str]] = [[], [], [], []]
    for m in _ANCORA_HREF.finditer(html_home):
        href, interno = m.group(1), m.group(2)
        if _ETICHETTA_AT.search(interno):
            per_priorita[0].append(href)
        elif _HREF_JCITYGOV.search(href):
            per_priorita[1].append(href)
        elif _HREF_AMM_TRASP.search(href):
            per_priorita[2].append(href)
        elif _HREF_TRASPARENZA.search(href):
            per_priorita[3].append(href)
    for candidati in per_priorita:
        if candidati:
            return urljoin(base, candidati[0])
    return None


def _host_senza_www(host: str) -> str:
    """Alias locale del canonico `host_guard.host_senza_www` (B5, ciclo16):
    mantenuto per non toccare gli altri call-site di questo modulo."""
    return host_senza_www(host)


def _fetch_at_guardato(url: str, *, timeout: float = 8.0) -> tuple[httpx.Headers, str] | None:
    """Scarica la pagina AT via `host_guard.fetch_guardato` (B5, ciclo16):
    host atteso `None` — si fissa al primo hop dell'URL RICHIESTO, non a
    quello del comune, perché l'AT vive spesso su un dominio SaaS
    indipendente (`halleyweb.com`, `trasparenza-valutazione-merito.it`) e
    imporre lo stesso host del portale scarterebbe sempre il candidato.

    Guardia SSRF (per-hop, redirect seguiti a mano, DNS validato su ogni
    hop, size-cap in streaming) invariata — vive ora in `host_guard.py`,
    condivisa con `registro.py`. Qualunque anomalia → `None`, mai
    un'eccezione che risale al chiamante e mai un URL indovinato al suo
    posto."""
    scaricato = fetch_guardato(url, timeout=timeout, max_bytes=MAX_AT_PAGINA_BYTES)
    if scaricato is None:
        return None
    intestazioni, dati, _ = scaricato
    return intestazioni, dati.decode("utf-8", errors="replace")


class EsitoDiscoveryAT(NamedTuple):
    """Discovery + classificazione della pagina Amministrazione Trasparente,
    con i nomi di campo del contratto — B4 li userà così com'è per popolare
    `RigaPortale`, senza rimappare nulla."""

    piattaforma_at: Piattaforma
    at_url: str | None
    piattaforma_at_prova: str | None
    #: Tutte le firme scattate, non solo la vincitrice: un runner-up forte
    #: (es. IGNOTA che ha comunque acceso un euristico) è diagnostica persa
    #: se si butta via subito, come per la battuta BASE.
    firme_scattate: list[FirmaScattata]


def scopri_pagina_at(*, html_home: str, base: str) -> EsitoDiscoveryAT:
    """Scopre e classifica la pagina Amministrazione Trasparente del comune,
    a partire dalla home già scaricata dallo sweep.

    Nessun link nella home, o la guardia SSRF scarta il candidato →
    `piattaforma_at=Piattaforma.NON_TROVATA`, `at_url=None`: un dato
    onesto, mai un URL indovinato persistito (D-16). Una pagina AT trovata
    e raggiunta ma senza firma riconosciuta resta `Piattaforma.IGNOTA` —
    l'URL però è verificato, non indovinato, e viene ritornato comunque.

    SIAMO/Publisys (shell Angular, nessun href server-rendered nella home)
    ricade qui in `NON_TROVATA` per costruzione: non c'è alcuna ancora in
    nessuna priorità. Tentare l'endpoint HAL `/kapi/api/trasparenza*` è
    deferred a un ciclo successivo — qui resta best-effort onesto.
    """
    url = scopri_url_at(html_home, base)
    if url is None:
        return EsitoDiscoveryAT(Piattaforma.NON_TROVATA, None, None, [])
    scaricato = _fetch_at_guardato(url)
    if scaricato is None:
        return EsitoDiscoveryAT(Piattaforma.NON_TROVATA, None, None, [])
    intestazioni, html_at = scaricato
    esito: ClassificaFirme = classifica_risposta(
        headers=dict(intestazioni), html=html_at, includi_at=True
    )
    return EsitoDiscoveryAT(
        esito.vincitore.piattaforma, url, esito.vincitore.prova, esito.scattate
    )


def _rest_base_uffici(*, sonda: _Sonda, base: str) -> str | None:
    """Quale `rest_base` pubblica gli uffici su questo portale, se uno c'è.

    Si chiede al portale invece di indovinare: `/wp-json/wp/v2/types` è
    l'indice che WordPress pubblica dei propri tipi di contenuto, e leggerlo
    costa una richiesta sola. Solo se quell'indice non risponde si prova il
    vocabolario chiuso a tentativi.
    """
    try:
        tipi = sonda.json(f"{base}/wp-json/wp/v2/types")
    except Exception:  # noqa: BLE001 — un indice assente è un esito, non un guasto
        return None
    if not isinstance(tipi, dict):
        return None
    disponibili = {
        str(v.get("rest_base"))
        for v in tipi.values()
        if isinstance(v, dict) and v.get("rest_base")
    }
    for candidato in REST_BASE_UFFICI:
        if candidato in disponibili:
            return candidato
    return None


def _elenco_uffici(*, sonda: _Sonda, base: str, rest_base: str) -> list[dict]:
    """Gli uffici pubblicati, o lista vuota se l'endpoint non li dà."""
    try:
        dati = sonda.json(f"{base}/wp-json/wp/v2/{rest_base}", per_page=MAX_UFFICI)
    except Exception:  # noqa: BLE001
        return []
    return [item for item in dati if isinstance(item, dict)] if isinstance(dati, list) else []


def _titolo(ufficio: dict) -> str:
    titolo = ufficio.get("title")
    grezzo = titolo.get("rendered", "") if isinstance(titolo, dict) else str(titolo or "")
    return strip_html(grezzo).strip()


def _scegli_urp(uffici: list[dict]) -> dict | None:
    """L'ufficio che somiglia a un URP, o niente.

    Niente ripiego sul primo della lista: misurare l'orario dell'ufficio
    tecnico e scriverlo alla voce URP sarebbe un dato falso prodotto da noi,
    non un dato mancante del comune.
    """
    for ufficio in uffici:
        if URP_RE.search(_titolo(ufficio)):
            return ufficio
    return None


def _orari_da_campo(ufficio: dict) -> str | None:
    """Un orario dentro un campo dell'API, se per una volta c'è.

    Guarda solo dove un orario avrebbe un senso — `meta`, `acf`, `orari` —
    mai in tutto il record: il titolo di un ufficio che contiene "lunedì" non
    è un orario di apertura, e prenderlo per tale trasformerebbe il caso
    migliore della scala nel più facile da sbagliare.
    """
    for chiave in ("orari", "orario", "meta", "acf"):
        valore = ufficio.get(chiave)
        if not valore:
            continue
        testo = strip_html(json.dumps(valore, ensure_ascii=False))
        trovato = ORARIO_RE.search(testo)
        if trovato:
            return _cita(testo, trovato)
    return None


def estrai_orari_da_testo(html: str) -> str | None:
    """Un orario nell'HTML di una pagina, citato alla lettera — o `None`.

    Nucleo puro (nessuna rete, nessun `_Sonda`): dato l'HTML grezzo di una
    pagina, ne estrae la citazione dell'orario. Riusato dal lettore on-demand
    dell'ufficio nominato (`orari_ufficio.py`), che scarica i byte con la
    guardia SSRF e li passa qui — l'unica definizione di "come si legge un
    orario da una pagina" vive in questa funzione, non duplicata altrove.
    """
    testo = strip_html(html)[:MAX_CARATTERI_PAGINA]
    testo = re.sub(r"\s+", " ", testo)
    trovato = ORARIO_RE.search(testo)
    return _cita(testo, trovato) if trovato else None


def _orari_da_pagina(*, sonda: _Sonda, url: str) -> str | None:
    """Un orario nel testo della pagina dell'ufficio, citato alla lettera."""
    try:
        html = sonda.testo(url)
    except Exception:  # noqa: BLE001
        return None
    return estrai_orari_da_testo(html)


def censisci_comune(
    *,
    codice_istat: str,
    nome: str,
    sito: str | None,
    timeout: float = 12.0,
    leggi_pagina: bool = True,
    misura_piattaforma: bool = False,
    misura_aderenza: bool = False,
    regione: str | None = None,
    ipa_noto: str | None = None,
) -> EsitoCensimento:
    """Misura un comune sui due assi. Non solleva mai: un guasto è un esito.

    `leggi_pagina=False` ferma la misura all'asse A — l'unico che si può
    porre a tutta l'Italia senza chiedere a ottomila server di leggere una
    pagina per noi. In quel caso l'asse B resta `NON_TENTATO`, che è
    esattamente ciò che è successo, e non va mai letto come un'assenza.
    """
    avvio = time.perf_counter()
    base = _normalizza_sito(sito)
    if base is None:
        return EsitoCensimento(
            codice_istat=codice_istat,
            nome=nome,
            sito=sito,
            indirizzabilita=Indirizzabilita.IRRAGGIUNGIBILE,
            recuperabilita=RecuperabilitaOrari.NON_TENTATO,
            errore="nessun sito noto per questo ente",
        )

    with _Sonda(timeout=timeout) as sonda:
        esito = _misura(sonda=sonda, base=base, leggi_pagina=leggi_pagina)
        if esito["indirizzabilita"] is Indirizzabilita.IRRAGGIUNGIBILE:
            alternativa = _variante_www(base)
            if alternativa:
                secondo = _misura(sonda=sonda, base=alternativa, leggi_pagina=leggi_pagina)
                if secondo["indirizzabilita"] is not Indirizzabilita.IRRAGGIUNGIBILE:
                    base, esito = alternativa, secondo
        if misura_piattaforma:
            esito.update(_impronta(sonda=sonda, base=base, regione=regione))
            # Quello che il portale dichiara batte l'anagrafe: e' verita' sul
            # campo, e i registri si disallineano quando un ente cambia nome
            # o si fonde. Ma se non dichiara niente, l'anagrafe evita che il
            # comune resti irraggiungibile per un dato che abbiamo in casa.
            if not esito.get("codice_ipa"):
                esito["codice_ipa"] = ipa_noto
            if esito.get("piattaforma") is Piattaforma.PEOPLEWEB:
                esito.update(_catalogo_peopleweb(sonda=sonda, base=base))
            else:
                esito.update(_catalogo(sonda=sonda, base=base))
                esito.update(_promuovi_design_comuni(esito))
            if misura_aderenza:
                esito.update(
                    _aderenza(
                        sonda=sonda,
                        base=base,
                        piattaforma=esito["piattaforma"],
                        ipa=esito.get("codice_ipa"),
                    )
                )
        esito.update(
            codice_istat=codice_istat,
            nome=nome,
            sito=base,
            richieste=sonda.richieste,
            secondi=round(time.perf_counter() - avvio, 3),
        )
    return EsitoCensimento(**esito)


#: Post type che pubblicano il catalogo dei servizi, in ordine di preferenza.
#: Il tema Design Comuni Italia usa `servizi`; alcune installazioni hanno
#: rinominato il `rest_base` al singolare.
_REST_BASE_SERVIZI = ("servizi", "servizio")


#: Dove ogni fornitore tiene l'indice dei servizi, e come si riconosce il link
#: a una scheda singola. Sono le rotte verificate sul campo, non dedotte: è la
#: sola conoscenza specifica di prodotto che serve, perché il *contenuto* poi
#: lo legge il modello AgID uguale per tutti.
_ROTTE_SERVIZI: dict[Piattaforma, tuple[str, re.Pattern[str]]] = {
    Piattaforma.PEOPLEWEB: ("/Servizi", re.compile(r'href="(/?Servizi\?ID=\d+)"')),
    Piattaforma.COMWEB: (
        "/it-it/servizi",
        re.compile(r'href="(/it-it/servizi/(?![^"]*-c")[^"]+)"'),
    ),
}


def _aderenza(
    *, sonda: _Sonda, base: str, piattaforma: Piattaforma, ipa: str | None = None
) -> dict:
    """Quanto di modello AgID espone davvero questo portale.

    Misurata su **una** scheda vera, non sulla vetrina del fornitore: i
    deployment divergono dal sito dimostrativo, e quella varianza è
    esattamente ciò che vogliamo vedere. Costa due richieste — l'indice e una
    scheda — e per questo sta dietro una sua opzione.

    Una scheda che non si trova lascia tutto a `None`. È diverso da
    un'aderenza zero: significa che non abbiamo guardato, e sommare le due
    cose farebbe sembrare inadempiente un fornitore che magari è solo
    organizzato in modo che non conosciamo.
    """
    if piattaforma is Piattaforma.WP_DESIGN_COMUNI:
        return _aderenza_wp(sonda=sonda, base=base)

    if piattaforma in _MYPORTAL:
        return _myportal(sonda=sonda, base=base, piattaforma=piattaforma, ipa=ipa)

    rotta = _ROTTE_SERVIZI.get(piattaforma)
    if rotta is None:
        return {}
    percorso, schema_link = rotta
    try:
        indice = sonda.testo(f"{base}{percorso}")
        trovati = schema_link.findall(indice)
        if not trovati:
            return {"nota_misura": "indice_senza_schede"}
        url = f"{base}/{trovati[0].lstrip('/')}"
        pagina = sonda.testo(url)
    except (httpx.HTTPError, ValueError) as exc:
        return {"nota_misura": f"scheda_non_raggiunta: {type(exc).__name__}"}

    scheda = leggi_scheda(pagina, declinazione=declinazione_per(piattaforma.value))
    if not scheda.sezioni:
        # Una pagina sotto `/servizi` che non ha nessuna sezione quasi sempre
        # non è una scheda: è una pagina informativa. Contarla come aderenza
        # zero calunnierebbe il fornitore — è già successo, e ha prodotto uno
        # 0,10 dove la media vera era 0,68.
        return {"scheda_campione": url, "nota_misura": "pagina_fuori_modello"}
    return _riassumi(scheda, url)


#: Le piattaforme costruite su MyPortal. Deployment diversi della stessa cosa:
#: l'Emilia-Romagna pubblica 31 tipi di contenuto, il Veneto 149, ma entrambe
#: rispondono agli stessi due endpoint.
_MYPORTAL = frozenset(
    {
        Piattaforma.RETE_CIVICA_LEPIDA,
        Piattaforma.REGIONE_VENETO,
    }
)

#: Quanti tipi provare prima di arrendersi. Ogni tentativo è una richiesta, e
#: oltre il terzo candidato la resa crolla.
_TENTATIVI_TIPO = 3


def _myportal(
    *, sonda: _Sonda, base: str, piattaforma: Piattaforma, ipa: str | None
) -> dict:
    """Catalogo e aderenza di un portale MyPortal.

    Il tipo di scheda servizio si **chiede al portale** invece di tenerne una
    tabella per regione: `default-types` lo dichiara, e una tabella scritta a
    mano invecchierebbe in silenzio.

    Fra i candidati si tiene quello che rende di più, e non è pignoleria: su
    Abano Terme il primo candidato in ordine di specificità (`pnrr_sc_service`)
    restituisce zero e il secondo (`pnrr_service`) novantadue. Un tipo
    sbagliato non dà errore, dà un comune che sembra non pubblicare niente —
    il modo più silenzioso di sbagliare che questo censimento conosca.
    """
    ipa = normalizza_ipa(ipa)
    if not ipa:
        return {"nota_misura": "codice_ipa_non_trovato"}
    try:
        dichiarati = sonda.json(url_tipi(base, ipa))
    except (httpx.HTTPError, ValueError) as exc:
        return {"nota_misura": f"tipi_non_raggiunti: {type(exc).__name__}"}

    candidati = tipi_candidati(dichiarati)
    if not candidati:
        return {"nota_misura": "nessun_tipo_servizio_dichiarato"}

    totale, entita = None, []
    for tipo in candidati[:_TENTATIVI_TIPO]:
        try:
            risposta = sonda.json(url_elenco(base, ipa, tipo, quanti=5))
        except (httpx.HTTPError, ValueError):
            continue
        quanti, schede = leggi_pagina_myportal(risposta)
        if quanti and (totale is None or quanti > totale):
            totale, entita = quanti, schede
    if totale is None:
        # Nessun tipo ha restituito contenuti. Può voler dire che il comune non
        # pubblica, oppure che il codice IPA è sbagliato — e i due casi si
        # somigliano troppo per sceglierne uno: registrarli come "zero servizi"
        # attribuirebbe a un comune un silenzio che potrebbe essere nostro.
        return {"nota_misura": "codice_ipa_non_verificato_o_catalogo_vuoto"}
    esito: dict = {"n_servizi": totale}
    if not entita:
        esito["nota_misura"] = "catalogo_vuoto"
        return esito
    campi = campi_scheda(entita[0])
    scheda = leggi_scheda_campi(
        campi,
        prefisso=PREFISSO_MYPORTAL,
        declinazione=piattaforma.value,
        alias=alias_pnrr() if usa_modello_pnrr(campi) else None,
    )
    if not scheda.esposte:
        esito["nota_misura"] = "nessun_campo_tipizzato"
        return esito
    url = f"{base.rstrip('/')}{entita[0].get('slug') or ''}"
    return {**esito, **_riassumi(scheda, url), "vincoli": stato_vincoli(campi)}


def _aderenza_wp(*, sonda: _Sonda, base: str) -> dict:
    """Aderenza del tema Design Comuni, letta dai campi tipizzati.

    L'unico fornitore su cui si possono separare due responsabilità: la
    sezione **esiste** perché il tema l'ha prevista, ed è **compilata** perché
    il comune l'ha riempita. Confrontarlo con gli altri usando solo il numero
    di sezioni piene lo farebbe sembrare peggiore proprio dove è più onesto —
    è l'unico che ci lascia vedere il campo vuoto invece di nasconderlo.
    """
    try:
        corpo, _ = sonda.json_con_header(
            f"{base}/wp-json/wp/v2/servizi", per_page=1, orderby="date", order="desc"
        )
    except (httpx.HTTPError, ValueError) as exc:
        return {"nota_misura": f"api_non_raggiunta: {type(exc).__name__}"}
    if not (isinstance(corpo, list) and corpo and isinstance(corpo[0], dict)):
        return {"nota_misura": "catalogo_vuoto"}

    record = corpo[0]
    campi = record.get("cmb2") or {}
    scheda = leggi_scheda_cmb2(campi)
    if scheda.esposte is None or not scheda.esposte:
        return {"nota_misura": "nessun_campo_tipizzato", "scheda_campione": record.get("link")}
    return {**_riassumi(scheda, str(record.get("link") or "")), "vincoli": stato_vincoli(campi)}


def _riassumi(scheda: object, url: str) -> dict:
    """I campi da registrare, uguali per la lettura HTML e per quella tipizzata."""
    esposte = getattr(scheda, "esposte", None)
    return {
        "aderenza": round(scheda.aderenza, 3),  # type: ignore[attr-defined]
        "sezioni_esposte": ",".join(
            s.value for s in SezioneAgid if s in scheda.sezioni  # type: ignore[attr-defined]
        ),
        "sezioni_dichiarate": (
            ",".join(s.value for s in SezioneAgid if s in esposte) if esposte else None
        ),
        "impronta_declinazione": scheda.impronta,  # type: ignore[attr-defined]
        "scheda_campione": url or None,
        "base_misura": scheda.base_misura,
        "nota_misura": (
            None
            if esposte is None
            else "aderenza sui soli box esposti dall'API, non sul modello intero"
        ),
    }


def _variante_www(base: str) -> str | None:
    """Lo stesso host con `www.` tolto, o aggiunto se non c'era.

    Non è pignoleria: Fonte Nuova, comune già ingerito da TreasureIQ, ha un
    certificato valido per `comune.fontenuova.rm.it` mentre IPA ne registra
    l'indirizzo con `www.`. Il TLS fallisce e la sonda lo dichiarava
    irraggiungibile — un portale vivo contato fra i morti. Su scala nazionale
    un errore così non fa rumore: gonfia una percentuale e nessuno se ne
    accorge, perché "irraggiungibile" è esattamente ciò che ci si aspetta
    dalla coda lunga dei piccoli comuni.
    """
    parti = urlsplit(base)
    host = parti.netloc
    girato = host[4:] if host.startswith("www.") else f"www.{host}"
    if not girato or girato == host:
        return None
    return f"{parti.scheme}://{girato}"


#: `<meta http-equiv="refresh" content="0;URL=...">`, cioè un redirect scritto
#: in HTML invece che negli header. `follow_redirects` non lo segue, perché
#: per HTTP non è un redirect: è una pagina come un'altra.
_META_REFRESH = re.compile(
    r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]+content=["'][^"']*url=([^"'>\s]+)""",
    re.I,
)

#: Sotto questa soglia una pagina non è un portale: è un cartello che indica
#: dov'è il portale.
_STUB_MASSIMO = 2_000


def _segui_meta_refresh(*, sonda: _Sonda, base: str, corpo: str) -> str | None:
    """L'indirizzo vero, quando la home è solo un cartello che punta altrove.

    Sessantacinque comuni campani risultavano senza alcuna firma: la loro home
    è un documento di 179 byte con dentro un meta refresh verso `/sito/`. La
    sonda leggeva il cartello e concludeva che il portale non dichiarava
    niente — una diagnosi sbagliata su un portale perfettamente normale.

    Non è un caso locale: vale per qualunque comune costruito così, e vale
    anche per l'asse A, perché su quel cartello non c'è nessuna API da
    trovare.
    """
    if len(corpo) > _STUB_MASSIMO:
        return None
    trovato = _META_REFRESH.search(corpo)
    if not trovato:
        return None
    destinazione = trovato.group(1).strip().strip("'\"")
    if destinazione.startswith("http"):
        return destinazione
    return f"{base.rstrip('/')}/{destinazione.lstrip('/')}"


def _impronta(*, sonda: _Sonda, base: str, regione: str | None = None) -> dict:
    """Asse C: una sola richiesta alla home, e cosa se ne ricava.

    Non solleva: un portale che non risponde è un esito `NON_MISURATA` con
    l'errore accanto, non un'eccezione che fa saltare il censimento di un
    comune e lo fa sparire dalla mappa.
    """
    try:
        resp = sonda.risposta(base)
    except httpx.RequestError as exc:
        return {"piattaforma": Piattaforma.NON_MISURATA, "errore": f"home: {exc!r}"[:200]}

    vero = _segui_meta_refresh(sonda=sonda, base=base, corpo=resp.text)
    if vero:
        try:
            resp = sonda.risposta(vero)
        except httpx.RequestError:
            pass

    intestazioni = dict(resp.headers)
    # BASE (home comune): una piattaforma AT-only non può vincere qui anche
    # se un link outbound alla pagina AT fa scattare la sua firma.
    firma = firma_da_risposta(headers=intestazioni, html=resp.text, includi_at=False)
    grezza = impronta_grezza(headers=intestazioni, html=resp.text)
    if firma.piattaforma is Piattaforma.IGNOTA:
        # Secondo passaggio: chi non si è dichiarato può ancora essere
        # riconosciuto dalla forma di ciò che serve. Non tocca chi ha già
        # detto cosa è: una regola statistica non smentisce una dichiarazione.
        seconda = da_impronta(impronta=grezza, regione=regione)
        if seconda is not None:
            firma = seconda
    # Discovery Amministrazione Trasparente (ciclo 16): best-effort, riusa la
    # home già scaricata (resp.text/base), non fa un secondo fetch della home.
    # Mai fatale: un guasto qui non deve far perdere la misura BASE del
    # comune. `scopri_pagina_at` stessa non solleva su percorso ordinario;
    # questa guardia è per l'imprevisto (bug, memoria, encoding).
    try:
        scoperta_at = scopri_pagina_at(html_home=resp.text, base=base)
    except Exception as exc:  # noqa: BLE001
        logger.info("scoperta AT fallita per %s: %r", base, exc)
        scoperta_at = None
    return {
        "piattaforma": firma.piattaforma,
        "piattaforma_prova": firma.prova,
        "server": (intestazioni.get("server") or intestazioni.get("Server") or None),
        "impronta_grezza": grezza,
        "codice_ipa": codice_ipa(resp.text),
        "url_finale": str(resp.url),
        "https_ok": str(resp.url).startswith("https://"),
        "stato_http": resp.status_code,
        # `non_trovata`/`ignota` sono copertura onesta e vanno registrati come
        # qualunque altro esito (D-16): nessun None-quando-inconveniente.
        "piattaforma_at": None if scoperta_at is None else scoperta_at.piattaforma_at.value,
        "at_url": None if scoperta_at is None else scoperta_at.at_url,
        "piattaforma_at_prova": None if scoperta_at is None else scoperta_at.piattaforma_at_prova,
        "firme_scattate": (
            None
            if scoperta_at is None
            else [
                {"piattaforma": f.piattaforma.value, "score": f.score, "prova": f.prova}
                for f in scoperta_at.firme_scattate
            ]
        ),
    }


#: I link della mappa del sito PeopleWeb che puntano a una scheda servizio.
_SERVIZI_PEOPLEWEB = re.compile(r"""href=["']/?Servizi\?""", re.I)


def _catalogo_peopleweb(*, sonda: _Sonda, base: str) -> dict:
    """Conta i servizi di un PeopleWeb dalla sua mappa del sito.

    PeopleWeb non ha un'API, ma ha `/Mappasito`: un indice completo, in una
    pagina sola, con un vocabolario di rotte stabile fra installazioni
    diverse (verificato su Roletto e Arborio, 59 e 52 servizi). Vale quanto
    `X-WP-Total` per WordPress e costa la stessa singola richiesta — con la
    differenza che qui l'indice arriva già completo, senza paginazione.

    Non tutte le installazioni la espongono: chi risponde 404 resta senza
    conteggio, che è diverso da un conteggio a zero.
    """
    try:
        pagina = sonda.testo(f"{base}/Mappasito")
    except (httpx.HTTPError, ValueError):
        return {}
    return {"n_servizi": len(_SERVIZI_PEOPLEWEB.findall(pagina)) or None}


def _catalogo(*, sonda: _Sonda, base: str) -> dict:
    """Quanti servizi pubblica il comune, e quanto è fresco l'ultimo.

    Una richiesta sola: chiedendo un elemento solo, ordinato dal più recente,
    WordPress mette il totale in `X-WP-Total` e la data nell'unico elemento.
    Scaricare il catalogo intero per contarlo costerebbe a ottomila comuni una
    banda che non ci devono.
    """
    for rest_base in _REST_BASE_SERVIZI:
        try:
            corpo, headers = sonda.json_con_header(
                f"{base}/wp-json/wp/v2/{rest_base}",
                per_page=1,
                orderby="date",
                order="desc",
            )
        except (httpx.HTTPError, ValueError):
            continue
        totale = headers.get("X-WP-Total")
        esito: dict = {"n_servizi": int(totale) if totale and totale.isdigit() else None}
        if isinstance(corpo, list) and corpo and isinstance(corpo[0], dict):
            esito["ultimo_contenuto"] = _data_iso(corpo[0].get("date"))
        return esito
    return {}


def _promuovi_design_comuni(esito: dict) -> dict:
    """Un catalogo `servizi` che risponde è la prova migliore del tema civico.

    La firma della home dice al più "WordPress"; questo dice "WordPress che
    pubblica servizi come post type", cioè esattamente ciò che TreasureIQ sa
    leggere. Costa zero richieste in più: la prova è già stata pagata da
    `_catalogo`.

    Promuove anche da `IGNOTA`, e la ragione viene dal campo: Albano Laziale
    non dichiara WordPress da nessuna parte, eppure `/wp-json/wp/v2/servizi`
    gli risponde con 32 servizi. Un catalogo che risponde su quel percorso è
    prova più forte di qualunque meta tag.

    Una piattaforma riconosciuta con certezza non viene invece toccata: la
    promozione non deve poter riscrivere un Drupal che espone per caso un
    percorso somigliante.
    """
    incerte = {
        Piattaforma.WORDPRESS_GENERICO,
        Piattaforma.IGNOTA,
        Piattaforma.NON_MISURATA,
    }
    if esito.get("piattaforma") not in incerte:
        return {}
    if esito.get("n_servizi") is None:
        return {}
    return {
        "piattaforma": Piattaforma.WP_DESIGN_COMUNI,
        "piattaforma_prova": f"catalogo servizi: {esito['n_servizi']} elementi",
    }


def _data_iso(grezza: object) -> date | None:
    """La data WordPress (`2026-07-01T09:12:00`) come data, o niente."""
    if not isinstance(grezza, str) or not grezza:
        return None
    try:
        return datetime.fromisoformat(grezza.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _misura(*, sonda: _Sonda, base: str, leggi_pagina: bool) -> dict:
    """I due assi, in ordine: senza l'elenco uffici l'orario non si cerca."""
    rest_base = _rest_base_uffici(sonda=sonda, base=base)
    if rest_base is None:
        return {
            "indirizzabilita": (
                Indirizzabilita.SOLO_HTML
                if sonda.raggiungibile
                else Indirizzabilita.IRRAGGIUNGIBILE
            ),
            "recuperabilita": RecuperabilitaOrari.NON_TENTATO,
        }

    uffici = _elenco_uffici(sonda=sonda, base=base, rest_base=rest_base)
    comune: dict = {
        "indirizzabilita": Indirizzabilita.API_UFFICI,
        "recuperabilita": RecuperabilitaOrari.NON_TENTATO,
        "rest_base": rest_base,
        "uffici_trovati": len(uffici),
    }

    urp = _scegli_urp(uffici)
    if urp is None:
        comune["recuperabilita"] = (
            RecuperabilitaOrari.URP_NON_TROVATO if uffici else RecuperabilitaOrari.NON_TENTATO
        )
        return comune
    comune["ufficio_scelto"] = _titolo(urp)
    comune["ufficio_url"] = urp.get("link")

    da_campo = _orari_da_campo(urp)
    if da_campo:
        comune["recuperabilita"] = RecuperabilitaOrari.CAMPO_TIPIZZATO
        comune["citazione_orari"] = da_campo
        return comune

    if not leggi_pagina or not comune["ufficio_url"]:
        return comune

    da_pagina = _orari_da_pagina(sonda=sonda, url=str(comune["ufficio_url"]))
    comune["recuperabilita"] = (
        RecuperabilitaOrari.PROSA if da_pagina else RecuperabilitaOrari.ASSENTE
    )
    comune["citazione_orari"] = da_pagina
    return comune


def campiona(
    comuni: list[dict], *, quanti: int, seme: int
) -> list[dict]:
    """Campione stratificato per regione, riproducibile.

    Stratificato perché l'apertura dei portali non è distribuita a caso sul
    territorio: un campione semplice che pescasse per metà in Lombardia
    misurerebbe la Lombardia e la chiamerebbe Italia. Ogni regione entra in
    proporzione al proprio numero di comuni, con almeno uno a testa perché
    una regione assente dal campione è una regione di cui non si può dire
    niente — e il T0 lo deve poter dire di tutte.

    Il seme è un argomento e non un caso: una misura che non si può rifare
    identica non è una misura, è un aneddoto.
    """
    per_regione: dict[str, list[dict]] = {}
    for c in comuni:
        if c.get("sito"):
            per_regione.setdefault(c.get("regione") or "?", []).append(c)

    totale = sum(len(v) for v in per_regione.values())
    if not totale:
        return []

    rng = random.Random(seme)
    scelti: list[dict] = []
    for regione in sorted(per_regione):
        gruppo = sorted(per_regione[regione], key=lambda c: c["codice_istat"])
        quota = max(1, round(quanti * len(gruppo) / totale))
        scelti.extend(rng.sample(gruppo, min(quota, len(gruppo))))
    return scelti


def censisci_molti(
    comuni: list[dict],
    *,
    leggi_pagina: bool,
    lavoratori: int = 8,
    misura_piattaforma: bool = False,
    misura_aderenza: bool = False,
    salva: Callable[[list[EsitoCensimento]], None] | None = None,
    ogni: int = 200,
) -> list[EsitoCensimento]:
    """Censisce molti comuni in parallelo, uno solo per volta per host.

    Il parallelismo è fra comuni diversi, mai dentro lo stesso portale: le
    richieste a un singolo comune restano in fila, come le farebbe una
    persona. Otto server diversi che ricevono una richiesta a testa non sono
    un carico; otto richieste allo stesso server piccolo lo sarebbero (D-22).

    `salva` viene chiamata ogni `ogni` comuni con il blocco appena misurato.
    Serve a una cosa sola: su scala nazionale la raccolta dura un'ora, e
    tenere tutto in memoria fino alla fine significa che un'interruzione al
    settemillesimo comune butta via settemila misure — cioè settemila portali
    pubblici a cui abbiamo chiesto qualcosa per niente, e a cui dovremmo
    richiederlo. Il costo di un guasto va pagato da noi, non da loro.
    """
    esiti: list[EsitoCensimento] = []
    with ThreadPoolExecutor(max_workers=lavoratori) as pool:
        futuri = {
            pool.submit(
                censisci_comune,
                codice_istat=c["codice_istat"],
                nome=c["nome"],
                sito=c.get("sito"),
                leggi_pagina=leggi_pagina,
                misura_piattaforma=misura_piattaforma,
                misura_aderenza=misura_aderenza,
                regione=c.get("regione"),
                ipa_noto=c.get("codice_ipa"),
            ): c
            for c in comuni
        }
        da_salvare: list[EsitoCensimento] = []
        for n, futuro in enumerate(as_completed(futuri), start=1):
            esito = futuro.result()
            esiti.append(esito)
            da_salvare.append(esito)
            if n % 25 == 0:
                print(f"  … {n}/{len(futuri)}", file=sys.stderr)
            if salva and len(da_salvare) >= ogni:
                salva(da_salvare)
                print(f"  ↳ salvati {n}/{len(futuri)}", file=sys.stderr)
                da_salvare = []
        if salva and da_salvare:
            salva(da_salvare)
    return sorted(esiti, key=lambda e: e.codice_istat)


def main(argv: list[str] | None = None) -> int:
    """CLI: censisce gli enti noti, o un sito singolo passato a mano."""
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.ingest.censimento",
        description=(
            "Misura quanti comuni sanno dire quali uffici hanno (asse A) e "
            "quando sono aperti (asse B). Deterministico: nessun modello."
        ),
    )
    parser.add_argument(
        "--sito",
        help="Censisci un solo portale (es. www.comune.trento.it) invece di data/enti.json.",
    )
    parser.add_argument("--nome", default="(ad hoc)", help="Nome dell'ente per --sito.")
    parser.add_argument("--istat", default="000000", help="Codice ISTAT per --sito.")
    parser.add_argument(
        "--solo-asse-a",
        action="store_true",
        help="Fermati all'elenco uffici: nessuna pagina letta, asse B non tentato.",
    )
    parser.add_argument(
        "--campione",
        type=int,
        metavar="N",
        help="Censisci N comuni estratti da data/comuni-istat.json, stratificati per regione.",
    )
    parser.add_argument(
        "--seme",
        type=int,
        default=2026,
        help="Seme del campionamento. Stesso seme, stesso campione (default: 2026).",
    )
    parser.add_argument(
        "--tutti",
        action="store_true",
        help="Censisci tutti i comuni di data/comuni-istat.json. Implica --solo-asse-a.",
    )
    parser.add_argument(
        "--piattaforma",
        action="store_true",
        help="Misura anche l'asse C (che software gira) e la dimensione del catalogo.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        metavar="FILE",
        help="Registra gli esiti in questo SQLite, una riga per comune per giorno.",
    )
    parser.add_argument(
        "--catalog-output",
        type=Path,
        metavar="DIR",
        help=(
            "Aggiorna anche il catalogo contrattuale a ogni blocco salvato. "
            "Richiede --db; lo sweep resta invariato se l'opzione è assente."
        ),
    )
    parser.add_argument(
        "--measurement-id",
        help="Identificativo immutabile della misura catalogo (default: timestamp UTC).",
    )
    parser.add_argument(
        "--solo-misurabili",
        action="store_true",
        help=(
            "Rimisura dal --db i comuni su piattaforme di cui sappiamo leggere le "
            "schede. Serve a rifare una fotografia coerente dopo che la misura e' "
            "cambiata, senza disturbare chi non sapremmo comunque leggere."
        ),
    )
    parser.add_argument(
        "--solo-ignoti",
        action="store_true",
        help=(
            "Rileggi dal --db i soli comuni rimasti senza piattaforma. Serve dopo una "
            "correzione della sonda: chi era gia' riconosciuto non viene ridisturbato."
        ),
    )
    parser.add_argument(
        "--riprendi",
        action="store_true",
        help="Salta i comuni già registrati nel --db per la data di oggi.",
    )
    parser.add_argument(
        "--lavoratori",
        type=int,
        default=8,
        metavar="N",
        help="Richieste in parallelo (default: 8). Tenerlo basso è cortesia, non prudenza.",
    )
    parser.add_argument(
        "--aderenza",
        action="store_true",
        help="Misura quanto del modello AgID espone il portale. Due richieste in più.",
    )
    parser.add_argument("--json", action="store_true", help="Stampa JSON invece della tabella.")
    parser.add_argument("--out", type=Path, help="Scrivi il JSON degli esiti in questo file.")
    args = parser.parse_args(argv)

    if args.catalog_output and not args.db:
        parser.error("--catalog-output richiede --db")
    args.measurement_at = datetime.now(timezone.utc)
    args.measurement_id = args.measurement_id or args.measurement_at.strftime(
        "sweep-%Y%m%dT%H%M%SZ"
    )
    # Il catalogo è parte del contratto dello sweep, non un'importazione
    # successiva. Il flag resta disponibile per scegliere un mount diverso,
    # ma con --db la destinazione standard è accanto allo storico.
    if args.db and args.catalog_output is None:
        args.catalog_output = args.db.parent / "catalog"

    esiti = _raccogli(args)
    if args.db:
        scritte = _registra(
            esiti,
            db=args.db,
            anagrafe=_anagrafe(),
            catalog_output=args.catalog_output,
            measurement_id=args.measurement_id,
            measured_at=args.measurement_at,
        )
        print(f"registrate {scritte} righe in {args.db}", file=sys.stderr)
    if args.json or args.out:
        blob = json.dumps([e.model_dump(mode="json") for e in esiti], ensure_ascii=False, indent=2)
        if args.out:
            args.out.write_text(blob + "\n", "utf-8")
            print(f"scritti {len(esiti)} esiti in {args.out}", file=sys.stderr)
        else:
            print(blob)
    else:
        _stampa_tabella(esiti)
    return 0


def _anagrafe() -> dict[str, dict]:
    """I comuni ISTAT per codice: provincia e regione senza chiedere niente a nessuno."""
    from treasureiq.integration import DATA_DIR

    elenco = json.loads((DATA_DIR / "comuni-istat.json").read_text("utf-8"))
    return {c["codice_istat"]: c for c in elenco}


def _registra(
    esiti: list[EsitoCensimento],
    *,
    db: Path,
    anagrafe: dict[str, dict],
    catalog_output: Path | None = None,
    measurement_id: str | None = None,
    measured_at: datetime | None = None,
) -> int:
    """Traduce gli esiti in righe di storico e le scrive.

    La traduzione sta qui e non nello store perché è il censimento a sapere
    cosa significano i propri enum; `storico` deve poter leggere una serie
    storica anche fra dieci anni, quando questi enum saranno cambiati.
    """
    from treasureiq.storico import RigaPortale, registra_portali

    righe = [
        RigaPortale(
            rilevato_il=e.misurato_il,
            codice_istat=e.codice_istat,
            nome=e.nome,
            provincia=anagrafe.get(e.codice_istat, {}).get("provincia"),
            regione=anagrafe.get(e.codice_istat, {}).get("regione"),
            # ISTAT non pubblica la popolazione in questo elenco: la colonna
            # resta vuota finché non entra un dataset che la porta. Vuota è
            # l'unico valore onesto — uno zero renderebbe invisibili proprio i
            # comuni piccoli in ogni grafico pesato sui cittadini.
            popolazione=None,
            url_dichiarato=anagrafe.get(e.codice_istat, {}).get("sito"),
            url_finale=e.url_finale or e.sito,
            https_ok=e.https_ok,
            stato_http=e.stato_http,
            indirizzabilita=e.indirizzabilita.value,
            recuperabilita=e.recuperabilita.value,
            piattaforma=e.piattaforma.value,
            piattaforma_prova=e.piattaforma_prova,
            rest_base=e.rest_base,
            aderenza=e.aderenza,
            sezioni_esposte=e.sezioni_esposte,
            sezioni_dichiarate=e.sezioni_dichiarate,
            classificato_da=e.classificato_da or "sonda",
            vincoli=e.vincoli,
            base_misura=e.base_misura,
            nota_misura=e.nota_misura,
            impronta_declinazione=e.impronta_declinazione,
            scheda_campione=e.scheda_campione,
            server=e.server,
            impronta_grezza=e.impronta_grezza,
            n_servizi=e.n_servizi,
            ultimo_contenuto=e.ultimo_contenuto,
            richieste=e.richieste,
            secondi=e.secondi,
            errore=e.errore,
            piattaforma_at=e.piattaforma_at,
            piattaforma_at_prova=e.piattaforma_at_prova,
            at_url=e.at_url,
            firme_scattate=e.firme_scattate,
        )
        for e in esiti
    ]
    scritte = registra_portali(db, righe)
    if catalog_output:
        from treasureiq.catalog.store import SnapshotStore
        from treasureiq.catalog.sweep_import import persist_sweep_snapshot_batch

        persist_sweep_snapshot_batch(
            db,
            store=SnapshotStore(catalog_output),
            codici_istat=tuple(r.codice_istat for r in righe),
            measurement_id=measurement_id or f"sweep-{righe[0].rilevato_il.isoformat()}",
            measured_at=measured_at
            or datetime.combine(
                max(r.misurato_il for r in esiti),
                datetime.min.time(),
                tzinfo=timezone.utc,
            ),
        )
    return scritte


def _gia_registrati(db: Path | None, giorno: date) -> set[str]:
    """Chi è già stato misurato oggi, per non chiedergli di nuovo la home.

    Riprendere è una cortesia verso i portali prima che verso di noi: uno
    sweep nazionale interrotto a metà, rilanciato senza questo, ribusserebbe
    a quattromila comuni che avevano già risposto.
    """
    if db is None or not db.exists():
        return set()
    from treasureiq.storico import apri

    with apri(db) as conn:
        righe = conn.execute(
            "SELECT codice_istat FROM portale_snapshot WHERE rilevato_il = ?",
            (giorno.isoformat(),),
        ).fetchall()
    return {r["codice_istat"] for r in righe}


def _ignoti(db: Path | None, giorno: date) -> set[str]:
    """I comuni rimasti senza piattaforma in un rilevamento."""
    from treasureiq.storico import apri

    if not db or not db.exists():
        return set()
    with apri(db) as conn:
        righe = conn.execute(
            "SELECT codice_istat FROM portale_snapshot "
            "WHERE rilevato_il = ? AND piattaforma = 'ignota'",
            (giorno.isoformat(),),
        ).fetchall()
    return {r["codice_istat"] for r in righe}


def _raccogli(args: argparse.Namespace) -> list[EsitoCensimento]:
    leggi_pagina = not args.solo_asse_a

    if getattr(args, "solo_misurabili", False):
        from treasureiq.integration import DATA_DIR
        from treasureiq.storico import apri

        elenco = json.loads((DATA_DIR / "comuni-istat.json").read_text("utf-8"))
        oggi = datetime.now(timezone.utc).date()
        misurabili = {
            Piattaforma.WP_DESIGN_COMUNI.value,
            Piattaforma.PEOPLEWEB.value,
            Piattaforma.COMWEB.value,
            *(p.value for p in _MYPORTAL),
        }
        with apri(args.db) as conn:
            righe = conn.execute(
                "SELECT codice_istat FROM portale_snapshot WHERE rilevato_il = ? "
                f"AND piattaforma IN ({','.join('?' * len(misurabili))})",
                (oggi.isoformat(), *sorted(misurabili)),
            ).fetchall()
        voluti = {r["codice_istat"] for r in righe}
        scelti = [c for c in elenco if c["codice_istat"] in voluti]
        print(f"rimisura: {len(scelti)} comuni su piattaforme leggibili", file=sys.stderr)
        anagrafe = {c["codice_istat"]: c for c in elenco}
        salva = (
            (
                lambda blocco: _registra(
                    blocco,
                    db=args.db,
                    anagrafe=anagrafe,
                    catalog_output=args.catalog_output,
                    measurement_id=args.measurement_id,
                    measured_at=args.measurement_at,
                )
            )
            if args.db
            else None
        )
        return censisci_molti(
            scelti,
            leggi_pagina=False,
            lavoratori=args.lavoratori,
            misura_piattaforma=args.piattaforma,
            misura_aderenza=args.aderenza,
            salva=salva,
        )

    if getattr(args, "solo_ignoti", False):
        from treasureiq.integration import DATA_DIR

        elenco = json.loads((DATA_DIR / "comuni-istat.json").read_text("utf-8"))
        oggi = datetime.now(timezone.utc).date()
        da_rileggere = _ignoti(args.db, oggi)
        scelti = [c for c in elenco if c["codice_istat"] in da_rileggere]
        print(
            f"rilettura: {len(scelti)} comuni rimasti senza piattaforma il {oggi}",
            file=sys.stderr,
        )
        anagrafe = {c["codice_istat"]: c for c in elenco}
        salva = (
            (
                lambda blocco: _registra(
                    blocco,
                    db=args.db,
                    anagrafe=anagrafe,
                    catalog_output=args.catalog_output,
                    measurement_id=args.measurement_id,
                    measured_at=args.measurement_at,
                )
            )
            if args.db
            else None
        )
        return censisci_molti(
            scelti,
            leggi_pagina=False,
            lavoratori=args.lavoratori,
            misura_piattaforma=args.piattaforma,
            misura_aderenza=args.aderenza,
            salva=salva,
        )

    if args.tutti:
        from treasureiq.integration import DATA_DIR

        elenco = json.loads((DATA_DIR / "comuni-istat.json").read_text("utf-8"))
        fatti = _gia_registrati(args.db, datetime.now(timezone.utc).date()) if args.riprendi else set()
        scelti = [c for c in elenco if c["codice_istat"] not in fatti]
        print(
            f"censimento nazionale: {len(scelti)} comuni da misurare"
            + (f", {len(fatti)} già fatti oggi" if fatti else ""),
            file=sys.stderr,
        )
        # L'asse B chiede a ogni comune di servirci una pagina intera: è il
        # solo che non si può porre a tutta l'Italia (vedi `censisci_comune`).
        anagrafe = {c["codice_istat"]: c for c in elenco}
        salva = (
            (
                lambda blocco: _registra(
                    blocco,
                    db=args.db,
                    anagrafe=anagrafe,
                    catalog_output=args.catalog_output,
                    measurement_id=args.measurement_id,
                    measured_at=args.measurement_at,
                )
            )
            if args.db
            else None
        )
        return censisci_molti(
            scelti,
            leggi_pagina=False,
            lavoratori=args.lavoratori,
            misura_piattaforma=args.piattaforma,
            misura_aderenza=args.aderenza,
            salva=salva,
        )

    if args.campione:
        from treasureiq.integration import DATA_DIR

        elenco = json.loads((DATA_DIR / "comuni-istat.json").read_text("utf-8"))
        scelti = campiona(elenco, quanti=args.campione, seme=args.seme)
        print(
            f"campione: {len(scelti)} comuni su {len(elenco)}, seme {args.seme}",
            file=sys.stderr,
        )
        return censisci_molti(
            scelti,
            leggi_pagina=leggi_pagina,
            lavoratori=args.lavoratori,
            misura_piattaforma=args.piattaforma,
            misura_aderenza=args.aderenza,
        )

    if args.sito:
        return [
            censisci_comune(
                codice_istat=args.istat,
                nome=args.nome,
                sito=args.sito,
                leggi_pagina=leggi_pagina,
                misura_piattaforma=args.piattaforma,
                misura_aderenza=args.aderenza,
            )
        ]

    from treasureiq.integration import load_enti

    esiti = []
    for ente in load_enti().values():
        esiti.append(
            censisci_comune(
                codice_istat=ente.codice_istat,
                nome=ente.ente,
                sito=ente.ipa.sito if ente.ipa else None,
                leggi_pagina=leggi_pagina,
            )
        )
    return esiti


def _stampa_tabella(esiti: list[EsitoCensimento]) -> None:
    for e in esiti:
        print(f"{e.codice_istat}  {e.nome}")
        print(f"    asse A  {e.indirizzabilita.value:16} rest_base={e.rest_base or '—'}")
        print(
            f"    asse B  {e.recuperabilita.value:16} "
            f"ufficio={e.ufficio_scelto or '—'} ({e.uffici_trovati or 0} letti)"
        )
        if e.citazione_orari:
            print(f"    prova   «{e.citazione_orari}»")
        if e.errore:
            print(f"    errore  {e.errore}")
        print(f"    costo   {e.richieste} richieste, {e.secondi}s")
    _riepilogo(esiti)


def _riepilogo(esiti: list[EsitoCensimento]) -> None:
    """Il T0 in due righe: la forbice fra i due assi è la misura."""
    totale = len(esiti)
    if not totale:
        return

    def quanti(**criteri: object) -> int:
        return sum(
            1
            for e in esiti
            if all(getattr(e, campo) in valori for campo, valori in criteri.items())  # type: ignore[operator]
        )

    irraggiungibili = quanti(indirizzabilita=(Indirizzabilita.IRRAGGIUNGIBILE,))
    misurati = totale - irraggiungibili
    con_api = quanti(indirizzabilita=(Indirizzabilita.API_UFFICI,))
    tipizzati = quanti(recuperabilita=(RecuperabilitaOrari.CAMPO_TIPIZZATO,))
    in_prosa = quanti(recuperabilita=(RecuperabilitaOrari.PROSA,))
    senza_urp = quanti(recuperabilita=(RecuperabilitaOrari.URP_NON_TROVATO,))
    orari_assenti = quanti(recuperabilita=(RecuperabilitaOrari.ASSENTE,))

    def pct(n: int) -> str:
        return f"{n * 100 / misurati:.0f}%" if misurati else "—"

    print(f"\n— T0 su {totale} comuni, di cui {misurati} misurati —")
    if irraggiungibili:
        print(f"  non misurati (portale irraggiungibile) : {irraggiungibili}")
    print(f"  ti dicono quali uffici hanno           : {con_api} ({pct(con_api)})")
    print(f"  ti dicono quando l'URP è aperto        : {tipizzati + in_prosa} "
          f"({pct(tipizzati + in_prosa)})")
    print(f"     in un campo tipizzato               : {tipizzati}")
    print(f"     solo in prosa, da estrarre          : {in_prosa}")
    print(f"  hanno l'API ma nessun URP riconoscibile: {senza_urp}")
    print(f"  hanno l'URP ma non ne pubblicano l'orario: {orari_assenti}")


if __name__ == "__main__":
    raise SystemExit(main())
