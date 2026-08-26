"""Arricchimento on-demand di un ufficio nominato dalla sua scheda-dettaglio.

Il livello acquisizione del flusso v1: preso l'ufficio catalogato dallo sweep
(`UfficioConnettore`, con la sua URL), ne legge ADESSO la pagina di dettaglio e
ne ritorna una copia con i campi letti sovrascritti: `orari` (la pagina
dedicata ha quasi sempre l'orario di *quell'* ufficio, non quello dell'URP di
ripiego) e, dove la famiglia li pubblica strutturati, `indirizzo` e
`responsabile` (estrattori per famiglia in `ufficio_estrattori`, via
`piattaforma`). Da lì i campi fluiscono per proiezione
(`catalog/flotta/_projection.py`) fino al `DataBatch` — senza che questo modulo
tocchi né la proiezione (che resta pura, senza rete) né la chat.

Questa è la rete del drill: la proiezione NON rilegge. La separazione dei tre
livelli (acquisizione → proiezione → arricchimento) vuole il fetch qui, una
volta, e la proiezione a valle sul risultato già acquisito.

Confini ereditati da `leggi_orari_ufficio` (D-32/D-33/D-34): si legge la URL
catalogata (mai indovinata), dietro la guardia SSRF e la cache; non solleva
mai. Un orario non trovato NON degrada l'ufficio a `None`: si torna l'ufficio
giusto con `orari=None`, così la scheda dice «non pubblicato per questo
ufficio» invece di spacciare quello dell'URP.
"""

from __future__ import annotations

from dataclasses import dataclass

from treasureiq.connettore import UfficioConnettore
from treasureiq.orari_ufficio import leggi_orari_ufficio
from treasureiq.ufficio_estrattori import _RESP_PER_FAMIGLIA


@dataclass(frozen=True)
class UfficioArricchito:
    """Un ufficio dopo la lettura on-demand della sua scheda-dettaglio.

    `ufficio` è una copia dell'ufficio catalogato con i campi letti dalla
    pagina sovrascritti (oggi: `orari`; prossimo step: `indirizzo`,
    `responsabile`). `orari_fonte` è la citazione verbatim dell'orario da
    affiancare come prova quando `ufficio.orari` è la forma normalizzata
    (D-07); `None` quando `orari` è già verbatim o non c'è alcun orario.
    """

    ufficio: UfficioConnettore
    orari_fonte: str | None
    #: La scheda-dettaglio è stata davvero ispezionata da una famiglia che
    #: pubblica il responsabile in forma strutturata (Slice 2): pagina raggiunta
    #: E famiglia con estrattore `responsabile`. Solo allora un `responsabile is
    #: None` significa «il Comune non lo pubblica» (mostrabile come tale a valle);
    #: `False` — URP di ripiego, famiglia senza estrattore, fetch fallita — vuol
    #: dire «mai verificato», e a valle il campo resta semplicemente nascosto.
    responsabile_ispezionato: bool = False


def arricchisci_ufficio(
    *, codice_istat: str, ufficio: UfficioConnettore, piattaforma: str | None = None
) -> UfficioArricchito:
    """Legge ADESSO la scheda-dettaglio dell'ufficio e ne ritorna una copia
    arricchita.

    `ufficio.orari` diventa la forma normalizzata (`OrarioSettimanale.reso`)
    quando la pagina la consente; altrimenti la citazione verbatim, con ripiego
    onesto sull'orario catalogato quando la pagina non ne pubblica uno.
    `orari_fonte` porta il verbatim da affiancare SOLO quando abbiamo
    normalizzato (D-07). `indirizzo` e `responsabile` entrano nella copia SOLO
    quando la scheda li pubblica (estrattori per famiglia, via `piattaforma`):
    un campo assente non sovrascrive mai con `None` ciò che l'indice aveva.

    Senza URL non c'è nulla da leggere: si torna l'ufficio catalogato
    invariato. Non solleva mai (`leggi_orari_ufficio` degrada da sé).
    """
    if not ufficio.url:
        # Nessuna URL da leggere: la scheda non è mai stata ispezionata.
        return UfficioArricchito(
            ufficio=ufficio, orari_fonte=None, responsabile_ispezionato=False
        )

    letto = leggi_orari_ufficio(
        codice_istat=codice_istat, url=ufficio.url, piattaforma=piattaforma
    )
    if letto is not None and letto.orario_schema is not None:
        # Pagina letta e orario in forma normalizzabile: mostra la forma pulita,
        # tieni il verbatim come fonte.
        display: str | None = letto.orario_schema.reso
        fonte: str | None = letto.orari
    else:
        # Niente schema: l'orario migliore che abbiamo (verbatim dalla pagina o
        # dal catalogo) va mostrato così com'è, senza una fonte da affiancare.
        display = (letto.orari if letto is not None else None) or ufficio.orari
        fonte = None

    aggiornamento: dict[str, object] = {"orari": display}
    if letto is not None and letto.indirizzo is not None:
        aggiornamento["indirizzo"] = letto.indirizzo
    if letto is not None and letto.responsabile is not None:
        aggiornamento["responsabile"] = letto.responsabile

    # Segnale onesto (Slice 2): il responsabile è «verificato assente» solo se la
    # pagina è stata davvero raggiunta E la famiglia ha un estrattore responsabile.
    # Una fetch fallita (`pagina_letta=False`) o una famiglia senza estrattore non
    # autorizzano a dire «non pubblicato» — resta «non verificato».
    responsabile_ispezionato = (
        letto is not None
        and letto.pagina_letta
        and (piattaforma or "") in _RESP_PER_FAMIGLIA
    )

    arricchito = ufficio.model_copy(update=aggiornamento)
    return UfficioArricchito(
        ufficio=arricchito,
        orari_fonte=fonte,
        responsabile_ispezionato=responsabile_ispezionato,
    )
