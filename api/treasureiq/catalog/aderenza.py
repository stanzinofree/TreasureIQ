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
from treasureiq.catalog.recognition import RecognitionResult

#: Census platform family -> platform ids the recognition may report for the
#: same data contract. The census measures families (one service-sheet model
#: per family); recognition names connectors. Only a match lets a coverage
#: measured by the census describe the connector that was recognised.
FAMIGLIE_CENSIMENTO: dict[str, frozenset[str]] = {
    "wp_design_comuni": frozenset({
        "wp_design_comuni", "wordpress_generico", "wordpress_agid", "comunibootstrapitalia",
    }),
    "peopleweb": frozenset({"peopleweb", "openweb"}),  # Siscom + SoluzioniPA OpenWeb
    "comweb": frozenset({"comweb"}),
}


def stessa_famiglia(piattaforma_censimento: object, piattaforma_riconosciuta: object) -> bool:
    """True when the census measured the same data contract that was recognised."""
    famiglia = FAMIGLIE_CENSIMENTO.get(str(piattaforma_censimento or ""))
    return bool(famiglia and piattaforma_riconosciuta in famiglia)


def check_da_riconoscimento(risultato: RecognitionResult) -> CheckResult:
    """The `CheckResult` view of a persisted recognition, for `fondi_aderenza`.

    The recognition's own `coverage_score` (connector capabilities recovered)
    is deliberately NOT carried over: the verdict must come from the census's
    data-model coverage, not from a different measure under the same name.
    """
    riconosciuto = bool(risultato.platform_id) and risultato.recognition_score > 0
    return CheckResult(
        source_id=risultato.source_id,
        surface=risultato.surface,
        status=CheckStatus.OK if riconosciuto else CheckStatus.UNKNOWN,
        source_health=risultato.source_health,
        recognition_score=risultato.recognition_score,
        connector_id=risultato.connector_id,
        connector_version=risultato.connector_version,
        fingerprint_version=risultato.fingerprint_version,
        fingerprint=risultato.fingerprint,
        identity={"platform": risultato.platform_id},
        evidence=risultato.evidence,
        failure_reason=risultato.failure_reason,
        action=risultato.action,
        checked_at=risultato.checked_at,
    )


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
    connettore: str | None = None          # motore/plugin (connector_id)
    piattaforma: str | None = None         # piattaforma riconosciuta (identity)
    surface: Surface
    status: CheckStatus
    recognition_score: float | None = Field(default=None, ge=0.0, le=1.0)
    coverage_score: float | None = Field(default=None, ge=0.0, le=1.0)
    #: What the coverage was measured against (census `base_misura`):
    #: `modello_intero` (the whole AgID model) or `schema_esposto` (only the
    #: boxes the portal API exposes). None when unknown or not measured.
    coverage_base: str | None = None
    #: When the coverage was measured (census `rilevato_il`), verbatim.
    coverage_misurata_il: str | None = None
    #: Sintesi 0..1: la copertura misurata, sbloccata dal riconoscimento e
    #: azzerata a None dal drift. None = non sintetizzabile (non riconosciuto,
    #: difforme, o copertura non misurata), mai uno zero inventato.
    verdetto: float | None = Field(default=None, ge=0.0, le=1.0)
    difforme: bool = False
    fingerprint: str | None = None
    misurata_il: datetime


def fondi_aderenza(
    check: CheckResult,
    *,
    coverage: float | None = None,
    coverage_base: str | None = None,
    coverage_misurata_il: str | None = None,
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
    - non riconosciuto → ``None``: senza un `recognition_score` positivo non
      sappiamo di quale contratto parlare. Uno stato OK non basta (SOURCE_IDENTITY
      può essere OK con recognition non misurato): serve il riconoscimento vero.
    - riconosciuto + copertura misurata → la copertura stessa.
    - riconosciuto + copertura non misurata → ``None`` (onesto, non uno zero).
    - copertura misurata solo sullo schema esposto (``coverage_base ==
      "schema_esposto"``) → ``None``: è registrata nel record, ma il 100% dei
      box che l'API espone non prova la conformità al modello intero.
    """
    difforme = check.status is CheckStatus.DIFFORME
    # La recognition sblocca la coverage solo se è davvero avvenuta: uno score
    # positivo, non il semplice "stato non pessimo". Così un OK senza
    # riconoscimento (recognition_score None) non produce mai un verdetto.
    riconosciuto = (
        check.recognition_score is not None and check.recognition_score > 0
    )
    # La copertura fornita ha la precedenza; in mancanza si usa quella che il
    # check porta già con sé (oggi None sul path confirmation).
    coverage_score = coverage if coverage is not None else check.coverage_score
    sintetizzabile = riconosciuto and not difforme and coverage_base != "schema_esposto"
    verdetto = coverage_score if sintetizzabile else None
    # connettore = motore/plugin (connector_id), stabile per il versionamento e
    # per l'admin; piattaforma = ciò che il riconoscimento ha visto. Sono due
    # cose diverse e vanno tenute separate, non collassate su una chiave sola.
    piattaforma = check.identity.get("platform")
    return Aderenza(
        source_id=check.source_id,
        connettore=check.connector_id,
        piattaforma=piattaforma if isinstance(piattaforma, str) else None,
        surface=check.surface,
        status=check.status,
        recognition_score=check.recognition_score,
        coverage_score=coverage_score,
        coverage_base=coverage_base,
        coverage_misurata_il=coverage_misurata_il,
        verdetto=verdetto,
        difforme=difforme,
        fingerprint=check.fingerprint,
        misurata_il=check.checked_at,
    )
