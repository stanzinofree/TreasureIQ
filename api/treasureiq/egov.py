"""Connettore eGov (B4a): scheletro del contratto D-09 per la firma-famiglia
`/EG0/EGS*.HBL?en=eg###` (D-10) — vista su Marino (RM), `en=eg176`, due
endpoint distinti (`EGSCHTST.HBL` servizi, `EGSMISTMSIT.HBL` mappa).

Questo modulo copre SOLO il boundary di rete (W1) + il degrado D-10 onesto:
gli endpoint riconosciuti nella home page del comune (link `href` che
matchano la firma) diventano `AreaAmministrativa` — un link verificato, non
un contenuto letto. Se uno di quei link si presenta testualmente come
"amministrazione trasparente" lo si scrive anche in
`AmministrazioneTrasparente.indice_url`. Il parser reale (uffici, bandi,
PDF) è B4b: la firma di `leggi_egov` qui è congelata (D-09 acceptance A9,
ciclo 10) — il corpo NON lo è.

Guardia security (W1) — stessa forma di `municipium.py:246` (follow-301
same-host) e `registro.py._scarica_logo` (size-cap streaming-con-abort):
schema allow-list http/https, host allow-list = dominio del comune
verificato DOPO il follow-301 (TOCTOU/SSRF: un host che non è il comune —
IP privato incluso — non passa mai questo confronto; non c'è un elenco di
range IP da mantenere separatamente), timeout esplicito per richiesta,
size-cap che ABORTISCE lo streaming (mai un `len()` calcolato dopo un
download intero, W-3).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

from treasureiq.connettore import (
    AmministrazioneTrasparente,
    AreaAmministrativa,
    EsitoConnettore,
)
from treasureiq.ingest.base import USER_AGENT
from treasureiq.ingest.censimento import _Sonda
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www
from treasureiq.sonda_live import ComuneNoto

logger = logging.getLogger(__name__)

#: Margine di cortesia — nessuna misura reale oltre Marino, B4b la affinerà
#: quando leggerà davvero le pagine servizi/mappa/AT. Stesso ordine di
#: grandezza del cap-logo in `registro.py`.
MAX_RISPOSTA_BYTES = 2_000_000

#: La firma-famiglia (D-09 A9): asset/rotta `EGS*.HBL` con querystring
#: `en=eg###`, letta dentro un `href` — stesso pattern del riconoscimento
#: piattaforma in `piattaforma.py` (`_ASSET`), qui applicato al singolo
#: link per costruire il degrado D-10, non solo per la firma di pagina.
_RE_HREF_EGOV = re.compile(
    r'<a[^>]+href=["\']([^"\']*?/EG0/EGS\w+\.HBL\?[^"\']*\ben=eg\d{1,4}\b[^"\']*)["\'][^>]*>([^<]*)</a>',
    re.IGNORECASE,
)
_RE_AT_TESTO = re.compile(r"amministrazione\s+trasparente", re.IGNORECASE)


def _ora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stesso_host(url: str, host_comune: str) -> bool:
    return _host_senza_www(urlparse(url).netloc.lower()) == host_comune


def _richiedi_con_guardia(url: str, host_comune: str, *, timeout: float) -> tuple[str, str] | None:
    """GET guardato (W1). `None` per qualunque esito non valido: schema
    non-http, stato non-200, redirect fuori host (controllato DOPO il
    follow-301, non sull'URL iniziale — TOCTOU/SSRF, stesso punto di
    `municipium.py:246`), o risposta oltre il size-cap. Lo stream si
    interrompe ABORTENDO la connessione al superamento del cap — mai un
    `len()` calcolato dopo un download intero (W-3, pattern identico a
    `registro._scarica_logo`). Ritorna `(testo, url_finale)`."""
    if urlparse(url).scheme not in ("http", "https"):
        return None
    try:
        with httpx.Client(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            with client.stream("GET", url) as risposta:
                if risposta.status_code != 200:
                    return None
                if not _stesso_host(str(risposta.url), host_comune):
                    logger.warning(
                        "eGov: redirect fuori host scartato %s -> %s", url, risposta.url
                    )
                    return None
                buffer = bytearray()
                for pezzo in risposta.iter_bytes():
                    buffer.extend(pezzo)
                    if len(buffer) > MAX_RISPOSTA_BYTES:
                        logger.info(
                            "eGov: risposta oltre size-cap, connessione interrotta: %s", url
                        )
                        return None
                url_finale = str(risposta.url)
    except Exception:  # noqa: BLE001 — portale eGov muto: nessun esito, mai un crash
        logger.info("eGov: pagina irraggiungibile: %s", url)
        return None
    return bytes(buffer).decode("utf-8", errors="replace"), url_finale


def _estrai_aree_egov(pagina: str, base: str, host_comune: str) -> list[AreaAmministrativa]:
    """Gli endpoint `EGS*.HBL` riconosciuti nella pagina, come link (D-10):
    solo quelli che restano sul dominio del comune. Nessun contenuto letto
    — è il degrado onesto in attesa di B4b."""
    aree: list[AreaAmministrativa] = []
    visti: set[str] = set()
    for grezzo, testo in _RE_HREF_EGOV.findall(pagina):
        url = urljoin(base, grezzo)
        if url in visti or not _stesso_host(url, host_comune):
            continue
        visti.add(url)
        nome = testo.strip() or url
        aree.append(AreaAmministrativa(nome=nome, url=url))
    return aree


def leggi_egov(comune: ComuneNoto, sonda: _Sonda) -> EsitoConnettore:
    """Contratto D-09 per la famiglia eGov. Firma congelata per B4b:
    `(comune, sonda) -> EsitoConnettore`, MAI `None` — un comune senza
    nulla da leggere è un esito vuoto onesto (`connettore._esito_vuoto` lo
    riconosce), non un guasto.

    Scheletro (B4a): non legge ancora uffici/bandi/PDF (B4b sostituirà
    questo corpo, non la firma). Il degrado D-10 servito già oggi: gli
    endpoint `EGS*.HBL?en=eg###` trovati nella home page diventano link
    (`AreaAmministrativa`); se uno di loro si presenta testualmente come
    "amministrazione trasparente" lo si scrive anche in
    `AmministrazioneTrasparente.indice_url`.
    """
    letto_il = _ora()
    base = _base_con_schema(comune.sito)
    if base is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=Piattaforma.EGOV.value, letto_il=letto_il
        )
    host_comune = _host_senza_www(urlparse(base).netloc.lower())

    letta = _richiedi_con_guardia(base, host_comune, timeout=8.0)
    if letta is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat, piattaforma=Piattaforma.EGOV.value, letto_il=letto_il
        )
    # Stesso contatore di `_Sonda._get`/`.risposta` (D-08): la richiesta
    # guardata bypassa `_Sonda` per lo streaming, ma il costo verso il
    # portale va comunque contato — la scansione non deve sembrare gratis.
    sonda.richieste += 1
    sonda.raggiungibile = True
    pagina, url_finale = letta

    aree = _estrai_aree_egov(pagina, url_finale, host_comune)
    indice_at = next((area.url for area in aree if _RE_AT_TESTO.search(area.nome)), None)
    amministrazione_trasparente = (
        AmministrazioneTrasparente(indice_url=indice_at) if indice_at else None
    )

    return EsitoConnettore(
        codice_istat=comune.codice_istat,
        piattaforma=Piattaforma.EGOV.value,
        letto_il=letto_il,
        aree_amministrative=aree,
        amministrazione_trasparente=amministrazione_trasparente,
    )


def _leggi_egov_cli(codice_istat: str, *, timeout: float = 8.0) -> None:
    """Uso standalone (`python -m treasureiq.egov <istat>`), stesso stampo
    del CLI di `municipium.py`."""
    from treasureiq.sonda_live import comune_per_codice

    comune = comune_per_codice(codice_istat)
    if comune is None:
        print(f"comune non trovato: {codice_istat}")
        return
    with _Sonda(timeout=timeout) as sonda:
        esito = leggi_egov(comune, sonda)
    print(esito.model_dump_json(indent=1))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Connettore eGov (D-09) — scheletro B4a")
    parser.add_argument("codice_istat", help="codice ISTAT del comune (es. 058048 Marino)")
    parser.add_argument("--timeout", type=float, default=8.0, help="timeout per richiesta (default 8.0)")
    args = parser.parse_args()
    _leggi_egov_cli(args.codice_istat, timeout=args.timeout)
