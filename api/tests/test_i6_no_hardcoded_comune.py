"""I6 guard: no hardcoded comune used as a *fallback* in production.

Invariant I6 of the source-engine rewrite: production never substitutes a fixed
comune for an unknown one. Three such fallbacks existed and were removed —
``_risposta_bandi`` (``... or DEFAULT_COMUNE_ISTAT``), the ``_build_informazione_answer``
gate (``if ente.codice_istat == DEFAULT_COMUNE_ISTAT``), and the ``/chat`` handler
(``scelto or DEFAULT_COMUNE_ISTAT``). This test is the tripwire that stops any of
them, or a new one, from coming back.

It does **not** ban the constants. ``DEFAULT_COMUNE_ISTAT`` / ``DEFAULT_COMUNE_NOME``
legitimately exist (they name Albano, the demo comune) and are legitimately
returned by ``_resolve_comune`` when the citizen actually *names* Albano — that is
identity resolution, not a silent substitution. What is banned is the two shapes a
fallback takes:

* ``<expr> or DEFAULT_COMUNE_*``  — a boolean-or default;
* ``<expr> == DEFAULT_COMUNE_*`` (or ``!=``) — a gate keyed on the fixed comune.

Both read a hardcoded comune where the citizen's own comune belongs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import treasureiq

BANNED = {"DEFAULT_COMUNE_ISTAT", "DEFAULT_COMUNE_NOME"}

#: Where the constants are *defined*; a plain assignment there is not a fallback.
DEFINITION_MODULE = "chat/respond.py"

PACKAGE_ROOT = Path(treasureiq.__file__).resolve().parent


def _production_modules() -> list[Path]:
    """Every shipped ``.py`` under the package (tests live outside it)."""
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _names(node: ast.AST) -> set[str]:
    """The banned constant names referenced directly inside ``node``.

    Matches both a bare ``DEFAULT_COMUNE_ISTAT`` (``ast.Name``) and a qualified
    ``respond.DEFAULT_COMUNE_ISTAT`` (``ast.Attribute``).
    """
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in BANNED:
            found.add(child.id)
        elif isinstance(child, ast.Attribute) and child.attr in BANNED:
            found.add(child.attr)
    return found


def _fallback_violations(tree: ast.AST) -> list[tuple[int, str]]:
    """Fallback-shaped uses of a banned constant: ``x or DEFAULT`` / ``== DEFAULT``."""
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            # `x or DEFAULT_COMUNE_*` — the constant stands in for a missing comune.
            for operand in node.values:
                if _names(operand):
                    violations.append((node.lineno, "boolean-or fallback"))
                    break
        elif isinstance(node, ast.Compare):
            # `something == DEFAULT_COMUNE_*` — a gate keyed on the fixed comune.
            parts = [node.left, *node.comparators]
            if any(_names(part) for part in parts):
                violations.append((node.lineno, "comparison gate"))
    return violations


def test_no_default_comune_used_as_fallback_in_production() -> None:
    offenders: list[str] = []
    for module in _production_modules():
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for lineno, shape in _fallback_violations(tree):
            rel = module.relative_to(PACKAGE_ROOT).as_posix()
            offenders.append(f"{rel}:{lineno}: {shape}")

    assert not offenders, (
        "I6 violated — a hardcoded comune is used as a fallback in production. "
        "Resolve the citizen's own comune instead (or ask for it). Offenders:\n"
        + "\n".join(offenders)
    )


def test_guard_is_alive_definition_is_present() -> None:
    """Sanity: the constants still exist where expected, so a rename can't turn
    this guard into a silent no-op that greenlights a reborn fallback."""
    definition = (PACKAGE_ROOT / DEFINITION_MODULE).read_text(encoding="utf-8")
    for name in BANNED:
        assert f"{name} = " in definition, f"{name} definition moved — update this guard"
