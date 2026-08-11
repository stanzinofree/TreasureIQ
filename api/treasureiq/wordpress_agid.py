"""Connettore WordPress-AgID (D-09): ADAPTER su `mappa_connettore`, non un
nuovo scraper.

Copre le famiglie WordPress a modello AgID/Comuni-Italia riconosciute da
`ingest.piattaforma` (`WP_DESIGN_COMUNI`, `WORDPRESS_GENERICO`,
`COMUNIBOOTSTRAPITALIA`): tutte espongono lo stesso REST di WordPress core
(`/wp-json/wp/v2/...`), la stessa cosa che `mappa_connettore` già sonda e
mette in cache per il routing diretto-vs-web. Questo modulo non fa una
seconda misura del portale — legge la mappa già pronta e la traduce nel
contratto D-09 (`EsitoConnettore`), lo stesso seam di `openweb.py`/
`peopleweb.py` ma senza fetch HTML: dove serve una lista, è REST JSON.

**Uffici**: index-only (nome+url), da `{base}/wp-json/wp/v2/{rest_base}
?per_page=100&_fields=title,link` — `rest_base` letto da `mappa.uffici`,
mai indovinato. `source_typed=False`: nessun recapito tipizzato qui, il
drill sulla scheda individuale resta deferred come negli altri connettori
di questa famiglia (costo +1 GET/ufficio non gentile a scala nazionale).

**Aree amministrative**: `mappa.servizi.categorie` (`CategoriaServizio`)
non porta un `url` — solo `nome`/`conteggio`/`id`/`slug` (vedi
`mappa_connettore.CategoriaServizio`). Senza un link reale non si fabbrica
un URL: `aree_amministrative` resta `[]`, onesto invece di indovinato.

**Amministrazione Trasparente**: solo `indice_url`, mai il drill bandi/PDF
(quello resta la strada REST già coperta da `mappa_connettore.bandi_criteri`
per chi lo consuma altrove). Si popola SOLO se il portale conferma la rotta
— una GET diretta sulla pagina convenzionale, o `mappa.
amministrazione_trasparente_via == "REST"` (il CPT è nell'indice tipi) — per
non fabbricare un link mai visto rispondere.

**Logo**: `estrai_logo_wordpress_agid`, firma identica a
`estrai_logo_openweb`/`estrai_logo_peopleweb` (`(pagina_home, base,
host_comune) -> str | None`) — SVG inline in `<header>` (tema tipo openweb)
prima, poi `<img>` in `.it-brand-wrapper` (tema tipo peopleweb) come
ripiego: entrambi i temi Bootstrap-Italia osservati sulle famiglie WP-AgID
vicine. Same-HOST stretto (D-S8): un url fuori dall'host esatto del comune
torna `None`, mai un CDN terzo.

`leggi_wordpress_agid` non solleva MAI: una sezione impraticabile resta al
degrado D-10 (lista/valore vuoto per quella sola sezione), le altre
estraggono comunque — stesso taglio di `openweb.leggi_openweb`.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from treasureiq.connettore import (
    AmministrazioneTrasparente,
    AreaAmministrativa,
    EsitoConnettore,
    UfficioConnettore,
)
from treasureiq.ingest.censimento import _Sonda
from treasureiq.mappa_connettore import (
    MappaConnettore,
    _base_con_schema,
    _host_senza_www,
    mappa_connettore,
)
from treasureiq.sonda_live import ComuneNoto

logger = logging.getLogger(__name__)

#: Piattaforma dichiarata da questo connettore (letterale, come
#: `openweb.PIATTAFORMA_OPENWEB` — copre più membri dell'enum `Piattaforma`
#: a monte, quindi non ha senso legarla a uno solo).
PIATTAFORMA_WORDPRESS_AGID = "wordpress_agid"

#: Cap difensivo sul numero di uffici estratti — stesso taglio di
#: `openweb.MAX_UFFICI_INDICE`/`peopleweb.MAX_UFFICI_INDICE`.
MAX_UFFICI_INDICE = 200

#: Il blocco `<header>...</header>` della home, dove vive il logo inline SVG
#: sui temi tipo openweb (`<image xlink:href=...>` dentro `<svg>`).
_RE_IMAGE_TAG = re.compile(r"<image\b[^>]*(?:xlink:href|href)=[\"']([^\"']+)[\"']", re.IGNORECASE)

#: `<img src="...">` dentro `.it-brand-wrapper` sui temi tipo peopleweb.
_RE_IMG_SRC = re.compile(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)


def _ora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _leggi_uffici_wordpress_agid(
    sonda: _Sonda, base: str, rest_base: str
) -> list[UfficioConnettore]:
    """Indice uffici REST, index-only: nome+url, `source_typed=False`,
    dedup per URL, cap `MAX_UFFICI_INDICE`. `[]` su qualunque errore — una
    collezione muta è un esito, non un guasto."""
    try:
        righe = sonda.json(f"{base}/wp-json/wp/v2/{rest_base}?per_page=100&_fields=title,link")
    except Exception:  # noqa: BLE001 — collezione muta: nessun ufficio
        return []
    if not isinstance(righe, list):
        return []
    ora = _ora()
    uffici: list[UfficioConnettore] = []
    visti: set[str] = set()
    for riga in righe:
        if not isinstance(riga, dict):
            continue
        titolo_raw = riga.get("title")
        titolo = titolo_raw.get("rendered") if isinstance(titolo_raw, dict) else titolo_raw
        link = riga.get("link")
        if not titolo or not link:
            continue
        url = str(link)
        if url in visti:
            continue
        visti.add(url)
        uffici.append(
            UfficioConnettore(
                nome=html.unescape(str(titolo)).strip(),
                url=url,
                source_typed=False,
                letto_il=ora,
            )
        )
        if len(uffici) >= MAX_UFFICI_INDICE:
            break
    return uffici


def _leggi_at_wordpress_agid(
    sonda: _Sonda, base: str, mappa: MappaConnettore
) -> AmministrazioneTrasparente | None:
    """L'indice AT convenzionale (`{base}/amministrazione-trasparente/`),
    accettato solo se confermato: una GET diretta che risponde 200, o
    `mappa.amministrazione_trasparente_via == "REST"` (il CPT `amm-
    trasparente` è nell'indice tipi WordPress, D-B2). Senza nessuno dei due
    segnali torna `None` — mai un link fabbricato su un portale mai visto
    rispondere lì. Solo `indice_url`: nessun drill bandi/PDF qui."""
    url = f"{base}/amministrazione-trasparente/"
    confermato = False
    try:
        risposta = sonda.risposta(url)
        confermato = risposta.status_code == 200
    except Exception:  # noqa: BLE001 — pagina muta: nessuna conferma, non un crash
        confermato = False
    if confermato or mappa.amministrazione_trasparente_via == "REST":
        return AmministrazioneTrasparente(indice_url=url, bandi_attivi=[], pdf_presenti=False)
    return None


def estrai_logo_wordpress_agid(pagina_home: str, base: str, host_comune: str) -> str | None:
    """Il logo del comune dal brand Bootstrap-Italia della home. Le famiglie
    WP-AgID condividono il tema con openweb/peopleweb ma non uniformemente:
    si prova prima l'SVG inline in `<header>` (tipo openweb), poi `<img>` in
    `.it-brand-wrapper` (tipo peopleweb) come ripiego. Same-HOST stretto
    (D-S8, come `registro._estrai_logo_header`): un url fuori dall'host
    esatto del comune torna `None`, mai un CDN terzo. Pura — nessun fetch."""
    pagina_lower = pagina_home.lower()
    inizio_header = pagina_lower.find("<header")
    if inizio_header != -1:
        fine = pagina_lower.find("</header>", inizio_header)
        if fine == -1:
            fine = inizio_header + 40_000  # margine di cortesia, non l'intera pagina
        blocco = pagina_home[inizio_header:fine]
        match = _RE_IMAGE_TAG.search(blocco)
        if match is not None:
            href = html.unescape(match.group(1)).strip()
            if href:
                url = urljoin(base, href)
                if _host_senza_www(urlparse(url).netloc.lower()) == host_comune:
                    return url

    inizio_brand = pagina_home.find("it-brand-wrapper")
    if inizio_brand != -1:
        finestra = pagina_home[inizio_brand : inizio_brand + 1500]
        trovato = _RE_IMG_SRC.search(finestra)
        if trovato is not None:
            src = html.unescape(trovato.group(1)).strip()
            if src:
                url = urljoin(base, src)
                if _host_senza_www(urlparse(url).netloc.lower()) == host_comune:
                    return url
    return None


def leggi_wordpress_agid(comune: ComuneNoto, sonda: _Sonda) -> EsitoConnettore:
    """Contratto D-09 per la famiglia WordPress-AgID. Firma congelata come
    `openweb.leggi_openweb`/`peopleweb.leggi_peopleweb`: `(comune, sonda) ->
    EsitoConnettore`, MAI un'eccezione — un comune senza nulla da leggere è
    un esito vuoto onesto (`connettore._esito_vuoto` lo riconosce).

    ADAPTER: nessun fetch HTML proprio. Legge `mappa_connettore(comune.
    codice_istat)` (già sonda/cache il portale per il routing diretto-vs-web)
    e la traduce nel contratto D-09 — se la mappa è assente o degradata,
    l'esito lo è altrettanto, mai un crash.
    """
    letto_il = _ora()
    try:
        mappa = mappa_connettore(comune.codice_istat)
    except Exception:  # noqa: BLE001 — mappa muta: esito vuoto onesto, mai un crash
        logger.warning("wordpress_agid: mappa connettore fallita per %s", comune.nome)
        mappa = None
    if mappa is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat,
            piattaforma=PIATTAFORMA_WORDPRESS_AGID,
            letto_il=letto_il,
        )
    base = _base_con_schema(mappa.sito)
    if base is None:
        return EsitoConnettore(
            codice_istat=comune.codice_istat,
            piattaforma=PIATTAFORMA_WORDPRESS_AGID,
            letto_il=letto_il,
        )

    uffici: list[UfficioConnettore] = []
    if mappa.uffici.esposto and mappa.uffici.rest_base:
        try:
            uffici = _leggi_uffici_wordpress_agid(sonda, base, mappa.uffici.rest_base)
        except Exception:  # noqa: BLE001 — indice uffici muto: esito senza uffici, mai un crash
            logger.warning("wordpress_agid: lettura indice uffici fallita per %s", comune.nome)
            uffici = []

    # `CategoriaServizio` (mappa.servizi.categorie) non porta un `url`: senza
    # un link reale non si fabbrica una `AreaAmministrativa` (D-01 onesto).
    aree_amministrative: list[AreaAmministrativa] = []

    amministrazione_trasparente: AmministrazioneTrasparente | None = None
    try:
        amministrazione_trasparente = _leggi_at_wordpress_agid(sonda, base, mappa)
    except Exception:  # noqa: BLE001 — ricerca AT muta: esito senza AT, mai un crash
        logger.warning("wordpress_agid: ricerca AT fallita per %s", comune.nome)
        amministrazione_trasparente = None

    return EsitoConnettore(
        codice_istat=comune.codice_istat,
        piattaforma=PIATTAFORMA_WORDPRESS_AGID,
        letto_il=letto_il,
        aree_amministrative=aree_amministrative,
        uffici=uffici,
        amministrazione_trasparente=amministrazione_trasparente,
    )


def _leggi_wordpress_agid_cli(codice_istat: str, *, timeout: float = 8.0) -> None:
    """Uso standalone (`python -m treasureiq.wordpress_agid <istat>`),
    stesso stampo del CLI di `openweb.py`/`peopleweb.py`."""
    from treasureiq.sonda_live import comune_per_codice

    comune = comune_per_codice(codice_istat)
    if comune is None:
        print(f"comune non trovato: {codice_istat}")
        return
    with _Sonda(timeout=timeout) as sonda:
        esito = leggi_wordpress_agid(comune, sonda)
    print(esito.model_dump_json(indent=1))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Connettore WordPress-AgID (D-09)")
    parser.add_argument("codice_istat", help="codice ISTAT del comune")
    parser.add_argument("--timeout", type=float, default=8.0, help="timeout per richiesta (default 8.0)")
    args = parser.parse_args()
    _leggi_wordpress_agid_cli(args.codice_istat, timeout=args.timeout)
