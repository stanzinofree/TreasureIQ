"""Guardia SSRF condivisa (ciclo 16, brief B5): un solo posto per la logica
di download-con-guardia usata da `censimento.py` (pagine Amministrazione
Trasparente, host non noto a priori — vive spesso su un SaaS indipendente)
e da `registro.py` (home/header/logo del comune, host noto a priori — deve
restare quello del comune per costruzione).

Prima di questo modulo la stessa logica esisteva in TRE varianti leggermente
diverse (`censimento._fetch_at_guardato` per-hop; `registro._scarica_logo`/
`_leggi_header_html`/`_logo_one_shot`, controllo solo DOPO il redirect
finale). Qui vince la versione più stretta — per-hop, non solo sul landing
finale — e i chiamanti di `registro.py` ereditano il rinforzo, non il
contrario.

Pattern SSRF invariato rispetto a prima dell'unificazione:
- redirect seguiti a mano (`follow_redirects=False`), mai automatico;
- risoluzione DNS validata a IP pubblico su OGNI hop, non solo sul finale;
- cap sul numero di hop (un redirect-loop non deve degradare a timeout);
- download in streaming con abort al superamento del cap byte, mai un
  `len()` dopo un download intero.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from treasureiq import freschezza
from treasureiq.ingest.base import USER_AGENT

logger = logging.getLogger(__name__)

#: Redirect HTTP seguiti a mano (mai `follow_redirects=True`).
REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})

#: Cap di default sugli hop di redirect: un numero basso non è solo un
#: limite di traffico, è quel che ferma un redirect-loop usato per far
#: scattare il timeout invece della guardia.
DEFAULT_MAX_REDIRECT_HOP = 5


def host_senza_www(host: str) -> str:
    """Normalizza per il confronto: `www.` è un prefisso di comodo, non
    identità del portale."""
    return host[4:] if host.startswith("www.") else host


def ip_non_sicuro(ip_str: str) -> bool:
    """Un IP privato/loopback/link-local/riservato/multicast/unspecified non
    è mai un esito legittimo per una risorsa pubblica — copre anche le forme
    IPv6 che nascondono un indirizzo privato. Un IP che non parsa non è
    "sicuro per esclusione": è trattato come non sicuro."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def host_risolve_a_ip_sicuro(hostname: str) -> bool:
    """Risolve l'hostname a TUTTI gli IP che il DNS restituisce e rifiuta se
    QUALSIASI IP risolto è privato/loopback/link-local/riservato/multicast/
    unspecified. Guardare solo se l'URL contiene un IP letterale non
    intercetta un hostname pubblico nell'aspetto ma il cui DNS risolve a
    `169.254.169.254` o `127.0.0.1` — è il gap SSRF reale.

    Nota: fra questa risoluzione e il connect effettivo di httpx c'è una
    finestra minima di DNS-rebinding (TOCTOU) che una validazione a livello
    applicativo, senza pin del socket, non chiude del tutto — qui si copre
    il caso concreto (hostname malevolo risolto ad oggi), non la variante
    temporale con TTL DNS avversariale."""
    try:
        risoluzioni = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    if not risoluzioni:
        return False
    return not any(ip_non_sicuro(sockaddr[0]) for *_, sockaddr in risoluzioni)


def fetch_guardato(
    url: str,
    *,
    timeout: float = 8.0,
    max_bytes: int,
    max_redirect_hop: int = DEFAULT_MAX_REDIRECT_HOP,
    host_atteso: str | None = None,
) -> tuple[httpx.Headers, bytes, str] | None:
    """Scarica `url` con la guardia SSRF PER-HOP: schema http(s), identità
    host, risoluzione DNS a IP pubblico rivalidati su OGNI hop (compreso il
    primo), mai solo sulla destinazione finale.

    `host_atteso`:
    - `None` (semantica AT-discovery, `censimento.py`): il primo hop FISSA
      l'host atteso, i successivi devono restare sullo stesso host — l'AT
      vive spesso su un dominio SaaS indipendente dal portale del comune,
      quindi non si può pretendere l'host del comune fin dal primo hop.
    - un host esplicito (semantica comune-noto, `registro.py`): OGNI hop,
      compreso il primo, deve risolvere a quell'host — un redirect fuori dal
      dominio del comune non è mai un logo/header legittimo del comune.

    Ritorna `(headers, bytes, url_finale)` o `None` per qualunque anomalia:
    schema non http(s), host fuori atteso, DNS non pubblico, status non-200/
    non-redirect, redirect senza `location`, troppi hop, o eccezione di rete
    — mai un'eccezione che risale al chiamante, mai un dato indovinato al
    suo posto."""
    corrente = url
    for _ in range(max_redirect_hop + 1):
        richiesta = urlsplit(corrente)
        if richiesta.scheme not in ("http", "https") or not richiesta.hostname:
            return None
        host_normalizzato = host_senza_www(richiesta.hostname.lower())
        if host_atteso is None:
            host_atteso = host_normalizzato
        elif host_normalizzato != host_atteso:
            logger.warning("fetch guardato fuori host atteso, scartato: %s -> %s", url, corrente)
            return None
        if not host_risolve_a_ip_sicuro(richiesta.hostname):
            logger.warning("fetch guardato host non risolve a IP pubblico, scartato: %s", corrente)
            return None
        try:
            with httpx.Client(
                timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=False
            ) as client:
                with client.stream("GET", corrente) as risposta:
                    if risposta.status_code in REDIRECT_STATUS:
                        location = risposta.headers.get("location")
                        if not location:
                            return None
                        corrente = urljoin(corrente, location)
                        continue
                    if risposta.status_code != 200:
                        return None
                    intestazioni = risposta.headers
                    buffer = bytearray()
                    for pezzo in risposta.iter_bytes():
                        buffer.extend(pezzo)
                        if len(buffer) > max_bytes:
                            logger.info("fetch guardato oltre cap, connessione interrotta: %s", corrente)
                            return None
                    # Traccia di freschezza: ogni fetch live andato a buon fine —
                    # è la prova auditabile che il dato viene ORA dal sito del
                    # comune, non da un DB stantio (un cache-hit non arriva qui).
                    logger.info("fetch live: %s (%d byte)", corrente, len(buffer))
                    freschezza.registra(corrente, len(buffer))
                    return intestazioni, bytes(buffer), corrente
        except Exception:  # noqa: BLE001 — risorsa muta: None, mai un crash
            logger.info("fetch guardato irraggiungibile: %s", corrente)
            return None
    logger.warning("fetch guardato troppi redirect, scartato: %s", url)
    return None
