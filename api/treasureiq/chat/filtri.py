"""Filtri civici riconosciuti dal testo libero del cittadino (ciclo 11, B2).

Modulo deterministico, catalogo-dati: nessun modello genera un valore, ogni
filtro emesso porta lo SPAN verbatim del testo che lo giustifica. Chiude i
gap che B1 ha congelato in `tests/corpus_filtri.py` — il troncamento ISEE
(«9360» letto come 936.0), le negazioni mai guardate («non sono disabile»
restava disabilita=True), e i toponimi spuri («minori» che risolveva al
comune di Minori, SA).

Regola dura (A12, L-5): una forma non riconosciuta resta uno slot vuoto.
Mai indovinare un valore che il testo non dimostra — un filtro senza `span`
verbatim (quando `sorgente="testo"`) semplicemente non viene emesso.

Questo modulo e' innestato in produzione (B3): `api.py` lo importa, e
`respond.py` chiama `riconosci_filtri` a ogni turno di chat. La scelta di
non spedire il modello spaCy in runtime e' deliberata: la produzione gira
sul fallback a cue-list per la negazione (degrado onesto, L-5).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel

from treasureiq.chat.intent import _DISABILITA_RE, _FIGLIO_DISABILE_MARKERS
from treasureiq.chat.respond import _comuni_candidati, _estrai_tema

logger = logging.getLogger(__name__)


class Span(BaseModel):
    inizio: int
    fine: int
    testo: str


class FiltroChiave(str, Enum):
    COMUNE = "comune"
    DISABILITA = "disabilita"
    DISABILITA_NUCLEO = "disabilita_nucleo"
    FIGLI_MINORI = "figli_minori"
    ETA = "eta"
    ANZIANO = "anziano"
    ISEE = "isee"
    NUCLEO_FAMILIARE = "nucleo_familiare"
    EMPLOYMENT_STATUS = "employment_status"
    TEMA = "tema"


class Filtro(BaseModel):
    chiave: FiltroChiave
    #: D-06 elencava `str | int | bool`; qui c'e' anche `float` perche' l'ISEE
    #: porta i centesimi («9.360,50») e troncarli a intero corromperebbe la
    #: cifra letta dal testo — lo stesso principio per cui il verbalizzatore
    #: non tocca i numeri (vedi nota `verbalizzatore-corrompe-cifre`).
    valore: str | int | float | bool
    span: Span | None
    sorgente: Literal["testo", "profilo", "override_client"]
    negato: bool = False


# -- negazione: spaCy se presente, cue-list IT come ripiego onesto ----------

#: Cue di negazione italiane cercate nella finestra che precede uno span. E'
#: il ripiego usato quando spaCy/it_core_news_lg non e' installato (500MB, non
#: garantito nell'ambiente di test): non fa scope-parsing sintattico vero, ma
#: evita di crashare o di restare ciechi alla negazione (L-5).
_CUE_NEGAZIONE = frozenset({"non", "senza", "né", "ne", "mai", "nessun", "nessuna"})
_FRASI_NEGAZIONE = ("privo di", "priva di", "prive di", "privi di")
_FINESTRA_NEGAZIONE = 5


@lru_cache(maxsize=1)
def _modello_spacy():
    """Carica `it_core_news_lg` una sola volta, degrada senza eccezioni.

    Lazy: il costo (import + 500MB di modello) si paga solo se qualcuno
    chiama davvero `riconosci_filtri`, e solo la prima volta. Se il pacchetto
    o il modello mancano, si torna al fallback a cue-list — mai un'eccezione
    che spezza il modulo (L-5).
    """
    try:
        import spacy
    except ImportError:
        logger.warning("spaCy non installato: filtri.py usa il fallback a cue-list per la negazione")
        return None
    try:
        return spacy.load("it_core_news_lg")
    except OSError:
        logger.warning("modello it_core_news_lg non disponibile: filtri.py usa il fallback a cue-list")
        return None


def _lemmi_finali(frammento: str, nlp) -> list[str]:
    """Ultimi lemmi (spaCy) di `frammento`, minuscoli. Il chiamante passa
    GIA' la sola ultima clausola: la finestra non deve scavalcare la
    virgola (altrimenti "non sono disoccupato, sono pensionato" negherebbe
    "pensionato" — vedi `_negato_prima_di`)."""
    doc = nlp(frammento)
    return [t.lemma_.lower() for t in doc][-_FINESTRA_NEGAZIONE:]


def _negato_prima_di(testo: str, inizio: int) -> bool:
    """C'e' una negazione che precede lo span che comincia a `inizio`?

    Con spaCy: lemmi degli ultimi token prima dello span. Senza: le stesse
    parole cercate nude (cue-list), stessa finestra, ma solo dentro l'ultima
    clausola (dopo l'ultimo `,;.:!?`) — una virgola chiude lo scope di una
    negazione ("non sono disoccupato, sono pensionato" non deve negare
    "pensionato"). Non e' uno scope-parser sintattico vero (un "non" nella
    stessa clausola ma logicamente slegato resta un falso positivo), ma e'
    deterministico e non manca mai la negazione diretta e vicina, il caso
    reale del corpus (A2).
    """
    prima = testo[:inizio].casefold()
    if any(prima.rstrip().endswith(frase) for frase in _FRASI_NEGAZIONE):
        return True
    ultima_clausola = re.split(r"[,;.:!?]", prima)[-1]
    nlp = _modello_spacy()
    if nlp is not None:
        parole = _lemmi_finali(ultima_clausola, nlp)
    else:
        parole = re.findall(r"\w+", ultima_clausola)[-_FINESTRA_NEGAZIONE:]
    return any(parola in _CUE_NEGAZIONE for parola in parole)


#: Confine di clausola: lo stesso `[,;.:!?]` gia' usato da `_negato_prima_di`
#: per delimitare lo scope di una negazione (ciclo 10/L-5). Riusato qui
#: (ciclo 11: BUG A) per delimitare lo scope di "chi e' disabile" — «un
#: bambino di 4 anni disabile» e «sono disabile, mio fratello no» hanno
#: entrambi bisogno di sapere quale sostantivo-figlio cade nella STESSA
#: clausola della parola "disabile", non altrove nella frase.
_CONFINE_CLAUSOLA_RE = re.compile(r"[,;.:!?]")


def _confini_clausola(testo: str, pos: int) -> tuple[int, int]:
    """Inizio/fine della clausola che contiene l'indice `pos`."""
    inizio = 0
    for m in _CONFINE_CLAUSOLA_RE.finditer(testo, 0, pos):
        inizio = m.end()
    fine_match = _CONFINE_CLAUSOLA_RE.search(testo, pos)
    fine = fine_match.start() if fine_match else len(testo)
    return inizio, fine


def _ultimo_match_prima_di(pattern: re.Pattern[str], testo: str, pos: int) -> re.Match[str] | None:
    """L'ultimo match di `pattern` che inizia prima di `pos` (il piu' vicino
    a `pos`), o None se non ce n'e' nessuno."""
    ultimo: re.Match[str] | None = None
    for m in pattern.finditer(testo, 0, pos):
        ultimo = m
    return ultimo


# -- importi (ISEE/reddito): fix del troncamento «9360» -> 936.0 -----------

#: Le stesse forme del vecchio `_ISEE_NEL_TESTO` (intent.py:678) PIU' quelle
#: che mancavano. Il bug reale: l'alternanza vecchia provava prima il ramo
#: "con separatore delle migliaia" e, su un numero senza separatore, il
#: gruppo `\d{1,3}` si fermava ai primi 3 cifre senza fare backtracking sul
#: ramo lungo — «9360» letto come 936. Qui il ramo "cifre piatte" (`piatto`,
#: 3-6 cifre) sta DOPO quello con separatore ma matcha tutta la stringa
#: quando non c'e' punteggiatura, perche' non e' vincolato a fermarsi a 3.
_IMPORTO_RE = re.compile(
    r"(?P<separato>\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?)"
    r"|(?P<piatto>\d{3,6}(?:,\d{1,2})?)"
    r"|(?P<numk>\d{1,3})\s*k\b"
    r"|(?P<nummila>\d{1,4})\s*mila\b"
    r"|\b(?P<parolamila>un|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)mila\b",
    re.IGNORECASE,
)

_UNITA_NUMERO = {
    "un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
}

#: Parole-chiave che devono comparire per leggere un numero come ISEE/reddito.
#: Un numero nudo («9k», «novemila») senza una di queste vicino non e'
#: evidenza di ISEE: potrebbe essere qualunque cosa (A12, mai indovinare).
_KEYWORD_IMPORTO_RE = re.compile(r"\b(?:isee|reddito)\b", re.IGNORECASE)

_FINESTRA_IMPORTO_CHAR = 30


def _valore_importo(match: re.Match) -> float | None:
    if match.group("separato"):
        grezzo = match.group("separato").replace(".", "").replace(" ", "").replace(",", ".")
        return float(grezzo)
    if match.group("piatto"):
        return float(match.group("piatto").replace(",", "."))
    if match.group("numk"):
        return float(match.group("numk")) * 1000
    if match.group("nummila"):
        return float(match.group("nummila")) * 1000
    if match.group("parolamila"):
        return float(_UNITA_NUMERO[match.group("parolamila").lower()]) * 1000
    return None


def _riconosci_isee(testo: str) -> list[Filtro]:
    keyword = _KEYWORD_IMPORTO_RE.search(testo)
    if keyword is None:
        return []
    finestra_inizio = keyword.end()
    finestra = testo[finestra_inizio : finestra_inizio + _FINESTRA_IMPORTO_CHAR]
    match = _IMPORTO_RE.search(finestra)
    if match is None:
        return []
    valore = _valore_importo(match)
    if valore is None:
        return []
    inizio = finestra_inizio + match.start()
    fine = finestra_inizio + match.end()
    span = Span(inizio=inizio, fine=fine, testo=testo[inizio:fine])
    if _negato_prima_di(testo, inizio):
        return []
    return [Filtro(chiave=FiltroChiave.ISEE, valore=valore, span=span, sorgente="testo")]


# -- sostantivi bambino/figlio: condivisi da eta', figli minori, disabilita' -

#: «bambino/a/i/e», «bimbo/a/i/e»: il sostantivo da solo implica un minore,
#: nessuna eta' esplicita serve per dedurlo (ciclo 11: BUG B).
_NOUN_BAMBINO_BIMBO = r"bambin[oaie]|bimb[oaie]"
#: «figlio/figlia» al singolare/plurale: da solo NON implica un minore (puo'
#: essere adulto) — serve un'evidenza in piu' (parola "minore/piccolo", vedi
#: `_FIGLI_MINORI_RE`, o un'eta' esplicita < 18, vedi `_FIGLIO_ETA_RE`).
_NOUN_FIGLIO = r"figli[oa]|figlie|figli"

#: Sostantivo bambino/bimbo/figlio, per il contesto-figlio di
#: `_riconosci_disabilita` (ciclo 11: BUG A) — qui basta la co-occorrenza in
#: clausola, non serve eta'.
_SOSTANTIVO_FIGLIO_RE = re.compile(
    r"\b(?:bambin[oaie]|bimb[oaie]|figli[oa]|figlie|figli)\b", re.I
)

#: Dichiarazione esplicita in prima persona («sono disabile», «io ... sono
#: disabile», «ho una disabilità»): quando questa e' PIU' VICINA al match di
#: "disabile" del sostantivo-figlio piu' vicino, vince lei — "non ho figli
#: disabili ma io sono disabile" ha "figli" nella stessa clausola (niente
#: punteggiatura in mezzo) ma "sono" e' molto piu' vicino al secondo
#: "disabile": la dichiarazione propria non deve perdere solo perche' un
#: figlio e' stato nominato prima, altrove nella stessa clausola.
_SELF_DISABILITA_RE = re.compile(r"\b(?:sono|io)\b|ho\s+una\s+disabilit\w*", re.I)

#: «bambino/bimbo/figlio di N anni»: l'eta' che segue appartiene al FIGLIO,
#: non al cittadino (ciclo 11: BUG B). `_riconosci_eta` esclude questo stesso
#: match dal proprio scanner, cosi' le due funzioni restano d'accordo su chi
#: e' il titolare dell'eta'.
_FIGLIO_ETA_RE = re.compile(
    r"\b(?P<n>\d{1,2}|un|uno|una|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)?\s*"
    r"(?:bambin[oaie]|bimb[oaie]|figli[oa]|figlie|figli)\s+di\s+(?P<eta_figlio>\d{1,2})"
    r"(?:\s*(?:e|,|ed)\s*(?P<eta_extra>\d{1,2}))*\s*anni",
    re.I,
)


# -- eta' (+ anziano derivato) -----------------------------------------------

_ETA_RE = re.compile(r"\b(?:ho\s+|di\s+|età\s+|eta\s+)?(?P<eta>\d{1,3})\s*(?:anni|enne\b)", re.I)
_SOGLIA_ANZIANO = 65


def _riconosci_eta(testo: str) -> list[Filtro]:
    # L'eta' di un figlio ("un bambino di 4 anni") non e' l'eta' del
    # cittadino: si esclude qualunque match di `_ETA_RE` che ricada dentro
    # un match di `_FIGLIO_ETA_RE` (ciclo 11: BUG B), poi si prende il primo
    # match valido rimasto (stesso ordine "prima occorrenza vince" di prima).
    esclusioni = [m.span() for m in _FIGLIO_ETA_RE.finditer(testo)]
    for match in _ETA_RE.finditer(testo):
        if any(match.start() < fine and match.end() > inizio for inizio, fine in esclusioni):
            continue
        valore = int(match.group("eta"))
        if not (0 < valore <= 130):
            continue  # oltre 130 e' un importo o un civico, non un'eta' (stesso guard di slot_dal_testo)
        if _negato_prima_di(testo, match.start()):
            continue
        span = Span(inizio=match.start(), fine=match.end(), testo=match.group(0))
        filtri = [Filtro(chiave=FiltroChiave.ETA, valore=valore, span=span, sorgente="testo")]
        if valore >= _SOGLIA_ANZIANO:
            filtri.append(Filtro(chiave=FiltroChiave.ANZIANO, valore=True, span=span, sorgente="testo"))
        return filtri
    return []


# -- nucleo familiare ---------------------------------------------------------

_NUCLEO_RE = re.compile(
    r"\b(?:famiglia|nucleo)\s+di\s+(?P<nucleo>\d{1,2})\b"
    r"|\bsiamo\s+in\s+(?P<nucleo2>\d{1,2})\b",
    re.I,
)


def _riconosci_nucleo(testo: str) -> list[Filtro]:
    match = _NUCLEO_RE.search(testo)
    if match is None:
        return []
    grezzo = match.group("nucleo") or match.group("nucleo2")
    valore = int(grezzo)
    if valore < 1:
        return []
    span = Span(inizio=match.start(), fine=match.end(), testo=match.group(0))
    if _negato_prima_di(testo, match.start()):
        return []
    return [Filtro(chiave=FiltroChiave.NUCLEO_FAMILIARE, valore=valore, span=span, sorgente="testo")]


# -- figli minori --------------------------------------------------------------

_FIGLI_MINORI_RE = re.compile(
    r"\b(?P<n>\d{1,2}|un|uno|una|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)?\s*"
    r"figl[io]\w*\s+(?:minorenn\w+|minor\w+|piccol\w+)",
    re.I,
)

#: «un bambino/bimbo (di N anni)?», senza bisogno della parola "minore": il
#: sostantivo da solo basta, un bambino e' per definizione minorenne (ciclo
#: 11: BUG B). Non copre "figlio/figlia" bare: quello resta ambiguo (puo'
#: essere adulto), serve `_FIGLIO_ETA_RE` (eta' esplicita) o `_FIGLI_MINORI_RE`
#: (parola "minore/piccolo") per quello.
_BAMBINO_BIMBO_RE = re.compile(
    r"\b(?P<n>\d{1,2}|un|uno|una|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)?\s*"
    r"(?:bambin[oaie]|bimb[oaie])\b",
    re.I,
)


def _valore_numerale(grezzo: str | None) -> int:
    if grezzo is None:
        return 1  # senza conteggio esplicito -> almeno uno
    if grezzo.isdigit():
        return int(grezzo)
    return _UNITA_NUMERO.get(grezzo.lower(), 1)


def _riconosci_figli_minori(testo: str) -> list[Filtro]:
    # Tre forme, in ordine di precedenza: (1) "figli minorenni/minori/piccoli"
    # — la parola "minore" e' gia' l'evidenza; (2) "figlio/figlia di N anni"
    # con N<18 — l'eta' esplicita e' l'evidenza (stesso match di
    # `_riconosci_eta`, che lo esclude dal proprio scanner); (3) "bambino/
    # bimbo" bare — il sostantivo stesso e' l'evidenza (ciclo 11: BUG B).
    match = _FIGLI_MINORI_RE.search(testo)
    if match is not None:
        valore = _valore_numerale(match.group("n"))
        if valore < 1:
            return []
        span = Span(inizio=match.start(), fine=match.end(), testo=match.group(0))
        if _negato_prima_di(testo, match.start()):
            return []
        return [Filtro(chiave=FiltroChiave.FIGLI_MINORI, valore=valore, span=span, sorgente="testo")]

    match = _FIGLIO_ETA_RE.search(testo)
    if match is not None:
        eta_valori = [int(x) for x in re.findall(r"\d{1,2}", match.group(0).split(" di ", 1)[-1])]
        if not any(eta < 18 for eta in eta_valori):
            match = None
    if match is not None:
        valore = _valore_numerale(match.group("n"))
        if valore < 1:
            return []
        span = Span(inizio=match.start(), fine=match.end(), testo=match.group(0))
        if _negato_prima_di(testo, match.start()):
            return []
        return [Filtro(chiave=FiltroChiave.FIGLI_MINORI, valore=valore, span=span, sorgente="testo")]

    match = _BAMBINO_BIMBO_RE.search(testo)
    if match is not None:
        valore = _valore_numerale(match.group("n"))
        if valore < 1:
            return []
        span = Span(inizio=match.start(), fine=match.end(), testo=match.group(0))
        if _negato_prima_di(testo, match.start()):
            return []
        return [Filtro(chiave=FiltroChiave.FIGLI_MINORI, valore=valore, span=span, sorgente="testo")]

    return []


# -- disabilita': propria vs figlio (R-8/D-53) -------------------------------


def _riconosci_disabilita(testo: str) -> list[Filtro]:
    """La disabilita' e' del cittadino o di un figlio? Riusa gli stessi
    marcatori e la stessa regex di `intent.py` (nessuna reinvenzione), qui
    solo per ricavarne lo span e applicarci la negazione.
    """
    haystack = testo.casefold()
    marcatore = next((m for m in _FIGLIO_DISABILE_MARKERS if m in haystack), None)
    marcatore_span: tuple[int, int] | None = None
    if marcatore is not None:
        inizio = haystack.find(marcatore)
        marcatore_span = (inizio, inizio + len(marcatore))
        if not _negato_prima_di(testo, inizio):
            fine = inizio + len(marcatore)
            span = Span(inizio=inizio, fine=fine, testo=testo[inizio:fine])
            return [Filtro(chiave=FiltroChiave.DISABILITA_NUCLEO, valore=True, span=span, sorgente="testo")]
    # Il marcatore figlio-disabile negato non basta a fermare il
    # riconoscimento: puo' condividere testo con `_DISABILITA_RE` (es.
    # "disabili" dentro "figli disabili"), quindi si scansionano TUTTI i
    # match e si scarta solo quello gia' consumato/negato dal marcatore,
    # non l'intera funzione.
    for match in _DISABILITA_RE.finditer(testo):
        if marcatore_span is not None and marcatore_span[0] <= match.start() < marcatore_span[1]:
            continue
        if _negato_prima_di(testo, match.start()):
            continue
        # «un bambino di 4 anni disabile»: i marcatori contigui sopra non lo
        # prendono (il sostantivo non e' "figlio" e non tocca "disabile").
        # Prima di attribuire la disabilita' al cittadino, si guarda se nella
        # STESSA clausola c'e' un sostantivo-figlio: se si', e' il figlio ad
        # essere disabile, non il cittadino (ciclo 11: BUG A).
        inizio_clausola, fine_clausola = _confini_clausola(testo, match.start())
        clausola = testo[inizio_clausola:fine_clausola]
        rel_match_start = match.start() - inizio_clausola
        figlio_match = _ultimo_match_prima_di(_SOSTANTIVO_FIGLIO_RE, clausola, rel_match_start)
        self_match = _ultimo_match_prima_di(_SELF_DISABILITA_RE, clausola, rel_match_start)
        # Vince il contesto piu' vicino al match di "disabile": se il
        # sostantivo-figlio e' piu' vicino (o e' l'unico presente), il figlio;
        # se la dichiarazione in prima persona e' piu' vicina, il cittadino.
        if figlio_match is not None and (self_match is None or figlio_match.start() > self_match.start()):
            span_inizio = inizio_clausola + figlio_match.start()
            span = Span(inizio=span_inizio, fine=match.end(), testo=testo[span_inizio:match.end()])
            return [Filtro(chiave=FiltroChiave.DISABILITA_NUCLEO, valore=True, span=span, sorgente="testo")]
        span = Span(inizio=match.start(), fine=match.end(), testo=match.group(0))
        return [Filtro(chiave=FiltroChiave.DISABILITA, valore=True, span=span, sorgente="testo")]
    return []


# -- employment status: nessun ripiego oggi in produzione (A10) -------------

#: `_profile_from_slots` (respond.py) oggi passa `slots.employment_status`
#: cosi' com'e': se il modello non lo riempie resta None anche quando il
#: testo lo dice esplicitamente («sono disoccupato»). Stesso idioma dei
#: marcatori di sesso/figlio-disabile: sostringa esplicita, nessuna inferenza.
_EMPLOYMENT_MARKERS: dict[str, tuple[str, ...]] = {
    "disoccupato": ("disoccupato", "disoccupata", "in cerca di lavoro", "senza lavoro"),
    "pensionato": ("pensionato", "pensionata"),
    "occupato": ("occupato", "occupata", "ho un lavoro"),
}


def _riconosci_employment(testo: str) -> list[Filtro]:
    haystack = testo.casefold()
    for stato, marcatori in _EMPLOYMENT_MARKERS.items():
        for marcatore in marcatori:
            inizio = haystack.find(marcatore)
            if inizio < 0:
                continue
            fine = inizio + len(marcatore)
            if _negato_prima_di(testo, inizio):
                continue
            span = Span(inizio=inizio, fine=fine, testo=testo[inizio:fine])
            return [Filtro(chiave=FiltroChiave.EMPLOYMENT_STATUS, valore=stato, span=span, sorgente="testo")]
    return []


# -- comune: wrapper del resolver esistente, non una reinvenzione (A3) ------

#: Stessa idea di `_norm` in sonda_live.py, ridotta al minimo che serve qui:
#: trovare nel testo originale la finestra di parole che, appiattita, coincide
#: col nome del comune gia' risolto da `_comuni_candidati` — per ricostruirne
#: lo span verbatim, che il resolver di produzione non restituisce.
def _appiattita(testo: str) -> str:
    piatta = unicodedata.normalize("NFKD", testo)
    piatta = "".join(c for c in piatta if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", piatta.lower())


_MASSIMA_FINESTRA_TOPONIMO = 4


def _span_comune(testo: str, nome_comune: str) -> Span | None:
    bersaglio = _appiattita(nome_comune)
    token = list(re.finditer(r"\S+", testo))
    for lunghezza in range(1, _MASSIMA_FINESTRA_TOPONIMO + 1):
        for i in range(len(token) - lunghezza + 1):
            finestra = token[i : i + lunghezza]
            pezzo = _appiattita(" ".join(t.group() for t in finestra))
            if pezzo and pezzo == bersaglio:
                inizio, fine = finestra[0].start(), finestra[-1].end()
                return Span(inizio=inizio, fine=fine, testo=testo[inizio:fine])
    return None


def _riconosci_comune(testo: str) -> list[Filtro]:
    """Wrappa `_comuni_candidati` (respond.py): stesso resolver di
    produzione, stessa stoplist su connettivi/toponimi-spuri (A3), qui
    esposto con lo span che serve al contratto D-06.

    Un solo candidato -> filtro con lo span verbatim. Zero o piu' di uno
    (ambiguita' reale, es. «pergine») -> nessun filtro: scegliere fra piu'
    comuni non e' un'evidenza testuale univoca, e' un'indovinata (A12/D-54).
    """
    candidati = _comuni_candidati(testo)
    if len(candidati) != 1:
        return []
    comune = candidati[0]
    span = _span_comune(testo, comune.nome)
    if span is None:
        return []  # nessuna sottostringa verbatim ricostruibile: A1, non si emette
    if _negato_prima_di(testo, span.inizio):
        return []
    return [Filtro(chiave=FiltroChiave.COMUNE, valore=comune.codice_istat, span=span, sorgente="testo")]


# -- tema (bandi): riusa `_estrai_tema`, ne verifica la contiguita' ---------


def _riconosci_tema(testo: str) -> list[Filtro]:
    """Riusa `_estrai_tema` (respond.py) per il valore, poi verifica che sia
    una sottostringa contigua del testo originale. `_estrai_tema` filtra
    parole non-contigue (stopword rimosse in mezzo): se il residuo non torna
    a essere una frase verbatim, niente span possibile -> niente filtro
    (A1/A12), anche se un tema "concettuale" esisterebbe.
    """
    tema = _estrai_tema(testo)
    if not tema:
        return []
    haystack = testo.lower()
    inizio = haystack.find(tema)
    if inizio < 0:
        return []
    fine = inizio + len(tema)
    if _negato_prima_di(testo, inizio):
        return []
    span = Span(inizio=inizio, fine=fine, testo=testo[inizio:fine])
    return [Filtro(chiave=FiltroChiave.TEMA, valore=testo[inizio:fine], span=span, sorgente="testo")]


# -- entrypoint ----------------------------------------------------------------

_RICONOSCITORI = (
    _riconosci_eta,
    _riconosci_isee,
    _riconosci_nucleo,
    _riconosci_figli_minori,
    _riconosci_disabilita,
    _riconosci_employment,
    _riconosci_comune,
    _riconosci_tema,
)


def riconosci_filtri(testo: str) -> list[Filtro]:
    """I filtri civici attivi riconosciuti in `testo`, con span di provenienza.

    Deterministico, catalogo-dati (A4/A11): aggiungere uno slot e' aggiungere
    una funzione alla tupla `_RICONOSCITORI`, non riscrivere questa funzione.
    Ogni sotto-riconoscitore e' isolato: se uno fallisce (es. un bug futuro in
    un nuovo pattern), gli altri restano operativi — un errore di parsing non
    deve azzerare l'intero profilo del cittadino (error handling reale, non
    un `except: pass`).

    Le negazioni sono gia' state filtrate via da ogni singolo riconoscitore
    (A2): questa lista contiene solo filtri ATTIVI.
    """
    if not testo:
        return []
    filtri: list[Filtro] = []
    for riconosci in _RICONOSCITORI:
        try:
            filtri.extend(riconosci(testo))
        except Exception:
            logger.warning("riconoscitore %s fallito su input libero", riconosci.__name__, exc_info=True)
    return filtri


# -- accumulo multi-turno (ciclo 12/A1) ----------------------------------------


def negazioni_esplicite(testo: str) -> set[FiltroChiave]:
    """Chiavi la cui evidenza testuale e' presente in `testo` ma negata.

    Riusa i pattern e `_negato_prima_di` degli stessi riconoscitori (nessun
    pattern nuovo, nessuna inferenza in piu'): un match che sarebbe un filtro
    attivo se non fosse negato conta come negazione ESPLICITA di quella
    chiave. Serve ad `accumula_filtri` per far cadere un filtro accumulato da
    un turno precedente quando il cittadino lo ritratta ("sono disabile" e
    poi, in un turno successivo, "non sono disabile") — mai per inventare una
    negazione su una chiave che il testo non nomina affatto (D-03).
    """
    if not testo:
        return set()
    chiavi: set[FiltroChiave] = set()
    for match in _ETA_RE.finditer(testo):
        if _negato_prima_di(testo, match.start()):
            chiavi.add(FiltroChiave.ETA)
    for match in _NUCLEO_RE.finditer(testo):
        if _negato_prima_di(testo, match.start()):
            chiavi.add(FiltroChiave.NUCLEO_FAMILIARE)
    for match in (*_FIGLI_MINORI_RE.finditer(testo), *_BAMBINO_BIMBO_RE.finditer(testo)):
        if _negato_prima_di(testo, match.start()):
            chiavi.add(FiltroChiave.FIGLI_MINORI)
    for match in _DISABILITA_RE.finditer(testo):
        if not _negato_prima_di(testo, match.start()):
            continue
        # Stessa distinzione self/figlio di `_riconosci_disabilita`: una
        # negazione su "mio figlio disabile" non deve far cadere una
        # DISABILITA (self) accumulata da un turno precedente, e viceversa.
        inizio_clausola, fine_clausola = _confini_clausola(testo, match.start())
        clausola = testo[inizio_clausola:fine_clausola]
        rel_match_start = match.start() - inizio_clausola
        figlio_match = _ultimo_match_prima_di(_SOSTANTIVO_FIGLIO_RE, clausola, rel_match_start)
        self_match = _ultimo_match_prima_di(_SELF_DISABILITA_RE, clausola, rel_match_start)
        if figlio_match is not None and (self_match is None or figlio_match.start() > self_match.start()):
            chiavi.add(FiltroChiave.DISABILITA_NUCLEO)
        else:
            chiavi.add(FiltroChiave.DISABILITA)
    return chiavi


def accumula_filtri(
    storia: list[str],
    message: str,
    filtri_esclusi: frozenset[FiltroChiave] | None = None,
) -> dict[FiltroChiave, Filtro]:
    """Filtri civici accumulati sull'intera conversazione (ciclo 12/A1).

    Prima `riconosci_filtri` girava solo sul messaggio corrente: un filtro
    dichiarato due turni fa ("ho 2 figli minorenni") spariva dal profilo alla
    prima domanda neutra successiva ("e per la mensa?"), perche' nessuno lo
    riportava — il client accumulava lato sidebar, il motore no.

    Qui si rilegge `riconosci_filtri` — stessa funzione, deterministica,
    nessuna inferenza nuova (D-03) — su ogni turno del cittadino in ordine
    (`storia` poi `message`), e l'ultimo valore per chiave vince. Una
    dichiarazione vale solo perche' un `riconosci_filtri` l'ha gia' letta in
    quel turno: qui non si indovina nulla di nuovo.

    Una negazione esplicita in un turno successivo (`negazioni_esplicite`) fa
    cadere la chiave accumulata, cosi' una ritrattazione vince sul turno che
    l'ha precede.

    `filtri_esclusi` (dal client, ciclo11/A8) vince per ultimo e sempre: una
    chiave che il cittadino ha rimosso con la "×" non deve risorgere solo
    perche' un turno precedente la conteneva.
    """
    esclusi = filtri_esclusi or frozenset()
    accumulati: dict[FiltroChiave, Filtro] = {}
    for turno in (*storia, message):
        for chiave in negazioni_esplicite(turno):
            accumulati.pop(chiave, None)
        for filtro in riconosci_filtri(turno):
            accumulati[filtro.chiave] = filtro
    for chiave in esclusi:
        accumulati.pop(chiave, None)
    return accumulati


def dichiarazione_figli_senza_numero(testo: str) -> bool:
    """Vero se `testo` dichiara figli ma nessun riconoscitore ha prodotto
    FIGLI_MINORI (ne' numero, ne' eta', ne' "minorenni/bambini/bimbi").

    Serve a chi deve decidere quando chiedere "quanti, che eta'?" invece di
    procedere con un profilo a meta' (B1). Negazione ("non ho figli") ->
    falso: non e' una dichiarazione da completare, e' la sua assenza.
    """
    if not testo:
        return False
    match = _SOSTANTIVO_FIGLIO_RE.search(testo)
    if match is None:
        return False
    if _negato_prima_di(testo, match.start()):
        return False
    ha_figli_minori = any(f.chiave == FiltroChiave.FIGLI_MINORI for f in riconosci_filtri(testo))
    return not ha_figli_minori
