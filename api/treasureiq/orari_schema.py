"""Normalizzazione deterministica di un orario di sportello in uno schema.

Cosa aggiunge, e perché è un modulo a sé. `censimento.estrai_orari_da_testo`
riconosce un orario e ne restituisce una *citazione verbatim*: onesta e
ricontrollabile, ma cieca a due cose che i portali comunali scrivono di
continuo — i giorni abbreviati («Lun-Mar-Mer-Gio-Ven-Sab 09.00-12.00», tipico
di comweb/Aglié) e la *forma* dell'orario (quali giorni, quali fasce). Questo
modulo aggiunge entrambe senza toccare il censimento: è la fase «normalizza»
di TIQ (legge → normalizza → risponde), tenuta separata dalla misura
nazionale così che allargarne il riconoscimento non muova un solo numero dello
storico.

Confine con D-07 ([[verbalizzatore-corrompe-cifre]]). Le cifre non si toccano
mai: i token orari (`09.00`, `12:30`) sono copiati come sottostringhe
byte-identiche dalla pagina; si normalizza solo l'etichetta del giorno e il
layout. `testo_grezzo` conserva la citazione verbatim come fonte
ricontrollabile — lo schema è la forma pulita, non la sostituisce come prova.

Puro: nessuna rete, nessuno stato. Dato del testo (o dell'HTML) torna uno
schema o `None`. Non solleva mai su input malformato.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from treasureiq.ingest.wp_comuni import strip_html

#: Indice canonico 0..6 (lunedì..domenica). L'ordine è quello con cui si
#: rende un intervallo: «Lun–Ven» ha senso solo se lunedì viene prima.
_ETICHETTA_BREVE = ("Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom")
_ETICHETTA_PIENA = (
    "Lunedì",
    "Martedì",
    "Mercoledì",
    "Giovedì",
    "Venerdì",
    "Sabato",
    "Domenica",
)

#: Un token-giorno: nome intero O abbreviazione di tre lettere. I nomi interi
#: vengono prima nell'alternanza così che «martedì» agganci l'intero e non si
#: fermi a «mar». Il `\b` a valle impedisce che «mar» prenda «mare» o «marzo».
_GIORNO = (
    r"luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica"
    r"|lun|mar|mer|gio|ven|sab|dom"
)

#: Un'ora scritta come HH.MM o HH:MM. Nessuna forma «9-12» senza minuti: è
#: indistinguibile da un intervallo di prezzi o di numeri, e prenderla per un
#: orario è esattamente il modo di sbagliare che il censimento evita.
_ORA = r"\d{1,2}[:.]\d{2}"

#: Tokenizza il testo in giorni e ore, in ordine di comparsa. Il `\b` su
#: entrambi i lati del giorno tiene fuori le sottostringhe dentro altre parole.
_TOKEN_RE = re.compile(rf"\b(?P<g>{_GIORNO})\b|(?P<o>{_ORA})", re.IGNORECASE)

#: Massimo di caratteri fra l'ultimo giorno e la prima ora di una riga. Oltre,
#: non sono la stessa cosa: un giorno in un menù e un'ora nel footer non fanno
#: un orario. Stesso spirito del `_SALTO_MASSIMO` del censimento.
_GAP_GIORNO_ORA = 60

#: Massimo fra due ore della stessa riga (due turni: «9-13 e 14-18»).
_GAP_TRA_ORE = 40

#: Oltre questo salto, dopo una riga chiusa, un nuovo giorno apre una sezione
#: diversa (un altro ufficio, un piè di pagina): la lettura si ferma.
_GAP_TRA_RIGHE = 220

#: Tetto sui caratteri esaminati, gemello di `censimento.MAX_CARATTERI_PAGINA`.
_MAX_CARATTERI = 60_000


class Fascia(BaseModel):
    """Una fascia oraria. `chiusura is None` = la pagina dà solo l'apertura
    (degrado onesto): mostrare un orario di chiusura inventato è peggio."""

    apertura: str
    chiusura: str | None = None


class RigaOrario(BaseModel):
    """Un gruppo di giorni con le stesse fasce. `giorni` sono indici canonici
    0..6; `etichetta` è la loro resa leggibile (range o lista)."""

    giorni: list[int]
    etichetta: str
    fasce: list[Fascia]


class OrarioSettimanale(BaseModel):
    """Lo schema normalizzato di un orario, con la sua fonte verbatim.

    `reso` è la forma pulita da mostrare; `testo_grezzo` è la citazione
    verbatim dalla pagina, tenuta come prova ricontrollabile — mai buttata via
    a favore della forma normalizzata.
    """

    righe: list[RigaOrario]
    testo_grezzo: str
    reso: str


def _indice_giorno(token: str) -> int:
    """L'indice canonico 0..6 di un token-giorno, intero o abbreviato.

    Le prime tre lettere bastano a distinguerli tutti (lun/mar/mer/gio/ven/
    sab/dom sono uniche), e valgono sia per l'abbreviazione sia per il nome
    intero.
    """
    return _PREFISSO_INDICE[token.lower()[:3]]


_PREFISSO_INDICE = {"lun": 0, "mar": 1, "mer": 2, "gio": 3, "ven": 4, "sab": 5, "dom": 6}


def _sep_e_solo_trattino(testo: str) -> bool:
    """Il testo fra due giorni è un trattino (con spazi), non una virgola/«e».

    Distingue «Lun-Ven» (da lunedì A venerdì, un intervallo) da «Lun, Ven» o
    «Lun e Ven» (due giorni sciolti).
    """
    return re.fullmatch(r"\s*[-–—]\s*", testo) is not None


def _giorni_di_riga(token_giorni: list[re.Match[str]], testo: str) -> list[int]:
    """Gli indici canonici dei giorni di una riga.

    Due giorni uniti da un solo trattino = intervallo (min..max): «Lun-Ven» →
    lun,mar,mer,gio,ven. Tre o più giorni concatenati = lista letterale di
    quei giorni (anche se separati da trattini, come nel comweb
    «Lun-Mar-Mer-Gio-Ven-Sab»): si prendono esattamente quelli, senza
    espandere. Così «Lun-Mer-Ven» resta lun,mer,ven e non diventa lun..ven.
    """
    indici = [_indice_giorno(m.group()) for m in token_giorni]
    if len(indici) == 2:
        fra = testo[token_giorni[0].end() : token_giorni[1].start()]
        if _sep_e_solo_trattino(fra):
            passo = 1 if indici[1] >= indici[0] else -1
            return list(range(indici[0], indici[1] + passo, passo))
    return sorted(dict.fromkeys(indici))


def _rendi_giorni(indici: list[int]) -> str:
    """L'etichetta leggibile di un insieme di giorni.

    Un solo giorno → nome intero («Martedì»). Una corsa contigua di due o più
    → intervallo breve («Lun–Sab»). Insieme sparso → lista breve («Lun, Mer,
    Ven»).
    """
    ordinati = sorted(dict.fromkeys(indici))
    if len(ordinati) == 1:
        return _ETICHETTA_PIENA[ordinati[0]]
    contigui = ordinati == list(range(ordinati[0], ordinati[-1] + 1))
    if contigui:
        return f"{_ETICHETTA_BREVE[ordinati[0]]}–{_ETICHETTA_BREVE[ordinati[-1]]}"
    return ", ".join(_ETICHETTA_BREVE[i] for i in ordinati)


def _fasce_da_ore(ore: list[str]) -> list[Fascia]:
    """Accoppia le ore in fasce apertura-chiusura, in ordine.

    Numero dispari di ore → l'ultima è un'apertura senza chiusura (onesto):
    accoppiarla con l'apertura del turno dopo inventerebbe una fascia che la
    pagina non dice.
    """
    fasce: list[Fascia] = []
    for i in range(0, len(ore), 2):
        chiusura = ore[i + 1] if i + 1 < len(ore) else None
        fasce.append(Fascia(apertura=ore[i], chiusura=chiusura))
    return fasce


def _rendi_riga(riga: RigaOrario) -> str:
    fasce = " e ".join(
        f"{f.apertura}–{f.chiusura}" if f.chiusura else f.apertura for f in riga.fasce
    )
    return f"{riga.etichetta}: {fasce}"


def estrai_orario_strutturato(html: str) -> OrarioSettimanale | None:
    """Lo schema normalizzato dell'orario in una pagina, o `None`.

    Accetta l'HTML grezzo (lo appiattisce come `estrai_orari_da_testo`), trova
    la prima sequenza plausibile di giorni+ore, la struttura in righe e la
    rende. `None` se non trova nessun orario. Non solleva mai.
    """
    testo = re.sub(r"\s+", " ", strip_html(html)[:_MAX_CARATTERI])
    token = list(_TOKEN_RE.finditer(testo))
    if not token:
        return None

    righe: list[RigaOrario] = []
    inizio_span: int | None = None
    fine_span = 0
    i = 0
    n = len(token)
    while i < n:
        # Una riga: uno o più giorni consecutivi, poi una o più ore vicine.
        if token[i].lastgroup != "g":
            i += 1
            continue
        giorni_riga = [token[i]]
        i += 1
        while i < n and token[i].lastgroup == "g":
            giorni_riga.append(token[i])
            i += 1
        # Le ore devono seguire i giorni, vicine: altrimenti non è una riga.
        if i >= n or token[i].lastgroup != "o":
            continue
        if token[i].start() - giorni_riga[-1].end() > _GAP_GIORNO_ORA:
            continue
        ore_riga = [token[i].group()]
        ultima_fine = token[i].end()
        i += 1
        while i < n and token[i].lastgroup == "o" and token[i].start() - ultima_fine <= _GAP_TRA_ORE:
            ore_riga.append(token[i].group())
            ultima_fine = token[i].end()
            i += 1

        if righe and giorni_riga[0].start() - fine_span > _GAP_TRA_RIGHE:
            break  # sezione nuova, non lo stesso orario

        indici = _giorni_di_riga(giorni_riga, testo)
        riga = RigaOrario(
            giorni=indici,
            etichetta=_rendi_giorni(indici),
            fasce=_fasce_da_ore(ore_riga),
        )
        righe.append(riga)
        if inizio_span is None:
            inizio_span = giorni_riga[0].start()
        fine_span = ultima_fine

    if not righe or inizio_span is None:
        return None

    testo_grezzo = testo[inizio_span:fine_span].strip()
    reso = " · ".join(_rendi_riga(r) for r in righe)
    return OrarioSettimanale(righe=righe, testo_grezzo=testo_grezzo, reso=reso)
