"""Il gradino 2: leggere il portale di un comune che non abbiamo mai ingerito.

D-32 emenda D-28. La regola era "nessuna rete mentre un cittadino aspetta", e
per i comuni di cui teniamo i dati resta intatta: quelli si rispondono dal
seed, senza toccare niente. Ma per un comune fuori copertura la regola
produceva un rifiuto e basta — e un rifiuto è la risposta giusta solo finché
non esiste una risposta migliore.

Una ce n'è, ed è più forte di una ricerca sul web: il portale del comune lo
sappiamo già, perché ISTAT dice quali comuni esistono e IPA dove stanno online
(F-7: 7.867 su 7.896). Se quel portale parla una piattaforma che conosciamo,
l'orario lo leggiamo **dal sito del comune stesso**, verbatim, adesso. Non è
un link trovato da un motore di ricerca: è la fonte, citata.

Tre confini, tutti stretti.

*Solo il rail INFORMAZIONE.* Un dato letto ora non entra mai in un verdetto di
eleggibilità: sarebbe D-01 violato per comodità. Le agevolazioni di un comune
fuori copertura restano un "non posso verificare".

*Solo fuori copertura.* Se il comune ha un ente in `enti.json` si risponde da
lì. Questo modulo non è una scorciatoia per saltare l'ingestione.

*Il primo cittadino paga, gli altri no.* L'esito finisce in cache su
`data-live/` (D-33) — scrivibile, fuori da git, separato dai dati curati, che
restano montati in sola lettura. Niente di ciò che si legge qui viene mai
promosso a dato del progetto (D-34).
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from treasureiq.ingest.censimento import (
    EsitoCensimento,
    Indirizzabilita,
    RecuperabilitaOrari,
    _Sonda,
    censisci_comune,
)
from treasureiq.integration import DATA_DIR

logger = logging.getLogger(__name__)

COMUNI_ISTAT_PATH = DATA_DIR / "comuni-istat.json"

#: Dati acquisiti a runtime. Mount separato e scrivibile: `DATA_DIR` è
#: montata in sola lettura apposta, perché l'API non deve poter riscrivere
#: uno snapshot curato nemmeno per sbaglio (D-33).
LIVE_DIR = Path(os.environ.get("TREASUREIQ_LIVE_DIR", "/live"))

#: Quanto resta valido un orario letto dal vivo. Gli orari di sportello
#: cambiano di rado, ma cambiano: una cache eterna trasformerebbe una lettura
#: fresca in un dato vecchio che continua a presentarsi come fresco.
GIORNI_VALIDITA = 14


class ComuneNoto(BaseModel):
    """Un comune italiano come lo conoscono ISTAT e IPA insieme."""

    codice_istat: str
    nome: str
    provincia: str
    regione: str
    sito: str | None


#: Parole che precedono un toponimo senza esserne separabili. Senza questa
#: guardia "San Marino" risolveva a Marino (RM) — e un cittadino di uno stato
#: estero si vedeva rispondere con i dati di un comune dei Castelli Romani.
#: Stesso ruolo di `_TOPONYM_PREFIXES` in `chat/respond.py`.
_PREFISSI_TOPONIMO = frozenset(
    {"san", "santa", "santo", "sant", "borgo", "villa", "castel", "castello", "monte", "rocca"}
)

#: Parole di servizio dentro i nomi ufficiali. ISTAT scrive "Reggio
#: nell'Emilia", un cittadino scrive "Reggio Emilia": senza toglierle il
#: comune non si riconosce, e non riconoscerlo qui significa rifiutare una
#: domanda perfettamente chiara.
_PAROLE_VUOTE = frozenset({"di", "del", "della", "dei", "delle", "in", "nel", "nell", "sul",
                           "sull", "su", "a", "al", "alla", "d", "l", "e", "con"})


#: Come si nomina un comune parlando: "comune di Roma", "città di Torino".
#: Nessun nome nell'elenco ISTAT contiene queste parole, quindi vanno tolte
#: dalla query prima di cercare, o la ricerca non trova il caso più comune.
_PREFISSO_COMUNE = re.compile(
    r"^\s*(?:il\s+|la\s+)?(?:comune|citt[àa]|municipio|paese)\s+(?:di\s+|d['’]\s*)?",
    re.IGNORECASE,
)


def _norm(testo: str) -> str:
    """Chiave di confronto: senza accenti, senza punteggiatura, minuscola."""
    piatto = unicodedata.normalize("NFKD", testo)
    piatto = "".join(c for c in piatto if not unicodedata.combining(c))
    piatto = re.sub(r"[^\w\s]", " ", piatto.lower())
    return re.sub(r"\s+", " ", piatto).strip()


@lru_cache(maxsize=1)
def _indice() -> dict[str, list[ComuneNoto]]:
    """I comuni italiani indicizzati per nome normalizzato.

    Lista e non singolo record perché gli omonimi esistono davvero — Castro
    sta in Puglia e in Lombardia, San Teodoro in Sardegna e in Sicilia. Un
    dizionario nome→comune ne farebbe sparire uno in silenzio, e chi ci vive
    riceverebbe le informazioni dell'altro.
    """
    if not COMUNI_ISTAT_PATH.exists():
        logger.warning("comuni-istat.json assente: la sonda live è disattivata")
        return {}
    grezzo = json.loads(COMUNI_ISTAT_PATH.read_text("utf-8"))
    indice: dict[str, list[ComuneNoto]] = {}
    for riga in grezzo:
        comune = ComuneNoto.model_validate(riga)
        for chiave in {_norm(comune.nome), _senza_parole_vuote(comune.nome)}:
            if chiave:
                indice.setdefault(chiave, []).append(comune)
    return indice


def _senza_parole_vuote(testo: str) -> str:
    """La forma in cui un cittadino scrive un nome ufficiale."""
    return " ".join(t for t in _norm(testo).split() if t not in _PAROLE_VUOTE)


def cerca_comuni(query: str, *, limite: int = 8) -> list[ComuneNoto]:
    """I comuni italiani che assomigliano a quello che il cittadino ha scritto.

    Serve a far scegliere invece di indovinare. Chi scrive "Roma" può
    intendere Roma, e chi scrive "Castro" deve poter dire quale dei due: una
    lista da cui si sceglie produce un `codice_istat` certo, che è l'unica
    forma in cui questo dato non causa equivoci più avanti.

    Ordinamento per quanto la corrispondenza è stretta — esatta, poi per
    inizio, poi per contenuto — e a parità in ordine alfabetico, così la
    stessa query dà sempre la stessa lista: una tendina che cambia ordine fra
    due battute è una tendina in cui si clicca la riga sbagliata.
    """
    # "comune di Roma" è il modo normale di nominare un comune, e senza questo
    # non trovava niente: nessun nome nell'elenco contiene la parola "comune".
    ripulita = _PREFISSO_COMUNE.sub("", query.strip())
    chiave = _norm(ripulita)
    if len(chiave) < 2:
        return []
    compatta = _senza_parole_vuote(ripulita)

    trovati: dict[str, tuple[int, str, ComuneNoto]] = {}
    for comune in _tutti():
        nome = _norm(comune.nome)
        senza = _senza_parole_vuote(comune.nome)
        if chiave in (nome, senza) or compatta in (nome, senza):
            rango = 0
        elif nome.startswith(chiave) or senza.startswith(chiave):
            rango = 1
        elif chiave in nome or chiave in senza:
            rango = 2
        else:
            continue
        precedente = trovati.get(comune.codice_istat)
        if precedente is None or rango < precedente[0]:
            trovati[comune.codice_istat] = (rango, nome, comune)

    ordinati = sorted(trovati.values(), key=lambda t: (t[0], t[1]))
    return [comune for _, _, comune in ordinati[:limite]]


@lru_cache(maxsize=1)
def _tutti() -> list[ComuneNoto]:
    """Tutti i comuni, in ordine di codice: la base della ricerca testuale."""
    visti: dict[str, ComuneNoto] = {}
    for gruppo in _indice().values():
        for comune in gruppo:
            visti.setdefault(comune.codice_istat, comune)
    return sorted(visti.values(), key=lambda c: c.codice_istat)


def comune_per_codice(codice_istat: str | None) -> ComuneNoto | None:
    """Il comune scelto dal cittadino, per codice.

    È la via che non può sbagliare: un codice ISTAT non è ambiguo, non ha
    omonimi e non dipende da come qualcuno ha scritto il nome. Quando c'è
    questo, non si guarda nessun accenno testuale.
    """
    if not codice_istat:
        return None
    return next((c for c in _tutti() if c.codice_istat == codice_istat), None)


def risolvi_comune(hint: str | None) -> ComuneNoto | None:
    """Il comune italiano che il cittadino ha nominato, se è uno solo.

    Confronto a token interi sul nome completo, come
    `_resolve_informazione_ente`: un `in` su stringa farebbe scattare "Marino"
    dentro "San Marino". Restituisce `None` sia quando non riconosce niente
    sia quando riconosce più di un comune con quel nome: fra due omonimi non
    si tira a indovinare, si chiede.
    """
    if not hint or not hint.strip():
        return None
    tokens = _norm(hint).split()
    if not tokens:
        return None

    indice = _indice()
    trovati: list[ComuneNoto] = []
    # Sequenze più lunghe per prime: "Reggio nell'Emilia" prima di "Reggio".
    for lunghezza in range(min(len(tokens), 4), 0, -1):
        for inizio in range(len(tokens) - lunghezza + 1):
            chiave = " ".join(tokens[inizio : inizio + lunghezza])
            if chiave not in indice:
                continue
            if inizio > 0 and tokens[inizio - 1] in _PREFISSI_TOPONIMO:
                # "San Marino" non è Marino. Il token che precede fa parte del
                # toponimo, quindi questa non è una corrispondenza: è il
                # troncamento di un nome più lungo che non conosciamo.
                continue
            trovati = indice[chiave]
            break
        if trovati:
            break

    # Un solo comune, oppure niente. Fra due omonimi — Castro in Puglia e in
    # Lombardia — la risposta giusta è chiedere quale, non sceglierne uno.
    unici = {c.codice_istat: c for c in trovati}
    return next(iter(unici.values())) if len(unici) == 1 else None


class OrariLive(BaseModel):
    """Cosa il portale di un comune ha detto di sé, e quando gliel'ho chiesto."""

    codice_istat: str
    nome: str
    sito: str | None
    #: Dal censimento, così la chat e il censimento non possono divergere sul
    #: significato di "raggiungibile" o "leggibile".
    indirizzabilita: Indirizzabilita
    recuperabilita: RecuperabilitaOrari
    ufficio: str | None = None
    ufficio_url: str | None = None
    #: Verbatim dalla pagina del comune. È la sola cosa che autorizza a
    #: mostrare un orario: senza citazione non si scrive un orario.
    citazione: str | None = None
    letto_il: str

    @property
    def ha_orari(self) -> bool:
        return bool(self.citazione)


def _percorso_cache(codice_istat: str) -> Path:
    return LIVE_DIR / "orari-urp" / f"{codice_istat}.json"


def _da_cache(codice_istat: str) -> OrariLive | None:
    percorso = _percorso_cache(codice_istat)
    if not percorso.exists():
        return None
    try:
        voce = OrariLive.model_validate_json(percorso.read_text("utf-8"))
    except Exception:  # noqa: BLE001 — una cache illeggibile è una cache assente
        logger.warning("voce di cache illeggibile: %s", percorso)
        return None
    eta = datetime.now(timezone.utc) - datetime.fromisoformat(voce.letto_il)
    return voce if eta.days < GIORNI_VALIDITA else None


def _in_cache(voce: OrariLive) -> None:
    """Scrittura atomica: un lettore concorrente vede la voce vecchia o la
    nuova, mai mezza voce."""
    percorso = _percorso_cache(voce.codice_istat)
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(voce.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        # Il mount live può mancare (sviluppo locale, test): la risposta al
        # cittadino è già pronta e non deve dipendere da questo.
        logger.warning("cache live non scrivibile (%s): %s", percorso, exc)


def leggi_orari_urp(comune: ComuneNoto, *, usa_cache: bool = True) -> OrariLive | None:
    """Legge dal portale del comune l'orario del suo URP. Non solleva mai.

    `None` significa "non c'è un sito noto da interrogare", che è diverso da
    un esito con `recuperabilita=ASSENTE` — lì il portale ha risposto e non
    aveva l'orario. Chi chiama deve poter distinguere le due cose (D-35).
    """
    if not comune.sito:
        return None
    if usa_cache:
        voce = _da_cache(comune.codice_istat)
        if voce is not None:
            return voce

    esito: EsitoCensimento = censisci_comune(
        codice_istat=comune.codice_istat,
        nome=comune.nome,
        sito=comune.sito,
        # Corto: dall'altra parte c'è un cittadino che aspetta, non un batch.
        timeout=6.0,
    )
    voce = OrariLive(
        codice_istat=esito.codice_istat,
        nome=esito.nome,
        sito=esito.sito,
        indirizzabilita=esito.indirizzabilita,
        recuperabilita=esito.recuperabilita,
        ufficio=esito.ufficio_scelto,
        ufficio_url=esito.ufficio_url,
        citazione=esito.citazione_orari,
        letto_il=datetime.now(timezone.utc).isoformat(),
    )
    # Anche un esito negativo va in cache: sapere che quel portale non
    # pubblica l'orario è una misura, e ripeterla a ogni domanda costerebbe
    # al comune senza aggiungere niente.
    _in_cache(voce)
    return voce


def main(argv: list[str] | None = None) -> int:
    """CLI: sonda dei comuni ora, così la cache è calda quando serve.

    Una domanda su un comune mai sondato paga la rete in diretta — due o sei
    secondi davanti a chi guarda. Sondarli prima sposta quell'attesa fuori
    dalla demo, senza cambiare di una virgola quello che il sistema risponde:
    la cache contiene la stessa lettura che avrebbe fatto sul momento.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.sonda_live",
        description=(
            "Legge ora l'orario URP dei comuni indicati e mette l'esito in "
            "cache su data-live/, così la prima domanda non aspetta la rete."
        ),
    )
    parser.add_argument("comuni", nargs="+", help="Nomi di comuni, es. 'Arquata Scrivia'.")
    parser.add_argument(
        "--rileggi",
        action="store_true",
        help="Ignora la cache esistente e rilegge dai portali.",
    )
    args = parser.parse_args(argv)

    caldi = freddi = 0
    for nome in args.comuni:
        comune = risolvi_comune(nome)
        if comune is None:
            print(f"  ?  {nome}: nessun comune italiano riconosciuto con questo nome")
            freddi += 1
            continue
        letto = leggi_orari_urp(comune, usa_cache=not args.rileggi)
        if letto is None:
            print(f"  ?  {comune.nome}: nessun sito noto")
            freddi += 1
            continue
        segno = "OK" if letto.ha_orari else "--"
        print(f"  {segno} {comune.nome} [{letto.recuperabilita.value}]")
        if letto.citazione:
            print(f"       «{letto.citazione}»")
        caldi += 1

    print(f"\n{caldi} in cache, {freddi} non sondabili")
    return 0


# --- Numeri utili: recapiti URP letti dal vivo (D-32, mai verificati) --------

class ContattiUrp(BaseModel):
    """Recapiti del comune letti ADESSO dal portale, mai verificati.

    Non è un dato conservato né controllato contro una fonte ingerita: è ciò
    che il sito del comune espone in questo momento. La guardia sui numeri vale
    anche qui — un recapito letto storto è peggio di un link — quindi resta
    marcato «non verificato» a schermo, esattamente come le pagine live.
    """

    telefoni: list[str]
    email: list[str]
    pec: list[str]
    #: La pagina da cui vengono i recapiti, così il cittadino può controllarli
    #: alla fonte invece di fidarsi della nostra lettura.
    fonte: str | None = None

    @property
    def vuoto(self) -> bool:
        return not (self.telefoni or self.email or self.pec)


#: `href="tel:..."` e `href="mailto:..."` sono il segnale più preciso: un
#: recapito che il portale stesso ha marcato come tale, non una sequenza di
#: cifre pescata a caso dal testo.
_TEL_HREF = re.compile(r'href=["\']tel:\s*([+0-9().\s/-]{6,})["\']', re.IGNORECASE)
_MAIL_HREF = re.compile(r'href=["\']mailto:\s*([^"\'?>\s]+@[^"\'?>\s]+)', re.IGNORECASE)
#: Fisso italiano (prefisso 0) o cellulare (3xx), separatori vari. Ancorato ai
#: confini per non azzannare pezzi di partita IVA, CAP o codici catastali.
_TEL_TESTO = re.compile(r"(?<![\d./])(?:\+39[\s.]?)?0\d{1,3}[\s./-]?\d{5,8}(?![\d])")
_EMAIL_TESTO = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
#: Una email è PEC se il dominio lo dichiara. Vale la pena distinguerla: è il
#: canale con valore legale, e per un cittadino è spesso quello che conta.
_PEC_DOMINIO = re.compile(r"pec|postacert|legalmail|cert\.", re.IGNORECASE)


def _tel_valido(grezzo: str) -> bool:
    cifre = re.sub(r"\D", "", grezzo)
    return 6 <= len(cifre) <= 12


def _estrai_recapiti(html: str) -> tuple[list[str], list[str], list[str]]:
    """Da HTML grezzo a (telefoni, email, pec). Prima gli href dichiarati,
    testo grezzo solo come ripiego per non restare a mani vuote."""
    tel = [g.strip() for g in _TEL_HREF.findall(html) if _tel_valido(g)]
    email: list[str] = []
    pec: list[str] = []
    for m in _MAIL_HREF.findall(html):
        (pec if _PEC_DOMINIO.search(m) else email).append(m.strip())

    if not tel or (not email and not pec):
        # Togli i tag prima di leggere il testo: dentro attributi e <script>
        # ci sono numeri e stringhe che non sono recapiti.
        testo = re.sub(r"<[^>]+>", " ", html)
        if not tel:
            tel = [g.strip() for g in _TEL_TESTO.findall(testo) if _tel_valido(g)]
        if not email and not pec:
            for m in _EMAIL_TESTO.findall(testo):
                (pec if _PEC_DOMINIO.search(m) else email).append(m)
    return tel, email, pec


def _dedup(valori: list[str], tetto: int) -> list[str]:
    visti: set[str] = set()
    fuori: list[str] = []
    for v in valori:
        chiave = re.sub(r"\s+", "", v).lower()
        if chiave and chiave not in visti:
            visti.add(chiave)
            fuori.append(v)
        if len(fuori) >= tetto:
            break
    return fuori


def recupera_contatti(codice_istat: str | None) -> ContattiUrp | None:
    """Legge i recapiti URP dal portale del comune, ADESSO, senza verificarli.

    `None` se il comune non è noto o non ha un sito da leggere. Prova la home e
    poche pagine-contatti tipiche, e si ferma appena ha sia un telefono sia un
    recapito scritto — o dopo pochi tentativi — per non trasformare una domanda
    in una scansione del sito. Ogni errore di rete su una pagina è saltato: un
    portale lento non deve far fallire l'intera richiesta.
    """
    comune = comune_per_codice(codice_istat)
    if comune is None or not comune.sito:
        return None
    # Il registro tiene l'host nudo («www.comune.x.it»), senza schema: httpx
    # rifiuta un URL senza `https://`, quindi lo si antepone qui.
    base = comune.sito.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    # Home per prima (spesso il footer ha centralino + PEC), poi due sole
    # pagine-contatti tipiche: il tetto tiene il tempo di risposta sotto ~18s.
    candidati = [base, f"{base}/contatti", f"{base}/servizi/contatti"]

    tel: list[str] = []
    email: list[str] = []
    pec: list[str] = []
    fonte: str | None = None
    with _Sonda(timeout=6.0) as sonda:
        for url in candidati:
            try:
                resp = sonda.risposta(url)
            except Exception:  # noqa: BLE001 — un portale muto non è un errore nostro
                continue
            if resp.status_code != 200 or not resp.text:
                continue
            t, m, p = _estrai_recapiti(resp.text)
            if (t or m or p) and fonte is None:
                fonte = url
            tel += t
            email += m
            pec += p
            if tel and (email or pec):
                break

    return ContattiUrp(
        telefoni=_dedup(tel, 3),
        email=_dedup(email, 3),
        pec=_dedup(pec, 2),
        fonte=fonte,
    )


class SondaConnettore(BaseModel):
    """Indirizzabilita' AgID di un comune fuori copertura, misurata al volo.

    `indirizzabile` = il portale espone l'API uffici del modello AgID, cioe'
    il connettore potrebbe leggerlo. `uffici` e' quanti ne ha elencati l'API:
    un conteggio strutturale, non una spettanza."""

    codice_istat: str
    indirizzabile: bool
    uffici: int
    rest_base: str | None = None


def sonda_connettore(codice_istat: str | None) -> SondaConnettore | None:
    """A ricerca fatta su un comune non ingerito, dice se il connettore lo
    raggiungerebbe. Salta la sonda-orari (`leggi_pagina=False`): qui serve
    solo l'indirizzabilita', non gli orari, e ogni GET in meno e' latenza in
    meno sul turno. `censisci_comune` non solleva mai, ma il resto lo
    incapsuliamo lo stesso: una sonda muta non deve mai rompere la risposta."""
    comune = comune_per_codice(codice_istat)
    if comune is None or not comune.sito:
        return None
    try:
        esito = censisci_comune(
            codice_istat=comune.codice_istat,
            nome=comune.nome,
            sito=comune.sito,
            timeout=6.0,
            leggi_pagina=False,
        )
    except Exception:  # noqa: BLE001 — sonda muta, mai fatale per la risposta
        logger.warning("sonda connettore fallita per %s", codice_istat, exc_info=True)
        return None
    return SondaConnettore(
        codice_istat=comune.codice_istat,
        indirizzabile=esito.indirizzabilita == Indirizzabilita.API_UFFICI,
        uffici=esito.uffici_trovati or 0,
        rest_base=esito.rest_base,
    )


if __name__ == "__main__":
    raise SystemExit(main())
