"""Entrypoint committato di promozione IMIS (``tributi_imu``) nel catalogo flat.

Toglie la promozione dagli script scratchpad e la rende riproducibile: un solo
comando che consuma il gate :func:`imis_allowlist.problemi_promozione` — l'unico
consumatore ufficiale dell'allowlist — decide per ogni comune
``PROMOSSO`` / ``ESCLUSO`` / ``SKIP-ESISTENTE`` e, solo con ``--apply``,
materializza la voce in ``data/catalog/{istat}.json`` col round-trip
``model_dump`` (nessun campo a mano). Default **dry-run**: stampa il rapporto
senza toccare nulla.

Confini (invarianti):

- NON tocca runtime, DB, cache, ``data-live``: scrive SOLO in
  ``data/catalog/{istat}.json`` (una chiave ``ServiceKey`` per file).
- Zero-overwrite: se la chiave esiste già per quel comune → ``SKIP``, mai
  sovrascritta (ricontrollato appena prima della scrittura).
- La raccolta live (``retrieve``) è dietro un seam iniettabile
  (:class:`RaccoglitoreLive` di default; un callback qualsiasi nei test), così la
  logica di gate e scrittura resta verificabile senza rete.

Esempio::

    PYTHONPATH=. python -m treasureiq.catalog.imis_promote \\
        --istat 022236 --apply
    PYTHONPATH=. python -m treasureiq.catalog.imis_promote \\
        --istat-file /tmp/istat.txt --json-out /tmp/rapporto.json   # dry-run
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from treasureiq.catalog.imis_allowlist import etichetta_delegata, problemi_promozione
from treasureiq.catalog.service_catalog import catalog_dir
from treasureiq.catalog.service_contracts import (
    ServiceAccessMode,
    ServiceKey,
    ServiceReference,
)
from treasureiq.ingest.host_guard import host_senza_www

#: Callback di raccolta: da ``(istat, service_key)`` a ``(ServiceReference|None,
#: nota)``.  ``None`` + causa = comune non raccoglibile (non risolto, connettore
#: assente, ambiguo, drift): l'esito diventa ``ESCLUSO`` con la causa.
Raccoglitore = Callable[[str, ServiceKey], "tuple[ServiceReference | None, str]"]


class Esito(str, Enum):
    PROMOSSO = "promosso"
    ESCLUSO = "escluso"
    SKIP_ESISTENTE = "skip_esistente"


@dataclass(frozen=True)
class Valutazione:
    """Verdetto del gate per un singolo comune."""

    istat: str
    esito: Esito
    service_id: str | None = None
    delegated_host: str | None = None
    motivi: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        d: dict = {"istat": self.istat, "esito": self.esito.value}
        if self.service_id is not None:
            d["service_id"] = self.service_id
        if self.delegated_host is not None:
            d["delegated_host"] = self.delegated_host
        if self.motivi:
            d["motivi"] = list(self.motivi)
        return d


def _host(url: str) -> str:
    return host_senza_www((urlsplit(url).netloc or "").lower().split(":")[0])


# --------------------------------------------------------------------------- #
# Gate (net-free): valuta una ServiceReference già raccolta.                   #
# --------------------------------------------------------------------------- #
def valuta_referenza(ref: ServiceReference, istat: str) -> Valutazione:
    """Applica il gate committato alla reference; nessuna rete, nessuna scrittura.

    ``ESCLUSO`` con i motivi del gate se ``problemi_promozione`` non è vuoto;
    altrimenti ``PROMOSSO``, annotando l'eventuale host delegato
    (``authenticated_online`` ammesso per quell'ISTAT).
    """
    problemi = problemi_promozione(ref, istat)
    if problemi:
        return Valutazione(
            istat, Esito.ESCLUSO, service_id=ref.service_id, motivi=tuple(problemi)
        )
    delegato: str | None = None
    for opzione in ref.options:
        if opzione.mode is ServiceAccessMode.AUTHENTICATED_ONLINE:
            delegato = etichetta_delegata(_host(str(opzione.url)), istat)
            break
    return Valutazione(
        istat, Esito.PROMOSSO, service_id=ref.service_id, delegated_host=delegato
    )


def materializza_entry(ref: ServiceReference, *, promo_date: str) -> dict:
    """Entry di catalogo via round-trip ufficiale; normalizza solo ``discovered_at``.

    ``model_dump(mode="json")`` è l'unico contratto (il reader
    ``service_catalog.carica`` fa ``model_validate`` sulla stessa entry): nessun
    campo costruito a mano.  ``discovered_at`` allineato alla data del batch,
    come le voci IMIS già promosse (tutte a ``T00:00:00Z``).
    """
    entry = ref.model_dump(mode="json")
    entry["discovered_at"] = promo_date
    return entry


# --------------------------------------------------------------------------- #
# I/O catalogo: SOLO data/catalog/{istat}.json, formato byte-fedele.           #
# --------------------------------------------------------------------------- #
def _percorso(istat: str, base: Path) -> Path:
    return base / f"{istat}.json"


def carica_doc(istat: str, base: Path) -> dict | None:
    """Documento catalogo del comune, o ``None`` se il file non esiste."""
    percorso = _percorso(istat, base)
    if not percorso.is_file():
        return None
    return json.loads(percorso.read_text(encoding="utf-8"))


def servizio_presente(doc: dict | None, key: ServiceKey) -> bool:
    return isinstance(doc, dict) and key.value in (doc.get("services") or {})


def scrivi_entry(istat: str, key: ServiceKey, entry: dict, base: Path) -> None:
    """Inserisce ``entry`` sotto ``key`` preservando gli altri servizi.

    Formato identico ai file esistenti: ``indent=1``, ``ensure_ascii=False``,
    **nessun newline finale**.  Se il file non esiste lo crea con lo schema
    minimo (``municipality_istat`` + ``services``).
    """
    percorso = _percorso(istat, base)
    doc = carica_doc(istat, base)
    if doc is None:
        doc = {"municipality_istat": istat, "services": {}}
    doc.setdefault("services", {})[key.value] = entry
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8"
    )  # niente newline finale, come le voci già promosse


# --------------------------------------------------------------------------- #
# Rapporto.                                                                    #
# --------------------------------------------------------------------------- #
@dataclass
class Rapporto:
    """Esito complessivo del giro: promossi, esclusi, skip-esistenti."""

    apply: bool = False
    promossi: list[Valutazione] = field(default_factory=list)
    esclusi: list[Valutazione] = field(default_factory=list)
    skip: list[Valutazione] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "apply": self.apply,
            "totali": {
                "promossi": len(self.promossi),
                "esclusi": len(self.esclusi),
                "skip_esistenti": len(self.skip),
            },
            "promossi": [v.as_dict() for v in self.promossi],
            "esclusi": [v.as_dict() for v in self.esclusi],
            "skip_esistenti": [v.as_dict() for v in self.skip],
        }

    def render(self) -> str:
        modo = "APPLY (scritture)" if self.apply else "DRY-RUN (nessuna scrittura)"
        righe = [
            f"promozione IMIS — {modo}",
            f"  promossi={len(self.promossi)}  "
            f"esclusi={len(self.esclusi)}  skip={len(self.skip)}",
        ]
        for v in self.promossi:
            marca = f" [{v.delegated_host}]" if v.delegated_host else ""
            righe.append(f"  PROMOSSO {v.istat}  {v.service_id}{marca}")
        for v in self.skip:
            righe.append(f"  SKIP     {v.istat}  (gia' presente)")
        for v in self.esclusi:
            righe.append(f"  ESCLUSO  {v.istat}  {'; '.join(v.motivi)}")
        return "\n".join(righe)


# --------------------------------------------------------------------------- #
# Pipeline (net-free: la rete vive dentro `raccogli`).                         #
# --------------------------------------------------------------------------- #
def esegui(
    istat_list: list[str],
    key: ServiceKey,
    *,
    base: Path,
    promo_date: str,
    apply: bool,
    raccogli: Raccoglitore,
) -> Rapporto:
    """Per ogni ISTAT: skip-se-esistente → raccolta → gate → (apply) scrittura."""
    rapporto = Rapporto(apply=apply)
    for istat in istat_list:
        if servizio_presente(carica_doc(istat, base), key):
            rapporto.skip.append(Valutazione(istat, Esito.SKIP_ESISTENTE))
            continue

        ref, nota = raccogli(istat, key)
        if ref is None:
            rapporto.esclusi.append(
                Valutazione(istat, Esito.ESCLUSO, motivi=(f"raccolta: {nota}",))
            )
            continue

        valutazione = valuta_referenza(ref, istat)
        if valutazione.esito is Esito.ESCLUSO:
            rapporto.esclusi.append(valutazione)
            continue

        if apply:
            # Zero-overwrite ricontrollato subito prima di scrivere (un altro
            # passo del lotto potrebbe aver appena creato la chiave).
            if servizio_presente(carica_doc(istat, base), key):
                rapporto.skip.append(Valutazione(istat, Esito.SKIP_ESISTENTE))
                continue
            scrivi_entry(
                istat, key, materializza_entry(ref, promo_date=promo_date), base
            )
        rapporto.promossi.append(valutazione)
    return rapporto


# --------------------------------------------------------------------------- #
# Raccoglitore live (rete): fuori dai test unitari.                           #
# --------------------------------------------------------------------------- #
class RaccoglitoreLive:
    """Raccolta live via ``retrieve()`` con conferma *exactly-one*.

    Un solo esecutore/registry riusati per l'intero lotto (memoizza gli host
    raggiungibili).  Import ritardati: il modulo resta importabile (e i test
    net-free girano) senza toccare la rete finché non lo si istanzia/chiama.
    """

    def __init__(self) -> None:
        from treasureiq.catalog.measurement_sweep import _nuovo_esecutore
        from treasureiq.catalog.service_registry import default_service_registry

        self._esecutore = _nuovo_esecutore()
        self._registry = default_service_registry(self._esecutore)
        self._host_raggiungibili: dict[str, bool] = {}

    def __call__(
        self, istat: str, key: ServiceKey
    ) -> tuple[ServiceReference | None, str]:
        from treasureiq.catalog.data_contracts import DataStatus
        from treasureiq.catalog.measurement_sweep import (
            _diagnostica_affidabile,
            _risolvi_mappa_live,
        )
        from treasureiq.catalog.planner import service_request
        from treasureiq.registro import leggi_registro

        mappa, nota = _risolvi_mappa_live(istat, esecutore=self._esecutore)
        if mappa is None:
            return None, f"comune_non_risolto ({nota})"

        record = leggi_registro(istat)
        platform_id = (record.piattaforma if record else "") or "openpa"
        richiesta = service_request(source_id=istat, service_key=key, namespace="promo")
        connettore = self._registry.resolve(request=richiesta, platform_id=platform_id)
        if connettore is None:
            return None, "connettore_non_disponibile"

        diag, nota_d = _diagnostica_affidabile(
            connettore,
            richiesta,
            mappa,
            tentativi=2,
            backoff_s=2.0,
            host_raggiungibili=self._host_raggiungibili,
        )
        if diag.confermati != 1:
            return None, f"non_exactly_one (confermati={diag.confermati}, {nota_d})"

        res = connettore.retrieve(richiesta, mappa=mappa, esito=None)
        if res.status is not DataStatus.FULFILLED or len(res.service_references) != 1:
            return None, f"drift_retrieve ({res.status.value}/{len(res.service_references)})"
        return res.service_references[0], "ok"


# --------------------------------------------------------------------------- #
# CLI.                                                                         #
# --------------------------------------------------------------------------- #
def _istat_richiesti(args: argparse.Namespace) -> list[str]:
    lista = list(args.istat or [])
    if args.istat_file:
        for riga in Path(args.istat_file).read_text(encoding="utf-8").splitlines():
            riga = riga.strip()
            if riga and not riga.startswith("#"):
                lista.append(riga)
    visti: set[str] = set()
    ordinati: list[str] = []
    for istat in lista:
        if istat not in visti:
            visti.add(istat)
            ordinati.append(istat)
    return ordinati


def _oggi_batch() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")


def main(argv: list[str] | None = None, *, raccogli: Raccoglitore | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.catalog.imis_promote",
        description="Promozione gated di servizi IMIS nel catalogo flat "
        "(dry-run di default; scrive solo con --apply).",
    )
    parser.add_argument(
        "--istat", action="append", metavar="ISTAT", help="codice ISTAT (ripetibile)"
    )
    parser.add_argument(
        "--istat-file", metavar="PATH", help="file con un ISTAT per riga (# = commento)"
    )
    parser.add_argument(
        "--service-key",
        default=ServiceKey.TRIBUTI_IMU.value,
        help=f"ServiceKey da promuovere (default {ServiceKey.TRIBUTI_IMU.value})",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="radice dati; il catalogo è {data-dir}/catalog "
        "(default: TREASUREIQ_DATA_DIR o data/)",
    )
    parser.add_argument(
        "--promo-date",
        default=None,
        help="discovered_at del batch, ISO Z (default: oggi T00:00:00Z)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="scrive le voci promosse (senza, è dry-run)",
    )
    parser.add_argument(
        "--json-out", type=Path, default=None, help="scrive il rapporto JSON su file"
    )
    args = parser.parse_args(argv)

    istat_list = _istat_richiesti(args)
    if not istat_list:
        parser.error("nessun ISTAT indicato (usa --istat o --istat-file)")
    try:
        key = ServiceKey(args.service_key)
    except ValueError:
        parser.error(f"service-key sconosciuta: {args.service_key!r}")

    base = (args.data_dir / "catalog") if args.data_dir is not None else catalog_dir()
    promo_date = args.promo_date or _oggi_batch()
    if raccogli is None:
        raccogli = RaccoglitoreLive()

    rapporto = esegui(
        istat_list, key, base=base, promo_date=promo_date, apply=args.apply, raccogli=raccogli
    )
    print(rapporto.render())
    if args.json_out:
        args.json_out.write_text(
            json.dumps(rapporto.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
