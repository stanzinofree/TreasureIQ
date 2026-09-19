"""Per-domain request pacing for the refresh/sweep path.

``fetch_guardato`` and ``_Sonda`` hammer a single comune's host with many
sequential GETs during a refresh: OpenPA/OpenCity readers walk home + offices +
areas + Amministrazione Trasparente + service pages, all on the same domain.
Those portals answer ``429 Too Many Requests`` to the burst, so pages drop out
of an otherwise successful refresh (the batch still returns 0, freshness is just
less complete).

This adds an **opt-in** per-domain minimum interval plus a bounded, 429-aware
backoff. It is scoped to a refresh through a ``ContextVar``: outside a refresh
the pacer is ``None`` and both fetch paths behave exactly as before — the live
chat resolver shares ``fetch_guardato`` and must pay nothing.

Self-contained on purpose: it mirrors ``catalog.fetch_policy.LimitatoreDominio``
but does not import it, so ``ingest`` gains no dependency on ``catalog`` (the
edge already runs the other way, ``catalog.fetch_runtime`` -> ``ingest``).
"""

from __future__ import annotations

import contextvars
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


def dominio_di(url: str) -> str:
    """Normalised host (lowercase, no ``www.``) used as the pacing key.

    ``www.comune.x`` and ``comune.x`` are the same host to be polite to;
    counting them apart would halve the spacing.
    """
    host = urlsplit(url).netloc.lower()
    if "@" in host:  # strip any userinfo
        host = host.rsplit("@", 1)[1]
    if ":" in host:  # strip the port
        host = host.rsplit(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PacerDominio:
    """Per-domain sequential-request pacer with a bounded 429 backoff.

    State is the last-request instant per domain. Unlike the pure
    ``fetch_policy`` primitives this one owns the clock and really sleeps: it is
    the dirty edge, driven by a real refresh loop, not a policy decision tested
    on an injected ``now``. Scope one instance per comune (via the ContextVar):
    within a comune every read hits the same host, so a single instant per host
    is all the state a burst needs.
    """

    def __init__(
        self,
        *,
        intervallo_minimo_s: float = 0.5,
        max_retry_429: int = 2,
        max_429_dominio: int = 3,
        backoff_base_s: float = 2.0,
        backoff_cap_s: float = 30.0,
    ) -> None:
        self._intervallo = max(0.0, intervallo_minimo_s)
        self._max_retry = max(0, max_retry_429)
        self._max_429_dominio = max(1, max_429_dominio)
        self._base = backoff_base_s
        self._cap = backoff_cap_s
        self._ultimo: dict[str, datetime] = {}
        self._429_consecutivi: dict[str, int] = {}
        self._domini_bloccati: set[str] = set()

    def bloccato(self, url: str) -> bool:
        """True when this domain has exhausted its 429 budget for this comune."""
        return dominio_di(url) in self._domini_bloccati

    def prima(self, url: str) -> None:
        """Sleep the residual min-interval before a GET to ``url``'s domain."""
        if self._intervallo <= 0:
            return
        ultimo = self._ultimo.get(dominio_di(url))
        if ultimo is None:
            return
        attesa = self._intervallo - (_now() - ultimo).total_seconds()
        if attesa > 0:
            time.sleep(attesa)

    def dopo(self, url: str, status_code: int | None = None) -> None:
        """Mark a GET and update the consecutive-429 circuit state."""
        dominio = dominio_di(url)
        self._ultimo[dominio] = _now()
        if status_code == 429:
            consecutivi = self._429_consecutivi.get(dominio, 0) + 1
            self._429_consecutivi[dominio] = consecutivi
            if consecutivi >= self._max_429_dominio:
                self._domini_bloccati.add(dominio)
                logger.warning(
                    "circuito pacing aperto per %s dopo %d risposte 429",
                    dominio,
                    consecutivi,
                )
        elif status_code is not None:
            self._429_consecutivi.pop(dominio, None)
            self._domini_bloccati.discard(dominio)

    def backoff_429(
        self, url: str, tentativo: int, retry_after_s: float | None = None
    ) -> bool:
        """Handle a 429: sleep, then say whether the caller should retry.

        Honours ``Retry-After`` when the server sent one, else an exponential
        backoff capped at ``backoff_cap_s``. Returns ``False`` once
        ``max_retry_429`` attempts are spent, so the caller stops instead of
        looping forever on a host that keeps refusing.
        """
        if tentativo >= self._max_retry:
            return False
        if self.bloccato(url):
            return False
        if retry_after_s is not None and retry_after_s >= 0:
            attesa = min(self._cap, retry_after_s)
        else:
            attesa = min(self._cap, self._base * (2.0**tentativo))
        logger.info(
            "429 su %s: backoff %.1fs (tentativo %d/%d)",
            url,
            attesa,
            tentativo + 1,
            self._max_retry,
        )
        if attesa > 0:
            time.sleep(attesa)
        return True


def retry_after_secondi(valore: str | None) -> float | None:
    """Parse a ``Retry-After`` header value into seconds, or ``None``.

    Only the delta-seconds form is honoured (the HTTP-date form is rare on the
    municipal portals seen here and not worth a date parser); a malformed or
    absent value yields ``None`` so the caller falls back to its own backoff.
    """
    if not valore:
        return None
    try:
        secondi = float(valore.strip())
    except (TypeError, ValueError):
        return None
    return secondi if secondi >= 0 else None


#: Active pacer for the current context, or ``None`` outside a refresh. Both
#: ``_Sonda`` and ``fetch_guardato`` consult it; the refresh loop sets it.
_ATTIVO: contextvars.ContextVar[PacerDominio | None] = contextvars.ContextVar(
    "treasureiq_pacer_dominio", default=None
)


def pacer_attivo() -> PacerDominio | None:
    """The pacer scoped to the current context, or ``None`` (no pacing)."""
    return _ATTIVO.get()


def attiva_pacer(pacer: PacerDominio | None) -> contextvars.Token:
    """Install ``pacer`` for the current context; returns a restore token."""
    return _ATTIVO.set(pacer)


def ripristina_pacer(token: contextvars.Token) -> None:
    """Restore the pacer that was active before the matching ``attiva_pacer``."""
    _ATTIVO.reset(token)
