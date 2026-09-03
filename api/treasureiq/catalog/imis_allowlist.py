"""Gate di promozione IMIS (``tributi_imu``) per i comuni OpenPA/OpenCity del
Trentino: allowlist degli host esterni ammessi come ``authenticated_online`` +
il validatore che la applica a una ``ServiceReference`` prima che entri nel
catalogo.

Policy-as-code E enforcement nello stesso posto. La provenienza (``source_url``)
e l'opzione ``information`` restano SEMPRE sull'host ufficiale del comune;
l'azione autenticata puo' essere delegata a un portale noto SOLO se elencato
qui, con scoping esplicito. Il resolver a runtime non e' toccato: valida solo lo
schema della ``ServiceReference``. Questo modulo e' il gate del *tooling di
promozione* (read-only), il punto unico dove si decide quale host di terzi entra
nel catalogo, per quali comuni e con quale path di tenant.

Regola dura: un host senza delega globale entra solo con scoping ESPLICITO per
codice ISTAT E path del tenant. Nessuna generalizzazione implicita — un secondo
comune sullo stesso vendor, o un path diverso, richiede una modifica esplicita a
questa tabella (e una recon).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from treasureiq.catalog.service_contracts import ServiceAccessMode, ServiceReference
from treasureiq.ingest.host_guard import host_senza_www


@dataclass(frozen=True)
class _Delega:
    """Delega di ``authenticated_online`` verso un host esterno.

    ``ambito``: ``None`` = delega globale del bacino (qualunque comune, path non
    vincolato — es. il portale regionale unico). Un ``dict`` = scoping per-ISTAT:
    codice comune -> path esatto del tenant atteso (match esatto, un path diverso
    e' rifiutato anche per un ISTAT ammesso).
    """

    etichetta: str
    ambito: dict[str, str] | None


#: host normalizzato (lowercase, senza ``www.``) -> delega.
_ALLOWLIST: dict[str, _Delega] = {
    # IMIS regionale del consorzio Comuni Trentini: delega globale — portale
    # unico del bacino (gli 84 authenticated_online gia' promossi in #78).
    "consulenza.comunitrentini.tn.it": _Delega("IMIS_TRENTINO", None),
    # DGE (dgegovpa.it): portale IMIS di terzi, tenant per-comune via path.
    # Ammesso SOLO per Altopiano della Vigolana (022236) sul path del suo tenant
    # ``/Vigolana/login``: unico comune la cui reference on-contract, emessa dal
    # connettore OpenPA dalla pagina ufficiale, punta gia' li' (recon 2026-09-02:
    # tenant vivo, HTTPS, host pubblico, comune-scoped). NON generalizzare: Imer
    # ha tenant DGE vivo ma il comune pubblica GISCO.
    "dgegovpa.it": _Delega("DGE", {"022236": "/Vigolana/login"}),
}


def _host(url: str) -> str:
    return host_senza_www((urlsplit(url).netloc or "").lower().split(":")[0])


def etichetta_delegata(host: str, istat: str) -> str | None:
    """Etichetta del vendor se ``host`` (gia' normalizzato) e' ammesso come
    ``authenticated_online`` per il comune ``istat``, altrimenti ``None``.
    Non valida schema/porta/path — per quello usa ``motivo_rifiuto_auth_online``.
    """
    voce = _ALLOWLIST.get(host)
    if voce is None:
        return None
    if voce.ambito is not None and istat not in voce.ambito:
        return None
    return voce.etichetta


def motivo_rifiuto_auth_online(url: str, istat: str) -> str | None:
    """``None`` se l'URL ``authenticated_online`` e' ammesso per ``istat``,
    altrimenti la stringa col motivo del rifiuto.

    Valida (responsabilita' del gate, non piu' implicite del chiamante):
    HTTPS, porta standard, host in allowlist, e per i vendor scoped l'ISTAT
    ammesso + il path esatto del tenant.
    """
    parti = urlsplit(url)
    if parti.scheme != "https":
        return f"non-https: {url}"
    try:
        porta = parti.port
    except ValueError:
        return f"porta non valida: {url}"
    if porta not in (None, 443):
        return f"porta non standard ({porta}): {url}"
    host = host_senza_www((parti.hostname or "").lower())
    voce = _ALLOWLIST.get(host)
    if voce is None:
        return f"host non in allowlist: {host}"
    if voce.ambito is not None:
        if istat not in voce.ambito:
            return f"{voce.etichetta} non ammesso per ISTAT {istat}"
        if parti.path != voce.ambito[istat]:
            return f"path non atteso per {voce.etichetta}/{istat}: {parti.path!r}"
    return None


def problemi_promozione(ref: ServiceReference, istat: str) -> list[str]:
    """Elenca le violazioni che impediscono la promozione di ``ref`` a catalogo
    per il comune ``istat``. Lista vuota = ammissibile.

    - la prima opzione e' ``INFORMATION`` sull'host ufficiale (== host di
      ``source_url``);
    - ogni opzione e' HTTPS;
    - ``information``/``download`` restano sull'host ufficiale;
    - ``authenticated_online`` supera ``motivo_rifiuto_auth_online`` (host+path
      in allowlist per l'ISTAT, HTTPS, porta standard).
    """
    if not ref.options:
        return ["reference senza opzioni"]
    host_ufficiale = _host(str(ref.source_url))
    problemi: list[str] = []
    if ref.options[0].mode is not ServiceAccessMode.INFORMATION:
        problemi.append(f"prima opzione non INFORMATION ({ref.options[0].mode.value})")
    for o in ref.options:
        u = str(o.url)
        if urlsplit(u).scheme != "https":
            problemi.append(f"non-https: {u}")
        if o.mode is ServiceAccessMode.AUTHENTICATED_ONLINE:
            motivo = motivo_rifiuto_auth_online(u, istat)
            if motivo:
                problemi.append(motivo)
        elif _host(u) != host_ufficiale:
            problemi.append(f"{o.mode.value} fuori host ufficiale: {_host(u)}")
    return problemi
