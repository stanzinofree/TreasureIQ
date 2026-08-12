"""Connettore Municipium (B2): la prima implementazione piena del contratto
D-09 (`treasureiq.connettore.EsitoConnettore`).

Scouting reale (3 comuni Municipium, tutto HTML statico sul dominio proprio,
0 JS — vedi `.kapi/spec.md`): la piattaforma non espone nulla di utile via
`api.municipiumapp.it` (503 lato WAF); tutto quello che serve sta sul
dominio del comune, raggiungibile con un client HTTP semplice.

- **Discovery uffici (D-02)**: `{base}/it/sitemap` elenca i link canonici
  `/it/organizational_unit/{slug}` — ingresso universale, verificato su
  Pomezia (115), Fiumicino (80), Riccione (133). Nessuno slug hardcoded.
  Fallback secondario: la pagina `/it/page/aree-amministrative[-N]`, anche
  lei linkata dalla sitemap.
- **Follow-301 same-host (D-08)**: alcuni comuni (Riccione, ma anche
  Pomezia) redirigono `organizational_unit/{slug}` → `unita_organizzative/
  {slug}` con un vero 301. `_Sonda` segue i redirect di suo; qui si
  verifica SOLO che l'host finale resti quello del comune (guardia SSRF,
  A5) — un redirect fuori host scarta la pagina, non la si legge.
- **Lettura ufficio (D-04/D-05/D-07)**: ogni pagina ufficio ha una sezione
  «Contatti Utili» (`id="contatti"`) con righe strutturate `<strong>Label</
  strong> : <a href="...">valore</a>`. Si legge SOLO quella sezione — la
  pagina porta anche un centralino ente in JSON-LD altrove, e confonderlo
  con un recapito diretto sarebbe il falso «centralino spacciato per
  ufficio» che D-05 vieta esplicitamente. Un campo assente in quella
  sezione resta assente: mai dedotto, mai indovinato.
"""

from __future__ import annotations

import argparse
import html
import logging
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from treasureiq.connettore import (
    AmministrazioneTrasparente,
    AreaAmministrativa,
    EndpointiConnettore,
    EsitoConnettore,
    UfficioConnettore,
)
from treasureiq.ingest.censimento import _Sonda
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.mappa_connettore import _base_con_schema, _host_senza_www
from treasureiq.sonda_live import ComuneNoto, comune_per_codice

logger = logging.getLogger(__name__)

#: Sitemap osservate 1-3.5MB nello scouting reale; il limite è un margine di
#: cortesia (D-08), non un valore misurato come soglia di rottura.
LIMITE_BYTE_SITEMAP = 4_000_000

#: Budget richieste per-ufficio (D-08): un comune grande (Riccione, 133
#: org_unit) non deve costare 133 fetch a ogni scansione — cap dal plan.
MAX_UFFICI = 40

_RE_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_RE_ORG_UNIT_PATH = re.compile(
    r"/it/(?:organizational_unit|unita_organizzative)/[^/?#\"']+/?$", re.IGNORECASE
)
_RE_AREE_AMM_PATH = re.compile(r"/it/page/aree-amministrative(?:-\d+)?/?$", re.IGNORECASE)
# B9 (ciclo16): la top-nav Municipium è `/it/menu/{amministrazione,servizi,...}`
# — verificato via fetch live su Pomezia/Andria/Fiumicino, NON `/it/servizi`/
# `/it/amministrazione` come si potrebbe assumere per convenzione. Pomezia
# porta un suffisso numerico sul nodo menu (es. `/it/menu/servizi-380465`),
# stesso schema di `_RE_AREE_AMM_PATH` sopra: suffisso opzionale, non fisso.
_RE_SERVIZI_PATH = re.compile(r"/it/menu/servizi(?:-\d+)?/?$", re.IGNORECASE)
_RE_AMM_PATH = re.compile(r"/it/menu/amministrazione(?:-\d+)?/?$", re.IGNORECASE)
_RE_ANCHOR = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', re.IGNORECASE)
_RE_CONTATTO = re.compile(r'<strong>([^<]+)</strong>\s*:\s*<a\s+href=["\']([^"\']+)["\']', re.IGNORECASE)
_RE_ORARI = re.compile(r'<strong>\s*Orari[^<]*</strong>\s*:\s*([^<]+)', re.IGNORECASE)
_RE_TITOLO_UFFICIO = re.compile(
    r'data-element=["\']organizationalunit-title["\'][^>]*>([^<]+)</h1>', re.IGNORECASE
)
_RE_TITLE_TAG = re.compile(r"<title>([^<]*)</title>", re.IGNORECASE)


def _ora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stesso_host(url: str, host_comune: str) -> bool:
    return _host_senza_www(urlparse(url).netloc.lower()) == host_comune


def _estrai_link(pagina: str, base: str) -> list[str]:
    """Ogni `href` della pagina, reso assoluto (D-08: input per la guardia
    host che segue, non ancora filtrato qui)."""
    assoluti = []
    for grezzo in _RE_HREF.findall(pagina):
        href = html.unescape(grezzo).strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        assoluti.append(urljoin(base, href))
    return assoluti


def _estrai_aree(pagina: str, base: str, host_comune: str) -> list[AreaAmministrativa]:
    """Le voci di un indice di aree amministrative (nome+url), solo quelle
    che restano sul dominio del comune e puntano a un `organizational_unit`
    — usato nel solo ramo degradato (D-02b), come segnale onesto residuo
    quando la sitemap non ha fruttato uffici."""
    aree: list[AreaAmministrativa] = []
    visti: set[str] = set()
    for grezzo, testo in _RE_ANCHOR.findall(pagina):
        href = html.unescape(grezzo).strip()
        if not href or href.startswith("#"):
            continue
        url = urljoin(base, href)
        if url in visti or not _stesso_host(url, host_comune) or not _RE_ORG_UNIT_PATH.search(url):
            continue
        visti.add(url)
        nome = html.unescape(testo).strip() or url
        aree.append(AreaAmministrativa(nome=nome, url=url))
    return aree


def _scopri_uffici(comune: ComuneNoto, sonda: _Sonda) -> tuple[list[str], list[str]]:
    """Discovery uffici (D-02): `(link_org_unit, link_sitemap)`.

    `link_sitemap` — TUTTI i link della sitemap, non filtrati — è il
    contratto verso B3 (`municipium_at.leggi_at`): una sola fetch della
    sitemap serve a entrambi (budget D-08), non due.
    """
    base = _base_con_schema(comune.sito)
    if base is None:
        return [], []
    host_comune = _host_senza_www(urlparse(base).netloc.lower())

    try:
        resp = sonda.risposta(f"{base}/it/sitemap")
    except Exception:  # noqa: BLE001 — sitemap muta: discovery vuota, mai un crash
        logger.info("sitemap irraggiungibile per %s", comune.nome)
        return [], []
    if resp.status_code != 200 or not _stesso_host(str(resp.url), host_comune):
        return [], []

    testo = resp.text
    if len(resp.content) > LIMITE_BYTE_SITEMAP:
        testo = testo[:LIMITE_BYTE_SITEMAP]

    link_sitemap = _estrai_link(testo, base)
    org_unit = list(
        dict.fromkeys(
            link
            for link in link_sitemap
            if _stesso_host(link, host_comune) and _RE_ORG_UNIT_PATH.search(link)
        )
    )
    if org_unit:
        return org_unit, link_sitemap

    # Fallback secondario: la pagina aree-amministrative, anche lei nella sitemap.
    for pagina_aree in (
        link for link in link_sitemap if _stesso_host(link, host_comune) and _RE_AREE_AMM_PATH.search(link)
    ):
        try:
            resp_aree = sonda.risposta(pagina_aree)
        except Exception:  # noqa: BLE001 — fallback muto: si prova il prossimo, poi si arrende
            continue
        if resp_aree.status_code != 200 or not _stesso_host(str(resp_aree.url), host_comune):
            continue
        org_unit = list(
            dict.fromkeys(
                link
                for link in _estrai_link(resp_aree.text, base)
                if _stesso_host(link, host_comune) and _RE_ORG_UNIT_PATH.search(link)
            )
        )
        if org_unit:
            break

    return org_unit, link_sitemap


def _blocco_contatti(pagina: str) -> str:
    """Il solo tratto di HTML sotto l'anchor `id="contatti"`, fino al
    prossimo `<h2>` (D-05: fuori da qui c'è il centralino ente in JSON-LD,
    che NON è un recapito di questo ufficio)."""
    inizio_anchor = pagina.find('id="contatti"')
    if inizio_anchor == -1:
        inizio_anchor = pagina.find("id='contatti'")
    if inizio_anchor == -1:
        return ""
    inizio_h2 = pagina.find("</h2>", inizio_anchor)
    inizio = inizio_h2 + len("</h2>") if inizio_h2 != -1 else inizio_anchor
    fine = pagina.find("<h2", inizio)
    if fine == -1:
        fine = inizio + 6000  # margine di cortesia: non scandire l'intera pagina
    return pagina[inizio:fine]


def _estrai_recapiti(blocco: str) -> tuple[list[str], list[str], list[str], str | None]:
    """Recapiti VERBATIM dalla sola sezione Contatti (D-07: nessuna cifra
    passa da un LLM, parsing deterministico su HTML)."""
    telefoni: list[str] = []
    email: list[str] = []
    pec: list[str] = []
    for label, href in _RE_CONTATTO.findall(blocco):
        etichetta = html.unescape(label).strip().lower()
        valore = html.unescape(href).strip()
        if valore.lower().startswith("tel:"):
            numero = valore[4:].strip()
            if numero:
                telefoni.append(numero)
        elif valore.lower().startswith("mailto:"):
            indirizzo = valore[7:].split("?")[0].strip()
            if indirizzo and "@" in indirizzo:
                if "pec" in etichetta or "pec" in indirizzo.lower():
                    pec.append(indirizzo)
                else:
                    email.append(indirizzo)

    orari_match = _RE_ORARI.search(blocco)
    orari = html.unescape(orari_match.group(1)).strip() if orari_match else None

    return (
        list(dict.fromkeys(telefoni)),
        list(dict.fromkeys(email)),
        list(dict.fromkeys(pec)),
        orari or None,
    )


def _estrai_nome_ufficio(pagina: str) -> str | None:
    titolo = _RE_TITOLO_UFFICIO.search(pagina)
    if titolo is not None:
        nome = html.unescape(titolo.group(1)).strip()
        if nome:
            return nome
    titolo_tag = _RE_TITLE_TAG.search(pagina)
    if titolo_tag is not None:
        nome = html.unescape(titolo_tag.group(1)).strip()
        if nome:
            return nome
    return None


def _leggi_ufficio(url: str, sonda: _Sonda, host_comune: str) -> UfficioConnettore | None:
    """Una pagina ufficio, letta e guardata (D-08: guardia host DOPO il
    follow-301 — `_Sonda` segue i redirect di suo, qui si scarta quello che
    è finito fuori dal dominio del comune, `None` = niente da leggere)."""
    try:
        resp = sonda.risposta(url)
    except Exception:  # noqa: BLE001 — pagina muta: si salta, non si propaga
        logger.info("ufficio irraggiungibile: %s", url)
        return None
    if resp.status_code != 200:
        return None
    url_finale = str(resp.url)
    if not _stesso_host(url_finale, host_comune):
        logger.warning("redirect fuori host scartato: %s -> %s", url, url_finale)
        return None

    pagina = resp.text
    nome = _estrai_nome_ufficio(pagina) or url_finale
    blocco = _blocco_contatti(pagina)
    telefoni, email, pec, orari = _estrai_recapiti(blocco)

    return UfficioConnettore(
        nome=nome,
        url=url_finale,
        telefoni=telefoni,
        email=email,
        pec=pec,
        orari=orari,
        source_typed=bool(telefoni or email or pec),
        letto_il=_ora(),
    )


def _aree_da_fallback(
    base: str, host_comune: str, link_sitemap: list[str], sonda: _Sonda
) -> list[AreaAmministrativa]:
    """Segnale residuo per il ramo degradato (D-02b): le voci lette dalla
    pagina aree-amministrative, se la sitemap non ha fruttato uffici."""
    for pagina_aree in (
        link for link in link_sitemap if _stesso_host(link, host_comune) and _RE_AREE_AMM_PATH.search(link)
    ):
        try:
            resp = sonda.risposta(pagina_aree)
        except Exception:  # noqa: BLE001 — fallback muto: si prova il prossimo
            continue
        if resp.status_code != 200 or not _stesso_host(str(resp.url), host_comune):
            continue
        aree = _estrai_aree(resp.text, base, host_comune)
        if aree:
            return aree
    return []


def _leggi_at(comune: ComuneNoto, sonda: _Sonda, link_sitemap: list[str]) -> AmministrazioneTrasparente | None:
    """Delega a B3 (`municipium_at.leggi_at`), import lazy: finché B3 non
    esiste (o fallisce) l'esito Municipium resta pieno di uffici — l'AT è
    un campo in più, non una precondizione (D-11). Firma canonica
    `(comune, sonda, link_sitemap)` — quella pinnata dal brief e
    implementata da B3 (`municipium_at.py`); `base` non serve, B3 lo
    ricava da `comune`."""
    try:
        from treasureiq.municipium_at import leggi_at
    except ImportError:
        logger.info("connettore amministrazione trasparente non ancora disponibile")
        return None
    try:
        return leggi_at(comune, sonda, link_sitemap)
    except Exception:  # noqa: BLE001 — AT muta: uffici restano, esito onesto
        logger.warning("lettura amministrazione trasparente fallita per %s", comune.nome)
        return None


def _endpoints_da_sitemap(base: str, host_comune: str, link_sitemap: list[str]) -> EndpointiConnettore:
    """Gli URL-indice DAVVERO fetchati/letti dal connettore (B9): mai un
    pattern costruito per convenzione. `mappa` è la sitemap stessa,
    attestata solo se ha fruttato almeno un link (sitemap muta/invalida →
    `_scopri_uffici` torna `[]` → mappa `None`, onesto). `servizi`/
    `amministrazione` sono il primo link same-host che matcha la top-nav
    reale `/it/menu/{servizi,amministrazione}` — verificato via fetch live
    su Pomezia/Andria/Fiumicino, NON `/it/servizi`/`/it/amministrazione`
    come si potrebbe assumere per convenzione. `amministrazione` ha
    fallback sulla pagina aree-amministrative già riconosciuta
    (`_RE_AREE_AMM_PATH`) quando il nodo menu dedicato non è in sitemap."""
    if not link_sitemap:
        return EndpointiConnettore()

    servizi = next(
        (link for link in link_sitemap if _stesso_host(link, host_comune) and _RE_SERVIZI_PATH.search(link)),
        None,
    )
    amministrazione = next(
        (link for link in link_sitemap if _stesso_host(link, host_comune) and _RE_AMM_PATH.search(link)),
        None,
    )
    if amministrazione is None:
        amministrazione = next(
            (link for link in link_sitemap if _stesso_host(link, host_comune) and _RE_AREE_AMM_PATH.search(link)),
            None,
        )

    return EndpointiConnettore(
        amministrazione=amministrazione,
        servizi=servizi,
        mappa=f"{base}/it/sitemap",
    )


def leggi_municipium(comune: ComuneNoto, sonda: _Sonda) -> EsitoConnettore:
    """Il contratto D-09 per un comune Municipium: uffici scoperti dalla
    sitemap e letti verbatim, più (se B3 c'è) l'indice Amministrazione
    Trasparente. Non persiste (lo fa il dispatcher, `connettore.py`) e non
    solleva mai: rete muta o pagine assenti diventano un esito magro
    (D-02b), non un'eccezione al chiamante."""
    ora = _ora()
    base = _base_con_schema(comune.sito)
    if base is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat,
            piattaforma=Piattaforma.MUNICIPIUM.value,
            letto_il=ora,
        )
    host_comune = _host_senza_www(urlparse(base).netloc.lower())

    try:
        link_org_unit, link_sitemap = _scopri_uffici(comune, sonda)
    except Exception:  # noqa: BLE001 — discovery muta: esito magro, mai un crash
        logger.warning("discovery municipium fallita per %s", comune.nome)
        link_org_unit, link_sitemap = [], []

    uffici: list[UfficioConnettore] = []
    for url in link_org_unit[:MAX_UFFICI]:
        try:
            ufficio = _leggi_ufficio(url, sonda, host_comune)
        except Exception:  # noqa: BLE001 — un ufficio muto non deve fermare gli altri
            logger.info("lettura ufficio fallita: %s", url)
            ufficio = None
        if ufficio is not None:
            uffici.append(ufficio)

    aree_amministrative: list[AreaAmministrativa] = []
    if not uffici:
        try:
            aree_amministrative = _aree_da_fallback(base, host_comune, link_sitemap, sonda)
        except Exception:  # noqa: BLE001 — segnale residuo opzionale, mai un crash
            aree_amministrative = []

    amministrazione_trasparente = _leggi_at(comune, sonda, link_sitemap)
    endpoints = _endpoints_da_sitemap(base, host_comune, link_sitemap)

    return EsitoConnettore(
        codice_istat=comune.codice_istat,
        piattaforma=Piattaforma.MUNICIPIUM.value,
        letto_il=ora,
        aree_amministrative=aree_amministrative,
        uffici=uffici,
        amministrazione_trasparente=amministrazione_trasparente,
        endpoints=endpoints,
    )


def _comune_da_argomento(argomento: str) -> ComuneNoto | None:
    """Il comune per ISTAT (via, canonica) o, per debug/scout, un
    `ComuneNoto` minimale costruito sul dominio passato a mano."""
    comune = comune_per_codice(argomento)
    if comune is not None:
        return comune
    if "." in argomento:
        return ComuneNoto(codice_istat="", nome=argomento, provincia="", regione="", sito=argomento)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.municipium",
        description="Legge il connettore Municipium di un comune (uffici, AT) — debug/scout, nessuna cache.",
    )
    parser.add_argument("comune", help="codice ISTAT (es. 058085) o dominio del comune (es. www.comune.pomezia.rm.it)")
    parser.add_argument("--timeout", type=float, default=8.0, help="timeout HTTP in secondi (default 8.0)")
    args = parser.parse_args(argv)

    comune = _comune_da_argomento(args.comune)
    if comune is None:
        print(f"comune non riconosciuto: {args.comune!r} (né ISTAT noto né dominio)", file=sys.stderr)
        return 1

    with _Sonda(timeout=args.timeout) as sonda:
        esito = leggi_municipium(comune, sonda)

    print(esito.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
