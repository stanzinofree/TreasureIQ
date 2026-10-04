"""Estrattori per famiglia di `indirizzo` e `responsabile` dalla scheda-dettaglio.

Funzioni pure HTML→dato: prendono la pagina di dettaglio di un ufficio (la
stessa già scaricata una volta da `leggi_orari_ufficio`, mai una seconda fetch)
e ne leggono, dove la famiglia le pubblica in forma strutturata, l'indirizzo
della sede e il responsabile. Nessuna rete, nessun LLM: solo lettura di ciò che
la pagina espone (D-07). Un campo assente resta `None` (non pubblicato, D-05),
mai inventato.

Onestà semantica dei due campi:

*`indirizzo`* è la sede dell'edificio/ente che ospita l'ufficio (municipio,
palazzo civico), condivisa da più uffici e NON esclusiva di quello nominato:
risponde a «dove vado», non «stanza di quell'ufficio». Documentato così a
monte (workstream Ramo 1).

*`responsabile`* porta `nome` (l'ancora di accountability, obbligatoria) e
`ruolo` quando la scheda lo espone come etichetta strutturata; `email`
personale non è MAI pubblicata dai portali → resta `None`.

Dispatch per famiglia sul valore `piattaforma` dell'`EsitoConnettore`. La
famiglia `peopleweb` è un solo fingerprint su DUE vendor (OpenWeb.NET e Siscom)
con DOM diversi: il suo ramo prova entrambe le forme. Vedi memoria
`peopleweb-due-vendor-openweb-siscom`.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlsplit

from treasureiq.connettore import PersonaUfficio, Responsabile

_RE_TAG = re.compile(r"<[^>]+>")

#: Un indirizzo civico italiano: parola-chiave di via + testo + CAP a 5 cifre,
#: con l'eventuale coda «Comune (PROV)». Ancorato al CAP per non catturare la
#: prosa attorno (es. «Orari al pubblico:») che segue nello stesso blocco.
_RE_INDIRIZZO = re.compile(
    r"((?:Via|Viale|Piazza|Piazzale|Corso|Largo|Vicolo|Strada|Borgo|Località)\b"
    r"[^<>\n]{2,80}?\b\d{5}\b"
    r"(?:\s+[A-Za-zÀ-ÿ'’.\- ]{2,30}?\([A-Z]{2}\))?)",
    re.I,
)


def _testo(frammento: str) -> str:
    """Testo pulito da un frammento HTML: tag via, entità sciolte, spazi normali."""
    return re.sub(r"\s+", " ", html.unescape(_RE_TAG.sub(" ", frammento))).strip()


def _inner(pagina: str, elem_id: str) -> str | None:
    """L'HTML interno dell'elemento con quell'`id`, con bilanciamento dello stesso
    tag (gestisce l'annidamento). `None` se l'id non c'è o il tag non si chiude."""
    apri = re.search(r'<(\w+)[^>]*\bid=["\']%s["\'][^>]*>' % re.escape(elem_id), pagina, re.I)
    if apri is None:
        return None
    tag = apri.group(1)
    inizio = apri.end()
    apertura = re.compile(r"<%s\b" % re.escape(tag), re.I)
    chiusura = re.compile(r"</%s>" % re.escape(tag), re.I)
    profondita = 1
    pos = inizio
    while profondita and pos < len(pagina):
        na = apertura.search(pagina, pos)
        nc = chiusura.search(pagina, pos)
        if nc is None:
            return None
        if na is not None and na.start() < nc.start():
            profondita += 1
            pos = na.end()
        else:
            profondita -= 1
            pos = nc.end()
            if profondita == 0:
                return pagina[inizio:nc.start()]
    return None


def _finestra(pagina: str, elem_id: str, n: int = 800) -> str | None:
    """Finestra grezza a partire dall'elemento con quell'`id`, fermata al
    prossimo `id=` (per non sconfinare nel blocco successivo).

    Serve al DOM Siscom, dove l'`id` sta su una `<span>` che avvolge solo
    l'etichetta e il valore vive nel `<div>` fratello: il bilanciamento del tag
    non basta, si legge la coda."""
    m = re.search(r'\bid=["\']%s["\']' % re.escape(elem_id), pagina, re.I)
    if m is None:
        return None
    coda = pagina[m.end():m.end() + n]
    successivo = re.search(r'\bid=["\']', coda)
    return coda[: successivo.start()] if successivo else coda


def _indirizzo_civico(frammento: str) -> str | None:
    """Il primo indirizzo civico riconoscibile nel testo del frammento."""
    m = _RE_INDIRIZZO.search(_testo(frammento))
    if m is None:
        return None
    return m.group(1).strip(" ,;-")


# --------------------------------------------------------------------------- #
# responsabile — per famiglia
# --------------------------------------------------------------------------- #


def _resp_openpa(pagina: str) -> Responsabile | None:
    blocco = _inner(pagina, "responsabile")
    if not blocco:
        return None
    mnome = re.search(r"<h3[^>]*card-title[^>]*>(.*?)</h3>", blocco, re.I | re.S)
    if mnome is None:
        return None
    nome = _testo(mnome.group(1))
    if not nome:
        return None
    mruolo = re.search(r"<li[^>]*>(.*?)</li>", blocco, re.I | re.S)
    ruolo = _testo(mruolo.group(1)) if mruolo else ""
    return Responsabile(nome=nome, ruolo=ruolo or None)


def _resp_openweb(pagina: str) -> Responsabile | None:
    blocco = _inner(pagina, "persone")
    if not blocco:
        return None
    manchor = re.search(r"<a[^>]*card-title[^>]*>(.*?)</a>", blocco, re.I | re.S)
    if manchor is None:
        return None
    nome = _testo(manchor.group(1))
    if not nome:
        return None
    mruolo = re.search(r"<small[^>]*descrizione_breve[^>]*>(.*?)</small>", blocco, re.I | re.S)
    ruolo = _testo(mruolo.group(1)) if mruolo else ""
    return Responsabile(nome=nome, ruolo=ruolo or None)


def _resp_peopleweb(pagina: str) -> Responsabile | None:
    # Vendor OpenWeb.NET: il nome è l'ancora dentro la card responsabile
    # (solo nome, il ruolo non è esposto come campo strutturato).
    blocco = _inner(pagina, "ContentPlaceHolder1_card_responsabile")
    if blocco:
        manchor = re.search(r"<a[^>]*>(.*?)</a>", blocco, re.I | re.S)
        nome = _testo(manchor.group(1)) if manchor else _testo(blocco)
        if nome:
            return Responsabile(nome=nome, ruolo=None)
    # Vendor Siscom: id-etichetta, valore nel div fratello. Il responsabile
    # dell'ufficio (`#resp`) prima del dirigente d'area (`#dirigente`).
    for elem_id, etichetta in (("resp", "Responsabile"), ("dirigente", "Dirigente")):
        fin = _finestra(pagina, elem_id, 800)
        if not fin:
            continue
        m = re.search(r"chip-label[^>]*>(.*?)</span>", fin, re.I | re.S)
        if m is None:
            continue
        nome = _testo(m.group(1))
        if nome:
            return Responsabile(nome=nome, ruolo=etichetta)
    return None


def _resp_municipium(pagina: str) -> Responsabile | None:
    testata = re.search(r"Persone che compongono la struttura\s*</h2>", pagina, re.I)
    if testata is None:
        return None
    frag = pagina[testata.end():testata.end() + 2000]
    manchor = re.search(r'<a[^>]*href="[^"]*/person/[^"]*"[^>]*>(.*?)</a>', frag, re.I | re.S)
    if manchor is None:
        return None
    nome = _testo(manchor.group(1))
    if not nome:
        return None
    return Responsabile(nome=nome, ruolo=None)


_RESP_PER_FAMIGLIA = {
    "openpa": _resp_openpa,
    "openweb": _resp_openweb,
    "peopleweb": _resp_peopleweb,
    "municipium": _resp_municipium,
}


def estrai_responsabile(pagina: str, *, piattaforma: str | None) -> Responsabile | None:
    """Il responsabile pubblicato dalla scheda, secondo la forma della famiglia.

    `None` se la famiglia non ha un estrattore, se la pagina non pubblica un
    responsabile in forma strutturata, o se manca il nome (senza nome un
    `Responsabile` non esiste)."""
    estrattore = _RESP_PER_FAMIGLIA.get(piattaforma or "")
    return estrattore(pagina) if estrattore else None


def estrai_persone(
    pagina: str, *, piattaforma: str | None, url: str
) -> list[PersonaUfficio]:
    """Tutte le persone del blocco WordPress `#persone`, senza gerarchizzarle."""
    if piattaforma != "wordpress_agid":
        return []
    blocco = _inner(pagina, "persone")
    if not blocco:
        return []
    persone: list[PersonaUfficio] = []
    visti: set[str] = set()
    for titolo, ruolo_html in re.findall(
        r"<h4\b[^>]*>(.*?)</h4>\s*<p\b[^>]*>(.*?)</p>", blocco, re.I | re.S
    ):
        anchor = re.search(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                           titolo, re.I | re.S)
        if anchor is None:
            continue
        persona_url = urljoin(url, html.unescape(anchor.group(1)))
        if (urlsplit(persona_url).scheme not in {"http", "https"}
                or (urlsplit(persona_url).hostname or "").removeprefix("www.")
                != (urlsplit(url).hostname or "").removeprefix("www.")):
            continue
        nome = _testo(anchor.group(2))
        if not nome or persona_url in visti:
            continue
        visti.add(persona_url)
        persone.append(PersonaUfficio(
            nome=nome, ruolo=_testo(ruolo_html) or None, url=persona_url,
        ))
    return persone


def estrai_recapiti(
    pagina: str, *, piattaforma: str | None
) -> tuple[list[str], list[str]]:
    """Recapiti diretti nel solo blocco `#contatti` della scheda WordPress."""
    if piattaforma != "wordpress_agid":
        return [], []
    blocco = _inner(pagina, "contatti")
    if not blocco:
        return [], []
    telefoni = [
        _testo(valore)
        for valore in re.findall(r"<p\b[^>]*>\s*Tel\.?\s*([^<]+)</p>", blocco, re.I)
    ]
    telefoni = list(dict.fromkeys(v for v in telefoni if re.fullmatch(r"\+?[\d\s().-]{6,}", v)))
    email = [
        html.unescape(valore).strip()
        for valore in re.findall(r'href=["\']mailto:([^"\']+)["\']', blocco, re.I)
    ]
    email = list(dict.fromkeys(v for v in email if "@" in v))
    return telefoni, email


# --------------------------------------------------------------------------- #
# indirizzo — per famiglia
# --------------------------------------------------------------------------- #


def _ind_openpa(pagina: str) -> str | None:
    blocco = _inner(pagina, "sede")
    return _indirizzo_civico(blocco) if blocco else None


def _ind_openweb(pagina: str) -> str | None:
    blocco = _inner(pagina, "sede_principale")
    return _indirizzo_civico(blocco) if blocco else None


def _ind_peopleweb(pagina: str) -> str | None:
    # Vendor OpenWeb.NET: indirizzo già in chiaro nel suo campo testuale.
    blocco = _inner(pagina, "ContentPlaceHolder1_indirizzo_testuale")
    if blocco:
        testo = _testo(blocco)
        if testo:
            return testo
    # Vendor Siscom: valore dopo l'etichetta «Indirizzo:» dentro il blocco luogo.
    fin = _finestra(pagina, "Luogo", 900)
    if fin:
        m = re.search(r"Indirizzo:\s*</b>\s*([^<]+)", fin, re.I)
        if m:
            testo = _testo(m.group(1))
            if testo:
                return testo
    return None


def _ind_municipium(pagina: str) -> str | None:
    # Municipium espone la sede dell'ente come PostalAddress JSON-LD.
    m = re.search(r'"streetAddress"\s*:\s*"([^"]+)"', pagina)
    if m is None:
        return None
    return _testo(m.group(1)) or None


def _ind_wordpress_agid(pagina: str) -> str | None:
    blocco = _inner(pagina, "sede-principale")
    if not blocco:
        return None
    testo = re.search(r'<div\b[^>]*class=["\'][^"\']*card-text[^"\']*["\'][^>]*>\s*<p>(.*?)</p>',
                      blocco, re.I | re.S)
    return _testo(testo.group(1)) if testo else _indirizzo_civico(blocco)


_IND_PER_FAMIGLIA = {
    "openpa": _ind_openpa,
    "openweb": _ind_openweb,
    "peopleweb": _ind_peopleweb,
    "municipium": _ind_municipium,
    "wordpress_agid": _ind_wordpress_agid,
}


def estrai_indirizzo(pagina: str, *, piattaforma: str | None) -> str | None:
    """L'indirizzo della sede pubblicato dalla scheda, secondo la forma della
    famiglia. `None` se la famiglia non ha un estrattore o la pagina non lo
    pubblica in forma riconoscibile."""
    estrattore = _IND_PER_FAMIGLIA.get(piattaforma or "")
    return estrattore(pagina) if estrattore else None
