"""Guard test for invariant I1 (Fase 1 strangler, recognition seam).

Two BASE call sites were migrated off the legacy classifier
(`classifica_risposta` / `firma_da_risposta` in `piattaforma.py`) onto the
registry seam `firma_da_registro` (`catalog/recognition_adapter.py`):
`catalog/inventory_discovery.py` (M1) and `ingest/censimento.py::_impronta`
(M2). This test is the tripwire that keeps a THIRD, unreviewed call site from
reappearing while the strangler is still in flight: it statically scans every
production module under `api/treasureiq/` and asserts that only a fixed,
named allowlist of files imports `classifica_risposta`, `firma_da_risposta`,
or `scopri_pagina_at`.

The allowlist is per-symbol, not per-file, because the three names are not
interchangeable:

* `classifica_risposta` / `firma_da_risposta` are defined in `piattaforma.py`
  (the definition site is trivially exempt) and are still legitimately used
  by `recognition_bridge.py` (wraps the classifier as one of the registry's
  bridge plugins — by design, not a migration gap, see its module docstring)
  and by `ingest/censimento.py` (its `scopri_pagina_at` AT-surface discovery
  still classifies via `classifica_risposta(includi_at=True)` — the AT
  surface was never in scope for this migration, only BASE was).

* `scopri_pagina_at` is defined in `censimento.py` and is legitimately called
  by `connettore.py` and `catalog/inventory_discovery.py` for AT (Amministrazione
  Trasparente) discovery — a surface this migration did not touch. Its
  presence in `inventory_discovery.py` is NOT a migration gap: M1 only moved
  that module's BASE recognition call, not its (unrelated) AT call.

TEMPORARY vs PERMANENT entries, spelled out so tightening this allowlist
later is a one-line diff instead of a re-investigation:

* TEMPORARY (C1, deferred blocker): `ingest/censimento.py`'s own AT discovery
  (`scopri_pagina_at`'s internal `classifica_risposta` call) is not yet
  migrated to a registry seam. When it is, `censimento.py` drops out of the
  `classifica_risposta` allowlist.
* PERMANENT: `piattaforma.py` (definition site), `recognition_bridge.py`
  (registry bridge plugin, wraps the classifier by design — see Gate 0 in
  `recognition_adapter.py`), and the AT call sites for `scopri_pagina_at`
  (`censimento.py` definition site, `connettore.py`, `inventory_discovery.py`)
  are expected to import these names indefinitely: AT recognition through the
  legacy classifier is not part of this strangler's BASE scope.

Limitation: this only sees `from module import name` (and plain `import
module` — walked for completeness even though no production file currently
uses that form). A call site that did `import treasureiq.ingest.piattaforma
as p` and then `p.classifica_risposta(...)` would not be caught. No
production file does that today (verified by grep); if one starts, this
guard's blind spot should be closed alongside it.
"""

from __future__ import annotations

import ast
from pathlib import Path

_GUARDED_NAMES = {"classifica_risposta", "firma_da_risposta", "scopri_pagina_at"}

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PRODUCTION_ROOT = _REPO_ROOT / "treasureiq"

# Per-symbol allowlist: relative path (from `api/treasureiq/`) -> reason.
# A file not listed here for a given symbol must not import that symbol.
_ALLOWED = {
    "classifica_risposta": {
        "ingest/piattaforma.py",  # definition site
        "catalog/recognition_bridge.py",  # registry bridge plugin (by design)
        "ingest/censimento.py",  # TEMPORARY: scopri_pagina_at's AT path (C1)
    },
    "firma_da_risposta": {
        "ingest/piattaforma.py",  # definition site
    },
    "scopri_pagina_at": {
        "ingest/censimento.py",  # definition site
        "connettore.py",  # AT confirmation, out of BASE migration scope
        "catalog/inventory_discovery.py",  # AT discovery call, unrelated to M1's BASE seam
    },
}


def _imported_guarded_names(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in _GUARDED_NAMES:
                    found.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                last_component = alias.name.rsplit(".", 1)[-1]
                if last_component in _GUARDED_NAMES:
                    found.add(last_component)
    return found


def _defined_guarded_names(tree: ast.AST) -> set[str]:
    """Top-level `def NAME(...)` — the definition site never imports its own
    name, so the import-based check alone would call it a stale allowlist
    entry. Only checked at module top level: none of the guarded names are
    ever nested defs in this codebase."""
    found: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _GUARDED_NAMES:
            found.add(node.name)
    return found


def test_only_the_allowlisted_files_import_the_legacy_classifier_seam():
    violations: list[str] = []
    for path in sorted(_PRODUCTION_ROOT.rglob("*.py")):
        relative = path.relative_to(_PRODUCTION_ROOT).as_posix()
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for name in _imported_guarded_names(tree):
            if relative not in _ALLOWED[name]:
                violations.append(f"{relative} imports {name!r} but is not in the allowlist")

    assert not violations, (
        "New/unreviewed import(s) of the legacy classifier seam found — "
        "either migrate the call site to firma_da_registro (recognition_adapter.py), "
        "or add it to _ALLOWED with a reason:\n" + "\n".join(violations)
    )


def test_allowlist_entries_still_exist_and_still_import_what_they_claim():
    # Keeps the allowlist itself honest: an entry that stops importing (or,
    # for a definition site, defining) the name it was added for — e.g. after
    # a later migration — should be removed here rather than left as a stale,
    # unverified exemption.
    for name, files in _ALLOWED.items():
        for relative in files:
            path = _PRODUCTION_ROOT / relative
            assert path.is_file(), f"allowlisted path {relative!r} for {name!r} does not exist"
            tree = ast.parse(path.read_text("utf-8"), filename=str(path))
            still_relevant = name in _imported_guarded_names(tree) or name in _defined_guarded_names(tree)
            assert still_relevant, (
                f"{relative} is allowlisted for {name!r} but no longer imports or defines it — "
                "remove the stale entry"
            )
