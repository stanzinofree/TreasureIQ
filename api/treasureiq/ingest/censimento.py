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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from treasureiq.ingest.base import USER_AGENT
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
    richieste: int = 0
    secondi: float | None = None
    errore: str | None = None
    misurato_il: date = Field(default_factory=lambda: datetime.now(timezone.utc).date())


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
            resp = self._client.get(url, params=params)
        except httpx.RequestError:
            if self.raggiungibile is None:
                self.raggiungibile = False
            raise
        self.raggiungibile = True
        resp.raise_for_status()
        return resp

    def json(self, url: str, **params: object) -> object:
        return self._get(url, **params).json()

    def testo(self, url: str) -> str:
        return self._get(url).text


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


def _orari_da_pagina(*, sonda: _Sonda, url: str) -> str | None:
    """Un orario nel testo della pagina dell'ufficio, citato alla lettera."""
    try:
        html = sonda.testo(url)
    except Exception:  # noqa: BLE001
        return None
    testo = strip_html(html)[:MAX_CARATTERI_PAGINA]
    testo = re.sub(r"\s+", " ", testo)
    trovato = ORARIO_RE.search(testo)
    return _cita(testo, trovato) if trovato else None


def censisci_comune(
    *,
    codice_istat: str,
    nome: str,
    sito: str | None,
    timeout: float = 12.0,
    leggi_pagina: bool = True,
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
        esito.update(
            codice_istat=codice_istat,
            nome=nome,
            sito=base,
            richieste=sonda.richieste,
            secondi=round(time.perf_counter() - avvio, 3),
        )
    return EsitoCensimento(**esito)


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
    comuni: list[dict], *, leggi_pagina: bool, lavoratori: int = 8
) -> list[EsitoCensimento]:
    """Censisce molti comuni in parallelo, uno solo per volta per host.

    Il parallelismo è fra comuni diversi, mai dentro lo stesso portale: le
    richieste a un singolo comune restano in fila, come le farebbe una
    persona. Otto server diversi che ricevono una richiesta a testa non sono
    un carico; otto richieste allo stesso server piccolo lo sarebbero (D-22).
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
            ): c
            for c in comuni
        }
        for n, futuro in enumerate(as_completed(futuri), start=1):
            esiti.append(futuro.result())
            if n % 25 == 0:
                print(f"  … {n}/{len(futuri)}", file=sys.stderr)
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
    parser.add_argument("--json", action="store_true", help="Stampa JSON invece della tabella.")
    parser.add_argument("--out", type=Path, help="Scrivi il JSON degli esiti in questo file.")
    args = parser.parse_args(argv)

    esiti = _raccogli(args)
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


def _raccogli(args: argparse.Namespace) -> list[EsitoCensimento]:
    leggi_pagina = not args.solo_asse_a

    if args.campione:
        from treasureiq.integration import DATA_DIR

        elenco = json.loads((DATA_DIR / "comuni-istat.json").read_text("utf-8"))
        scelti = campiona(elenco, quanti=args.campione, seme=args.seme)
        print(
            f"campione: {len(scelti)} comuni su {len(elenco)}, seme {args.seme}",
            file=sys.stderr,
        )
        return censisci_molti(scelti, leggi_pagina=leggi_pagina)

    if args.sito:
        return [
            censisci_comune(
                codice_istat=args.istat,
                nome=args.nome,
                sito=args.sito,
                leggi_pagina=leggi_pagina,
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
