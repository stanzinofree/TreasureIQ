"""Independent source-inventory discovery.

This is intentionally upstream of data connectors: an unsupported BASE
platform must still produce a useful AT/SP inventory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition_adapter import firma_da_registro
from treasureiq.catalog.service_discovery import (
    discover_service_portal_candidates,
    update_source_inventory,
)
from treasureiq.catalog.fetch_runtime import EsecutoreFetch
from treasureiq.ingest.censimento import scopri_pagina_at
from treasureiq.ingest.host_guard import fetch_guardato, host_senza_www


def discover_source_inventory(
    *, live_dir: Path, source_id: str, base_url: str, timeout: float = 8.0,
    dry_run: bool = False, esecutore: EsecutoreFetch | None = None,
):
    """Discover BASE/AT/SP facts without invoking a data connector.

    ``dry_run`` runs the full discovery (fetch + recognition) but persists
    nothing to ``data-live`` (invariante I4: sweep sicuro).

    ``esecutore`` media l'unico fetch di rete della discovery (la home BASE)
    attraverso la `PoliticaFetch` — rate-limit e budget per dominio come la
    confirmation. `scopri_pagina_at` e i candidati SP lavorano sull'HTML già
    scaricato, non fanno rete. Se la politica rifiuta il fetch (budget del
    dominio esaurito) la discovery ritorna `None` senza scrivere inventario.
    Nota: la home BASE non ha uno stato persistito (quello vive per AT/SP),
    quindi il backoff parte da 0 — rate-limit e budget restano gli argini attivi.
    """
    base_url = base_url.strip()
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    parsed = urlsplit(base_url)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host:
        return None
    fetch_kwargs = dict(
        timeout=timeout, max_bytes=1_000_000,
        host_atteso=host_senza_www(host.lower()), return_non_200=True,
    )
    if esecutore is not None:
        esito = esecutore.esegui(base_url, **fetch_kwargs)
        if not esito.consentito:
            return None  # budget del dominio esaurito: discovery saltata
        fetched = esito.fetched
    else:
        fetched = fetch_guardato(base_url, **fetch_kwargs)
    if fetched is None:
        return update_source_inventory(
            live_dir=live_dir, source_id=source_id, base_url=base_url,
            base_platform=None, base_fingerprint=None,
            transparency_url=None, transparency_platform=None, candidates=(),
            confirmed_at=datetime.now(timezone.utc), base_source_health=False,
            base_failure_reason="entrypoint_unreachable", dry_run=dry_run,
        )
    headers, data, final_url, *status_tail = fetched
    status_code = status_tail[0] if status_tail else 200
    if status_code != 200:
        return update_source_inventory(
            live_dir=live_dir, source_id=source_id, base_url=final_url,
            base_platform=None, base_fingerprint=None,
            transparency_url=None, transparency_platform=None, candidates=(),
            confirmed_at=datetime.now(timezone.utc), base_source_health=True,
            base_failure_reason=f"http_{status_code}", dry_run=dry_run,
        )
    html_home = data.decode("utf-8", errors="replace")
    # BASE recognition through the registry seam (not the legacy classifier
    # directly): a new BASE plugin now governs this discovery path too, no
    # second recognition truth to keep in sync.
    base = firma_da_registro(
        headers=dict(headers), html=html_home, surface=Surface.ORDINARY_DATA,
        source_id=source_id, entrypoint_url=final_url,
    )
    at = scopri_pagina_at(html_home=html_home, base=final_url)
    now = datetime.now(timezone.utc)
    return update_source_inventory(
        live_dir=live_dir,
        source_id=source_id,
        base_url=final_url,
        base_platform=base.piattaforma.value,
        base_fingerprint=None,
        transparency_url=at.at_url,
        transparency_platform=at.piattaforma_at.value if at.at_url else None,
        candidates=discover_service_portal_candidates(
            base_url=final_url,
            html_home=html_home,
            base_platform=base.piattaforma.value,
            discovered_at=now,
        ),
        confirmed_at=now,
        dry_run=dry_run,
    )
