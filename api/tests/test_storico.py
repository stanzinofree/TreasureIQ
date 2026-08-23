"""Tests for the ciclo-16 AT columns on `portale_snapshot`: migration,
write path, and the new analytics function — plus a guard that `evoluzione`
stays blind to the new columns."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from treasureiq.storico import (
    RigaPortale,
    apri,
    evoluzione,
    panoramica_piattaforme_at,
    registra_portali,
    rimuovi_portali,
)

# The `portale_snapshot` CREATE TABLE exactly as it stood before ciclo 16,
# without the four AT columns. Copied verbatim (minus comments) from the
# pre-ciclo-16 `SCHEMA` so the migration test exercises the real shape a
# committed `data/storico.db` has, not an approximation.
SCHEMA_PRE_CICLO16 = """
CREATE TABLE IF NOT EXISTS portale_snapshot (
    rilevato_il          TEXT    NOT NULL,
    codice_istat         TEXT    NOT NULL,
    nome                 TEXT    NOT NULL,
    provincia            TEXT,
    regione              TEXT,
    popolazione          INTEGER,
    url_dichiarato       TEXT,
    url_finale           TEXT,
    https_ok             INTEGER,
    stato_http           INTEGER,
    indirizzabilita      TEXT    NOT NULL,
    recuperabilita       TEXT    NOT NULL,
    piattaforma          TEXT    NOT NULL,
    piattaforma_prova    TEXT,
    rest_base            TEXT,
    n_servizi            INTEGER,
    ultimo_contenuto     TEXT,
    aderenza             REAL,
    sezioni_esposte      TEXT,
    vincoli              TEXT,
    classificato_da      TEXT,
    base_misura          TEXT,
    sezioni_dichiarate   TEXT,
    nota_misura          TEXT,
    impronta_declinazione TEXT,
    scheda_campione      TEXT,
    server               TEXT,
    impronta_grezza      TEXT,
    richieste            INTEGER NOT NULL DEFAULT 0,
    secondi              REAL,
    errore               TEXT,
    PRIMARY KEY (rilevato_il, codice_istat)
);
"""


def _crea_db_schema_vecchio(db_path: Path) -> None:
    """Build a fixture with the real pre-ciclo-16 shape, populated with rows,
    using raw sqlite3 rather than `apri()` — the module under test must never
    be trusted to build the fixture that tests it."""
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PRE_CICLO16)
    conn.execute(
        """
        INSERT INTO portale_snapshot (
            rilevato_il, codice_istat, nome, provincia, regione, popolazione,
            indirizzabilita, recuperabilita, piattaforma, richieste
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("2026-01-01", "058091", "Roma", "RM", "Lazio", 2800000, "api", "diretta", "hgate", 3),
    )
    conn.execute(
        """
        INSERT INTO portale_snapshot (
            rilevato_il, codice_istat, nome, provincia, regione, popolazione,
            indirizzabilita, recuperabilita, piattaforma, richieste
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("2026-01-01", "058009", "Anzio", "RM", "Lazio", 55000, "solo_html", "scrape", "ignota", 1),
    )
    conn.commit()
    conn.close()


def test_migrazione_su_schema_vecchio_reale_aggiunge_colonne_at(tmp_path: Path) -> None:
    db_path = tmp_path / "storico.db"
    _crea_db_schema_vecchio(db_path)

    with apri(db_path, scrittura=True) as conn:
        colonne = {r["name"] for r in conn.execute("PRAGMA table_info(portale_snapshot)")}

    for nome_colonna in ("piattaforma_at", "piattaforma_at_prova", "at_url", "firme_scattate"):
        assert nome_colonna in colonne


def test_migrazione_su_schema_vecchio_righe_esistenti_restano_leggibili(tmp_path: Path) -> None:
    db_path = tmp_path / "storico.db"
    _crea_db_schema_vecchio(db_path)

    with apri(db_path, scrittura=True) as conn:
        righe = conn.execute(
            "SELECT nome, piattaforma, piattaforma_at, at_url, firme_scattate "
            "FROM portale_snapshot ORDER BY codice_istat"
        ).fetchall()

    assert [r["nome"] for r in righe] == ["Anzio", "Roma"]
    assert [r["piattaforma"] for r in righe] == ["ignota", "hgate"]
    # The old rows never measured AT: NULL is the honest value, not a guess.
    for r in righe:
        assert r["piattaforma_at"] is None
        assert r["at_url"] is None
        assert r["firme_scattate"] is None


def test_migrazione_e_idempotente_sulla_seconda_apertura(tmp_path: Path) -> None:
    db_path = tmp_path / "storico.db"
    _crea_db_schema_vecchio(db_path)

    with apri(db_path, scrittura=True):
        pass
    # Second write-open must not raise "duplicate column name" or anything else.
    with apri(db_path, scrittura=True) as conn:
        colonne = [r["name"] for r in conn.execute("PRAGMA table_info(portale_snapshot)")]

    assert colonne.count("piattaforma_at") == 1


def _riga(
    codice_istat: str,
    nome: str,
    regione: str,
    piattaforma: str,
    *,
    rilevato_il: date,
    piattaforma_at: str | None = None,
    at_url: str | None = None,
    firme_scattate: list[dict] | None = None,
    popolazione: int | None = 1000,
) -> RigaPortale:
    return RigaPortale(
        rilevato_il=rilevato_il,
        codice_istat=codice_istat,
        nome=nome,
        provincia=None,
        regione=regione,
        popolazione=popolazione,
        url_dichiarato=None,
        url_finale=None,
        https_ok=None,
        stato_http=None,
        indirizzabilita="api",
        recuperabilita="diretta",
        piattaforma=piattaforma,
        piattaforma_prova=None,
        rest_base=None,
        aderenza=None,
        sezioni_esposte=None,
        sezioni_dichiarate=None,
        classificato_da=None,
        vincoli=None,
        base_misura=None,
        nota_misura=None,
        impronta_declinazione=None,
        scheda_campione=None,
        server=None,
        impronta_grezza=None,
        n_servizi=None,
        ultimo_contenuto=None,
        richieste=1,
        secondi=0.5,
        errore=None,
        piattaforma_at=piattaforma_at,
        at_url=at_url,
        firme_scattate=firme_scattate,
    )


def test_registra_portali_scrive_le_colonne_at_e_serializza_firme_scattate(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "storico.db"
    oggi = date(2026, 8, 11)
    riga = _riga(
        "058091",
        "Roma",
        "Lazio",
        "hgate",
        rilevato_il=oggi,
        piattaforma_at="iswebtrasparenza",
        at_url="https://trasparenza.comune.roma.it",
        firme_scattate=[{"nome": "publisys", "punteggio": 0.4}],
    )

    registra_portali(db_path, [riga])

    with apri(db_path, scrittura=True) as conn:
        salvata = conn.execute(
            "SELECT piattaforma_at, at_url, firme_scattate FROM portale_snapshot "
            "WHERE codice_istat = ?",
            ("058091",),
        ).fetchone()

    assert salvata["piattaforma_at"] == "iswebtrasparenza"
    assert salvata["at_url"] == "https://trasparenza.comune.roma.it"
    assert json.loads(salvata["firme_scattate"]) == [{"nome": "publisys", "punteggio": 0.4}]


def test_registra_portali_firme_scattate_none_scrive_null(tmp_path: Path) -> None:
    db_path = tmp_path / "storico.db"
    oggi = date(2026, 8, 11)
    riga = _riga("058009", "Anzio", "Lazio", "ignota", rilevato_il=oggi)

    registra_portali(db_path, [riga])

    with apri(db_path, scrittura=True) as conn:
        salvata = conn.execute(
            "SELECT firme_scattate FROM portale_snapshot WHERE codice_istat = ?",
            ("058009",),
        ).fetchone()

    assert salvata["firme_scattate"] is None


def test_rimuovi_portali_consente_il_retry_del_batch(tmp_path: Path) -> None:
    db_path = tmp_path / "storico.db"
    oggi = date(2026, 8, 11)
    registra_portali(
        db_path,
        [
            _riga("058009", "Anzio", "Lazio", "ignota", rilevato_il=oggi),
            _riga("058091", "Roma", "Lazio", "hgate", rilevato_il=oggi),
        ],
    )

    assert rimuovi_portali(db_path, rilevato_il=oggi, codici_istat=["058009"]) == 1

    with apri(db_path) as conn:
        righe = conn.execute(
            "SELECT codice_istat FROM portale_snapshot ORDER BY codice_istat"
        ).fetchall()
    assert [r["codice_istat"] for r in righe] == ["058091"]


def test_panoramica_piattaforme_at_raggruppa_ed_esclude_i_null(tmp_path: Path) -> None:
    db_path = tmp_path / "storico.db"
    oggi = date(2026, 8, 11)
    righe = [
        _riga("058091", "Roma", "Lazio", "hgate", rilevato_il=oggi,
              piattaforma_at="iswebtrasparenza", popolazione=2800000),
        _riga("058009", "Anzio", "Lazio", "ignota", rilevato_il=oggi,
              piattaforma_at="iswebtrasparenza", popolazione=55000),
        _riga("072006", "Bari", "Puglia", "peopleweb", rilevato_il=oggi,
              piattaforma_at="NON_TROVATA", popolazione=320000),
        # Never probed for AT: must not appear in any group.
        _riga("058008", "Ardea", "Lazio", "ignota", rilevato_il=oggi,
              piattaforma_at=None, popolazione=48000),
    ]
    registra_portali(db_path, righe)

    panorama = panoramica_piattaforme_at(db_path)

    per_piattaforma = {r["piattaforma_at"]: r for r in panorama}
    assert set(per_piattaforma) == {"iswebtrasparenza", "NON_TROVATA"}
    assert per_piattaforma["iswebtrasparenza"]["comuni"] == 2
    assert per_piattaforma["iswebtrasparenza"]["popolazione"] == 2800000 + 55000
    assert per_piattaforma["NON_TROVATA"]["comuni"] == 1


def test_panoramica_piattaforme_at_su_db_non_migrato_ritorna_vuoto(tmp_path: Path) -> None:
    db_path = tmp_path / "storico.db"
    _crea_db_schema_vecchio(db_path)

    # No write-open has happened yet on this fixture, so the AT columns do
    # not exist — same honest-empty answer as a fresh checkout, not a crash.
    assert panoramica_piattaforme_at(db_path) == []


def test_panoramica_piattaforme_at_su_db_assente_ritorna_vuoto(tmp_path: Path) -> None:
    assert panoramica_piattaforme_at(tmp_path / "non-esiste.db") == []


def test_evoluzione_resta_invariata_quando_solo_le_colonne_at_cambiano(
    tmp_path: Path,
) -> None:
    """`evoluzione` compares `piattaforma`, `indirizzabilita`, and
    `impronta_declinazione` between two sweeps. The AT columns are new and
    must never enter that comparison: a comune whose AT connector was
    discovered between two sweeps, with the base portal unchanged, must not
    be reported as having evolved."""
    db_path = tmp_path / "storico.db"
    prima = date(2026, 8, 1)
    dopo = date(2026, 8, 8)

    riga_prima = _riga(
        "058091", "Roma", "Lazio", "hgate", rilevato_il=prima, piattaforma_at=None
    )
    riga_dopo = _riga(
        "058091", "Roma", "Lazio", "hgate", rilevato_il=dopo,
        piattaforma_at="iswebtrasparenza", at_url="https://trasparenza.comune.roma.it",
    )
    registra_portali(db_path, [riga_prima])
    registra_portali(db_path, [riga_dopo])

    cambi = evoluzione(db_path, da=prima, a=dopo)

    assert cambi == []


def test_evoluzione_rileva_ancora_un_cambio_di_piattaforma_base(tmp_path: Path) -> None:
    """Sanity check alongside the guard above: `evoluzione` must still fire on
    a real base-platform change, so the previous test proves AT-blindness and
    not a broken comparison."""
    db_path = tmp_path / "storico.db"
    prima = date(2026, 8, 1)
    dopo = date(2026, 8, 8)

    riga_prima = _riga("058091", "Roma", "Lazio", "ignota", rilevato_il=prima)
    riga_dopo = _riga(
        "058091", "Roma", "Lazio", "hgate", rilevato_il=dopo,
        piattaforma_at="iswebtrasparenza",
    )
    registra_portali(db_path, [riga_prima])
    registra_portali(db_path, [riga_dopo])

    cambi = evoluzione(db_path, da=prima, a=dopo)

    assert len(cambi) == 1
    assert cambi[0]["piattaforma_da"] == "ignota"
    assert cambi[0]["piattaforma_a"] == "hgate"
    # The AT columns are not `classificato_da` and must not appear in the
    # comparison's output shape.
    assert "piattaforma_at" not in cambi[0]
    assert "piattaforma_at_a" not in cambi[0]
