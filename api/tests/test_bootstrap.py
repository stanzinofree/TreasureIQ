"""Tests for the bootstrap selection logic (`treasureiq.bootstrap`).

Pure selection, no network: which eligible-and-uninitialised comuni get picked,
in what order, and how the canary stratifies across platforms.
"""

from __future__ import annotations

import json
from pathlib import Path

from treasureiq import bootstrap


def _catalog(dir_: Path, codice: str, piattaforma: str) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / f"{codice}.json").write_text(
        json.dumps(
            {
                "municipality_istat": codice,
                "services": {
                    "s1": {"provider_platform": piattaforma, "source_url": "https://x/s1"},
                },
            }
        ),
        "utf-8",
    )


def _scena(tmp_path: Path) -> Path:
    cat = tmp_path / "catalog"
    # Five native catalog labels, the WordPress alias, and two HTML families.
    plats = ["hgate", "comweb", "openpa", "openweb", "comunibootstrapitalia"]
    for pi, plat in enumerate(plats):
        for j in range(3):
            _catalog(cat, f"{pi:02d}{j:04d}", plat)
    _catalog(cat, "990001", "wordpress_agid")  # eligible via census WP mapping
    _catalog(cat, "990002", "magnolia")
    _catalog(cat, "990003", "drupal")
    return cat


def test_mappa_eleggibili_solo_piattaforme_refresh(tmp_path: Path) -> None:
    cat = _scena(tmp_path)
    m = bootstrap.mappa_eleggibili(cat)
    assert len(m) == 18
    assert m["990001"] == "wordpress_agid"
    assert m["990002"] == "magnolia" and m["990003"] == "drupal"


def test_seleziona_interseca_coda_e_non_inizializzati(tmp_path: Path) -> None:
    cat = _scena(tmp_path)
    eleggibili = set(bootstrap.mappa_eleggibili(cat))
    # Queue misses one eligible comune; another is already initialised.
    fuori_coda = "000000"  # hgate rank 0
    gia_init = "010000"    # comweb rank 0
    coda = eleggibili - {fuori_coda}
    cand = bootstrap.seleziona(cat, coda, {gia_init})
    codici = {c for c, _ in cand}
    assert fuori_coda not in codici  # not in queue -> excluded
    assert gia_init not in codici    # already initialised -> excluded
    assert len(cand) == 16           # 18 - 2
    # Ordered by (platform, codice): stable and reproducible.
    assert cand == sorted(cand, key=lambda cp: (cp[1], cp[0]))


def test_canary_due_per_piattaforma_round_robin(tmp_path: Path) -> None:
    cat = _scena(tmp_path)
    eleggibili = set(bootstrap.mappa_eleggibili(cat))
    cand = bootstrap.seleziona(cat, eleggibili, set())
    scelti = bootstrap.canary(cand, per_piattaforma=2)
    assert len(scelti) == 13  # 2 x 5 platforms + 3 single-platform examples
    plats = [dict(cand)[c] for c in scelti]
    from collections import Counter
    assert Counter(plats) == {
        "hgate": 2, "comweb": 2, "openpa": 2, "openweb": 2, "comunibootstrapitalia": 2,
        "wordpress_agid": 1,
        "magnolia": 1, "drupal": 1,
    }
    # Round-robin: first eight are rank-0 of each platform.
    assert len(set(plats[:8])) == 8


def test_canary_regge_piattaforma_scarsa(tmp_path: Path) -> None:
    """A platform with fewer than per_piattaforma comuni must not break the canary."""
    cat = tmp_path / "catalog"
    _catalog(cat, "000001", "hgate")
    _catalog(cat, "000002", "hgate")
    _catalog(cat, "010001", "comweb")  # only one comweb
    cand = bootstrap.seleziona(cat, {"000001", "000002", "010001"}, set())
    scelti = bootstrap.canary(cand, per_piattaforma=2)
    assert set(scelti) == {"000001", "000002", "010001"}  # takes what exists


def test_lotto_rispetta_limit(tmp_path: Path) -> None:
    cat = _scena(tmp_path)
    cand = bootstrap.seleziona(cat, set(bootstrap.mappa_eleggibili(cat)), set())
    assert len(bootstrap.lotto(cand, 4)) == 4
    assert len(bootstrap.lotto(cand, None)) == 18
