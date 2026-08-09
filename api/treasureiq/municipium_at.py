"""Il connettore Amministrazione Trasparente / bandi per Municipium (B3).

Contratto verso B2 (firma pinnata, D-09-style): `leggi_at(comune, sonda,
link_sitemap)`. `link_sitemap` è la lista di link GIÀ estratti dalla sitemap
da B2 — questo modulo non rifà quel fetch, parte da lì.

Scout reale (2026-08-08, Pomezia e Fiumicino — comuni Municipium veri, non
inventati): NON esiste un indice unico e affidabile dei bandi attivi sul
dominio del comune.

- **Pomezia**: la sitemap linka la trasparenza su un dominio TERZO
  (`pomezia.trasparenza-valutazione-merito.it`). La guardia host (SSRF, A5)
  lo scarta: non è il portale del comune, e leggerlo lì sarebbe un salto di
  fiducia che il comune non ha dato. Nessun candidato → `None`.
- **Fiumicino**: nessuna pagina aggregatrice, ma 40+ pagine individuali
  `public_documents/*` (bando-*, avviso-pubblico-*, ecc.) già presenti come
  link singoli nella sitemap — ognuna è la sua stessa "pagina indice" con un
  solo bando dentro. `/it/amministrazione-trasparente` risponde 410 su
  entrambi i comuni provati: il path non esiste come route diretta.

Per questo `leggi_at` non assume un indice-poi-lista: tratta ogni link
candidato (path che somiglia a bando/avviso/gara/concorso, stesso host del
comune) come una pagina da leggere. Se quella pagina contiene A SUA VOLTA
altri link-bando (un vero aggregatore, se un comune lo espone), quelli
diventano l'elenco e la pagina diventa `indice_url`; altrimenti la pagina
stessa è un bando (titolo verbatim dalla pagina, mai da LLM — D-07).

Niente analisi PDF qui (D-11): solo elenco + flag `pdf_presenti`. L'analisi
su richiesta è l'endpoint `/api/at-analisi` (B4), non questo modulo.
"""

from __future__ import annotations

import html
import logging
import re
from urllib.parse import urlparse

from treasureiq.connettore import AmministrazioneTrasparente, BandoAT
from treasureiq.ingest.censimento import _Sonda
from treasureiq.mappa_connettore import (
    _base_con_schema,
    _host_senza_www,
    _normalizza_link,
    _titolo_pagina,
)
from treasureiq.sonda_live import ComuneNoto

logger = logging.getLogger(__name__)

#: Quanti link-candidato fetchare al massimo in una lettura: Fiumicino ne ha
#: già 40+ nella sola sitemap principale, e ogni lettura è una richiesta HTTP
#: vera contro il portale del comune — un tetto protegge sia il comune che il
#: tempo di risposta della chat.
MAX_CANDIDATI = 30

#: Tetto sui bandi accumulati (candidati diretti + voci trovate dentro un
#: eventuale aggregatore): stesso principio, un aggregatore anomalo non deve
#: tradursi in centinaia di fetch impliciti nei link interni.
MAX_BANDI = 60

#: Pagine AT/bandi non sono mai enormi; un taglio difensivo evita di tenere
#: in memoria una risposta anomala (o un mimetype sbagliato servito come testo).
MAX_BYTES_PAGINA = 700_000

#: Sotto questa soglia una pagina NON è trattata come aggregatore. Una pagina-
#: bando reale (Fiumicino) porta quasi sempre un link al proprio stesso PDF di
#: allegato — un solo link interno che somiglia a un bando è quell'allegato,
#: non un indice. Un vero indice ne elenca più di uno (visto nella sitemap
#: reale con l'accordion a decine di voci).
MIN_VOCI_AGGREGATORE = 2

#: Euristica multi-parola dello scout (brief B3): bandi, bandi-di-gara, gare,
#: avvisi, concorsi, public_documents/*band*. `\b` con `-`/`_` come confine di
#: parola prende sia "bando-agevolazioni-tari" sia "public_documents/bandi".
_PAROLE_BANDO = re.compile(r"\b(band[oi]|gar[ae]|avvis[oi]|concors[oi])\b", re.I)


def _e_candidato_bando(url: str) -> bool:
    """Vero se il path dell'url somiglia a una pagina di bando/gara/avviso/
    concorso. Guarda solo il path (mai host/query) per non prendere falsi
    positivi da un dominio che contenga quelle lettere per caso.

    Un ufficio (`/it/organizational_unit/...` o `/it/unita_organizzative/...`,
    es. "Sezione Gare") NON è un bando anche se il suo path contiene una
    parola-bando (es. "gare") — escluso PRIMA del match parole."""
    path = urlparse(url).path.lower()
    if "/organizational_unit/" in path or "/unita_organizzative/" in path:
        return False
    return bool(_PAROLE_BANDO.search(path))


def _stesso_host(host_comune: str, url: str) -> bool:
    """Guardia SSRF (A5): l'url deve stare sullo stesso host del portale del
    comune, apex/`www` pareggiati come nel resto del connettore
    (`mappa_connettore._host_senza_www`)."""
    host = _host_senza_www(urlparse(url).netloc.lower())
    return bool(host) and host == host_comune


def _pulisci_testo_ancora(testo_html: str) -> str:
    """Il testo visibile di un'ancora, senza markup interno (icone SVG,
    span): stesso spirito di `_testo_pulito` altrove, ridotto all'essenziale
    perché qui serve solo come ripiego quando l'ancora non ha `title=`."""
    senza_tag = re.sub(r"<[^>]+>", " ", testo_html)
    return re.sub(r"\s+", " ", html.unescape(senza_tag)).strip()


def _pdf_nella_pagina(pagina: str, base: str) -> str | None:
    """Il primo link a un PDF nella pagina, reso assoluto. `None` se non ce
    n'è — la sola presenza guida `pdf_presenti`, l'analisi resta su
    richiesta (D-11)."""
    match = re.search(r'href=["\']([^"\']+\.pdf)["\']', pagina, re.I)
    if match is None:
        return None
    return _normalizza_link(base, html.unescape(match.group(1).strip()))


def _bandi_interni(pagina: str, base: str, host_comune: str) -> list[tuple[str, str]]:
    """Le voci-bando trovate DENTRO una pagina (caso indice aggregatore):
    ancore il cui href somiglia a un bando/gara/avviso/concorso e che stanno
    sullo stesso host del comune. Titolo dall'attributo `title` dell'ancora
    (verbatim, com'è nella sitemap di Fiumicino), o dal testo del link come
    ripiego.

    Un vero aggregatore linka altre PAGINE HTML-bando (`public_documents/*`,
    `bando-*`), non file `.pdf`: una singola pagina-avviso linka solo i
    propri allegati PDF, che non sono bandi fratelli — quei link `.pdf`
    sono esclusi qui, non contano per `MIN_VOCI_AGGREGATORE`."""
    trovati: list[tuple[str, str]] = []
    visti: set[str] = set()
    for ancora in re.finditer(
        r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", pagina, re.I | re.S
    ):
        href_grezzo, testo_interno = ancora.groups()
        href = _normalizza_link(base, html.unescape(href_grezzo.strip()))
        if not _e_candidato_bando(href) or not _stesso_host(host_comune, href):
            continue
        if href.lower().endswith(".pdf"):
            continue
        if href in visti:
            continue
        title_attr = re.search(r'title=["\']([^"\']+)["\']', ancora.group(0), re.I)
        titolo = (
            html.unescape(title_attr.group(1)).strip()
            if title_attr is not None
            else _pulisci_testo_ancora(testo_interno)
        )
        if not titolo:
            continue
        visti.add(href)
        trovati.append((titolo, href))
        if len(trovati) >= MAX_BANDI:
            break
    return trovati


def leggi_at(
    comune: ComuneNoto, sonda: _Sonda, link_sitemap: list[str]
) -> AmministrazioneTrasparente | None:
    """L'indice di Amministrazione Trasparente / bandi attivi di un comune
    Municipium, letto SOLO dai link `link_sitemap` già estratti da B2.

    `None` quando: il comune non ha sito; nessun link nella sitemap somiglia
    a una pagina di bandi/gare/avvisi/concorsi sullo STESSO host del comune
    (Pomezia reale: la trasparenza vive su un dominio terzo, scartato dalla
    guardia host); tutte le fetch falliscono; o nessuna pagina letta produce
    un bando riconoscibile. Mai un `AmministrazioneTrasparente` con
    `bandi_attivi` vuoto — l'oggetto vuoto violerebbe L-5 (conterebbe come
    "non vuoto" e verrebbe persistito dal chiamante).
    """
    base = _base_con_schema(comune.sito)
    if base is None:
        return None
    host_comune = _host_senza_www(urlparse(base).netloc.lower())

    candidati = [
        url
        for url in link_sitemap
        if _e_candidato_bando(url) and _stesso_host(host_comune, url)
    ][:MAX_CANDIDATI]
    if not candidati:
        return None

    bandi: list[BandoAT] = []
    visti: set[str] = set()
    indice_url: str | None = None

    for url in candidati:
        if len(bandi) >= MAX_BANDI:
            break
        try:
            risposta = sonda.risposta(url)
        except Exception:  # noqa: BLE001 — pagina muta: si salta, mai un crash
            logger.info("pagina bando illeggibile, salto: %s", url)
            continue
        if risposta.status_code != 200:
            continue
        if not _stesso_host(host_comune, str(risposta.url)):
            # Guardia SSRF (A5) post-redirect: il client segue i redirect, e
            # solo QUI, dopo il fetch, si sa dove è finita davvero la
            # richiesta. Un candidato pre-filtrato sullo stesso host può
            # comunque essere rediretto altrove — si scarta, non si processa.
            logger.info("bando rediretto fuori host, scarto: %s -> %s", url, risposta.url)
            continue
        pagina = risposta.text[:MAX_BYTES_PAGINA]

        interni = _bandi_interni(pagina, base, host_comune)
        interni = [(t, h) for t, h in interni if h != url]
        if len(interni) >= MIN_VOCI_AGGREGATORE:
            # Pagina-aggregatore: le voci al suo interno sostituiscono la
            # lettura a pagina singola, e questa diventa l'indice.
            if indice_url is None:
                indice_url = url
            for titolo, href in interni:
                if href in visti or len(bandi) >= MAX_BANDI:
                    continue
                visti.add(href)
                pdf_url = href if href.lower().endswith(".pdf") else None
                bandi.append(BandoAT(titolo=titolo, url=href, pdf_url=pdf_url))
            continue

        if url in visti:
            continue
        titolo = _titolo_pagina(pagina)
        if titolo is None:
            continue
        visti.add(url)
        bandi.append(BandoAT(titolo=titolo, url=url, pdf_url=_pdf_nella_pagina(pagina, base)))

    if not bandi:
        return None

    return AmministrazioneTrasparente(
        indice_url=indice_url,
        bandi_attivi=bandi,
        pdf_presenti=any(bando.pdf_url is not None for bando in bandi),
    )
