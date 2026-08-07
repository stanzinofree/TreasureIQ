"""Il modello di contenuto AgID come interfaccia, e i fornitori come dialetti.

La scoperta che ha prodotto questo modulo: la scheda servizio di PeopleWeb
espone `A chi è rivolto`, `Come fare`, `Cosa serve`, `Tempi e scadenze` — le
stesse identiche voci che il tema WordPress Design Comuni tiene in campi
tipizzati. Due prodotti diversi, di due aziende diverse, scritti in due
linguaggi diversi, che dicono la stessa cosa con le stesse parole.

Quindi l'interfaccia da leggere non è il CMS: è il modello AgID. Un lettore
agganciato alle *sezioni* attraversa PeopleWeb, WordPress, Plone e Drupal,
mentre un connettore per prodotto ne attraversa uno solo e va riscritto sei
volte.

Ogni fornitore però lo declina a modo suo — chi con `<h4>`, chi con `<h3>`,
chi solo per metà. Da qui le due cose che questo modulo produce insieme al
contenuto:

*L'aderenza.* Quante sezioni del modello quel portale espone davvero. È una
misura del fornitore prima che del comune, ed è la ragione per cui vale la
pena calcolarla: dice a chi va chiesto conto, perché è il fornitore ad aver
scelto, non il comune.

Va però letta come media su più comuni, mai su una pagina sola: sotto
`/servizi` vivono anche pagine informative che il modello non ce l'hanno per
disegno, e misurare quelle fa sembrare inadempiente chi non lo è. Sul campo,
ComWeb misurato su una pagina sbagliata dava 0,10 e su ventitré comuni dà
0,70.

*L'impronta.* La forma strutturale su cui il lettore si è agganciato, ridotta
a un hash. Nessun fornitore pubblica un numero di versione; questo lo
sostituisce. Finché l'hash regge, la declinazione è quella. Quando cambia — di
solito su tutti i comuni di quel fornitore la stessa notte — sappiamo cosa si
sta per rompere e dove mettere le mani, prima che se ne accorga un cittadino.
"""

from __future__ import annotations

import hashlib
import html as libhtml
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

#: Fin dove leggiamo il corpo di una sezione. Le schede civiche sono prolisse
#: e la coda è quasi sempre navigazione: tenere tutto gonfierebbe lo storico
#: senza aggiungere un fatto.
CORPO_MASSIMO = 4_000


class SezioneAgid(str, Enum):
    """Le sezioni della scheda servizio, come le nomina il modello.

    L'ordine è quello del modello e conta: `impronta` lo usa per accorgersi
    che un fornitore ha rimescolato la pagina, non solo che ne ha persa una.
    """

    A_CHI_E_RIVOLTO = "a_chi_e_rivolto"
    DESCRIZIONE = "descrizione"
    COME_FARE = "come_fare"
    COSA_SERVE = "cosa_serve"
    COSA_SI_OTTIENE = "cosa_si_ottiene"
    TEMPI_E_SCADENZE = "tempi_e_scadenze"
    QUANTO_COSTA = "quanto_costa"
    ACCEDI_AL_SERVIZIO = "accedi_al_servizio"
    CONDIZIONI_DI_SERVIZIO = "condizioni_di_servizio"
    DOCUMENTI_E_ALLEGATI = "documenti_e_allegati"
    CONTATTI = "contatti"


#: Le sezioni che decidono se un cittadino può agire. `TEMPI_E_SCADENZE` sta
#: qui perché una scadenza mancante non si nota mai leggendo la pagina: la si
#: scopre quando il diritto è già decaduto.
SEZIONI_CRITICHE = frozenset(
    {
        SezioneAgid.A_CHI_E_RIVOLTO,
        SezioneAgid.COSA_SERVE,
        SezioneAgid.TEMPI_E_SCADENZE,
        SezioneAgid.COME_FARE,
    }
)

#: Etichette accettate per ogni sezione, già normalizzate. Le varianti non
#: sono ipotesi: sono come le scrivono i portali veri, plurali e accenti
#: compresi. Aggiungerne una è il modo giusto di far salire l'aderenza —
#: allargare invece il criterio di somiglianza la farebbe salire mentendo.
_ETICHETTE: dict[SezioneAgid, tuple[str, ...]] = {
    SezioneAgid.A_CHI_E_RIVOLTO: ("a chi e rivolto", "destinatari", "a chi si rivolge"),
    SezioneAgid.DESCRIZIONE: ("descrizione", "cos e", "di cosa si tratta"),
    SezioneAgid.COME_FARE: ("come fare", "come si fa", "procedura"),
    SezioneAgid.COSA_SERVE: ("cosa serve", "cosa serve per", "requisiti", "documenti necessari"),
    SezioneAgid.COSA_SI_OTTIENE: ("cosa si ottiene", "risultato", "output"),
    SezioneAgid.TEMPI_E_SCADENZE: ("tempi e scadenze", "tempi", "scadenze", "termini"),
    SezioneAgid.QUANTO_COSTA: ("quanto costa", "costi", "costo", "spese"),
    # `accedi servizio` senza articolo è il nome del box CMB2 nel tema Design
    # Comuni: gli identificatori di campo abbreviano dove la pagina no.
    SezioneAgid.ACCEDI_AL_SERVIZIO: (
        "accedi al servizio",
        "accedi servizio",
        "come accedere",
        "accesso al servizio",
    ),
    SezioneAgid.CONDIZIONI_DI_SERVIZIO: ("condizioni di servizio", "condizioni"),
    SezioneAgid.DOCUMENTI_E_ALLEGATI: ("documenti e allegati", "allegati", "documenti", "modulistica"),
    SezioneAgid.CONTATTI: ("contatti", "contatta", "ufficio responsabile"),
}


@dataclass(frozen=True)
class Declinazione:
    """Come un fornitore scrive il modello. Solo differenze di forma."""

    nome: str
    #: I livelli di intestazione da guardare. PeopleWeb usa `h4`, altri `h2`:
    #: guardarli tutti confonderebbe i titoli di pagina con le sezioni.
    livelli: tuple[str, ...] = ("h2", "h3", "h4")
    #: Etichette in più che questo fornitore usa e gli altri no.
    alias: dict[SezioneAgid, tuple[str, ...]] = field(default_factory=dict)


#: Le declinazioni note. `GENERICA` non è un ripiego: è ciò che si usa su un
#: portale mai visto, ed è anche il modo in cui un fornitore nuovo viene
#: misurato prima che qualcuno gli scriva una declinazione su misura.
GENERICA = Declinazione(nome="generica")
PEOPLEWEB = Declinazione(nome="peopleweb", livelli=("h4",))
COMWEB = Declinazione(nome="comweb", livelli=("h2", "h3"))
WP_DESIGN_COMUNI = Declinazione(nome="wp_design_comuni", livelli=("h2", "h3", "h4"))

#: MyPortal (Rete Civica Lepida e affini) nomina i campi `sys_<sezione>`.
PREFISSO_MYPORTAL = "sys_"

MYPORTAL = Declinazione(nome="myportal")

DECLINAZIONI: dict[str, Declinazione] = {
    "rete_civica_lepida": MYPORTAL,
    "peopleweb": PEOPLEWEB,
    "comweb": COMWEB,
    "wp_design_comuni": WP_DESIGN_COMUNI,
}


@dataclass
class SchedaAgid:
    """Una scheda servizio letta, con quanto se n'è potuto ricavare."""

    declinazione: str
    sezioni: dict[SezioneAgid, str]
    #: Le intestazioni trovate che non corrispondono a nessuna sezione nota.
    #: Non sono scarto: sono i candidati per l'etichetta che ci manca.
    non_riconosciute: list[str]
    #: Le sezioni che *esistono nello schema* del portale, riempite o no.
    #:
    #: Ha senso solo dove le sezioni sono campi tipizzati — cioè oggi solo sul
    #: tema WordPress Design Comuni. Leggendo intestazioni HTML la distinzione
    #: non esiste: una sezione senza testo è indistinguibile da una sezione
    #: che non c'è, e fingere di saperlo attribuirebbe al comune una colpa del
    #: fornitore o viceversa. `None` significa proprio questo: non si può dire.
    esposte: frozenset[SezioneAgid] | None = None

    @property
    def aderenza(self) -> float:
        """Quota di ciò che era disponibile e risulta effettivamente compilato.

        Il denominatore cambia con la fonte, ed è deliberato. Leggendo HTML
        non sappiamo cosa il fornitore *avrebbe* previsto, quindi si misura
        sul modello intero. Leggendo i campi tipizzati sappiamo esattamente
        quali box lo schema espone, e misurare lo stesso sul modello intero
        significherebbe punire un fornitore per ciò che la sua API non
        serializza: il tema Design Comuni pubblica due box su undici nel
        payload REST, e a denominatore fisso risultava ultimo proprio il
        fornitore più conforme di tutti.

        Perciò i due numeri **non vanno messi nella stessa classifica** senza
        guardare `base_misura`, ed è per questo che quel campo esiste.
        """
        disponibili = len(self.esposte) if self.esposte else len(SezioneAgid)
        return len(self.sezioni) / disponibili if disponibili else 0.0

    @property
    def base_misura(self) -> str:
        """Su cosa è calcolata l'aderenza: il modello intero o lo schema esposto."""
        return "schema_esposto" if self.esposte else "modello_intero"

    @property
    def critiche_mancanti(self) -> frozenset[SezioneAgid]:
        """Le sezioni senza cui un cittadino non può agire, e che non ci sono."""
        return frozenset(SEZIONI_CRITICHE - set(self.sezioni))

    @property
    def dichiarate_vuote(self) -> frozenset[SezioneAgid]:
        """Sezioni che il fornitore ha previsto e che il comune non ha riempito.

        È il numero su cui TreasureIQ è nato. Vale solo dove lo schema è
        leggibile: altrove resta vuoto, perché dedurlo sarebbe attribuire una
        colpa a caso fra chi ha costruito il portale e chi lo compila.
        """
        if self.esposte is None:
            return frozenset()
        return frozenset(self.esposte - set(self.sezioni))

    @property
    def impronta(self) -> str:
        """Hash della forma su cui il lettore si è agganciato.

        Sostituisce il numero di versione che nessun fornitore pubblica.
        Cambia quando cambiano le sezioni o il loro ordine — cioè quando la
        declinazione va rivista — e non cambia perché un comune ha riscritto
        il testo di una sezione, che non ci riguarda.
        """
        forma = "|".join(s.value for s in SezioneAgid if s in self.sezioni)
        return hashlib.sha256(f"{self.declinazione}::{forma}".encode()).hexdigest()[:12]


def _normalizza(testo: str) -> str:
    """Minuscole, senza accenti e senza punteggiatura: `A chi è rivolto?` e
    `A CHI E' RIVOLTO` sono la stessa sezione e devono restare tali."""
    pulito = libhtml.unescape(testo)
    piatto = unicodedata.normalize("NFKD", pulito)
    piatto = "".join(c for c in piatto if not unicodedata.combining(c))
    piatto = re.sub(r"[^\w\s]", " ", piatto.lower())
    return re.sub(r"\s+", " ", piatto).strip()


def _sezione_per_etichetta(etichetta: str, declinazione: Declinazione) -> SezioneAgid | None:
    """L'etichetta deve corrispondere per intero, non somigliare.

    Il confronto è di uguaglianza sulla stringa normalizzata perché la
    sottostringa qui costa cara: `Documenti` comparirebbe dentro `Documenti
    necessari per il rinnovo`, e due sezioni diverse collasserebbero in una,
    gonfiando l'aderenza proprio dove il portale è più confuso.
    """
    normale = _normalizza(etichetta)
    if not normale:
        return None
    for sezione, etichette in _ETICHETTE.items():
        ammesse = (*etichette, *declinazione.alias.get(sezione, ()))
        if normale in ammesse:
            return sezione
    return None


def _spoglia(frammento: str) -> str:
    """Il testo di una sezione, senza markup e senza script."""
    senza = re.sub(r"(?s)<(script|style|nav)\b.*?</\1>", " ", frammento)
    testo = re.sub(r"<[^>]+>", " ", senza)
    return re.sub(r"\s+", " ", libhtml.unescape(testo)).strip()[:CORPO_MASSIMO]


def leggi_scheda(html: str, *, declinazione: Declinazione = GENERICA) -> SchedaAgid:
    """Legge una scheda servizio come sezioni del modello AgID.

    Il corpo di una sezione è tutto ciò che sta fra la sua intestazione e la
    successiva dello stesso rango. Niente parser DOM: le pagine civiche sono
    HTML malformato con generosità, e un parser severo si rifiuterebbe di
    leggere proprio i portali messi peggio — cioè quelli che ci interessano.
    """
    livelli = "|".join(declinazione.livelli)
    intestazioni = list(
        re.finditer(rf"<({livelli})\b[^>]*>(?P<testo>.*?)</\1>", html, re.S | re.I)
    )
    sezioni: dict[SezioneAgid, str] = {}
    non_riconosciute: list[str] = []

    for indice, trovata in enumerate(intestazioni):
        etichetta = re.sub(r"<[^>]+>", " ", trovata.group("testo"))
        sezione = _sezione_per_etichetta(etichetta, declinazione)
        if sezione is None:
            pulita = _normalizza(etichetta)
            if pulita:
                non_riconosciute.append(pulita[:80])
            continue
        fine = intestazioni[indice + 1].start() if indice + 1 < len(intestazioni) else len(html)
        corpo = _spoglia(html[trovata.end() : fine])
        # Una sezione che c'è ma è vuota non è una sezione esposta: il titolo
        # senza contenuto è il modo più comune di sembrare conformi.
        if corpo:
            sezioni.setdefault(sezione, corpo)

    return SchedaAgid(
        declinazione=declinazione.nome, sezioni=sezioni, non_riconosciute=non_riconosciute
    )


#: Prefisso dei "box" CMB2 del tema Design Comuni: un box per sezione AgID.
_PREFISSO_BOX = "_dci_servizio_box_"


def _ha_contenuto(valore: object) -> bool:
    """Un campo compilato davvero, non solo presente.

    Le installazioni WordPress restituiscono stringhe vuote, liste vuote e
    dizionari di stringhe vuote a seconda del tipo di campo: sono tutti modi
    diversi di dire la stessa cosa, cioè che nessuno l'ha riempito.
    """
    if isinstance(valore, str):
        return bool(re.sub(r"<[^>]+>", "", valore).strip())
    if isinstance(valore, (list, tuple)):
        return any(_ha_contenuto(v) for v in valore)
    if isinstance(valore, dict):
        return any(_ha_contenuto(v) for v in valore.values())
    return valore not in (None, 0, False)


def leggi_scheda_campi(
    campi: dict,
    *,
    prefisso: str,
    declinazione: str,
    alias: dict[str, SezioneAgid] | None = None,
) -> SchedaAgid:
    """Legge una scheda da campi tipizzati, qualunque sia il prodotto.

    Serve a due piattaforme molto diverse — i box CMB2 del tema WordPress e i
    campi `sys_*` di MyPortal — perché entrambe fanno la stessa cosa: nominano
    i campi come le sezioni del modello AgID. Quel nome è il contratto, e
    leggerlo una volta sola evita che le due letture divergano.
    """
    sezioni: dict[SezioneAgid, str] = {}
    esposte: set[SezioneAgid] = set()
    non_riconosciute: list[str] = []

    mappa = alias or {}
    for chiave, contenuto in (campi or {}).items():
        # La mappatura esplicita viene prima del prefisso: alcuni deployment
        # nominano i campi in inglese (`pnrr_what_is_needed`), e lì il nome non
        # somiglia all'etichetta italiana della sezione nemmeno da lontano.
        sezione = mappa.get(chiave)
        if sezione is None:
            if not chiave.startswith(prefisso):
                continue
            etichetta = chiave[len(prefisso) :].replace("_", " ")
            sezione = _sezione_per_etichetta(etichetta, GENERICA)
        if sezione is None:
            pulita = _normalizza(chiave.replace(prefisso, "", 1).replace("_", " "))
            if pulita:
                non_riconosciute.append(pulita[:80])
            continue
        esposte.add(sezione)
        if _ha_contenuto(contenuto):
            sezioni[sezione] = _spoglia(str(contenuto))[:CORPO_MASSIMO]

    return SchedaAgid(
        declinazione=declinazione,
        sezioni=sezioni,
        non_riconosciute=non_riconosciute,
        esposte=frozenset(esposte),
    )


def leggi_scheda_cmb2(cmb2: dict) -> SchedaAgid:
    """Legge una scheda dai campi tipizzati del tema Design Comuni.

    È l'unico posto dove si possono separare due responsabilità che altrove
    restano incollate: la sezione **esiste** perché il fornitore l'ha prevista
    nello schema, ed è **compilata** perché il comune l'ha riempita.

    Questa distinzione è la scoperta fondativa di TreasureIQ, e qui torna
    misurabile su scala: su Albano Laziale `_dci_servizio_vincoli` — il campo
    fatto apposta per i requisiti di accesso — è presente e vuoto, mentre la
    soglia ISEE sta scritta nella prosa a fianco. Il portale è conforme e non
    dice niente, e senza questa lettura la colpa finirebbe sull'azienda che ha
    fatto la cosa giusta.
    """
    return leggi_scheda_campi(
        cmb2, prefisso=_PREFISSO_BOX, declinazione=WP_DESIGN_COMUNI.nome
    )


#: Il campo che dice **chi ha diritto**, come lo nomina ogni piattaforma.
#:
#: E' lo stesso dato con tre nomi: il tema WordPress lo chiama
#: `_dci_servizio_vincoli`, la Rete Civica Lepida `sys_vincoli`, il modello
#: PNRR del Veneto `pnrr_constraints`. Tre aziende diverse, tre regioni, e
#: tutte e tre hanno previsto il posto dove scrivere i requisiti di accesso.
CAMPI_VINCOLI = frozenset({"_dci_servizio_vincoli", "sys_vincoli", "pnrr_constraints"})

#: Gli esiti possibili, tenuti distinti perche' dicono cose diverse a persone
#: diverse. `assente` e' una scelta del fornitore, `vuoto` una del comune, e
#: sommarli darebbe la colpa a chi non ce l'ha.
VINCOLI_COMPILATO = "compilato"
VINCOLI_VUOTO = "vuoto"
VINCOLI_ASSENTE = "assente"


def stato_vincoli(campi: dict, _profondita: int = 0) -> str:
    """Se il campo dei requisiti c'e', e se qualcuno l'ha riempito.

    E' la misura per cui TreasureIQ esiste. Un servizio comunale che non dice
    a chi spetta obbliga il cittadino a scoprirlo allo sportello — e chi ha
    meno tempo e piu' bisogno e' chi allo sportello ci arriva peggio.

    Cerca in profondita' perche' il tema WordPress annida i campi dentro box:
    `_dci_servizio_vincoli` vive sotto `_dci_servizio_box_accedi_servizio`, e
    fermarsi al primo livello direbbe `assente` per un campo che c'e'.
    """
    if not isinstance(campi, dict) or _profondita > 3:
        return VINCOLI_ASSENTE
    for chiave, valore in campi.items():
        if chiave in CAMPI_VINCOLI:
            return VINCOLI_COMPILATO if _ha_contenuto(valore) else VINCOLI_VUOTO
    for valore in campi.values():
        if isinstance(valore, dict):
            dentro = stato_vincoli(valore, _profondita + 1)
            if dentro != VINCOLI_ASSENTE:
                return dentro
    return VINCOLI_ASSENTE


def declinazione_per(piattaforma: str) -> Declinazione:
    """La declinazione di un fornitore, o quella generica se non la conosciamo."""
    return DECLINAZIONI.get(piattaforma, GENERICA)
