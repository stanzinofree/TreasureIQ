"""Corpus condiviso di frasi IT per la rete di caratterizzazione (ciclo 11, B1).

Congela cosa intent.py/respond.py restituiscono OGGI su testo libero, prima
che D-05 tocchi quel codice. Ogni voce e' un `CasoTesto`: input verbatim +
atteso ATTUALE (non wishlist — vedi `test_characterization_intent.py`).

Condiviso con B2 (recall sulle forme numeriche): le voci con
`oggi_non_colto=True` sono quelle che `slot_dal_testo` OGGI non cattura o
cattura male — B2 le usa per misurare il gap, non le nasconde.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CasoTesto:
    """Una frase e l'atteso ATTUALE per una o piu' funzioni deterministiche.

    `atteso` e' un dict libero: le chiavi corrispondono a cio' che il test
    verifica per quel caso (es. `{"eta": 38}` per `slot_dal_testo`, o
    `{"disabilita": True}` per `_disabilita_dichiarata_nel_testo`). Non ogni
    caso popola ogni chiave — assente vuol dire "non verificato qui", non
    "vuoto".
    """

    id: str
    testo: str
    categoria: str
    atteso: dict = field(default_factory=dict)
    #: OGGI il codice non coglie (o coglie male) questa forma. Non e' un bug
    #: nascosto: e' il motivo per cui la voce e' nel corpus.
    oggi_non_colto: bool = False
    nota: str = ""


CORPUS: tuple[CasoTesto, ...] = (
    # -- eta': forme reali che `_ETA_NEL_TESTO` coglie oggi ------------------
    CasoTesto("eta-01", "ho 67 anni", "eta", {"eta": 67}),
    CasoTesto("eta-02", "ho 38 anni e sono di pergine", "eta", {"eta": 38}),
    CasoTesto("eta-03", "sono un 45enne", "eta", {"eta": 45}),
    CasoTesto("eta-04", "ho compiuto 30 anni", "eta", {"eta": 30}),
    CasoTesto(
        "eta-05",
        "civico 140 anni luce",
        "eta",
        {"eta": None},
        nota="oltre 130 scartato dal guard 0<valore<=130",
    ),

    # -- ISEE: forme reali, incluso lo scar di troncamento -------------------
    CasoTesto("isee-01", "ISEE 9.360", "isee", {"isee": 9360.0}),
    CasoTesto("isee-02", "isee 9.360,50", "isee", {"isee": 9360.5}),
    CasoTesto(
        "isee-03",
        "ISEE di 9360 euro",
        "isee",
        {"isee": 936.0},
        oggi_non_colto=True,
        nota=(
            "# atteso-attuale, ciclo11 cambia in: 9360.0. Bug di "
            "_ISEE_NEL_TESTO: senza separatore delle migliaia il primo "
            "ramo dell'alternanza (\\d{1,3}) matcher greedy ma NON "
            "backtracka sul ramo lungo — 'isee di 9360 euro' legge 936, "
            "non 9360. Numero letto = importo dimezzato di un ordine di "
            "grandezza, silenziosamente."
        ),
    ),
    CasoTesto(
        "isee-04",
        "ISEE 9360",
        "isee",
        {"isee": 936.0},
        oggi_non_colto=True,
        nota="stesso troncamento di isee-03, senza la parola 'di'",
    ),
    CasoTesto(
        "isee-05",
        "novemila euro",
        "isee",
        {},
        oggi_non_colto=True,
        nota="numero scritto a parole, nessuna parola-chiave 'isee' vicino: non letto",
    ),
    CasoTesto(
        "isee-06",
        "9k",
        "isee",
        {},
        oggi_non_colto=True,
        nota="notazione 'k' per mille: fuori pattern, non letto",
    ),
    CasoTesto(
        "isee-07",
        "reddito 15 mila",
        "isee",
        {},
        oggi_non_colto=True,
        nota="'reddito' non e' una delle parole-chiave cercate (solo 'isee'); non letto",
    ),

    # -- nucleo familiare ------------------------------------------------
    CasoTesto("nucleo-01", "famiglia di 4", "nucleo", {"nucleo_familiare": 4}),
    CasoTesto("nucleo-02", "nucleo di 5", "nucleo", {"nucleo_familiare": 5}),
    CasoTesto("nucleo-03", "siamo in 4", "nucleo", {"nucleo_familiare": 4}),
    CasoTesto(
        "nucleo-04",
        "in famiglia siamo in tanti",
        "nucleo",
        {},
        oggi_non_colto=True,
        nota="nessuna cifra nel testo: il regex non ha nulla da leggere",
    ),

    # -- figli minori: forme numeriche reali ------------------------------
    CasoTesto("figli-01", "due figli minorenni", "figli_minori", {"figli_minori": 2}),
    CasoTesto("figli-02", "un figlio minore", "figli_minori", {"figli_minori": 1}),
    CasoTesto("figli-03", "3 figli minori", "figli_minori", {"figli_minori": 3}),
    CasoTesto(
        "figli-04",
        "ho figli minori",
        "figli_minori",
        {"figli_minori": 1},
        nota="nessun conteggio esplicito -> almeno uno (default 1), per design",
    ),
    CasoTesto(
        "figli-05",
        "ho due figli",
        "figli_minori",
        {},
        nota="senza qualificatore minor.../piccol... il regex non scatta (per design)",
    ),
    CasoTesto("figli-06", "figli piccoli a casa", "figli_minori", {"figli_minori": 1}),

    # -- negazioni: lo scar reale (nessuna gestione della negazione) --------
    CasoTesto(
        "neg-01",
        "non ho figli minori",
        "figli_minori",
        {"figli_minori": 1},
        oggi_non_colto=True,
        nota=(
            "# atteso-attuale, ciclo11 cambia in: {} (nessun figlio minore). "
            "_FIGLI_MINORI_NEL_TESTO non guarda la negazione: 'non ho figli "
            "minori' legge figli_minori=1, il contrario di quanto dichiarato."
        ),
    ),
    CasoTesto(
        "neg-02",
        "mia figlia è maggiorenne",
        "figli_minori",
        {},
        nota="nessun qualificatore minor/piccol nel testo: nessun falso positivo, per design",
    ),
    CasoTesto(
        "neg-03",
        "non sono disabile",
        "disabilita",
        {"disabilita": True},
        oggi_non_colto=True,
        nota=(
            "# atteso-attuale, ciclo11 cambia in: False. "
            "_DISABILITA_RE non guarda la negazione: 'non sono disabile' "
            "dichiara disabilita=True, il contrario di quanto scritto."
        ),
    ),
    CasoTesto(
        "neg-04",
        "non sono un uomo",
        "sesso",
        {"sesso": "m"},
        oggi_non_colto=True,
        nota=(
            "# atteso-attuale, ciclo11 cambia in: None. "
            "_sesso_dichiarato_nel_testo non guarda la negazione: "
            "'non sono un uomo' legge sesso='m'."
        ),
    ),

    # -- toponimi scar: parole che sono ANCHE nomi di comune -----------------
    CasoTesto(
        "topo-01",
        "minori",
        "comune",
        {"candidati": []},
        nota="stoplist _PAROLE_NON_TOPONIMI: 'minori' non risolve al comune Minori (SA)",
    ),
    CasoTesto(
        "topo-02",
        "ho due figli minori",
        "comune",
        {"candidati": []},
        nota="stessa stoplist, dentro una frase reale",
    ),
    CasoTesto(
        "topo-03",
        "bolletta della luce",
        "comune",
        {"candidati": []},
        nota="stoplist _CONNETTIVI_NOME: 'della' non aggancia comuni con 'della' nel nome",
    ),
    CasoTesto(
        "topo-04",
        "monte rotondo",
        "comune",
        {"candidati": [("Monterotondo", "RM")]},
        nota="comune scritto spezzato: risolve via chiave compatta senza spazi",
    ),
    CasoTesto(
        "topo-05",
        "sono di monte rotondo",
        "comune",
        {"candidati": [("Monterotondo", "RM")]},
        nota="stessa risoluzione dentro una frase reale",
    ),
    CasoTesto(
        "topo-06",
        "sono di pergine",
        "comune",
        {"ambiguo": True},
        nota="Pergine Valsugana (TN) vs Laterina Pergine Valdarno (AR): resta ambiguo, per design",
    ),

    # -- disabilita': propria vs figlio (R-8/D-53) ----------------------------
    CasoTesto("dis-01", "sono disabile", "disabilita", {"disabilita": True, "figlio": False}),
    CasoTesto(
        "dis-02", "ho un'invalidità", "disabilita", {"disabilita": True, "figlio": False}
    ),
    CasoTesto("dis-03", "handicap fisico", "disabilita", {"disabilita": True, "figlio": False}),
    CasoTesto(
        "dis-04",
        "mia figlia con disabilità",
        "disabilita",
        {"disabilita": False, "figlio": True},
        nota="la disabilita' e' del figlio, non del cittadino: 'disabilita' cede il passo",
    ),
    CasoTesto(
        "dis-05",
        "figlio disabile",
        "disabilita",
        {"disabilita": False, "figlio": True},
    ),
    CasoTesto(
        "dis-06",
        "sono disabilitato il servizio",
        "disabilita",
        {"disabilita": False, "figlio": False},
        nota="'disabilitato' non e' 'disabile': i confini di parola espliciti nel regex evitano il falso positivo",
    ),

    # -- eta': altre forme reali --------------------------------------------
    CasoTesto("eta-06", "ha 82 anni", "eta", {"eta": 82}),
    CasoTesto("eta-07", "il nonno ha 91 anni", "eta", {"eta": 91}),

    # -- ISEE: altre forme reali ---------------------------------------------
    CasoTesto("isee-08", "ISEE pari a 15.200 euro", "isee", {"isee": 15200.0}),
    CasoTesto("isee-09", "isee basso", "isee", {}, nota="nessuna cifra dopo la parola: nulla da leggere"),

    # -- nucleo familiare: altre forme -----------------------------------
    CasoTesto("nucleo-05", "nucleo di 2", "nucleo", {"nucleo_familiare": 2}),
    CasoTesto("nucleo-06", "famiglia di 6", "nucleo", {"nucleo_familiare": 6}),

    # -- figli minori: altre forme numeriche ------------------------------
    CasoTesto("figli-07", "quattro figli minorenni", "figli_minori", {"figli_minori": 4}),
    CasoTesto("figli-08", "cinque figli piccoli", "figli_minori", {"figli_minori": 5}),
    CasoTesto("figli-09", "un figlio piccolo", "figli_minori", {"figli_minori": 1}),
    CasoTesto(
        "figli-10",
        "mia figlia non è più minorenne",
        "figli_minori",
        {},
        nota=(
            "il qualificatore non e' adiacente ('figlia' ... 'minorenne' "
            "separate da altre parole): il regex vuole figl[io]\\w*\\s+minorenn... "
            "di seguito, quindi non scatta — nessun falso positivo, per design"
        ),
    ),

    # -- disabilita': altre forme reali (R-8) --------------------------------
    CasoTesto(
        "dis-07",
        "sono invalido al 100%",
        "disabilita",
        {"disabilita": True, "figlio": False},
    ),
    CasoTesto(
        "dis-08",
        "mia madre è disabile",
        "disabilita",
        {"disabilita": True, "figlio": False},
        nota=(
            "terza persona non-figlio (beneficiario) conta come 'disabilita', "
            "non come 'figlio': solo i marcatori espliciti figlio/figlia "
            "cedono il passo a disabilita_nucleo, per design"
        ),
    ),
    CasoTesto(
        "dis-09",
        "sono persone disabili",
        "disabilita",
        {"disabilita": True, "figlio": False},
    ),

    # -- sesso dichiarato esplicitamente (D-52) ------------------------------
    CasoTesto("sesso-01", "sono una donna", "sesso", {"sesso": "f"}),
    CasoTesto("sesso-02", "sono un uomo", "sesso", {"sesso": "m"}),
    CasoTesto("sesso-03", "sono donna", "sesso", {"sesso": "f"}),
    CasoTesto(
        "sesso-04",
        "lavoro come donna delle pulizie",
        "sesso",
        {"sesso": None},
        nota="nessun marcatore esplicito 'sono donna/uomo': non dichiarato, per design",
    ),

    # -- toponimi scar: altre forme -----------------------------------------
    CasoTesto(
        "topo-07",
        "vivo a monte rotondo da anni",
        "comune",
        {"candidati": [("Monterotondo", "RM")]},
        nota="stessa risoluzione dentro una frase piu' lunga",
    ),
    CasoTesto(
        "topo-08",
        "gorla minore",
        "comune",
        {"candidati": [("Gorla Maggiore", "VA"), ("Gorla Minore", "VA")]},
        nota=(
            "'minore' e' tolto perche' e' nella stoplist, ma il resto ('gorla') "
            "aggancia DUE comuni realmente diversi — resta ambiguo, non risolve "
            "al comune sbagliato ne' al giusto: chiede, come da design D-54"
        ),
    ),

    # -- employment: nessun ripiego deterministico ---------------------------
    CasoTesto(
        "empl-01",
        "sono disoccupato da un anno",
        "employment",
        {"non_estratto_dal_testo": True},
        nota=(
            "employment_status non ha regex di ripiego come eta/isee/nucleo/"
            "figli_minori: `_profile_from_slots` passa `slots.employment_status` "
            "cosi' com'e' — se il modello non lo riempie, resta None anche "
            "quando il testo lo dice esplicitamente."
        ),
    ),
    CasoTesto(
        "empl-02",
        "sono pensionato",
        "employment",
        {"non_estratto_dal_testo": True},
        nota="stessa assenza di ripiego testuale, altra dichiarazione esplicita",
    ),
)


def casi_per_categoria(categoria: str) -> tuple[CasoTesto, ...]:
    """Filtro di comodo per i test che vogliono solo una fetta del corpus."""
    return tuple(c for c in CORPUS if c.categoria == categoria)


def casi_non_colti() -> tuple[CasoTesto, ...]:
    """Le voci che oggi il codice non coglie (o coglie male) — il gap onesto
    che B2 misura per il recall."""
    return tuple(c for c in CORPUS if c.oggi_non_colto)
