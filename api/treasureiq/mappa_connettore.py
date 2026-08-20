"""Mappa di capacità di un connettore comunale, misurata al volo e messa in cache.

Per un comune a modello AgID il portale espone, via REST, molto più degli uffici
già sondati da `sonda_connettore`: il catalogo **servizi** e la sua tassonomia di
**categorie** (le 15 categorie standard del modello). Sapere in anticipo *cosa*
un connettore espone serve a tre cose distinte, tutte a costo zero-runtime:

1. **routing diretto-vs-web** — se i servizi sono in API, una domanda «come faccio
   X» si risponde dall'API invece che dalla ricerca web;
2. **chip a cascata** — le categorie con conteggio sono le voci fra cui far
   scegliere il cittadino senza ridigitare;
3. **worklist di ingestion** — ogni servizio ha una pagina di dettaglio con la
   modulistica (PDF): la lista servizi È la coda di ingestion di domani.

Confini onesti, misurati su Bisceglie/Figline/Perugia/Benevento e non da
assumere altrove — si sonda, non si assume:
- **servizi**: CPT REST (`servizi`), con tassonomia `categorie_servizio`. C'è.
- **amministrazione trasparente** (dove vivono bandi/agevolazioni): CPT REST
  (`amm-trasparente`, D-B2) quando il tema lo espone. `amministrazione_trasparente_via`
  è `"REST"` solo se il type compare in `/wp-json/wp/v2/types` — su Figline c'è,
  la vecchia nota qui che la dava scrape-only era sbagliata.
- **contatti URP**: CPT REST candidato (`punti_di_contatto` e varianti, stesso
  vocabolario chiuso di uffici/servizi) — MAI visto esposto sui comuni sondati
  finora: resta scrape (`recupera_contatti`). Qui si registra solo la *via*,
  non i dati.

Nessun giudizio di spettanza qui: è una misura di struttura del portale, come il
censimento. D-01 resta intatto — questa mappa non risponde a nessun cittadino da
sola, dice solo per quali strade lo *potremmo* fare a basso costo.
"""

from __future__ import annotations

import argparse
import html
import logging
import re
import sys
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from treasureiq.ingest.censimento import REST_BASE_UFFICI, _Sonda
from treasureiq.sonda_live import LIVE_DIR, ComuneNoto, comune_per_codice

logger = logging.getLogger(__name__)

#: Una mappa più vecchia di così va rimisurata: il catalogo di un comune cambia
#: di rado, ma non è immutabile, e una categoria in meno è meno grave di una
#: categoria fantasma.
GIORNI_VALIDITA = 30

#: Come il tema AgID nomina il CPT dei servizi. `servizi` è il `rest_base`
#: canonico del Design Comuni; le varianti coprono deployment più vecchi.
REST_BASE_SERVIZI: tuple[str, ...] = ("servizi", "servizio", "servizio_pubblico")

#: La tassonomia delle categorie di servizio. `categorie_servizio` è quella del
#: modello (15 voci standard); si tiene comunque un fallback per nome.
REST_BASE_CATEGORIE: tuple[str, ...] = (
    "categorie_servizio",
    "categoria_servizio",
    "categorie-servizio",
)

#: Il CPT di Amministrazione Trasparente e lo slug del term dei bandi al suo
#: interno. Fissi per contratto (D-B2 vale per il term, non per questi due:
#: sono il CPT e lo slug attesi dal tema, non capacità sondate).
CPT_AMM_TRASPARENTE = "amm-trasparente"
SLUG_TERM_BANDI = "criteri-e-modalita"

#: Vocabolario chiuso per il CPT dei contatti URP (probe, non assunzione):
#: `punti_di_contatto` è il nome atteso dal tema Comuni Italia; le varianti
#: coprono grafie diverse. Su nessun comune sondato finora è REST — si
#: registra solo la via, non si inventa una copertura che non c'è (D-S1).
REST_BASE_CONTATTI: tuple[str, ...] = (
    "punti_di_contatto",
    "punto_di_contatto",
    "punti-di-contatto",
)


class CategoriaServizio(BaseModel):
    """Una categoria di servizio con quanti servizi ci ricadono.

    `id` è il term della tassonomia: serve a scendere di livello (filtrare i
    servizi di questa categoria). Default `0` per i portali che non lo espongono
    — un chip senza `id` mostra il conteggio ma non fa da imbuto.
    """

    nome: str
    conteggio: int
    id: int = 0
    slug: str = ""


class ServizioLink(BaseModel):
    """Un servizio del catalogo comunale: il titolo e il link alla sua pagina.

    È la foglia della cascata: non un verdetto e non un modulo estratto, ma la
    pagina del portale del comune «citata come fonte». Chi la apre legge la
    scheda vera del servizio, dove — in produzione — vive la modulistica PDF.
    """

    titolo: str
    url: str


class SchedaServizio(BaseModel):
    """L'anteprima di un servizio, letta adesso dalla sua pagina sul portale.

    Le sezioni sono quelle standard del modello «Servizi» AgID (tema Comuni
    Italia): stessi ancoraggi su ogni comune a modello, quindi l'estrazione è
    la stessa ovunque. Non è un verdetto e non è modulistica estratta: è un
    riassunto della scheda «citata come fonte», con `url` per aprirla intera.
    D-01 intatto: nessun numero, nessuna eleggibilità — solo cosa è il servizio.
    """

    titolo: str
    url: str
    descrizione: str | None = None
    a_chi: str | None = None
    cosa_ottieni: str | None = None


class Bando(BaseModel):
    """Un bando/criterio pubblicato su Amministrazione Trasparente: titolo,
    link alla pagina, data grezza (passthrough REST) e anteprima.

    Fonte citata, non verdetto: nessuna cifra toccata o generata dal modello
    (D-B7), nessun verdetto di apertura (D-B4).
    """

    titolo: str
    url: str
    data: str
    anteprima: str | None = None


class AssetRest(BaseModel):
    """Un tipo di contenuto esposto (o no) via REST, e quanto ne ha."""

    esposto: bool = False
    rest_base: str | None = None
    totale: int = 0


class AssetServizi(AssetRest):
    """Il catalogo servizi, con la ripartizione per categoria per i chip."""

    categorie: list[CategoriaServizio] = Field(default_factory=list)
    #: Il `rest_base` della tassonomia categorie: è il parametro di filtro con
    #: cui si scende di livello (`?<categorie_rest_base>=<term_id>`). Salvato qui
    #: così il drill non deve ri-scoprire l'indice tassonomie a ogni tap.
    categorie_rest_base: str | None = None


class MappaConnettore(BaseModel):
    """Cosa un connettore comunale espone, e per quali strade lo si raggiunge.

    `sondato_il` è ISO-8601 UTC: la mappa dice sempre *quando* è stata misurata,
    perché una capacità è una misura come un'altra e va datata.
    """

    codice_istat: str
    nome: str
    sito: str | None
    sondato_il: str
    #: Identificativo della piattaforma principale, quando la sonda lo ha
    #: riconosciuto. Optional per retrocompatibilità con le mappe v0.
    piattaforma_id: str | None = None
    #: Identificativo separato della piattaforma Amministrazione Trasparente.
    piattaforma_at_id: str | None = None
    servizi: AssetServizi = Field(default_factory=AssetServizi)
    uffici: AssetRest = Field(default_factory=AssetRest)
    #: Non un dato, una strada: «scrape» finché il probe non trova il CPT in
    #: REST. Chi legge sa così se questi due hanno una rotta diretta o no.
    contatti_via: str = "scrape"
    amministrazione_trasparente_via: str = "scrape"
    #: Il `rest_base` della tassonomia legata al CPT `amm-trasparente` (quello
    #: che `bandi_live._rung1_cpt` altrimenti risonderebbe da
    #: `_rest_base_tassonomia_per_tipo` a ogni scoperta bandi). Popolato SOLO
    #: quando `amministrazione_trasparente_via == "REST"`; `None` altrimenti,
    #: e `None` anche su una voce di cache scritta prima di questo campo
    #: (default retrocompatibile, D-01/D-05/D-06) — un `None` degrada al probe
    #: live, non un dato mancante da trattare come errore.
    amministrazione_trasparente_rest_base: str | None = None
    #: Logo letto dalla homepage del comune, MAI da un CDN terzo (D-S8):
    #: `None` se il portale non lo espone o è su un altro host — degrado muto.
    logo_url: str | None = None

    @property
    def indirizzabile(self) -> bool:
        """Almeno una rotta diretta utile esiste su questo portale."""
        return self.servizi.esposto or self.uffici.esposto


def _base_con_schema(sito: str | None) -> str | None:
    """L'host nudo del registro («www.comune.x.it») non è un URL: httpx rifiuta
    un URL senza schema, quindi lo si antepone. Stessa regola di
    `recupera_contatti` — chi tocca `.sito` per un fetch deve farlo."""
    if not sito or not sito.strip():
        return None
    base = sito.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    return base


def _tipi_disponibili(sonda: _Sonda, base: str) -> dict[str, str]:
    """Mappa `slug CPT -> rest_base` da `/wp-json/wp/v2/types`.

    È l'indice che WordPress pubblica dei propri tipi di contenuto: leggerlo
    costa una richiesta sola ed evita di indovinare il `rest_base` a tentativi.
    """
    try:
        tipi = sonda.json(f"{base}/wp-json/wp/v2/types")
    except Exception:  # noqa: BLE001 — un indice assente è un esito, non un guasto
        return {}
    if not isinstance(tipi, dict):
        return {}
    fuori: dict[str, str] = {}
    for slug, voce in tipi.items():
        if isinstance(voce, dict) and voce.get("rest_base"):
            fuori[str(slug)] = str(voce["rest_base"])
    return fuori


def _prima_presente(candidati: tuple[str, ...], disponibili: set[str]) -> str | None:
    """Il primo `rest_base` del vocabolario chiuso che il portale espone."""
    for candidato in candidati:
        if candidato in disponibili:
            return candidato
    return None


def _rest_base_categorie(
    sonda: _Sonda, base: str, cpt_servizi: str | None
) -> str | None:
    """Il `rest_base` della tassonomia categorie-servizio, se c'è.

    Prima si prova a dedurla dall'indice tassonomie legandola al CPT servizi
    (`/wp-json/wp/v2/taxonomies`): la tassonomia giusta è quella applicata a
    quel tipo. Solo se l'indice tace si ripiega sul vocabolario chiuso per
    nome, che è meno affidabile ma meglio di niente.
    """
    try:
        tass = sonda.json(f"{base}/wp-json/wp/v2/taxonomies")
    except Exception:  # noqa: BLE001 — indice assente: si passa al fallback
        tass = None
    if isinstance(tass, dict):
        for voce in tass.values():
            if not isinstance(voce, dict) or not voce.get("rest_base"):
                continue
            tipi = voce.get("types")
            rest_base = str(voce["rest_base"])
            lega_ai_servizi = (
                cpt_servizi is not None
                and isinstance(tipi, list)
                and cpt_servizi in tipi
            )
            if lega_ai_servizi and "categor" in rest_base.lower():
                return rest_base
        # Nessuna «categor…» legata ai servizi: prova il vocabolario chiuso
        # comunque presente nell'indice, così non si chiede una rotta morta.
        disponibili = {
            str(v.get("rest_base"))
            for v in tass.values()
            if isinstance(v, dict) and v.get("rest_base")
        }
        trovata = _prima_presente(REST_BASE_CATEGORIE, disponibili)
        if trovata:
            return trovata
    return None


def _totale_rest(sonda: _Sonda, base: str, rest_base: str) -> int:
    """Quanti elementi ha una collezione REST, dall'header `X-WP-Total`.

    Si chiede una pagina da uno solo: il conteggio sta nell'header, non serve
    scaricare gli elementi. `0` anche su risposta storta — un conteggio che non
    si è potuto leggere è indistinguibile da un catalogo vuoto, e gonfiarlo
    sarebbe peggio.
    """
    try:
        resp = sonda.risposta(f"{base}/wp-json/wp/v2/{rest_base}?per_page=1")
    except Exception:  # noqa: BLE001 — collezione muta: conteggio ignoto = 0
        return 0
    if resp.status_code != 200:
        return 0
    try:
        return int(resp.headers.get("X-WP-Total", 0))
    except (TypeError, ValueError):
        return 0


def _categorie(sonda: _Sonda, base: str, rest_base: str) -> list[CategoriaServizio]:
    """Le categorie con conteggio, ordinate dalla più popolata.

    Si scartano le categorie a conteggio zero: sono voci dello standard che il
    comune non usa, e come chip porterebbero il cittadino su un vicolo vuoto.
    """
    try:
        righe = sonda.json(
            f"{base}/wp-json/wp/v2/{rest_base}?per_page=100&_fields=id,name,count,slug"
        )
    except Exception:  # noqa: BLE001 — tassonomia muta: nessuna categoria
        return []
    if not isinstance(righe, list):
        return []
    categorie = [
        CategoriaServizio(
            nome=html.unescape(str(r["name"])),
            conteggio=int(r.get("count", 0)),
            id=int(r.get("id", 0)),
            slug=str(r.get("slug", "")),
        )
        for r in righe
        if isinstance(r, dict) and r.get("name") and int(r.get("count", 0)) > 0
    ]
    categorie.sort(key=lambda c: c.conteggio, reverse=True)
    return categorie


def _sonda_mappa(comune: ComuneNoto, *, timeout: float = 8.0) -> MappaConnettore:
    """La misura vera: apre il portale una volta e legge tutti gli assi.

    Non solleva mai. Un portale muto o storto dà una mappa con tutto `esposto`
    a `False`, che è esattamente ciò che è successo, e non un errore da propagare
    fino a chi ha fatto la domanda.
    """
    sondato_il = datetime.now(timezone.utc).isoformat()
    base = _base_con_schema(comune.sito)
    vuota = MappaConnettore(
        codice_istat=comune.codice_istat,
        nome=comune.nome,
        sito=comune.sito,
        sondato_il=sondato_il,
    )
    if base is None:
        return vuota

    with _Sonda(timeout=timeout) as sonda:
        tipi = _tipi_disponibili(sonda, base)
        rest_bases = set(tipi.values())

        rb_uffici = _prima_presente(REST_BASE_UFFICI, rest_bases)
        rb_servizi = _prima_presente(REST_BASE_SERVIZI, rest_bases)

        uffici = AssetRest(esposto=rb_uffici is not None, rest_base=rb_uffici)
        if rb_uffici is not None:
            uffici.totale = _totale_rest(sonda, base, rb_uffici)

        servizi = AssetServizi(esposto=rb_servizi is not None, rest_base=rb_servizi)
        if rb_servizi is not None:
            servizi.totale = _totale_rest(sonda, base, rb_servizi)
            # Lo slug del CPT (chiave dell'indice types) serve a legare la
            # tassonomia al tipo giusto, non il suo rest_base.
            cpt_servizi = next(
                (slug for slug, rb in tipi.items() if rb == rb_servizi), None
            )
            rb_categorie = _rest_base_categorie(sonda, base, cpt_servizi)
            if rb_categorie is not None:
                servizi.categorie_rest_base = rb_categorie
                servizi.categorie = _categorie(sonda, base, rb_categorie)

        rb_contatti = _prima_presente(REST_BASE_CONTATTI, rest_bases)
        contatti_via = "REST" if rb_contatti is not None else "scrape"
        amministrazione_trasparente_via = (
            "REST" if CPT_AMM_TRASPARENTE in tipi else "scrape"
        )
        amministrazione_trasparente_rest_base: str | None = None
        if amministrazione_trasparente_via == "REST":
            # Stessa misura che `bandi_live._rung1_cpt` farebbe da sé a ogni
            # scoperta bandi: la si fa qui, una volta, e si persiste — non un
            # fetch aggiuntivo rispetto a quanto la sonda già avrebbe pagato
            # nel ciclo di vita del comune, solo spostato dal path caldo
            # (bandi, ogni TTL bandi-live) al path freddo (mappa, ogni
            # GIORNI_VALIDITA).
            amministrazione_trasparente_rest_base = _rest_base_tassonomia_per_tipo(
                sonda, base, CPT_AMM_TRASPARENTE
            )

        logo_url = None
        try:
            risposta_home = sonda.risposta(base)
        except Exception:  # noqa: BLE001 — homepage muta: nessun logo, non un errore
            risposta_home = None
        if (
            risposta_home is not None
            and risposta_home.status_code == 200
            and risposta_home.text
        ):
            logo_url = _estrai_logo(risposta_home.text, base)

    return MappaConnettore(
        codice_istat=comune.codice_istat,
        nome=comune.nome,
        sito=comune.sito,
        sondato_il=sondato_il,
        servizi=servizi,
        uffici=uffici,
        contatti_via=contatti_via,
        amministrazione_trasparente_via=amministrazione_trasparente_via,
        amministrazione_trasparente_rest_base=amministrazione_trasparente_rest_base,
        logo_url=logo_url,
    )


def _percorso_cache(codice_istat: str) -> Path:
    return LIVE_DIR / "mappa-connettore" / f"{codice_istat}.json"


def _da_cache(codice_istat: str) -> MappaConnettore | None:
    percorso = _percorso_cache(codice_istat)
    if not percorso.exists():
        return None
    try:
        voce = MappaConnettore.model_validate_json(percorso.read_text("utf-8"))
    except Exception:  # noqa: BLE001 — una cache illeggibile è una cache assente
        logger.warning("mappa connettore illeggibile: %s", percorso)
        return None
    eta = datetime.now(timezone.utc) - datetime.fromisoformat(voce.sondato_il)
    return voce if eta.days < GIORNI_VALIDITA else None


def _in_cache(voce: MappaConnettore) -> None:
    """Scrittura atomica: un lettore concorrente vede la voce vecchia o la nuova,
    mai mezza voce. Il mount live può mancare in sviluppo/test: la mappa è già
    pronta in memoria e non deve dipendere dal disco."""
    percorso = _percorso_cache(voce.codice_istat)
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(voce.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        logger.warning("cache mappa non scrivibile (%s): %s", percorso, exc)


def mappa_connettore(
    codice_istat: str | None, *, usa_cache: bool = True
) -> MappaConnettore | None:
    """La mappa di capacità di un comune. `None` se il comune non è noto.

    Con cache calda torna in memoria; a freddo sonda il portale una volta e
    scrive la cache — così la stessa lettura non si ripete a ogni domanda,
    educato verso il portale e istantaneo per chi guarda.
    """
    comune = comune_per_codice(codice_istat)
    if comune is None:
        return None
    if usa_cache:
        voce = _da_cache(comune.codice_istat)
        if voce is not None:
            return voce
    mappa = _sonda_mappa(comune)
    _in_cache(mappa)
    return mappa


def _normalizza_link(base: str, link: str) -> str:
    """Il portale a volte torna un link relativo (`/servizio/...`): gli si
    antepone il sito, così chi lo apre non atterra su una rotta cieca."""
    link = link.strip()
    if link.startswith("/"):
        return f"{base}{link}"
    return link


def _servizi_link(
    sonda: _Sonda, base: str, cpt: str, filtro: str, term_id: int, limite: int
) -> list[ServizioLink]:
    """I servizi di una categoria, come titolo + link, letti adesso."""
    try:
        righe = sonda.json(
            f"{base}/wp-json/wp/v2/{cpt}"
            f"?{filtro}={term_id}&per_page={limite}&_fields=title,link"
        )
    except Exception:  # noqa: BLE001 — collezione muta: nessun servizio
        return []
    if not isinstance(righe, list):
        return []
    servizi: list[ServizioLink] = []
    for r in righe:
        if not isinstance(r, dict):
            continue
        titolo_raw = r.get("title")
        titolo = (
            titolo_raw.get("rendered")
            if isinstance(titolo_raw, dict)
            else titolo_raw
        )
        link = r.get("link")
        if not titolo or not link:
            continue
        servizi.append(
            ServizioLink(
                titolo=html.unescape(str(titolo)).strip(),
                url=_normalizza_link(base, str(link)),
            )
        )
    return servizi


def servizi_di_categoria(
    codice_istat: str | None, term_id: int, *, limite: int = 60, timeout: float = 8.0
) -> list[ServizioLink] | None:
    """I servizi di una categoria di un comune: il livello sotto ai chip.

    `None` se il comune non è noto o non espone il catalogo; lista vuota se la
    categoria non ha (più) servizi. Riusa la mappa in cache per sapere sito e
    rotte senza ri-scoprirle, poi fa una sola lettura live filtrata per term.
    """
    mappa = mappa_connettore(codice_istat)
    if mappa is None or not mappa.servizi.esposto or mappa.servizi.rest_base is None:
        return None
    base = _base_con_schema(mappa.sito)
    if base is None:
        return None
    # Il filtro è il rest_base della tassonomia; se la cache è vecchia e non lo
    # porta, si ripiega sul vocabolario chiuso più probabile.
    filtro = mappa.servizi.categorie_rest_base or REST_BASE_CATEGORIE[0]
    with _Sonda(timeout=timeout) as sonda:
        return _servizi_link(
            sonda, base, mappa.servizi.rest_base, filtro, term_id, limite
        )


#: Ancoraggi delle sezioni standard del modello «Servizi» AgID (tema Comuni
#: Italia). Se ne aggiunge una nuova → il resto continua a funzionare.
# I confini di sezione servono a `_sezione` per sapere dove finisce una sezione
# e inizia la prossima. Il tema Bootstrap Italia non usa un vocabolario unico:
# alcuni comuni marcano le ancore all'inglese AgID (`what-you-get`), altri con
# una variante propria (`obtain`, `needed`, `how-to`). Qui teniamo l'UNIONE di
# tutte le ancore note: se una non figura sulla pagina, semplicemente non taglia.
_SEZIONI_SERVIZIO = (
    "who-needs",
    "description",
    "how-to",
    "how-to-do",
    "needed",
    "what-you-need",
    "obtain",
    "what-you-get",
    "procedure-esito",
    "deadlines",
    "timing",
    "costs",
    "submit-request",
    "conditions",
    "contacts",
)

# Per ogni campo della scheda, le ancore candidate in ordine di preferenza: la
# prima presente sulla pagina vince. Copre entrambi i vocabolari del tema.
_ANCORE_A_CHI = ("who-needs",)
_ANCORE_DESCRIZIONE = ("description",)
_ANCORE_COSA_OTTIENI = ("what-you-get", "obtain")


def _testo_pulito(frammento: str, *, limite: int) -> str:
    """Da un pezzo di HTML a testo leggibile: via i tag, entità decodificate,
    spazi normalizzati, tagliato a `limite` su confine di parola."""
    testo = re.sub(r"<[^>]+>", " ", frammento)
    testo = html.unescape(re.sub(r"\s+", " ", testo)).strip()
    if len(testo) <= limite:
        return testo
    tronco = testo[:limite].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f"{tronco}…"


def _sezione(pagina: str, ancora: str, *, limite: int = 320) -> str | None:
    """Il testo della sezione ancorata da `id="<ancora>"`, fino alla prossima
    sezione nota. `None` se assente o vuota dopo la pulizia."""
    trovato = re.search(r'id=["\']' + re.escape(ancora) + r'["\']', pagina)
    if trovato is None:
        return None
    coda = pagina[trovato.end() : trovato.end() + 8000]
    prossima = re.search(
        r'id=["\'](?:' + "|".join(map(re.escape, _SEZIONI_SERVIZIO)) + r')["\']', coda
    )
    if prossima is not None:
        coda = coda[: prossima.start()]
    # Il taglio può lasciare un tag monco in coda (`…<section `): via, o il
    # ripulitore lo lascerebbe come testo letterale.
    coda = re.sub(r"<[^>]*$", "", coda)
    # La sezione si apre con la sua intestazione (`<h2>Descrizione</h2>`): la si
    # scarta se compare subito, così resta solo il corpo, non l'etichetta.
    intestazione = re.search(r"</h[1-6]>", coda[:300])
    if intestazione is not None:
        coda = coda[intestazione.end() :]
    testo = _testo_pulito(coda, limite=limite)
    return testo or None


def _prima_sezione(
    pagina: str, ancore: tuple[str, ...], *, limite: int = 320
) -> str | None:
    """La prima sezione presente tra le `ancore` candidate. Serve perché lo
    stesso campo cambia ancora tra temi (`what-you-get` vs `obtain`)."""
    for ancora in ancore:
        testo = _sezione(pagina, ancora, limite=limite)
        if testo is not None:
            return testo
    return None


def _titolo_pagina(pagina: str) -> str | None:
    """Il titolo del servizio: prima l'`og:title`, poi il primo `<h1>`."""
    og = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', pagina
    )
    if og is not None:
        return html.unescape(og.group(1)).strip() or None
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", pagina, re.S)
    if h1 is not None:
        testo = _testo_pulito(h1.group(1), limite=140)
        return testo or None
    return None


def _host_senza_www(host: str) -> str:
    """L'host senza un eventuale prefisso `www.`, per pareggiare apex e `www`
    dello stesso dominio nella guardia SSRF. Non tocca altri sottodomini."""
    return host[4:] if host.startswith("www.") else host


def _estrai_logo(pagina: str, base: str) -> str | None:
    """Il logo del comune, letto dalla homepage: `<link rel="icon">` /
    `apple-touch-icon`, poi `og:image` come ripiego.

    Accettato SOLO se sta sullo stesso host del portale sondato (D-S8, stessa
    guardia di `scheda_servizio`): mai un CDN terzo. Assente o host estraneo
    → `None`, degrado muto, mai un placeholder rotto.
    """
    candidati: list[str] = []
    for tag in re.findall(r"<link\b[^>]*>", pagina, re.I):
        rel = re.search(r'rel=["\']([^"\']+)["\']', tag, re.I)
        href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if rel and href and re.search(r"\bicon\b", rel.group(1), re.I):
            candidati.append(href.group(1))
    og = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        pagina,
    )
    if og is not None:
        candidati.append(og.group(1))
    host_comune = _host_senza_www(urlparse(base).netloc.lower())
    for link in candidati:
        url = _normalizza_link(base, html.unescape(link))
        host_url = _host_senza_www(urlparse(url).netloc.lower())
        if host_url and host_url == host_comune:
            return url
    return None


def scheda_servizio(
    codice_istat: str | None, url: str, *, timeout: float = 10.0
) -> SchedaServizio | None:
    """L'anteprima di un servizio, letta adesso dalla sua pagina.

    `None` se il comune non è noto, se l'`url` non appartiene al portale di quel
    comune (l'anteprima si legge solo dal sito del comune scelto, non da un host
    arbitrario passato dall'esterno), o se la pagina non è leggibile.
    """
    mappa = mappa_connettore(codice_istat)
    if mappa is None:
        return None
    base = _base_con_schema(mappa.sito)
    if base is None:
        return None
    # Guardia host: l'url deve stare sul portale del comune. Impedisce che la
    # rotta diventi un proxy verso un host qualsiasi (SSRF).
    #
    # Confronto normalizzato sul `www.`: la REST del tema AgID restituisce i
    # permalink dei servizi sull'apex (`comune.benevento.it`), mentre l'anagrafe
    # del comune tiene il `www` (`www.comune.benevento.it`). Un confronto host
    # esatto scartava OGNI scheda-foglia di quei comuni (None -> la UI mostrava
    # «Non sono riuscito a leggere l'anteprima»). Apex e `www` dello STESSO
    # dominio sono lo stesso comune: sicuro pareggiarli. Ogni altro sottodominio
    # o host resta rifiutato — `comune.benevento.it.evil.com` non pareggia.
    host_comune = _host_senza_www(urlparse(base).netloc.lower())
    host_url = _host_senza_www(urlparse(url.strip()).netloc.lower())
    if not host_url or host_url != host_comune:
        return None
    with _Sonda(timeout=timeout) as sonda:
        try:
            risposta = sonda.risposta(url.strip())
        except Exception:  # noqa: BLE001 — pagina muta: nessuna anteprima
            return None
    if risposta.status_code != 200:
        return None
    pagina = risposta.text
    return SchedaServizio(
        titolo=_titolo_pagina(pagina) or "Servizio del comune",
        url=url.strip(),
        descrizione=_prima_sezione(pagina, _ANCORE_DESCRIZIONE),
        a_chi=_prima_sezione(pagina, _ANCORE_A_CHI),
        cosa_ottieni=_prima_sezione(pagina, _ANCORE_COSA_OTTIENI),
    )


def _rest_base_tassonomia_per_tipo(sonda: _Sonda, base: str, tipo: str) -> str | None:
    """Il `rest_base` della tassonomia legata al CPT `tipo`, letto dall'indice
    tassonomie (`/wp-json/wp/v2/taxonomies`): la tassonomia giusta è quella il
    cui `types` include quel CPT. `None` se l'indice tace o non lega nulla.

    Generalizza `_rest_base_categorie` (che filtra anche per nome "categor…",
    non adatto qui) — id di tassonomia/term variano per comune, si risolve
    sempre per rest_base+slug, mai per id fisso (D-B2).
    """
    try:
        tass = sonda.json(f"{base}/wp-json/wp/v2/taxonomies")
    except Exception:  # noqa: BLE001 — indice assente
        return None
    if not isinstance(tass, dict):
        return None
    for voce in tass.values():
        if not isinstance(voce, dict) or not voce.get("rest_base"):
            continue
        tipi = voce.get("types")
        if isinstance(tipi, list) and tipo in tipi:
            return str(voce["rest_base"])
    return None


def _term_bandi(categorie: list[CategoriaServizio]) -> CategoriaServizio | None:
    """Il term dei bandi/criteri fra quelli della tassonomia: prima lo slug
    esatto atteso, poi tollerante su varianti (RISK: slug variabile fra
    deployment del tema)."""
    for categoria in categorie:
        if categoria.slug == SLUG_TERM_BANDI:
            return categoria
    # Tolerant: only variants of the canonical slug (e.g. "criteri-e-modalita-2"),
    # not unrelated terms that merely start with "criteri" (e.g. "criteri-accessibilita").
    for categoria in categorie:
        if SLUG_TERM_BANDI in categoria.slug:
            return categoria
    return None


def _bando_da_riga(base: str, riga: object) -> Bando | None:
    """Un `Bando` dalla riga REST grezza di `amm-trasparente`. `None` se la
    riga non è leggibile o il titolo è vuoto.

    Testo verbatim dalla REST: nessuna cifra toccata o generata dal modello
    (D-B7). Anteprima da excerpt, ripiego su content se l'excerpt è vuoto.
    """
    if not isinstance(riga, dict):
        return None
    titolo_raw = riga.get("title")
    titolo_html = titolo_raw.get("rendered") if isinstance(titolo_raw, dict) else titolo_raw
    link = riga.get("link")
    if not titolo_html or not link:
        return None
    titolo = html.unescape(str(titolo_html)).strip()
    if not titolo:
        return None

    excerpt_raw = riga.get("excerpt")
    excerpt_html = excerpt_raw.get("rendered") if isinstance(excerpt_raw, dict) else None
    content_raw = riga.get("content")
    content_html = content_raw.get("rendered") if isinstance(content_raw, dict) else None

    anteprima = _testo_pulito(excerpt_html, limite=280) if excerpt_html else ""
    if not anteprima and content_html:
        anteprima = _testo_pulito(content_html, limite=280)

    return Bando(
        titolo=titolo,
        url=_normalizza_link(base, str(link)),
        data=str(riga.get("date", "")),
        anteprima=anteprima or None,
    )


def bandi_criteri(
    codice_istat: str | None, *, limite: int = 20, timeout: float = 8.0
) -> list[Bando] | None:
    """I bandi/criteri pubblicati su Amministrazione Trasparente del comune.

    `None` se il comune non è noto, il portale non ha sito, o la tassonomia /
    il term dei bandi non si risolvono. NB: `_categorie` scarta i term a
    conteggio zero, quindi un term esistente ma senza item pubblicati NON si
    risolve e la funzione ritorna `None` (non `[]`); rotta e frontend collassano
    comunque su "nessun bando" (`or []` + auto-null, D-B5). Lista vuota `[]`
    solo se il term ha item ma nessuno è parsabile.
    Fonte citata, nessun verdetto di apertura (D-B4).
    """
    mappa = mappa_connettore(codice_istat)
    if mappa is None:
        return None
    base = _base_con_schema(mappa.sito)
    if base is None:
        return None

    with _Sonda(timeout=timeout) as sonda:
        rest_base_tax = _rest_base_tassonomia_per_tipo(sonda, base, CPT_AMM_TRASPARENTE)
        if rest_base_tax is None:
            return None
        term = _term_bandi(_categorie(sonda, base, rest_base_tax))
        if term is None:
            return None
        try:
            righe = sonda.json(
                f"{base}/wp-json/wp/v2/{CPT_AMM_TRASPARENTE}"
                f"?{rest_base_tax}={term.id}&per_page={limite}"
                "&_fields=title,link,date,excerpt,content&orderby=date&order=desc"
            )
        except Exception:  # noqa: BLE001 — collezione muta: nessun bando
            return []

    if not isinstance(righe, list):
        return []
    return [bando for riga in righe if (bando := _bando_da_riga(base, riga)) is not None]


def _riga_riassunto(mappa: MappaConnettore) -> str:
    """Una riga terse per la CLI: cosa espone questo comune."""
    servizi = mappa.servizi
    testa = f"{mappa.codice_istat} {mappa.nome}"
    if not mappa.indirizzabile:
        return f"{testa}: nessuna rotta diretta"
    pezzi = []
    if servizi.esposto:
        pezzi.append(f"servizi={servizi.totale} in {len(servizi.categorie)} cat")
    if mappa.uffici.esposto:
        pezzi.append(f"uffici={mappa.uffici.totale}")
    return f"{testa}: " + ", ".join(pezzi)


def main(argv: list[str] | None = None) -> int:
    """CLI: costruisci/aggiorna la mappa dei connettori indicati.

    Sonda i comuni ora, così la cache è calda quando servirà (chip, routing,
    ingestion). La misura è la stessa che si farebbe sul momento: precalcolarla
    sposta solo l'attesa fuori dal turno del cittadino.
    """
    parser = argparse.ArgumentParser(description="Mappa di capacità dei connettori comunali.")
    parser.add_argument("istat", nargs="+", help="codici ISTAT dei comuni da sondare")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="rimisura anche se la cache è ancora valida",
    )
    args = parser.parse_args(argv)

    uscita = 0
    for codice in args.istat:
        mappa = mappa_connettore(codice, usa_cache=not args.no_cache)
        if mappa is None:
            print(f"{codice}: comune non noto", file=sys.stderr)
            uscita = 1
            continue
        print(_riga_riassunto(mappa))
    return uscita


if __name__ == "__main__":
    raise SystemExit(main())
