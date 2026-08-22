"""Verdetto unico di aderenza per (comune, connettore).

Fase 2C. Oggi tre segnali di aderenza vivono scollegati: il `recognition_score`
e il drift stanno nel `CheckResult` del path catalog (per-fingerprint), la
copertura reale del modello dati è misurata solo dal censimento (`_aderenza`,
per-modello, e per una manciata di famiglie). Nessuno li fonde in un verdetto
per (comune, connettore).

Questo modulo lo fa in modo **famiglia-agnostico**: opera sul `CheckResult`
uniforme più una copertura misurata opzionale, senza sapere nulla di WordPress
o MyPortal e senza fare I/O. La misura di copertura arriva da chi la sa
calcolare (il censimento); qui si fonde, non si misura — coerente con la scelta
"fusione in catalog" e con l'invariante "confirmation = solo liveness".
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from pydantic import Field

from treasureiq.catalog.checks import CheckResult, CheckStatus
from treasureiq.catalog.contracts import Surface, _StrictModel


def coverage_da_misura(misura: Mapping[str, object] | None) -> float | None:
    """Estrae la copertura 0..1 dal dict di misura del censimento.

    Il censimento (`_aderenza_wp`/`_myportal`/scheda HTML generica) ritorna una
    forma uniforme: la chiave ``aderenza`` c'è solo quando una scheda campione è
    stata letta davvero, altrimenti c'è solo ``nota_misura`` (indice vuoto,
    pagina fuori modello, API non raggiunta...). Un `None` qui significa "non
    misurata", diverso da uno zero — non abbiamo guardato, non è inadempienza.
    """
    if not misura:
        return None
    valore = misura.get("aderenza")
    if isinstance(valore, (int, float)) and not isinstance(valore, bool):
        return max(0.0, min(1.0, float(valore)))
    return None


class Aderenza(_StrictModel):
    """Aderenza fusa di un connettore su un comune: un solo verdetto.

    Chiave logica: ``(source_id, connettore, surface)``. Fonde riconoscimento
    (il connettore è ancora quello?), copertura misurata (quanto del modello
    dati espone davvero) e drift (la piattaforma è cambiata sotto il contratto).
    """

    source_id: str = Field(min_length=1)  # comune (ISTAT)
    connettore: str | None = None          # piattaforma riconosciuta
    surface: Surface
    status: CheckStatus
    recognition_score: float | None = Field(default=None, ge=0.0, le=1.0)
    coverage_score: float | None = Field(default=None, ge=0.0, le=1.0)
    #: Sintesi 0..1: la copertura misurata, sbloccata dal riconoscimento e
    #: azzerata a None dal drift. None = non sintetizzabile (non riconosciuto,
    #: difforme, o copertura non misurata), mai uno zero inventato.
    verdetto: float | None = Field(default=None, ge=0.0, le=1.0)
    difforme: bool = False
    fingerprint: str | None = None
    misurata_il: datetime


def fondi_aderenza(
    check: CheckResult, *, coverage: float | None = None
) -> Aderenza:
    """Fonde un `CheckResult` con una copertura misurata (opzionale).

    Funzione pura, nessun I/O: prende ciò che il path catalog ha già osservato
    (riconoscimento + drift + fingerprint) e la copertura che il censimento sa
    misurare, e ne ricava il verdetto unico. Vale per **tutte** le famiglie
    perché lavora sul `CheckResult` uniforme, non sul codice per-piattaforma.

    Regole del `verdetto` (la copertura è la misura, il riconoscimento la
    sblocca, il drift la invalida):

    - drift (DIFFORME) → ``None``: la copertura, se c'è, è stata misurata contro
      un contratto che non vale più — sommarla ingannerebbe.
    - non riconosciuto (MANUAL_REVIEW / recognition 0) → ``None``: non sappiamo
      di quale contratto parlare.
    - riconosciuto + copertura misurata → la copertura stessa.
    - riconosciuto + copertura non misurata → ``None`` (onesto, non uno zero).
    """
    difforme = check.status is CheckStatus.DIFFORME
    riconosciuto = check.status not in {
        CheckStatus.DIFFORME,
        CheckStatus.MANUAL_REVIEW,
        CheckStatus.UNAVAILABLE,
        CheckStatus.UNKNOWN,
    }
    # La copertura fornita ha la precedenza; in mancanza si usa quella che il
    # check porta già con sé (oggi None sul path confirmation).
    coverage_score = coverage if coverage is not None else check.coverage_score
    verdetto = coverage_score if (riconosciuto and not difforme) else None
    piattaforma = check.identity.get("platform")
    connettore = piattaforma if isinstance(piattaforma, str) else check.connector_id
    return Aderenza(
        source_id=check.source_id,
        connettore=connettore,
        surface=check.surface,
        status=check.status,
        recognition_score=check.recognition_score,
        coverage_score=coverage_score,
        verdetto=verdetto,
        difforme=difforme,
        fingerprint=check.fingerprint,
        misurata_il=check.checked_at,
    )
