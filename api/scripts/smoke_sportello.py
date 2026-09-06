"""Smoke live READ-ONLY del connettore Sportello Telematico (ciclo 1).

Opt-in: gira solo con ``TREASUREIQ_SMOKE_SPORTELLO=1`` (rete verso i comuni
reali). NON promuove, NON scrive, NON cacha nulla: risolve e stampa. Comuni
campione: Cologno Monzese (indice paginato) e Pomezia (sitemap flat).

Asserzione dura: Cologno IMU → FULFILLED (unico candidato nazionale, la sola
verità di terra esattamente-uno robusta). Gli altri esiti sono stampati come
diagnostica (carta d'identità e trascrizione sono ambiguità ≥2 → NOT_FOUND
onesti, non hit).

    TREASUREIQ_SMOKE_SPORTELLO=1 PYTHONPATH=api api/.venv/bin/python \
        api/scripts/smoke_sportello.py
"""

from __future__ import annotations

import os
import sys

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, Surface
from treasureiq.catalog.data_contracts import DataRequest, DataStatus, FreshnessPolicy
from treasureiq.catalog.fetch_policy import PoliticaFetch
from treasureiq.catalog.fetch_runtime import EsecutoreFetch
from treasureiq.catalog.service_connectors.esecutore_fetcher import EsecutoreServiceFetcher
from treasureiq.catalog.service_connectors.sportello_service import (
    SportelloServiceConnector,
    _SportelloDiscovery,
)
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.mappa_connettore import AssetServizi, MappaConnettore

_COMUNI = [
    ("015081", "colognoeasy.comune.colognomonzese.mi.it", "Cologno Monzese"),
    ("058079", "sportellotelematico.comune.pomezia.rm.it", "Pomezia"),
]
_CHIAVI = [
    ServiceKey.TRIBUTI_IMU,
    ServiceKey.CARTA_IDENTITA,
    ServiceKey.STATO_CIVILE,
    ServiceKey.TRIBUTI_TARI,
]


def _mappa(istat: str, host: str) -> MappaConnettore:
    return MappaConnettore(
        codice_istat=istat,
        nome=host,
        sito=host,
        sondato_il="2026-09-06T00:00:00+00:00",
        piattaforma_id="sportello_telematico",
        servizi=AssetServizi(esposto=False, rest_base=None, totale=0),
    )


def _request(istat: str, key: ServiceKey) -> DataRequest:
    return DataRequest(
        request_id=f"smoke:{istat}:{key.value}",
        source_id=istat,
        surface=Surface.ORDINARY_DATA,
        capability=CAPABILITY_SERVICES,
        selection={"service_key": key.value},
        freshness=FreshnessPolicy(max_age_seconds=86_400),
        manifest_revision=1,
    )


def main() -> int:
    if os.environ.get("TREASUREIQ_SMOKE_SPORTELLO") != "1":
        print("skip: set TREASUREIQ_SMOKE_SPORTELLO=1 per lo smoke live read-only")
        return 0

    esecutore = EsecutoreFetch(PoliticaFetch(massimo_per_dominio=50))
    transport = EsecutoreServiceFetcher(esecutore).con(_SportelloDiscovery())
    conn = SportelloServiceConnector(transport)

    cologno_imu_ok = False
    for istat, host, nome in _COMUNI:
        print(f"\n=== {nome} ({istat}) — {host} ===")
        for key in _CHIAVI:
            r = conn.retrieve(_request(istat, key), mappa=_mappa(istat, host), esito=None)
            riga = f"  {key.value:16s} -> {r.status.name}"
            if r.status is DataStatus.FULFILLED:
                ref = r.service_references[0]
                riga += f"  id={ref.service_id}  url={ref.source_url}"
            print(riga)
            if nome == "Cologno Monzese" and key is ServiceKey.TRIBUTI_IMU:
                cologno_imu_ok = r.status is DataStatus.FULFILLED

    print()
    if not cologno_imu_ok:
        print("FAIL: Cologno IMU atteso FULFILLED")
        return 1
    print("OK: Cologno IMU FULFILLED (esattamente-uno)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
