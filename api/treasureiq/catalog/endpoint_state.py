"""Stato persistente per (comune, superficie, entrypoint).

Fase 2D. Il `CheckResult` è la fotografia di *un* controllo; lo stato è la
memoria *fra* controlli. Serve per due cose concrete che una singola foto non
dà: sapere da quanto un endpoint è in un certo stato (stabilità, non flapping) e
contare i fallimenti di rete consecutivi che alimentano il backoff (2D-ii).

La transizione è **pura** e guidata dal core: `transiziona(stato, check)`
prende lo stato corrente e l'esito nuovo e ne ricava lo stato successivo, senza
I/O e senza orologio proprio (il tempo arriva dal `CheckResult.checked_at`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from treasureiq.catalog.checks import CheckResult, CheckStatus
from treasureiq.catalog.contracts import Surface, _StrictModel

#: Gli esiti che contano come "fallimento di rete" ai fini del backoff: l'host
#: non ha risposto. Un DIFFORME o un MANUAL_REVIEW NON sono guasti di rete —
#: l'endpoint è vivo, è il contratto a non tornare — quindi non fanno backoff.
_FALLIMENTI_RETE = frozenset({CheckStatus.UNAVAILABLE})


class EndpointState(_StrictModel):
    """Memoria di un endpoint fra un controllo e l'altro.

    Identità: ``(source_id, surface, entrypoint_url)``. Non è un secondo
    verdetto — quello sta nel `CheckResult`/`Aderenza`; qui vive solo ciò che
    richiede storia: da quando dura lo stato, quanti fallimenti di rete di fila,
    l'ultimo esito buono.
    """

    source_id: str = Field(min_length=1)
    surface: Surface
    entrypoint_url: str = Field(min_length=1)
    status: CheckStatus
    #: Fallimenti di rete consecutivi (solo UNAVAILABLE). Alimenta il backoff.
    fallimenti_consecutivi: int = Field(default=0, ge=0)
    #: Esiti OK consecutivi. Segnala stabilità recuperata.
    ok_consecutivi: int = Field(default=0, ge=0)
    #: Quando lo `status` corrente è stato raggiunto la prima volta (per capire
    #: da quanto dura senza confonderlo con un semplice ricontrollo).
    da: datetime
    ultimo_controllo_il: datetime
    ultimo_ok_il: datetime | None = None


def stato_iniziale(check: CheckResult, *, entrypoint_url: str) -> EndpointState:
    """Primo stato di un endpoint mai visto prima, dal suo primo controllo."""
    e_ok = check.status is CheckStatus.OK
    e_guasto = check.status in _FALLIMENTI_RETE
    return EndpointState(
        source_id=check.source_id,
        surface=check.surface,
        entrypoint_url=entrypoint_url,
        status=check.status,
        fallimenti_consecutivi=1 if e_guasto else 0,
        ok_consecutivi=1 if e_ok else 0,
        da=check.checked_at,
        ultimo_controllo_il=check.checked_at,
        ultimo_ok_il=check.checked_at if e_ok else None,
    )


def transiziona(stato: EndpointState, check: CheckResult) -> EndpointState:
    """Stato successivo dopo un nuovo controllo. Puro, nessun I/O.

    - `da` scatta solo quando lo stato **cambia**: un ricontrollo che conferma
      lo stesso esito non azzera la durata.
    - `fallimenti_consecutivi` cresce solo sui guasti di rete (UNAVAILABLE) e si
      azzera a ogni esito raggiungibile — è il segnale per il backoff, non un
      contatore di "tutto ciò che non è OK".
    - `ok_consecutivi` cresce sugli OK e si azzera a ogni non-OK.
    """
    e_ok = check.status is CheckStatus.OK
    e_guasto = check.status in _FALLIMENTI_RETE
    cambio_stato = check.status is not stato.status
    return stato.model_copy(
        update={
            "status": check.status,
            "fallimenti_consecutivi": (
                stato.fallimenti_consecutivi + 1 if e_guasto else 0
            ),
            "ok_consecutivi": stato.ok_consecutivi + 1 if e_ok else 0,
            "da": check.checked_at if cambio_stato else stato.da,
            "ultimo_controllo_il": check.checked_at,
            "ultimo_ok_il": check.checked_at if e_ok else stato.ultimo_ok_il,
        }
    )
