"""Step 4/6 (T0): generatore atomico (valida-prima-di-pubblicare, manifest) e
diff/transizioni a monte. Tutto offline: nessuna rete."""

from __future__ import annotations

import json
from pathlib import Path

from treasureiq import frame_manifest
from treasureiq.ingest import comuni_istat
from treasureiq.municipality_registry import reset_registry_cache


def _riga(codice: str, nome: str, prov: str = "RM", reg: str = "Lazio") -> dict:
    return {"codice_istat": codice, "nome": nome, "provincia": prov,
            "regione": reg, "sito": None}


_CONTEGGI = {"abbinati": 2, "ambigui": 0, "recuperati_su_nome": 0}


# -- Step 4: publish -------------------------------------------------------

def test_pubblica_scrive_frame_e_manifest(tmp_path: Path) -> None:
    out = tmp_path / "comuni-istat.json"
    comuni = [_riga("058091", "Roma"), _riga("058079", "Pomezia")]
    rc = comuni_istat._pubblica(comuni, _CONTEGGI, out)
    assert rc == 0
    assert json.loads(out.read_text("utf-8"))[0]["codice_istat"] == "058091"
    m = frame_manifest.read_manifest(out)
    assert m is not None and m.row_count == 2 and m.valid_codes == 2
    ok, _ = frame_manifest.verify(out)
    assert ok is True


def test_pubblica_rifiuta_frame_invalid_senza_toccare_esistente(tmp_path: Path) -> None:
    out = tmp_path / "comuni-istat.json"
    out.write_text("SENTINELLA", "utf-8")  # frame buono preesistente
    invalido = [_riga("058091", "Roma"), _riga("058091", "Roma")]  # duplicato → INVALID
    rc = comuni_istat._pubblica(invalido, _CONTEGGI, out)
    assert rc == 2
    assert out.read_text("utf-8") == "SENTINELLA"  # intatto
    assert frame_manifest.manifest_path_for(out).exists() is False


def test_pubblica_copertura_bassa_avvisa(tmp_path: Path) -> None:
    out = tmp_path / "comuni-istat.json"
    comuni = [_riga("058091", "Roma"), _riga("058079", "Pomezia")]
    rc = comuni_istat._pubblica(comuni, {"abbinati": 1, "ambigui": 0,
                                         "recuperati_su_nome": 0}, out)
    assert rc == 1  # 50% < COPERTURA_ATTESA
    assert out.exists()  # scritto comunque: è un warning, non un rifiuto


# -- Step 6: diff + transizioni -------------------------------------------

def _scrivi_frame(path: Path, comuni: list[dict]) -> None:
    path.write_text(json.dumps(comuni, ensure_ascii=False) + "\n", "utf-8")


def _scrivi_istat_csv(path: Path, comuni: list[dict]) -> None:
    righe = [";".join([comuni_istat.COL_CODICE, comuni_istat.COL_NOME,
                       comuni_istat.COL_SIGLA, comuni_istat.COL_REGIONE])]
    for c in comuni:
        righe.append(";".join([c["codice_istat"], c["nome"],
                               c["provincia"], c["regione"]]))
    path.write_text("\n".join(righe) + "\n", "latin-1")


def test_diff_upstream_classifica_aggiunti_rimossi_rinominati(tmp_path: Path) -> None:
    reset_registry_cache()
    frame = tmp_path / "comuni-istat.json"
    _scrivi_frame(frame, [
        _riga("058091", "Roma"),
        _riga("058079", "Pomezia"),
        _riga("058003", "Albano"),  # rinominato a monte
    ])
    istat = tmp_path / "istat.csv"
    _scrivi_istat_csv(istat, [
        _riga("058091", "Roma"),
        _riga("058003", "Albano Laziale"),  # stesso codice, nome nuovo
        _riga("058100", "Nuovo Comune"),    # aggiunto
    ])  # 058079 sparito → rimosso

    diff = comuni_istat.diff_upstream(frame, istat)
    assert [d["codice"] for d in diff["aggiunti"]] == ["058100"]
    assert [d["codice"] for d in diff["rimossi"]] == ["058079"]
    assert [d["codice"] for d in diff["rinominati"]] == ["058003"]


def test_pianifica_transizioni_etichetta_i_tipi() -> None:
    diff = {
        "aggiunti": [{"codice": "058100", "nome": "Nuovo"}],
        "rimossi": [{"codice": "058079", "nome": "Pomezia"}],
        "rinominati": [{"codice": "058003", "prima": "Albano", "dopo": "Albano Laziale"}],
    }
    tipi = {t["codice"]: t["tipo"] for t in comuni_istat.pianifica_transizioni(diff)}
    assert tipi == {
        "058100": "NUOVO",
        "058079": "SOPPRESSIONE_O_FUSIONE",
        "058003": "RINOMINA",
    }
