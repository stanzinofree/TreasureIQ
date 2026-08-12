"""Lettura on-demand dell'orario di un ufficio *nominato* dal cittadino.

Il problema che risolve. Quando un cittadino chiede «gli orari dell'ufficio
anagrafe», il rail informazione gli attacca l'ufficio di ripiego (URP) con il
suo orario. È onesto ma non è la risposta migliore: il portale, quasi sempre,
ha una pagina dedicata a *quell'* ufficio con il *suo* orario — e noi ne
conosciamo già la URL, perché lo sweep del connettore l'ha catalogata fra gli
`uffici` del comune. Questo modulo legge quella pagina, adesso, e ne cita
l'orario alla lettera.

Tre confini, gli stessi di `sonda_live` (D-32/D-33/D-34):

*Solo il rail INFORMAZIONE.* Un orario letto qui non entra mai in un verdetto.

*Si legge la URL catalogata, non una indovinata.* La URL arriva dallo store del
connettore (`UfficioConnettore.url`), scritto dallo sweep; qui non si compone
nessun host. E non salta la guardia SSRF: `fetch_guardato` con `host_atteso`
derivato dal SUO stesso host (D-02, stesso stampo di `alberatura._rami_da_registro`).

*Il primo cittadino paga, gli altri no.* L'esito — anche negativo — finisce in
cache su `data-live/orari-ufficio/{istat}/{slug}.json`. Sapere che quella
pagina non pubblica un orario è una misura: ripeterla a ogni domanda costerebbe
al comune senza aggiungere niente. Non solleva mai: la risposta al cittadino è
già pronta e non deve dipendere da questa lettura.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel

from treasureiq.alberatura import _decodifica_bytes
from treasureiq.ingest.censimento import estrai_orari_da_testo
from treasureiq.ingest.host_guard import fetch_guardato, host_senza_www
from treasureiq.orari_schema import OrarioSettimanale, estrai_orario_strutturato

logger = logging.getLogger(__name__)

#: Mount runtime scrivibile, stesso di `sonda_live.LIVE_DIR` (D-33).
LIVE_DIR = Path(os.environ.get("TREASUREIQ_LIVE_DIR", "/live"))

#: Un orario d'ufficio cambia di rado: una lettura vale a lungo. Oltre questa
#: soglia la voce in cache è considerata stantia e si rilegge.
GIORNI_VALIDITA = 6

#: Tetto sui byte scaricati dalla pagina dell'ufficio (guardia, non un dato).
MAX_BYTES_PAGINA = 2_000_000


class OrariUfficio(BaseModel):
    """L'esito della lettura on-demand di una pagina-ufficio.

    `orari is None` con `letto_il` valorizzato NON significa "non letto": la
    pagina è stata raggiunta e non pubblica un orario (degrado onesto). Chi
    chiama non deve spacciare per orario di quell'ufficio quello dell'URP.
    """

    codice_istat: str
    slug: str
    url: str
    orari: str | None
    #: Lo schema normalizzato dell'orario (giorni + fasce), quando la pagina lo
    #: espone in una forma riconoscibile. Additivo e opzionale: le voci in
    #: cache scritte prima di questo campo restano valide (default `None`).
    #: `orari` resta la fonte verbatim; `orario_schema.reso` è la forma pulita.
    #: Nominato `orario_schema` e non `schema` per non oscurare `BaseModel.schema`.
    orario_schema: OrarioSettimanale | None = None
    letto_il: str


def _slug_da_url(url: str) -> str:
    """L'ultimo segmento di path della URL, come chiave di cache stabile.

    `.../unita_organizzativa/ufficio-anagrafe-e-leva/` -> `ufficio-anagrafe-e-leva`.
    Sanifica ciò che finirebbe in un nome di file: mai un separatore di path.
    """
    percorso = urlsplit(url).path.strip("/")
    ultimo = percorso.rsplit("/", 1)[-1] if percorso else ""
    return re.sub(r"[^a-z0-9_-]+", "-", ultimo.lower()).strip("-")


def _percorso_cache(codice_istat: str, slug: str) -> Path:
    return LIVE_DIR / "orari-ufficio" / codice_istat / f"{slug}.json"


def _da_cache(codice_istat: str, slug: str) -> OrariUfficio | None:
    """La voce in cache se esiste ed è fresca, altrimenti `None`."""
    percorso = _percorso_cache(codice_istat, slug)
    try:
        voce = OrariUfficio.model_validate_json(percorso.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    try:
        letto = datetime.fromisoformat(voce.letto_il)
    except ValueError:
        return None
    if datetime.now(timezone.utc) - letto > timedelta(days=GIORNI_VALIDITA):
        return None
    return voce


def _in_cache(voce: OrariUfficio) -> None:
    """Scrive la voce in modo atomico (.tmp + replace). Mai mezza voce."""
    percorso = _percorso_cache(voce.codice_istat, voce.slug)
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(voce.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        # Il mount live può mancare (sviluppo locale, test): la risposta al
        # cittadino è già pronta e non deve dipendere da questo.
        logger.warning("cache orari-ufficio non scrivibile (%s): %s", percorso, exc)


def leggi_orari_ufficio(
    *, codice_istat: str, url: str, usa_cache: bool = True, timeout: float = 6.0
) -> OrariUfficio | None:
    """L'orario pubblicato nella pagina di un ufficio nominato, citato verbatim.

    Ritorna:
    - `None` se la URL non è interrogabile (vuota, non http, senza host, senza
      slug): non c'è niente da leggere né da mettere in cache.
    - una `OrariUfficio` con `orari` valorizzato se la pagina lo pubblica.
    - una `OrariUfficio` con `orari is None` se la pagina è stata raggiunta ma
      non pubblica un orario: esito negativo, comunque messo in cache.

    Non solleva mai.
    """
    if not url or not url.startswith(("http://", "https://")):
        return None
    slug = _slug_da_url(url)
    if not slug:
        return None

    if usa_cache:
        voce = _da_cache(codice_istat, slug)
        if voce is not None:
            return voce

    host = urlsplit(url).hostname
    if not host:
        return None
    host_atteso = host_senza_www(host.lower())

    orari: str | None = None
    schema: OrarioSettimanale | None = None
    try:
        esito = fetch_guardato(
            url, timeout=timeout, max_bytes=MAX_BYTES_PAGINA, host_atteso=host_atteso
        )
        if esito is not None:
            intestazioni, contenuto, _url_finale = esito
            pagina = _decodifica_bytes(intestazioni.get("content-type", "") or "", contenuto)
            orari = estrai_orari_da_testo(pagina)
            schema = estrai_orario_strutturato(pagina)
            # Fonte verbatim: la citazione ricca del censimento se c'è (porta il
            # contesto di frase); altrimenti lo span verbatim dello schema, così
            # una pagina a giorni abbreviati (comweb), muta al riconoscitore del
            # censimento ma leggibile dallo schema, ha comunque una fonte da
            # mostrare e non solo la forma normalizzata.
            if orari is None and schema is not None:
                orari = schema.testo_grezzo
    except Exception:  # noqa: BLE001 — risorsa muta: esito negativo, mai un crash
        logger.info("lettura orari-ufficio fallita: %s", url)

    voce = OrariUfficio(
        codice_istat=codice_istat,
        slug=slug,
        url=url,
        orari=orari,
        orario_schema=schema,
        letto_il=datetime.now(timezone.utc).isoformat(),
    )
    _in_cache(voce)
    return voce
