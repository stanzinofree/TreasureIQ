"""A dated record of what each comune has cost us, kept over time.

Usage:
    python -m treasureiq.storico [--db data/storico.db]

Everything else in this project reports the present: what a comune publishes
today, what it costs today. That is enough to state a fact and not enough to
show a change, and a change is the only thing that would tell an
administration whether opening their data actually did anything. So each
ingestion writes one dated row per comune and leaves it there.

Written at ingestion, read at runtime. The API container mounts `data/`
read-only, which SQLite is content with for reads and which keeps the property
the rest of the system relies on: a citizen's question never writes anything,
so two people asking the same thing cannot get different answers.

One row per comune per day, replaced if the day is run twice. Two ingestions
on the same afternoon are not two observations of the world — treating them as
two points would put a slope in a chart that only measured how often we
happened to run the job.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from treasureiq.costo import CostoComune, costo_comune
from treasureiq.integration import load_enti
from treasureiq.schema import Livello, Opportunity

logger = logging.getLogger(__name__)

DEFAULT_DB = Path("data/storico.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS costo_snapshot (
    rilevato_il          TEXT    NOT NULL,
    codice_istat         TEXT    NOT NULL,
    ente                 TEXT    NOT NULL,
    modo                 TEXT    NOT NULL,
    record_totali        INTEGER NOT NULL,
    record_strutturati   INTEGER NOT NULL,
    record_recuperati    INTEGER NOT NULL,
    record_non_recuperati INTEGER NOT NULL,
    costo_totale         REAL    NOT NULL,
    costo_per_record     REAL,
    scoperta_il          TEXT    NOT NULL,
    scoperta_scaduta     INTEGER NOT NULL,
    secondi_recupero     REAL,
    PRIMARY KEY (rilevato_il, codice_istat)
);

-- The census of every Italian municipal portal, whether or not we ingest it.
--
-- `costo_snapshot` above answers "what did the comuni we read cost us". This
-- one answers a question nobody has been publishing: what does the whole
-- country actually expose, and is that changing. The two are kept apart on
-- purpose — a comune appears here from the first sweep, years before anyone
-- writes a connector for it, and conflating "measured" with "ingested" would
-- quietly turn a national map into a report about our own backlog.
--
-- Same rule as above: one row per comune per day, replaced if the sweep is
-- run twice in a day. Re-running a sweep is a correction, not a second
-- observation of the country.
--
-- Every column that was not measured stays NULL. A census that fills gaps
-- with zeros measures its own imagination, and these rows are meant to be
-- charted — a zero and an unknown look identical on a chart and mean
-- opposite things.
CREATE TABLE IF NOT EXISTS portale_snapshot (
    rilevato_il          TEXT    NOT NULL,
    codice_istat         TEXT    NOT NULL,
    nome                 TEXT    NOT NULL,
    provincia            TEXT,
    regione              TEXT,
    -- Carried on every row so a chart can weight by citizens, not by comuni.
    -- Denormalised deliberately: ISTAT restates population per edition, and a
    -- join against today's figures would silently rewrite last year's chart.
    popolazione          INTEGER,
    url_dichiarato       TEXT,
    url_finale           TEXT,
    https_ok             INTEGER,
    stato_http           INTEGER,
    indirizzabilita      TEXT    NOT NULL,
    recuperabilita       TEXT    NOT NULL,
    piattaforma          TEXT    NOT NULL,
    -- Verbatim string that decided the classification. Same doctrine as
    -- `citazione_orari`: an enum without its evidence is an opinion wearing a
    -- serious face, and unreviewable a year later.
    piattaforma_prova    TEXT,
    rest_base            TEXT,
    -- Size of the published catalogue. Summed over comuni with an API, this
    -- is the exact volume of a recurring seed — not an extrapolation.
    n_servizi            INTEGER,
    -- Date of the most recent published content: separates a live portal from
    -- a shop window that has an API and stopped updating in 2019.
    ultimo_contenuto     TEXT,
    -- How much of the AgID service model this portal actually exposes, 0..1,
    -- measured on one real service card. NULL when no card could be read —
    -- which is not the same as a portal that publishes an empty one.
    aderenza             REAL,
    -- The sections found, comma-separated. Kept alongside the ratio because
    -- the civic question is not "how conformant" but "which part is missing":
    -- a portal without `tempi_e_scadenze` costs a citizen a deadline.
    sezioni_esposte      TEXT,
    -- Whether the eligibility-constraints field exists and whether anyone
    -- filled it: `compilato`, `vuoto`, `assente`, or NULL when not measured.
    --
    -- The three platforms that expose typed fields all provide this field —
    -- `_dci_servizio_vincoli`, `sys_vincoli`, `pnrr_constraints` — so for the
    -- first time the question "does this comune say who qualifies" has a
    -- national answer. `assente` is the vendor's choice and `vuoto` the
    -- comune's: kept apart, because merging them blames the wrong party.
    vincoli              TEXT,
    -- Who decided `piattaforma`: the probe during the sweep (`sonda`) or a
    -- later rule applied to the stored fingerprint (`riclassificazione`).
    --
    -- This exists to protect the metric that matters most. Backfilling old
    -- rows with new rules makes a comune look like it moved from `ignota` to
    -- `hgate` when nothing changed on its portal — what changed was our
    -- knowledge. Counting that as "a comune became machine-readable" would
    -- inflate the one number this project would most like to be true.
    classificato_da      TEXT,
    -- Which denominator `aderenza` was computed against: `modello_intero`
    -- when read from HTML, `schema_esposto` when read from typed fields.
    -- Grouping across the two without this produces a ranking that puts the
    -- most compliant vendor last, because its API serialises only part of
    -- what its theme implements.
    base_misura          TEXT,
    -- Sections the vendor's schema declares, filled or not. Only readable
    -- where sections are typed fields (today: the WordPress Design Comuni
    -- theme). A section declared and left empty is the founding finding of
    -- this project, and it apportions blame correctly: the vendor built the
    -- field, the comune did not fill it. NULL where the distinction cannot be
    -- made, never guessed.
    sezioni_dichiarate   TEXT,
    -- Why a measurement is missing, when it is. Keeps our own limits out of
    -- the vendors' numbers: a card our scraper failed to reach must never
    -- read as a vendor that publishes nothing.
    nota_misura          TEXT,
    -- Hash of the structural shape the reader latched onto. No vendor
    -- publishes a version number; this stands in for one. Stable across
    -- deployments of the same vendor, so when it moves on many comuni at
    -- once, that vendor changed its template and a connector is about to
    -- break — known before a citizen hits it.
    impronta_declinazione TEXT,
    -- The exact card the adherence was measured on. Same doctrine as
    -- `piattaforma_prova`: a score whose evidence cannot be reopened is an
    -- opinion, and this one gets published next to a company's name.
    scheda_campione      TEXT,
    -- Product-level `Server` header, when the portal sends one.
    server               TEXT,
    -- Coarse, stable signals for portals that declare nothing: cookie names,
    -- route extensions, first-level asset directories. Half the comuni are
    -- mute, and they are not all different from each other — they are a few
    -- vendors who do not sign their work. This column is the key that groups
    -- them later, by querying the store instead of re-sweeping the country.
    impronta_grezza      TEXT,
    richieste            INTEGER NOT NULL DEFAULT 0,
    secondi              REAL,
    errore               TEXT,
    -- Ciclo 16: la stessa domanda ma per amministrazione-trasparente, non per
    -- il portale principale. Un comune spesso serve i due con vendor diversi
    -- (Barletta: Publisys sul portale, ISWEB sulla trasparenza), quindi la
    -- piattaforma AT vive in colonne proprie, non sovrascrive `piattaforma`.
    piattaforma_at       TEXT,
    piattaforma_at_prova TEXT,
    at_url               TEXT,
    -- JSON: la diagnostica dei runner-up della batteria di firme provate, per
    -- capire perché la sonda ha scartato le alternative — non solo cosa ha
    -- scelto.
    firme_scattate       TEXT,
    PRIMARY KEY (rilevato_il, codice_istat)
);

-- The two axes every analytics question starts from: "how many comuni are on
-- each platform, on each date" and "how did one comune change over time".
CREATE INDEX IF NOT EXISTS idx_portale_data_piattaforma
    ON portale_snapshot (rilevato_il, piattaforma);
CREATE INDEX IF NOT EXISTS idx_portale_comune
    ON portale_snapshot (codice_istat, rilevato_il);
"""


@dataclass
class PuntoStorico:
    rilevato_il: date
    codice_istat: str
    ente: str
    modo: str
    record_totali: int
    record_strutturati: int
    record_recuperati: int
    record_non_recuperati: int
    costo_totale: float
    costo_per_record: float | None
    scoperta_scaduta: bool


def apri(db_path: Path, *, scrittura: bool = False) -> sqlite3.Connection:
    """Open the store, read-only unless writing is explicitly asked for.

    The read path opens through a `file:...?mode=ro` URI rather than trusting
    the caller: at runtime `data/` is mounted read-only anyway, and a
    connection that cannot write is a cheaper guarantee than a convention that
    it will not.
    """
    if scrittura:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA)
        # Anche in scrittura: chi aggiorna righe esistenti le legge prima, e
        # una connessione che restituisce tuple al posto di `Row` fa fallire
        # quel codice solo al primo accesso per nome — cioè in produzione,
        # non nel test che apre in lettura.
        conn.row_factory = sqlite3.Row
        _migra_colonne_at(conn)
        return conn
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


#: The four ciclo-16 columns, additive on top of whatever `portale_snapshot`
#: looked like before. Kept as its own tuple (not folded into
#: `_COLONNE_PORTALE`) because the migration below needs exactly this list,
#: independent of column order in the INSERT statement.
_COLONNE_AT_MIGRAZIONE = (
    "piattaforma_at",
    "piattaforma_at_prova",
    "at_url",
    "firme_scattate",
)


def _migra_colonne_at(conn: sqlite3.Connection) -> None:
    """Add the ciclo-16 AT columns to a `portale_snapshot` created before them.

    `CREATE TABLE IF NOT EXISTS` in `SCHEMA` never touches a table that
    already exists, so a database committed under ciclo 15 or earlier reaches
    here without the four columns. This reads the table's real columns via
    `PRAGMA table_info` — not a try/except around `ALTER TABLE` — so it stays
    idempotent without depending on parsing sqlite's "duplicate column name"
    error text: it only issues `ALTER TABLE ADD COLUMN` for names still
    missing, and does nothing on a second call. Old rows are unaffected and
    read back with the new columns as NULL, which is the honest state for a
    sweep that ran before AT discovery existed.
    """
    esistenti = {riga["name"] for riga in conn.execute("PRAGMA table_info(portale_snapshot)")}
    for colonna in _COLONNE_AT_MIGRAZIONE:
        if colonna not in esistenti:
            conn.execute(f"ALTER TABLE portale_snapshot ADD COLUMN {colonna} TEXT")
    conn.commit()


def registra(conn: sqlite3.Connection, costo: CostoComune, *, oggi: date) -> None:
    """Write today's row for one comune, replacing any earlier run today."""
    conn.execute(
        """
        INSERT INTO costo_snapshot (
            rilevato_il, codice_istat, ente, modo,
            record_totali, record_strutturati, record_recuperati,
            record_non_recuperati, costo_totale, costo_per_record,
            scoperta_il, scoperta_scaduta, secondi_recupero
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(rilevato_il, codice_istat) DO UPDATE SET
            ente=excluded.ente, modo=excluded.modo,
            record_totali=excluded.record_totali,
            record_strutturati=excluded.record_strutturati,
            record_recuperati=excluded.record_recuperati,
            record_non_recuperati=excluded.record_non_recuperati,
            costo_totale=excluded.costo_totale,
            costo_per_record=excluded.costo_per_record,
            scoperta_il=excluded.scoperta_il,
            scoperta_scaduta=excluded.scoperta_scaduta,
            secondi_recupero=excluded.secondi_recupero
        """,
        (
            oggi.isoformat(),
            costo.codice_istat,
            costo.ente,
            costo.modo.value,
            costo.record_totali,
            costo.record_strutturati,
            costo.record_recuperati_da_prosa,
            costo.record_non_recuperati,
            costo.costo_totale,
            costo.costo_per_record,
            costo.scoperta_il.isoformat(),
            int(costo.scoperta_scaduta),
            costo.secondi_recupero,
        ),
    )


def serie(db_path: Path, *, codice_istat: str | None = None) -> list[PuntoStorico]:
    """Every recorded point, oldest first. Empty when the store does not exist.

    A missing file is the ordinary state before the first ingestion, not an
    error: the pages that read this have to render on a fresh checkout, and a
    chart with no points is the honest picture of a history nobody has
    recorded yet.
    """
    if not db_path.exists():
        return []
    with apri(db_path) as conn:
        sql = "SELECT * FROM costo_snapshot"
        params: tuple[str, ...] = ()
        if codice_istat:
            sql += " WHERE codice_istat = ?"
            params = (codice_istat,)
        sql += " ORDER BY rilevato_il ASC, ente ASC"
        righe = conn.execute(sql, params).fetchall()
    return [
        PuntoStorico(
            rilevato_il=date.fromisoformat(r["rilevato_il"]),
            codice_istat=r["codice_istat"],
            ente=r["ente"],
            modo=r["modo"],
            record_totali=r["record_totali"],
            record_strutturati=r["record_strutturati"],
            record_recuperati=r["record_recuperati"],
            record_non_recuperati=r["record_non_recuperati"],
            costo_totale=r["costo_totale"],
            costo_per_record=r["costo_per_record"],
            scoperta_scaduta=bool(r["scoperta_scaduta"]),
        )
        for r in righe
    ]


@dataclass
class RigaPortale:
    """One municipal portal, as measured on one day.

    Mirrors `EsitoCensimento` but deliberately does not import it: the store
    must stay readable without pulling in the network layer, and the census
    must stay free to grow fields the store has not learned yet.
    """

    rilevato_il: date
    codice_istat: str
    nome: str
    provincia: str | None
    regione: str | None
    popolazione: int | None
    url_dichiarato: str | None
    url_finale: str | None
    https_ok: bool | None
    stato_http: int | None
    indirizzabilita: str
    recuperabilita: str
    piattaforma: str
    piattaforma_prova: str | None
    rest_base: str | None
    aderenza: float | None
    sezioni_esposte: str | None
    sezioni_dichiarate: str | None
    classificato_da: str | None
    vincoli: str | None
    base_misura: str | None
    nota_misura: str | None
    impronta_declinazione: str | None
    scheda_campione: str | None
    server: str | None
    impronta_grezza: str | None
    n_servizi: int | None
    ultimo_contenuto: date | None
    richieste: int
    secondi: float | None
    errore: str | None
    #: Ciclo 16 — amministrazione-trasparente, non il portale principale.
    #: Opzionali con default `None` così un `RigaPortale` costruito da codice
    #: pre-ciclo-16 resta valido senza toccare ogni chiamante esistente.
    piattaforma_at: str | None = None
    piattaforma_at_prova: str | None = None
    at_url: str | None = None
    #: Diagnostica dei runner-up della batteria di firme, come lista di dict
    #: pronta per `json.dumps` — `registra_portali` la serializza, questa
    #: classe non lo fa, per restare leggibile a chi la costruisce.
    firme_scattate: list[dict] | None = None


_COLONNE_PORTALE = (
    "rilevato_il", "codice_istat", "nome", "provincia", "regione", "popolazione",
    "url_dichiarato", "url_finale", "https_ok", "stato_http", "indirizzabilita",
    "recuperabilita", "piattaforma", "piattaforma_prova", "rest_base", "aderenza",
    "sezioni_esposte", "sezioni_dichiarate", "classificato_da", "vincoli", "base_misura",
    "nota_misura",
    "impronta_declinazione", "scheda_campione", "server",
    "impronta_grezza", "n_servizi",
    "ultimo_contenuto", "richieste", "secondi", "errore",
    "piattaforma_at", "piattaforma_at_prova", "at_url", "firme_scattate",
)


def registra_portali(db_path: Path, righe: Iterable[RigaPortale]) -> int:
    """Write a sweep's rows, replacing that day's measurement if it exists.

    Committed in one transaction: a sweep interrupted halfway through would
    otherwise leave a partial day in the store that looks, to every chart
    downstream, exactly like a day when half of Italy went offline.
    """
    valori = [
        (
            r.rilevato_il.isoformat(), r.codice_istat, r.nome, r.provincia, r.regione,
            r.popolazione, r.url_dichiarato, r.url_finale,
            None if r.https_ok is None else int(r.https_ok),
            r.stato_http, r.indirizzabilita, r.recuperabilita, r.piattaforma,
            r.piattaforma_prova, r.rest_base, r.aderenza, r.sezioni_esposte,
            r.sezioni_dichiarate, r.classificato_da, r.vincoli, r.base_misura, r.nota_misura,
            r.impronta_declinazione, r.scheda_campione, r.server, r.impronta_grezza,
            r.n_servizi,
            r.ultimo_contenuto.isoformat() if r.ultimo_contenuto else None,
            r.richieste, r.secondi, r.errore,
            r.piattaforma_at, r.piattaforma_at_prova, r.at_url,
            None if r.firme_scattate is None else json.dumps(r.firme_scattate),
        )
        for r in righe
    ]
    if not valori:
        return 0
    segnaposto = ", ".join("?" * len(_COLONNE_PORTALE))
    sql = (
        f"INSERT OR REPLACE INTO portale_snapshot ({', '.join(_COLONNE_PORTALE)}) "
        f"VALUES ({segnaposto})"
    )
    with apri(db_path, scrittura=True) as conn:
        conn.executemany(sql, valori)
        conn.commit()
    return len(valori)


def date_censimento(db_path: Path) -> list[date]:
    """Sweep dates present in the store, oldest first."""
    if not db_path.exists():
        return []
    with apri(db_path) as conn:
        righe = conn.execute(
            "SELECT DISTINCT rilevato_il FROM portale_snapshot ORDER BY rilevato_il ASC"
        ).fetchall()
    return [date.fromisoformat(r["rilevato_il"]) for r in righe]


def panoramica_piattaforme(db_path: Path, *, rilevato_il: date | None = None) -> list[dict]:
    """Per-platform totals for one sweep: comuni, citizens, published services.

    Citizens are reported alongside comuni because the two tell opposite
    stories — a platform used by three hundred small comuni and one used by
    Rome are the same row on a count and nowhere near it on a map of who is
    actually served.
    """
    if not db_path.exists():
        return []
    giorno = rilevato_il or (date_censimento(db_path) or [None])[-1]
    if giorno is None:
        return []
    with apri(db_path) as conn:
        righe = conn.execute(
            """
            SELECT piattaforma,
                   COUNT(*)                AS comuni,
                   COUNT(DISTINCT regione)  AS regioni,
                   -- La regione dove il prodotto pesa di più, e quanto: è ciò
                   -- che separa un fornitore nazionale da una piattaforma
                   -- messa a disposizione da una Regione ai propri comuni.
                   (SELECT p2.regione FROM portale_snapshot p2
                     WHERE p2.rilevato_il = portale_snapshot.rilevato_il
                       AND p2.piattaforma = portale_snapshot.piattaforma
                     GROUP BY p2.regione ORDER BY COUNT(*) DESC LIMIT 1) AS regione_prima,
                   (SELECT COUNT(*) FROM portale_snapshot p3
                     WHERE p3.rilevato_il = portale_snapshot.rilevato_il
                       AND p3.piattaforma = portale_snapshot.piattaforma
                       AND p3.regione = (SELECT p4.regione FROM portale_snapshot p4
                         WHERE p4.rilevato_il = portale_snapshot.rilevato_il
                           AND p4.piattaforma = portale_snapshot.piattaforma
                         GROUP BY p4.regione ORDER BY COUNT(*) DESC LIMIT 1)) AS comuni_prima,
                   -- Senza COALESCE di proposito: se nessuna riga ha la
                   -- popolazione il totale resta NULL, non zero. Uno zero
                   -- disegnerebbe una barra vuota accanto a "0 cittadini
                   -- serviti", che è una frase falsa detta da un grafico.
                   SUM(popolazione)              AS popolazione,
                   SUM(COALESCE(n_servizi, 0))   AS servizi,
                   SUM(CASE WHEN n_servizi IS NOT NULL THEN 1 ELSE 0 END) AS con_catalogo
            FROM portale_snapshot
            WHERE rilevato_il = ?
            GROUP BY piattaforma
            ORDER BY comuni DESC
            """,
            (giorno.isoformat(),),
        ).fetchall()
    return [dict(r) | {"rilevato_il": giorno} for r in righe]


def panoramica_piattaforme_at(db_path: Path, *, rilevato_il: date | None = None) -> list[dict]:
    """Per-platform totals for one sweep's amministrazione-trasparente discovery.

    Grouped by `piattaforma_at`, deliberately not `piattaforma`: the connector
    a comune's transparency page needs is often a different vendor than the
    one serving its main portal (Barletta runs Publisys on the front door and
    ISWEB on trasparenza — same comune, two rows in two different panoramas).

    Rows where `piattaforma_at IS NULL` are dropped, not grouped as a bucket:
    NULL means the AT probe never ran on that comune (sweep predates AT
    discovery, or the probe run itself is what set the column and it's still
    missing), which is a fact about our coverage, not a measurement. A comune
    where the probe ran and found nothing keeps its `NON_TROVATA` value and
    is counted as its own row — that is an honest negative result, not a gap.

    Returns `[]` both when the store has no sweep yet and when the store
    predates ciclo 16 and has not been through a write-open (`registra_portali`
    or any `apri(..., scrittura=True)`) since — the migration in `apri()` is
    what adds the column, and until it runs the empty result is the honest
    state, same as a fresh checkout with no history at all.
    """
    if not db_path.exists():
        return []
    with apri(db_path) as conn:
        colonne = {riga["name"] for riga in conn.execute("PRAGMA table_info(portale_snapshot)")}
        if "piattaforma_at" not in colonne:
            return []
        giorno = rilevato_il or (date_censimento(db_path) or [None])[-1]
        if giorno is None:
            return []
        righe = conn.execute(
            """
            SELECT piattaforma_at,
                   COUNT(*)                AS comuni,
                   COUNT(DISTINCT regione)  AS regioni,
                   -- Stessa lettura del panorama BASE: la regione dove la
                   -- piattaforma di trasparenza pesa di più separa un
                   -- fornitore nazionale da una diffusione regionale.
                   (SELECT p2.regione FROM portale_snapshot p2
                     WHERE p2.rilevato_il = portale_snapshot.rilevato_il
                       AND p2.piattaforma_at = portale_snapshot.piattaforma_at
                     GROUP BY p2.regione ORDER BY COUNT(*) DESC LIMIT 1) AS regione_prima,
                   (SELECT COUNT(*) FROM portale_snapshot p3
                     WHERE p3.rilevato_il = portale_snapshot.rilevato_il
                       AND p3.piattaforma_at = portale_snapshot.piattaforma_at
                       AND p3.regione = (SELECT p4.regione FROM portale_snapshot p4
                         WHERE p4.rilevato_il = portale_snapshot.rilevato_il
                           AND p4.piattaforma_at = portale_snapshot.piattaforma_at
                         GROUP BY p4.regione ORDER BY COUNT(*) DESC LIMIT 1)) AS comuni_prima,
                   SUM(popolazione)         AS popolazione
            FROM portale_snapshot
            WHERE rilevato_il = ? AND piattaforma_at IS NOT NULL
            GROUP BY piattaforma_at
            ORDER BY comuni DESC
            """,
            (giorno.isoformat(),),
        ).fetchall()
    return [dict(r) | {"rilevato_il": giorno} for r in righe]


def portale_del_comune(db_path: Path, codice_istat: str) -> dict | None:
    """The latest measured platform and AgID adherence for one comune.

    `None` when the comune has never been swept, which is the normal state
    for a fresh checkout and for comuni outside the census — not an error.
    Reads the last row by `rilevato_il` rather than recomputing anything, on
    the index it was built for: `(codice_istat, rilevato_il)`.
    """
    if not db_path.exists():
        return None
    with apri(db_path) as conn:
        riga = conn.execute(
            """
            SELECT nome, piattaforma, aderenza, rilevato_il,
                   piattaforma_at, at_url, classificato_da
            FROM portale_snapshot
            WHERE codice_istat = ?
            ORDER BY rilevato_il DESC
            LIMIT 1
            """,
            (codice_istat,),
        ).fetchone()
    if riga is None:
        return None
    return dict(riga) | {"rilevato_il": date.fromisoformat(riga["rilevato_il"])}


def aderenza_fornitori(db_path: Path, *, rilevato_il: date | None = None) -> list[dict]:
    """How well each vendor implements the AgID service model.

    Reported per vendor rather than per comune because that is where the
    decision was made: a comune on a platform that omits `tempi_e_scadenze`
    cannot publish a deadline no matter how diligent its staff are.

    `impronte` counts the distinct structural fingerprints seen. One means the
    vendor ships a uniform template; several mean deployments have drifted,
    and a connector written against one of them will not fit the others.
    """
    if not db_path.exists():
        return []
    giorno = rilevato_il or (date_censimento(db_path) or [None])[-1]
    if giorno is None:
        return []
    with apri(db_path) as conn:
        righe = conn.execute(
            """
            SELECT piattaforma,
                   base_misura,
                   COUNT(*)                          AS comuni,
                   COUNT(aderenza)                   AS misurati,
                   ROUND(AVG(aderenza), 3)           AS aderenza_media,
                   MIN(aderenza)                     AS aderenza_minima,
                   COUNT(DISTINCT impronta_declinazione) AS impronte
            FROM portale_snapshot
            WHERE rilevato_il = ?
            GROUP BY piattaforma, base_misura
            HAVING misurati > 0
            ORDER BY comuni DESC
            """,
            (giorno.isoformat(),),
        ).fetchall()
    return [dict(r) | {"rilevato_il": giorno} for r in righe]


def sezioni_mancanti(db_path: Path, *, rilevato_il: date | None = None) -> list[dict]:
    """Which model sections Italian portals omit most often.

    Counted over every measured comune, because the interesting answer is
    national: the section missing most often is the one the country is
    quietly failing to publish.
    """
    from treasureiq.ingest.modello_agid import SezioneAgid

    if not db_path.exists():
        return []
    giorno = rilevato_il or (date_censimento(db_path) or [None])[-1]
    if giorno is None:
        return []
    with apri(db_path) as conn:
        righe = conn.execute(
            "SELECT sezioni_esposte FROM portale_snapshot "
            "WHERE rilevato_il = ? AND sezioni_esposte IS NOT NULL",
            (giorno.isoformat(),),
        ).fetchall()
    misurati = len(righe)
    esposte = [set((r["sezioni_esposte"] or "").split(",")) for r in righe]
    conteggio = [
        {
            "sezione": s.value,
            "manca_su": sum(1 for e in esposte if s.value not in e),
            "misurati": misurati,
        }
        for s in SezioneAgid
    ]
    return sorted(conteggio, key=lambda x: x["manca_su"], reverse=True)


def vincoli_nazionali(db_path: Path, *, rilevato_il: date | None = None) -> list[dict]:
    """Chi pubblica i requisiti di accesso, e chi lascia il campo vuoto.

    Solo i comuni su piattaforme con campi tipizzati compaiono qui: altrove la
    domanda non si puo' porre, e riportarli come "non pubblicano" sarebbe
    accusarli di un silenzio che non abbiamo misurato.
    """
    if not db_path.exists():
        return []
    giorno = rilevato_il or (date_censimento(db_path) or [None])[-1]
    if giorno is None:
        return []
    with apri(db_path) as conn:
        righe = conn.execute(
            "SELECT vincoli AS stato, COUNT(*) AS comuni FROM portale_snapshot "
            "WHERE rilevato_il = ? AND vincoli IS NOT NULL GROUP BY vincoli "
            "ORDER BY comuni DESC",
            (giorno.isoformat(),),
        ).fetchall()
    return [dict(r) for r in righe]


def evoluzione(db_path: Path, *, da: date, a: date) -> list[dict]:
    """Comuni whose platform or addressability changed between two sweeps.

    This is the question the whole table exists to answer. A portal moving
    from `solo_html` to an API is a comune that became machine-readable, and
    counting those over a year measures something about Italian public
    administration that is currently nobody's published number.

    Comuni absent from either sweep are left out rather than reported as
    changed: appearing in a sweep for the first time is a fact about our
    coverage, not about them.
    """
    if not db_path.exists():
        return []
    with apri(db_path) as conn:
        righe = conn.execute(
            """
            SELECT p.codice_istat, p.nome, p.popolazione,
                   d.piattaforma      AS piattaforma_da,
                   p.piattaforma      AS piattaforma_a,
                   d.indirizzabilita  AS indirizzabilita_da,
                   p.indirizzabilita  AS indirizzabilita_a,
                   d.impronta_declinazione AS impronta_da,
                   p.impronta_declinazione AS impronta_a,
                   d.aderenza         AS aderenza_da,
                   p.aderenza         AS aderenza_a
            FROM portale_snapshot p
            JOIN portale_snapshot d
              ON d.codice_istat = p.codice_istat AND d.rilevato_il = ?
            WHERE p.rilevato_il = ?
              -- Un cambio di piattaforma vale solo se entrambe le righe sono
              -- state decise dalla sonda. Se una delle due viene da una
              -- riclassificazione, la differenza racconta noi, non il comune.
              AND NOT (IFNULL(d.classificato_da, 'sonda') = 'riclassificazione'
                       OR IFNULL(p.classificato_da, 'sonda') = 'riclassificazione')
              AND (d.piattaforma <> p.piattaforma
                   OR d.indirizzabilita <> p.indirizzabilita
                   -- A moved fingerprint is the template change itself. When
                   -- it moves on many comuni of one vendor on the same night,
                   -- that is a connector about to break, and this is where it
                   -- surfaces first.
                   OR IFNULL(d.impronta_declinazione, '')
                      <> IFNULL(p.impronta_declinazione, ''))
            ORDER BY COALESCE(p.popolazione, 0) DESC
            """,
            (da.isoformat(), a.isoformat()),
        ).fetchall()
    return [dict(r) for r in righe]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--seed-dir", default="data/seed")
    args = p.parse_args(argv)

    oggi = date.today()
    enti = load_enti()
    seed_dir = Path(args.seed_dir)
    db_path = Path(args.db)

    scritti = 0
    with apri(db_path, scrittura=True) as conn:
        for percorso in sorted(seed_dir.glob("*.json")):
            dati = json.loads(percorso.read_text("utf-8"))
            if not dati:
                continue
            istat = dati[0].get("source", {}).get("ente_codice_istat")
            ente = enti.get(istat) if istat else None
            if ente is None:
                logger.info("salto %s: nessun ente con codice %s", percorso.name, istat)
                continue
            records = [Opportunity.model_validate(x) for x in dati]
            records = [r for r in records if r.livello is Livello.COMUNALE]
            c = costo_comune(ente=ente, records=records, oggi=oggi)
            registra(conn, c, oggi=oggi)
            scritti += 1
            logger.info(
                "%-26s costo %.1f (%.2f/record) su %d record",
                c.ente,
                c.costo_totale,
                c.costo_per_record or 0,
                c.record_totali,
            )
        conn.commit()

    punti = serie(db_path)
    giorni = sorted({p.rilevato_il for p in punti})
    logger.info(
        "scritti %d comuni in %s — %d punti su %d giorni distinti",
        scritti,
        db_path,
        len(punti),
        len(giorni),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
