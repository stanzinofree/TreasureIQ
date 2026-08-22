"""I2 guard: connectors are isolated — a connector change touches no other.

Invariant I2 of the source-engine rewrite: each fleet connector is an island.
Adding or changing one platform's connector must not force an edit anywhere else —
not in another connector, not in engine-common code. Two import edges, scanned by
AST, keep that true as a structural fact rather than a habit:

1. **No connector imports a sibling.** A module under ``catalog/flotta/<platform>/``
   may import shared contracts (``_base``, ``_projection``, ``catalog.contracts`` …)
   but never another connector package. The single exception is the fleet
   aggregator ``catalog/flotta/__init__.py`` — the one place whose job *is* to know
   every connector and assemble them into ``flotta_connectors()``.

2. **No engine-common module imports a concrete connector.** Core (chat, api,
   catalog runtime/planner/registries) resolves connectors through the registry,
   never by importing ``flotta.municipium`` & co. directly. If it did, a new
   platform would mean editing core — exactly what I2 forbids.

Both edges hold today; this test stops either from being crossed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import treasureiq

PACKAGE_ROOT = Path(treasureiq.__file__).resolve().parent
FLOTTA_ROOT = PACKAGE_ROOT / "catalog" / "flotta"

#: The connector package names (dirs under flotta/ that are not shared ``_`` helpers).
CONNECTOR_PACKAGES = {
    p.name
    for p in FLOTTA_ROOT.iterdir()
    if p.is_dir() and not p.name.startswith("_") and not p.name.startswith(".")
}

#: The only module allowed to import every connector: the fleet aggregator.
AGGREGATOR = FLOTTA_ROOT / "__init__.py"


def _imported_connector(module: str | None) -> str | None:
    """The connector package a ``from ...flotta.<pkg>...`` import targets, if any."""
    if not module or ".flotta." not in module:
        return None
    tail = module.split(".flotta.", 1)[1].split(".")[0]
    return tail if tail in CONNECTOR_PACKAGES else None


def _from_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """``(lineno, module)`` for every ``from X import ...`` in the tree."""
    return [
        (node.lineno, node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    ]


def _owning_connector(path: Path) -> str | None:
    """Which connector package a flotta module belongs to (None for shared/aggregator)."""
    rel = path.relative_to(FLOTTA_ROOT).parts
    return rel[0] if len(rel) > 1 and rel[0] in CONNECTOR_PACKAGES else None


def test_connectors_do_not_import_each_other() -> None:
    offenders: list[str] = []
    for module in sorted(FLOTTA_ROOT.rglob("*.py")):
        if module == AGGREGATOR:
            continue  # the aggregator's job is to know them all
        owner = _owning_connector(module)
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for lineno, imported in _from_imports(tree):
            target = _imported_connector(imported)
            if target is not None and target != owner:
                rel = module.relative_to(PACKAGE_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}: imports sibling connector '{target}'")

    assert not offenders, (
        "I2 violated — a connector imports another connector. Route shared logic "
        "through the connector contract (_base/_projection), not a sibling. Offenders:\n"
        + "\n".join(offenders)
    )


def test_engine_common_does_not_import_a_concrete_connector() -> None:
    offenders: list[str] = []
    for module in sorted(PACKAGE_ROOT.rglob("*.py")):
        if FLOTTA_ROOT in module.parents or module.parent == FLOTTA_ROOT:
            continue  # inside the fleet — covered by the sibling test above
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for lineno, imported in _from_imports(tree):
            target = _imported_connector(imported)
            if target is not None:
                rel = module.relative_to(PACKAGE_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}: imports connector '{target}' directly")

    assert not offenders, (
        "I2 violated — engine-common code imports a concrete connector. Resolve it "
        "through the connector registry so a new platform never edits core. Offenders:\n"
        + "\n".join(offenders)
    )


def test_guard_sees_the_fleet() -> None:
    """Sanity: the scan actually found the connectors, so a moved directory can't
    silently turn both guards into vacuous passes."""
    assert len(CONNECTOR_PACKAGES) >= 5, CONNECTOR_PACKAGES
    assert AGGREGATOR.exists(), "fleet aggregator moved — update this guard"
