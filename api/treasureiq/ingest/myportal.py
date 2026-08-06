"""MyPortal: il catalogo dei servizi in JSON, indirizzato dal codice IPA.

I portali costruiti su MyPortal — in Emilia-Romagna la Rete Civica di Lepida —
non hanno niente di leggibile nell'HTML: sono applicazioni che si disegnano
nel browser, e la sonda su quelle pagine vedeva un guscio vuoto. Dietro però
c'è un'API vera, che risponde JSON strutturato.

Due cose la rendono economica.

*L'indirizzo si costruisce da ciò che abbiamo già.* Il percorso è
`/myportal/{codice_IPA}/…`, e il codice IPA sta scritto nella home — la
stessa pagina che la sonda scarica comunque per l'impronta. Nessuna richiesta
di scoperta, nessun elenco da mantenere a mano.

*I campi sono tipizzati e nominati come il modello AgID.* `sys_a_chi_e_rivolto`,
`sys_cosa_serve`, `sys_tempi_scadenze`, `sys_vincoli`: gli stessi nomi delle
sezioni, quindi la stessa lettura che facciamo sui campi CMB2 di WordPress.
Ed è la terza piattaforma su cui si può distinguere ciò che il fornitore ha
previsto da ciò che il comune ha riempito — la misura per cui TreasureIQ
esiste.

Il tipo di contenuto però **non** è universale: in Emilia-Romagna è
`rer_schedaservizio`, dove `rer` è la Regione. Ogni regione che adotta
MyPortal porta il proprio, e va scoperto invece che indovinato: chiedere un
tipo inesistente non dà errore, dà zero risultati — cioè un comune che sembra
non pubblicare niente.
"""

from __future__ import annotations

import re

#: Il codice IPA come lo scrive l'Indice delle Pubbliche Amministrazioni.
_CODICE_IPA = re.compile(r"\b(C_[A-Z]\d{3}[A-Z]?)\b")

#: Parole che, nel nome o nel codice di un tipo, indicano una scheda servizio.
#: Ordinate: `schedaservizio` è più specifico di `service`, che compare anche
#: in tipi che servizi non sono (`atti_opere_servizi_forniture`).
_INDIZI_SERVIZIO: tuple[str, ...] = ("schedaservizio", "scheda servizio", "service", "servizio")

#: Tipi da escludere sempre: contengono la parola ma descrivono altro.
_NON_SERVIZI: tuple[str, ...] = ("atti_opere", "forniture", "portal_service", "allegato")


def tipi_candidati(payload: object) -> list[str]:
    """I tipi che potrebbero essere schede servizio, dal più promettente.

    Ogni deployment dichiara i propri: l'Emilia-Romagna ne pubblica 31,
    il Veneto 149. Chiederglieli è meglio che tenerne una tabella a mano —
    quella invecchia in silenzio, e un tipo sbagliato non dà errore: dà zero
    risultati, cioè un comune che sembra non pubblicare niente.
    """
    if not isinstance(payload, dict):
        return []
    entita = payload.get("entities")
    if not isinstance(entita, list):
        return []
    trovati: list[tuple[int, str]] = []
    for voce in entita:
        if not isinstance(voce, dict):
            continue
        codice = str(voce.get("type") or "")
        nome = str(voce.get("name") or "")
        insieme = f"{codice} {nome}".lower()
        if any(x in insieme for x in _NON_SERVIZI):
            continue
        for posto, indizio in enumerate(_INDIZI_SERVIZIO):
            if indizio in insieme:
                trovati.append((posto, codice))
                break
    trovati.sort()
    visti: set[str] = set()
    return [c for _, c in trovati if c and not (c in visti or visti.add(c))]


def url_tipi(base: str, ipa: str) -> str:
    """Dove il portale dichiara quali tipi di contenuto pubblica."""
    return f"{base.rstrip('/')}/myportal/{ipa}/content/default-types"


def url_elenco(base: str, ipa: str, tipo: str, *, quanti: int = 5) -> str:
    """L'elenco dei contenuti di un tipo. Più semplice della ricerca a faccette
    e disponibile su entrambi i deployment visti."""
    return (
        f"{base.rstrip('/')}/myportal/{ipa}/api/content"
        f"?type={tipo}&pageIndex=1&onlyNotHidden=true&sortBy=title&pageSize={quanti}"
    )

#: Corpo minimo accettato dalla ricerca. I campi vuoti non sono decorativi:
#: l'API rifiuta con 400 la richiesta a cui ne manca uno.
#: I quattro campi di tassonomia sono **oggetti**, non liste, anche quando
#: sono vuoti: mandarli come liste fa rispondere
#: `"taxonomiesMust" must be an object`. Sembra un dettaglio e non lo è —
#: un dizionario vuoto e una lista vuota si stampano quasi uguali quando si
#: ispeziona una cattura, ed è esattamente così che ci siamo sbagliati.
CORPO_RICERCA: dict = {
    "filters": {"intervals": {}, "terms": {}},
    "taxonomiesMust": {},
    "taxonomiesShould": {},
    "extraTaxonomiesMust": {},
    "extraTaxonomiesShould": {},
    "orderBy": [],
}


#: Il modello PNRR nomina i campi in inglese, con prefisso `pnrr_`. Le
#: sezioni sono le stesse del modello AgID: cambia solo la lingua degli
#: identificatori, quindi la corrispondenza va scritta invece che dedotta.
#:
#: Restano fuori di proposito `pnrr_constraints` (i vincoli di accesso) e
#: `pnrr_particular_cases`: il modello AgID non ha una sezione per loro, e
#: inventargliene una gonfierebbe il denominatore dell'aderenza con una voce
#: che nessuno ha mai chiesto di pubblicare. Compaiono fra le non riconosciute,
#: che è il posto giusto per un campo che meritiamo di guardare ma non di
#: contare.
CAMPI_PNRR: dict[str, str] = {
    "pnrr_interlocutors": "a_chi_e_rivolto",
    "sys_description": "descrizione",
    "pnrr_how_to_do": "come_fare",
    "pnrr_what_is_needed": "cosa_serve",
    "pnrr_output": "cosa_si_ottiene",
    "pnrr_times_and_deadlines": "tempi_e_scadenze",
    "pnrr_costs": "quanto_costa",
    "pnrr_external_service_url": "accedi_al_servizio",
    "pnrr_terms_of_service": "condizioni_di_servizio",
    "pnrr_documents": "documenti_e_allegati",
    "pnrr_contacts": "contatti",
}


def alias_pnrr() -> dict:
    """La mappatura PNRR con le sezioni risolte, pronta per il lettore."""
    from treasureiq.ingest.modello_agid import SezioneAgid

    return {campo: SezioneAgid(sezione) for campo, sezione in CAMPI_PNRR.items()}


def usa_modello_pnrr(campi: dict) -> bool:
    """Questo deployment nomina i campi in inglese col prefisso PNRR?"""
    return any(k.startswith("pnrr_") for k in (campi or {}))


def codice_ipa(html: str) -> str | None:
    """Il codice IPA scritto nella home, o niente.

    Sta nell'unica pagina che scarichiamo comunque, quindi leggerlo non costa
    una richiesta. Se non c'è, il comune non è indirizzabile per questa via e
    la cosa onesta è dirlo, non tirare a indovinare un codice plausibile.
    """
    trovato = _CODICE_IPA.search(html or "")
    return trovato.group(1) if trovato else None


def normalizza_ipa(codice: str | None) -> str | None:
    """Il codice IPA nella forma che MyPortal accetta.

    IndicePA distribuisce i codici in minuscolo (`c_a138`); MyPortal risponde
    solo al maiuscolo. E non risponde con un errore: `c_a138` restituisce
    `200` con zero contenuti, cioè un comune che sembra non pubblicare
    niente. È la ragione per cui questa funzione esiste invece di una nota
    nella documentazione.
    """
    if not codice:
        return None
    pulito = codice.strip()
    return pulito.upper() if pulito else None


def url_ricerca(base: str, ipa: str, *, pagina: int = 1, quanti: int = 10) -> str:
    return (
        f"{base.rstrip('/')}/myportal/{ipa}/search-faceted-advanced"
        f"?page={pagina}&pageSize={quanti}&minimumShouldMatch=0"
    )


def corpo_ricerca(tipo: str) -> dict:
    """Il corpo della ricerca per un tipo di scheda."""
    return {**CORPO_RICERCA, "types": [tipo]}


def leggi_pagina(risposta: object) -> tuple[int | None, list[dict]]:
    """Totale e schede da una risposta di ricerca.

    Un totale assente resta `None`: zero significherebbe "questo comune non
    pubblica servizi", che è un'affermazione forte da non fare per un campo
    che semplicemente non è arrivato.
    """
    if not isinstance(risposta, dict) or risposta.get("status") != "ok":
        return None, []
    pagina = risposta.get("page")
    if not isinstance(pagina, dict):
        return None, []
    entita = pagina.get("entities")
    totale = pagina.get("entitiesCount")
    return (
        totale if isinstance(totale, int) else None,
        [e for e in entita if isinstance(e, dict)] if isinstance(entita, list) else [],
    )


def campi_scheda(entita: dict) -> dict:
    """Gli attributi tipizzati di una scheda, come li espone MyPortal."""
    attributi = entita.get("attributes")
    return attributi if isinstance(attributi, dict) else {}
