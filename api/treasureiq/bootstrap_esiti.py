"""Per-comune ledger of Base bootstrap outcomes (``data-live/_bootstrap_esiti.json``).

One entry per comune the bootstrap ever tried: last outcome, when, how many
attempts, and when it may be tried again. It replaces per-lot checkpoints as
the memory of the continuous worker, so a comune that came back empty is not
re-read at every cycle, and it is what the monitoring page reads to show
progress and errors.

Outcomes are the ones ``registro_cli._scansiona_uno`` returns. An ``ok``
writes a connettore record and from then on belongs to the refresh loop, so it
has no retry date.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ESITI_FILENAME = "_bootstrap_esiti.json"

#: How long to wait before re-reading a comune, per outcome. A vuoto is a
#: successful read with nothing to keep (the site rarely changes in days); an
#: errore is usually transient; a network failure is often an IP block that
#: lasts. Mirrors ``registro_cli.RETE_BACKOFF_DAYS`` for the network case.
ATTESA_PER_ESITO: dict[str, timedelta | None] = {
    "ok": None,
    "vuoto": timedelta(days=14),
    "errore": timedelta(days=1),
    "rete_non_raggiungibile": timedelta(days=14),
}


def percorso(live_dir: Path) -> Path:
    return live_dir / ESITI_FILENAME


def carica(live_dir: Path) -> dict[str, dict]:
    """The ledger, or empty when missing or corrupt (it is rebuilt by use)."""
    try:
        dati = json.loads(percorso(live_dir).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    comuni = dati.get("comuni") if isinstance(dati, dict) else None
    if not isinstance(comuni, dict):
        return {}
    return {c: v for c, v in comuni.items() if isinstance(c, str) and isinstance(v, dict)}


def registra(
    live_dir: Path, istat: str, esito: str, nota: str, ora: datetime | None = None
) -> None:
    """Record one outcome, atomically. A write failure is logged, never raised:
    losing one ledger line only costs an early re-read."""
    ora = ora or datetime.now(timezone.utc)
    comuni = carica(live_dir)
    attesa = ATTESA_PER_ESITO.get(esito, ATTESA_PER_ESITO["errore"])
    comuni[istat] = {
        "esito": esito,
        "il": ora.isoformat(),
        "prossimo_il": (ora + attesa).isoformat() if attesa else None,
        "tentativi": int(comuni.get(istat, {}).get("tentativi", 0)) + 1,
        "nota": nota,
    }
    destinazione = percorso(live_dir)
    try:
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = destinazione.with_suffix(".tmp")
        provvisorio.write_text(
            json.dumps({"comuni": comuni}, ensure_ascii=False, indent=1), "utf-8"
        )
        provvisorio.replace(destinazione)
    except OSError as exc:
        logger.warning("esiti bootstrap non scrivibili (%s): %s", destinazione, exc)


def in_attesa(comuni: dict[str, dict], ora: datetime | None = None) -> set[str]:
    """Comuni whose retry date is still in the future."""
    ora = ora or datetime.now(timezone.utc)
    attesa: set[str] = set()
    for codice, voce in comuni.items():
        try:
            prossimo = datetime.fromisoformat(voce.get("prossimo_il") or "")
        except (TypeError, ValueError):
            continue
        if prossimo.tzinfo is None:
            prossimo = prossimo.replace(tzinfo=timezone.utc)
        if prossimo > ora:
            attesa.add(codice)
    return attesa
