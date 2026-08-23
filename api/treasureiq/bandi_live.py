"""Motore live a due gradini per i bandi/criteri comunali (KAPI 7, bandi-live-agid).

`mappa_connettore.bandi_criteri` legge SOLO Amministrazione Trasparente via
CPT AgID (rung1): un comune che espone i bandi soltanto su `wp/v2/pages`
(WordPress "semplice", come Albano — vedi `ingest/wp_pages.py`) risulta
`None` lì, anche se i bandi ci sono davvero. Questo modulo prova rung1 e,
solo se non risolve, prova rung2 (`wp/v2/pages` con le stesse sei parole
chiave del B1/B4, filtrate dallo stesso segnale di ammissibilità) — così un
comune "solo-HTML" non collassa silenziosamente su `non_coperto` quando ha
bandi pubblicati in una forma diversa da quella AgID.

Ogni bando trovato (in entrambi i gradini) viene arricchito allo stesso modo
di `ingest/wp_pages.py`: corpus condiviso (`extract/corpus.py`, B1), estrattore
quote-gated (`extract/llm.py`), stessa guardia sui numeri (D-05) — mai un
valore che il modello non abbia potuto citare nel testo che gli è stato
mostrato. La scadenza segue la stessa regola (D-07): è mostrata solo se la
data che il modello ha prodotto compare davvero nel corpus letto.

Tutto è sincrono e bloccante di proposito (sonda REST + parse LLM): la rotta
in `api.py` lo gira con `asyncio.to_thread`, mai dentro un loop async.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Sequence
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from pydantic import BaseModel

from treasureiq import alberatura
from treasureiq import mappa_connettore as mappa_connettore_module
from treasureiq.alberatura import BandoScoperto
from treasureiq.extract.corpus import build_corpus, collect_pdf_segments
from treasureiq.extract.llm import RequirementsExtractor, Segment
from treasureiq.extract.providers import load_provider
from treasureiq.ingest.censimento import _Sonda
from treasureiq.ingest.host_guard import fetch_guardato
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.ingest.wp_comuni import strip_html
from treasureiq.ingest.wp_pages import (
    _ELIGIBILITY_SIGNAL_RE,
    _PDF_LINK_RE,
    SEARCH_KEYWORDS,
)
from treasureiq.mappa_connettore import (
    CPT_AMM_TRASPARENTE,
    Bando,
    _bando_da_riga,
    _base_con_schema,
    _categorie,
    _host_senza_www,
    _rest_base_tassonomia_per_tipo,
    _term_bandi,
)
from treasureiq.schema import (
    Confidence,
    Opportunity,
    OpportunityKind,
    Requirements,
    Source,
    TargetGroup,
)
from treasureiq.sonda_live import LIVE_DIR, ComuneNoto, comune_per_codice

logger = logging.getLogger(__name__)

#: Quanto resta valida una scansione bandi-live prima di rifare la sonda REST
#: (D-B... 6-12h è la finestra: abbastanza corta da riflettere un bando aperto
#: da poche ore, abbastanza lunga da non martellare il portale a ogni domanda).
TTL_ORE = 8

#: A7: dati acquisiti a runtime, gitignorata (vive sotto LIVE_DIR come le
#: altre cache live: mappa-connettore, scansioni, orari-urp).
CACHE_DIR = LIVE_DIR / "bandi-criteri"

#: Budget LLM per scansione: quanti bandi normalizzati arrivano all'estrattore
#: quote-gated per singola chiamata di `bandi_arricchiti` (D-15-style cap).
MAX_BANDI_ARRICCHITI = 5

#: Cap per comune sulla cache estrazioni: prima di scrivere si pota per mtime
#: chi è più vecchio, mai un troncamento arbitrario di ciò che si sta scrivendo.
CAP_CACHE_BYTES_PER_COMUNE = 20 * 1024 * 1024


class Documento(BaseModel):
    """Un allegato PDF linkato dalla pagina del bando. `url` è quello scritto
    nella pagina (già filtrato stesso-host da `_filtra_pdf_stesso_host`, D-05),
    reso assoluto; `etichetta` è il nome-file ripulito. Nessun contenuto letto
    e nessun titolo inventato: è un puntatore alla fonte, non una lettura di
    essa — chi vuole il documento se lo scarica dal comune (D-07)."""

    url: str
    etichetta: str


class BandoArricchito(BaseModel):
    """Un bando, con i requisiti estratti e una scadenza SOLO se verificabile."""

    opportunity: Opportunity
    scadenza: str | None
    scadenza_verificata: bool
    #: Ranking morbido profilo↔requisiti (KAPI 7): True se il bando risuona con
    #: i segnali del cittadino (figli minori, età, disabilità...). NON è un
    #: verdetto di eleggibilità — quello lo dà `match/engine.py` solo su dati
    #: DECLARED — ma un ORDINE indicativo, «controlla i requisiti». Default
    #: False: nessun profilo o nessun riscontro → nessun bando marcato, ordine
    #: del portale intatto. La scansione di rete non lo popola mai (è
    #: profilo-agnostica): lo imposta `respond._ordina_bandi_per_profilo`.
    consigliato: bool = False
    #: KAPI 8 (bandi-alberatura): agevolazione (WP, contributo/sovvenzione) o
    #: concorso pubblico (Halley `/zf/`). `None` sui bandi dei gradini cpt/pages
    #: — quella fonte non distingue il tipo, e non lo si inventa qui. Popolato
    #: SOLO dal gradino `alberatura`, da `BandoScoperto.tipo` (B1).
    tipo: Literal["agevolazione", "concorso"] | None = None
    #: Filtro conversazionale (KAPI 9, ciclo bandi-conversazionale): True/False
    #: solo quando la chat ha estratto un tema dal messaggio del cittadino
    #: («bandi per la mobilità?») e questo bando ne è risultato pertinente o no.
    #: `None` di default e SEMPRE quando non c'è tema — il filtro evidenzia,
    #: MAI esclude: ogni bando resta nell'esito. Impostato da
    #: `respond._risposta_bandi` su una copia (`model_copy`), mai sull'oggetto
    #: cache condiviso.
    corrisponde: bool | None = None
    #: Allegati PDF linkati dalla pagina del bando (ciclo17, «link ai
    #: documenti»): stessi URL che `_arricchisci` già raccoglie stesso-host per
    #: contarli (`pdfs_linked`), qui esposti — ripuliti dal rumore (cookie,
    #: privacy), i doc-like in cima, capati. Vuoto quando la pagina non linka
    #: PDF o il bando arriva da un gradino senza HTML pieno (alberatura). La
    #: card li mostra come link diretti: TIQ porta al documento, non lo legge.
    documenti: list[Documento] = []


class BandiLiveEsito(BaseModel):
    """Esito di una scansione bandi-live per un comune: cosa si è trovato,
    e su quale gradino REST."""

    codice_istat: str
    comune_nome: str
    esito: Literal["coperto_con_bandi", "coperto_senza_bandi", "non_coperto", "comune_ignoto"]
    #: Quale gradino REST ha coperto il comune. `None` su `non_coperto` (nessuno
    #: dei tre) e su `comune_ignoto` (non si è nemmeno sondato). `alberatura`
    #: (KAPI 8) è il terzo gradino, tentato solo quando cpt/pages non coprono.
    gradino: Literal["cpt", "pages", "alberatura"] | None
    verificato_il: str
    bandi: list[BandoArricchito] = []
    #: Tema conversazionale (KAPI 9) estratto dal messaggio, verbatim, se
    #: presente — eco, mai riformulato dal modello. `None` quando il
    #: cittadino non ha nominato un tema (retrocompat: comportamento odierno
    #: invariato, D-07).
    tema: str | None = None
    #: Piattaforma AT del comune (B5, ciclo16), letta dal registro
    #: (`registro.RegistroComune.piattaforma_at`, classificata da
    #: `connettore.leggi_connettore`) — SOLO informativo: `None` se il
    #: comune non è mai stato scansionato o l'AT non è stata classificata.
    piattaforma_at: str | None = None
    #: Quale connettore AT si USEREBBE per `piattaforma_at`, se ne esiste
    #: già uno costruito (`_CONNETTORE_AT_PER_PIATTAFORMA`) — non-goal di
    #: questo brief costruire il connettore stesso: qui si espone solo la
    #: scelta, l'uso reale arriva con B8 (ISWEB). `None` se la piattaforma
    #: non è nota o non ha ancora un connettore.
    connettore_at: str | None = None


#: Piattaforma AT classificata → nome del connettore che la leggerebbe, per
#: le piattaforme dove B8+ ha (o avrà) un connettore dedicato. Vuota oggi
#: per costruzione (B5, ciclo16 = solo classificazione, NON-GOAL costruire
#: un connettore AT qui): popolata quando un connettore AT arriva davvero
#: (ISWEB, B8), mai a priori. Distinta da `_GRADINI_PER_PIATTAFORMA_AT` sotto:
#: questa e' solo il nome informativo esposto in `BandiLiveEsito.connettore_at`,
#: quella decide quali gradini di SCOPERTA girano davvero.
_CONNETTORE_AT_PER_PIATTAFORMA: dict[str, str] = {}

#: Vocabolario stabile dei gradini di scoperta bandi/concorsi che il dispatch
#: AT-aware può selezionare. "cpt"/"pages" sono la cascata WP interna a
#: `_scopri_bandi` (rung1→rung2, D-05/D-06: si tenta l'uno e poi l'altro,
#: mai i due come sonde indipendenti — la scelta cpt-vs-pages resta di
#: `_scopri_bandi`, non del dispatch); "alberatura" è il terzo gradino
#: (KAPI 8) che legge il ramo ANAC bersaglio, anche su host esterno.
_TUTTI_I_GRADINI: tuple[str, ...] = ("cpt", "pages", "alberatura")

#: `piattaforma_at` (catalogata, letta da `_piattaforma_e_connettore_at`) →
#: gradini da tentare in UNIONE (D-01/D-03). Entrambe le voci di oggi
#: coincidono col ventaglio pieno, di proposito: nessun record prova ancora
#: che una delle due possa fare a meno di un gradino.
#:
#: - `WP_AMM_TRASP`: è comunque un WordPress (cpt/pages restano pertinenti
#:   per costruzione) e non è mai stato verificato assente di rami
#:   Amministrazione Trasparente su host esterno — tagliare `alberatura` qui
#:   sarebbe un'assunzione, non una classificazione (vedi il monito in
#:   `ingest/piattaforma.py` su `HGATE`).
#: - `HALLEY_TRASPARENZA`: il caso Benevento (D-03, BLOCKER) prova che
#:   l'apice WP e il sottodominio Halley rispondono ENTRAMBI — Benevento ha
#:   `piattaforma_at == halley_trasparenza` ma `amministrazione_trasparente_via
#:   == "scrape"`, quindi i bandi WP arrivano da `pages` (mai da `cpt`, che
#:   lì non risolve) e i concorsi da `alberatura`: tagliare `pages` da questa
#:   voce perderebbe i bandi dell'apice WP. `_scopri_bandi` decide da solo se
#:   è `cpt` o `pages` a rispondere davvero; qui si autorizza il tentativo di
#:   ENTRAMBI, non si sceglie fra loro.
#:
#: Una voce con un solo gradino (es. `("alberatura",)`) è ammessa SOLO
#: quando un record prova che l'altro gradino è impossibile per quella
#: piattaforma — mai per assunzione. Qualunque `piattaforma_at` assente da
#: questa tabella (non catalogata, o catalogata con un valore che B5+ non
#: ha ancora coperto qui) ricade sulla cascata cieca invariata
#: (`_TUTTI_I_GRADINI`): il silenzio del catalogo non è mai un motivo per
#: saltare una sonda che potrebbe ancora rispondere (D-05/D-06).
_GRADINI_PER_PIATTAFORMA_AT: dict[str, tuple[str, ...]] = {
    Piattaforma.WP_AMM_TRASP.value: _TUTTI_I_GRADINI,
    Piattaforma.HALLEY_TRASPARENZA.value: _TUTTI_I_GRADINI,
}

#: Quanto resta valido il dato di catalogo (`piattaforma_at`, letto dal
#: registro insieme a `ultima_scansione`) prima che il dispatch AT-aware
#: smetta di fidarsene e ripieghi sulla cascata cieca: una classificazione
#: vecchia può essere sbagliata quanto un comune mai scansionato — il
#: catalogo è un'accelerazione, mai l'unica fonte di verità (D-05/D-06).
TTL_CATALOGO_AT_GIORNI = 14


def _piattaforma_e_connettore_at(
    codice_istat: str,
) -> tuple[str | None, str | None, str | None]:
    """`(piattaforma_at, connettore_at, ultima_scansione)` per un comune,
    letti dal registro (D-01: zero fetch qui, solo lo store già scritto da
    una scansione connettore precedente — UNA sola lettura, riusata anche
    dal dispatch AT-aware per decidere se il dato è ancora fresco). Import
    lazy per evitare un giro di import a modulo (`registro` non è mai stato
    una dipendenza forte di `bandi_live`); qualunque anomalia (registro non
    ancora scritto, modulo assente) degrada a `(None, None, None)`, mai un
    crash del motore bandi."""
    try:
        from treasureiq.registro import leggi_registro

        record = leggi_registro(codice_istat)
    except Exception:  # noqa: BLE001 — registro muto: nessuna classificazione, mai un crash
        return None, None, None
    if record is None or record.piattaforma_at is None:
        return None, None, None
    connettore = _CONNETTORE_AT_PER_PIATTAFORMA.get(record.piattaforma_at)
    if connettore is not None:
        logger.info(
            "AT %s: piattaforma nota (%s), connettore %s non ancora invocato (deferred, B8)",
            codice_istat, record.piattaforma_at, connettore,
        )
    return record.piattaforma_at, connettore, record.ultima_scansione


def _catalogo_at_scaduto(ultima_scansione: str | None) -> bool:
    """Il dato di catalogo (`piattaforma_at`) è troppo vecchio per fidarsene
    da solo? `None` (mai scansionato, data malformata) conta come scaduto:
    stessa regola di `_da_cache` — un dubbio si risolve sondando, mai
    fidandosi di un dato che non si può leggere."""
    if ultima_scansione is None:
        return True
    try:
        eta = datetime.now(timezone.utc) - datetime.fromisoformat(ultima_scansione)
    except ValueError:
        return True
    return eta.days >= TTL_CATALOGO_AT_GIORNI


def _gradini_da_tentare(piattaforma_at: str | None, ultima_scansione: str | None) -> tuple[str, ...]:
    """Quali gradini di scoperta girare per questo comune (D-01/D-03/D-05/D-06).

    Una `piattaforma_at` catalogata E fresca seleziona il sottoinsieme di
    `_GRADINI_PER_PIATTAFORMA_AT` — salta le sonde che il catalogo prova
    impossibili. Assente dalla tabella, mai classificata, o oltre
    `TTL_CATALOGO_AT_GIORNI`: cascata cieca invariata (si tenta tutto) — il
    catalogo può mancare o essere vecchio, mai un motivo per saltare una
    sonda che potrebbe ancora rispondere.
    """
    if piattaforma_at is not None and piattaforma_at in _GRADINI_PER_PIATTAFORMA_AT:
        if not _catalogo_at_scaduto(ultima_scansione):
            return _GRADINI_PER_PIATTAFORMA_AT[piattaforma_at]
    return _TUTTI_I_GRADINI


def _ora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _esito_vuoto(
    comune: ComuneNoto,
    esito: str,
    gradino: str | None,
    *,
    piattaforma_at: str | None = None,
    connettore_at: str | None = None,
) -> BandiLiveEsito:
    return BandiLiveEsito(
        codice_istat=comune.codice_istat,
        comune_nome=comune.nome,
        esito=esito,  # type: ignore[arg-type]
        gradino=gradino,  # type: ignore[arg-type]
        verificato_il=_ora_iso(),
        bandi=[],
        piattaforma_at=piattaforma_at,
        connettore_at=connettore_at,
    )


# --- Cache listing (stile mappa_connettore.py:386-414) ----------------------


def _percorso_listing(codice_istat: str) -> Path:
    return CACHE_DIR / codice_istat / "listing.json"


def _da_cache(codice_istat: str) -> BandiLiveEsito | None:
    percorso = _percorso_listing(codice_istat)
    if not percorso.exists():
        return None
    try:
        esito = BandiLiveEsito.model_validate_json(percorso.read_text("utf-8"))
        # `verificato_il` sta nel try: una data malformata è cache corrotta,
        # da trattare come cache assente — non un crash a ogni lettura.
        eta = datetime.now(timezone.utc) - datetime.fromisoformat(esito.verificato_il)
    except Exception:  # noqa: BLE001 — una cache illeggibile è una cache assente
        logger.warning("listing bandi-live illeggibile: %s", percorso)
        return None
    return esito if eta.total_seconds() < TTL_ORE * 3600 else None


def _in_cache(esito: BandiLiveEsito) -> None:
    """Scrittura atomica: un lettore concorrente vede la voce vecchia o la
    nuova, mai mezza voce (stesso schema di `mappa_connettore._in_cache`)."""
    percorso = _percorso_listing(esito.codice_istat)
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(esito.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        logger.warning("cache bandi-live non scrivibile (%s): %s", percorso, exc)


def _prune_cache(codice_istat: str) -> None:
    """Pota per mtime la cache-estrazioni di un comune sotto
    `CAP_CACHE_BYTES_PER_COMUNE`, prima di scriverne di nuove.

    Circoscritta alla sottocartella `estrazioni/`: il `listing.json`
    (l'esito servito) vive un livello sopra e NON va mai contato né potato —
    altrimenti la potatura potrebbe cancellare la voce di cache che si sta
    per servire."""
    root = CACHE_DIR / codice_istat / "estrazioni"
    if not root.exists():
        return
    file_e_dimensione = [(p, p.stat().st_size) for p in root.rglob("*") if p.is_file()]
    totale = sum(dimensione for _, dimensione in file_e_dimensione)
    if totale <= CAP_CACHE_BYTES_PER_COMUNE:
        return
    file_e_dimensione.sort(key=lambda coppia: coppia[0].stat().st_mtime)
    for percorso, dimensione in file_e_dimensione:
        if totale <= CAP_CACHE_BYTES_PER_COMUNE:
            break
        try:
            percorso.unlink()
            totale -= dimensione
        except OSError:
            pass


# --- §5.2 Scoperta due gradini pluggable (D-02 emendata) --------------------


def _rung1_cpt(
    sonda: _Sonda, base: str, *, codice_istat: str | None = None
) -> list[dict[str, Any]] | None:
    """Amministrazione Trasparente via CPT AgID.

    Stessa catena di `mappa_connettore.bandi_criteri` (riga 754): riusa la
    LOGICA importandone gli helper, senza toccare il modulo. `None` se il
    portale non espone la tassonomia, o il term dei bandi non si risolve —
    esattamente quando `bandi_criteri` stesso tornerebbe `None`.

    `codice_istat`, se dato, legge PRIMA la mappa-connettore già in cache
    (D-01/D-05/D-06, ciclo18a): se è calda, dice `via == "REST"` e ha già il
    `rest_base` della tassonomia amm-trasparente, si evita del tutto il probe
    `/wp-json/wp/v2/taxonomies` — quel valore l'ha già misurato `_sonda_mappa`.
    Lettura pura da disco (`mappa_connettore._da_cache`), MAI
    `mappa_connettore.mappa_connettore()`: quella sonda a freddo, qui si
    vuole solo leggere, mai un fetch in più. Una cache calda ma col campo
    ancora `None` (scritta prima di questo campo) è valida-ma-incompleta, non
    un buco: si degrada al probe live come oggi, che poi ripopola il campo al
    prossimo giro di `_sonda_mappa`.
    """
    rest_base_tax: str | None = None
    if codice_istat is not None:
        voce_cache = mappa_connettore_module._da_cache(codice_istat)
        if (
            voce_cache is not None
            and voce_cache.amministrazione_trasparente_via == "REST"
            and voce_cache.amministrazione_trasparente_rest_base is not None
        ):
            rest_base_tax = voce_cache.amministrazione_trasparente_rest_base
    if rest_base_tax is None:
        rest_base_tax = _rest_base_tassonomia_per_tipo(sonda, base, CPT_AMM_TRASPARENTE)
    if rest_base_tax is None:
        return None
    term = _term_bandi(_categorie(sonda, base, rest_base_tax))
    if term is None:
        return None
    try:
        righe = sonda.json(
            f"{base}/wp-json/wp/v2/{CPT_AMM_TRASPARENTE}"
            f"?{rest_base_tax}={term.id}&per_page=20"
            "&_fields=title,link,date,excerpt,content&orderby=date&order=desc"
        )
    except Exception:  # noqa: BLE001 — collezione muta: rung1 non risolve
        return None
    if not isinstance(righe, list):
        return None
    return righe


#: Termine-bando a CONFINE DI PAROLA. WordPress `search=` fa match per
#: sottostringa: `search=bando` su Benevento tornava «La Storia» (una moneta
#: bronzea del IV sec a.C.) perché il corpo diceva «abbandono». Il `\b`
#: distingue «bando» da «abbandono»/«sbando» e taglia i falsi positivi che
#: rendevano l'esito senza senso per il cittadino (principio dell'esito onesto:
#: una pagina di museo spacciata per bando è peggio di «nessun bando»).
_CONTESTO_BANDO_RE = re.compile(
    r"\b(?:band[oi]|avvis[oi]\s+pubblic|concors|contribut|"
    r"bors[ae]\s+di\s+studio|graduatori|domand[ae]\s+di\s+partecipazione|"
    r"voucher|sovvenzion|agevolazion)\w*",
    re.IGNORECASE,
)


def _ha_segnale(record: dict[str, Any]) -> bool:
    """La pagina merita l'estrazione come bando?

    WordPress `search=` è per sottostringa, quindi prima di tutto si pretende
    un VERO termine-bando a confine di parola (`_CONTESTO_BANDO_RE`) in titolo
    o corpo — senza, «La Storia» entrava come bando. Solo allora conta il
    filtro di ammissibilità di `wp_pages._select_pages`: un segnale nel corpo o
    un PDF collegato (dove lo spike ha trovato i criteri veri) (D-07/D-15)."""
    content_raw = record.get("content")
    body_html = content_raw.get("rendered", "") if isinstance(content_raw, dict) else ""
    title_raw = record.get("title")
    title = title_raw.get("rendered", "") if isinstance(title_raw, dict) else ""
    testo = strip_html(body_html)

    if not _CONTESTO_BANDO_RE.search(f"{title} {testo}"):
        return False
    if _ELIGIBILITY_SIGNAL_RE.search(testo):
        return True
    return bool(_PDF_LINK_RE.findall(body_html))


def _rung2_pages(sonda: _Sonda, base: str) -> list[dict[str, Any]] | None:
    """Le sei `SEARCH_KEYWORDS` su `wp/v2/pages`, dedup per id.

    Endpoint vivo (almeno una ricerca risponde con una lista, anche vuota)
    equivale a "coperto"; se le candidate sopravvissute al filtro segnale
    sono zero il chiamante deciderà `coperto_senza_bandi`, non `non_coperto`
    — la differenza fra "il portale non ha questa sezione" e "ce l'ha, ma
    oggi non c'è niente dentro" (advocacy).
    """
    seen: dict[int, dict[str, Any]] = {}
    live = False
    for keyword in SEARCH_KEYWORDS:
        try:
            payload = sonda.json(
                f"{base}/wp-json/wp/v2/pages?search={quote(keyword)}&per_page=20"
            )
        except Exception:  # noqa: BLE001 — una keyword muta non decide la copertura
            continue
        if not isinstance(payload, list):
            continue
        live = True
        for record in payload:
            if not isinstance(record, dict):
                continue
            page_id = record.get("id")
            if page_id is None or page_id in seen:
                continue
            seen[page_id] = record
    if not live:
        return None
    return [record for record in seen.values() if _ha_segnale(record)]


def _scopri_bandi(
    sonda: _Sonda, base: str, *, codice_istat: str | None = None
) -> tuple[list[dict[str, Any]], str] | None:
    """Prova rung1, poi rung2. `None` se nessuno dei due copre il portale.

    NIENTE terzo gradino: lo scraper (Tier 3) è deferred, per esplicito
    scope-cut di questo brief.

    `codice_istat` passa attraverso a `_rung1_cpt` (read-first di cache,
    ciclo18a): nessun cambiamento di comportamento su rung2 o sul risultato,
    solo su quanti fetch rung1 fa per arrivarci.
    """
    righe_cpt = _rung1_cpt(sonda, base, codice_istat=codice_istat)
    if righe_cpt is not None:
        return righe_cpt, "cpt"

    righe_pages = _rung2_pages(sonda, base)
    if righe_pages is not None:
        return righe_pages, "pages"

    return None


# --- Guardia host PDF (anti-SSRF) --------------------------------------------


def _filtra_pdf_stesso_host(base: str, pdf_urls: list[str]) -> tuple[list[str], list[str]]:
    """Scarica solo PDF sullo stesso host del portale.

    Stessa regola apex/www di `scheda_servizio` (mappa_connettore.py:649-662):
    un URL assoluto su un host diverso (dopo aver tolto un eventuale `www.` da
    entrambe le parti) è scartato prima ancora di provare a scaricarlo —
    diversamente da corpus.py's skip reasons (cap/dimensione/download/parsing),
    questa non è mai una scelta di budget, è una guardia di sicurezza."""
    host_base = _host_senza_www(urlparse(base).netloc.lower())
    tenuti: list[str] = []
    note: list[str] = []
    for url in pdf_urls:
        if url.startswith(("http://", "https://")):
            host_url = _host_senza_www(urlparse(url).netloc.lower())
            if host_url != host_base:
                note.append(f"Allegato PDF ignorato (host esterno al portale): {url}")
                continue
        tenuti.append(url)
    return tenuti, note


# --- Documenti PDF mostrabili (ciclo17, «link ai documenti») -----------------

#: Rumore ricorrente fra i PDF di una pagina comunale: policy e note che non
#: sono il bando. Tolti dalla lista mostrata (restano contati in
#: `pdfs_linked`), mai un documento del bando spacciato per rumore.
_PDF_RUMORE = re.compile(r"cookie|privacy|informativa|accessibilit|sitemap|manuale", re.I)
#: Parole che qualificano un PDF come documento del bando: salgono in cima.
#: Non escludono nulla — ordinano soltanto, il resto resta sotto.
_PDF_DOCLIKE = re.compile(
    r"band|domanda|allegat|avvis|graduatori|disciplinar|capitolat|modul"
    r"|istanz|regolament|determin|decret|delibera|manifestazione",
    re.I,
)
#: Cap sui documenti mostrati per bando (D-15-style): la card resta leggibile,
#: e ciò che non entra è comunque contato in `pdfs_linked`.
_MAX_DOCUMENTI = 6
_PDF_ETICHETTA_MAX = 80


def _etichetta_pdf(url: str) -> str:
    """Nome-file leggibile dall'URL: basename decodificato, separatori →
    spazi, estensione `.pdf` via. Verbatim dalla pagina, mai riscritto nel
    merito — se non resta nulla di sensato, un'etichetta neutra."""
    nome = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    nome = re.sub(r"\.pdf$", "", nome, flags=re.I)
    nome = re.sub(r"[_\-]+", " ", nome)
    nome = re.sub(r"\s+", " ", nome).strip()
    if not nome:
        return "Documento PDF"
    return nome[:_PDF_ETICHETTA_MAX] + "…" if len(nome) > _PDF_ETICHETTA_MAX else nome


def _documenti_da_pdf(base: str, pdf_urls: list[str]) -> list[Documento]:
    """Da URL PDF già filtrati stesso-host a lista mostrabile: rumore via,
    doc-like in cima, URL reso assoluto, cap. Preserva l'ordine della pagina
    dentro ciascun gruppo — non riordina i documenti per rilevanza inventata."""
    puliti = [u for u in pdf_urls if not _PDF_RUMORE.search(u)]
    doclike = [u for u in puliti if _PDF_DOCLIKE.search(u)]
    resto = [u for u in puliti if not _PDF_DOCLIKE.search(u)]
    ordinati = [*doclike, *resto][:_MAX_DOCUMENTI]
    return [Documento(url=urljoin(base, u), etichetta=_etichetta_pdf(u)) for u in ordinati]


# --- Documenti dei concorsi Halley /zf (estensione multi-piattaforma) --------
#
# Stessa promessa di `_documenti_da_pdf` su una piattaforma diversa da
# WordPress: la scheda concorso Halley `/zf/` non linka `.pdf` diretti ma
# endpoint `/download-.../bando/N/...` (il nome-file vero sta nel
# Content-Disposition, l'ancora in pagina è muta, un'icona). L'etichetta si
# deriva quindi dal VERBO dell'endpoint — «originali-bando», «esito» — che è
# ciò che il portale stesso dice sia quel file, non un titolo inventato
# (D-07). L'URL resta verbatim dalla pagina, reso assoluto e capato.

_HALLEY_DOC_RE = re.compile(
    r'href=["\']([^"\']*/download-([a-z-]+)/bando/[^"\']+)["\']', re.I
)
_HALLEY_ETICHETTE = {
    "originali-bando": "Documento del bando",
    "esito": "Esito della procedura",
    "moduli-iscrizione": "Modulo di iscrizione",
    "traccia-prova-scritta": "Traccia della prova scritta",
    "graduatoria": "Graduatoria",
}
#: Verbi meno frequenti: mappa per prefisso, così un `traccia-prova-orale` o
#: `moduli-domanda` cade su un'etichetta sensata senza doverli enumerare tutti.
_HALLEY_ETICHETTE_PREFISSO = (
    ("allegat", "Allegato"),
    ("modul", "Modulo"),
    ("traccia", "Traccia della prova"),
    ("graduatori", "Graduatoria"),
    ("verbal", "Verbale"),
)
#: Fetch della sola scheda concorso per leggerne i link-documento: guardia SSRF
#: ancorata all'host della scheda, dimensione e timeout modesti. Degrada a
#: nessun documento (mai un crash) se la scheda non è raggiungibile — coerente
#: con l'onestà del gradino: assente ≠ inventato.
_HALLEY_SCHEDA_MAX_BYTES = 2_000_000
_HALLEY_SCHEDA_TIMEOUT = 12.0


def _etichetta_halley(verbo: str) -> str:
    verbo = verbo.lower()
    if verbo in _HALLEY_ETICHETTE:
        return _HALLEY_ETICHETTE[verbo]
    for prefisso, etichetta in _HALLEY_ETICHETTE_PREFISSO:
        if verbo.startswith(prefisso):
            return etichetta
    return "Documento"


def _documenti_halley(url_scheda: str, html: str) -> list[Documento]:
    """Dagli allegati linkati in una scheda concorso Halley `/zf/` a lista
    mostrabile: URL verbatim reso assoluto, dedup, cap. Nessun contenuto
    letto — porta al documento, non lo legge."""
    documenti: list[Documento] = []
    visti: set[str] = set()
    for href, verbo in _HALLEY_DOC_RE.findall(html):
        assoluto = urljoin(url_scheda, href)
        if assoluto in visti:
            continue
        visti.add(assoluto)
        documenti.append(Documento(url=assoluto, etichetta=_etichetta_halley(verbo)))
        if len(documenti) >= _MAX_DOCUMENTI:
            break
    return documenti


def _documenti_scheda_halley(url_scheda: str) -> list[Documento]:
    """Scarica la scheda concorso (guardia SSRF sul suo stesso host) e ne
    estrae i link-documento. Lista vuota — mai eccezione — se irraggiungibile."""
    host = urlparse(url_scheda).hostname
    host_atteso = _host_senza_www(host.lower()) if host else None
    esito = fetch_guardato(
        url_scheda,
        timeout=_HALLEY_SCHEDA_TIMEOUT,
        max_bytes=_HALLEY_SCHEDA_MAX_BYTES,
        host_atteso=host_atteso,
    )
    if esito is None:
        return []
    _headers, raw, _finale = esito
    return _documenti_halley(url_scheda, raw.decode("utf-8", "replace"))


# --- §5.2/§5.3 Arricchimento di un singolo bando -----------------------------


def _raw_hash(url_bando: str, content_rendered: str, pdf_urls: list[str]) -> str:
    """§5.3: chiave deterministica. Stesso contenuto ⇒ stesso hash ⇒ nessuna
    nuova estrazione."""
    materiale = url_bando + content_rendered + "\n".join(sorted(pdf_urls))
    return hashlib.sha256(materiale.encode("utf-8")).hexdigest()


_MESI_IT = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def _scadenza_nel_corpus(deadline_iso: str, segments: Sequence[Segment]) -> bool:
    """La data prodotta dal modello compare DAVVERO nel corpus letto?

    Stessa promessa del quote-gate D-07 (mostrare la scadenza SOLO se
    citabile nel testo che il modello ha visto), ma `quote_appears_in` qui
    è inservibile: una data ISO è lunga ~10 caratteri, sotto la soglia
    `_FUZZY_MIN_MATCH_CHARS` (20), quindi tornerebbe SEMPRE `False` — il
    gate sarebbe morto e nessuna scadenza uscirebbe mai. Confronto quindi la
    data in modo consapevole del formato: la sua forma ISO più le forme
    italiane comuni (`15 marzo 2026`, `15/03/2026`, …). Non è fiducia cieca
    nel modello — la data deve comparire, verbatim, in un segmento visibile;
    è verifica contro la fonte, con la sola aggiunta necessaria a un tipo
    "data" (non una seconda regola di normalizzazione per cifre arbitrarie,
    WN-3/D-07)."""
    try:
        anno, mese, giorno = (int(pezzo) for pezzo in deadline_iso.split("-"))
        nome_mese = _MESI_IT[mese - 1]
    except (ValueError, IndexError):
        return False
    varianti = {
        re.sub(r"\s+", " ", forma.lower())
        for forma in (
            f"{giorno} {nome_mese} {anno}",
            f"{giorno:02d}/{mese:02d}/{anno}",
            f"{giorno}/{mese}/{anno}",
            f"{giorno:02d}-{mese:02d}-{anno}",
            f"{giorno:02d}.{mese:02d}.{anno}",
            deadline_iso,
        )
    }
    for seg in segments:
        testo = re.sub(r"\s+", " ", seg.text.lower())
        if any(variante in testo for variante in varianti):
            return True
    return False


def _arricchisci(
    client: httpx.Client,
    base: str,
    comune: ComuneNoto,
    riga: dict[str, Any],
    bando: Bando,
    extractor: RequirementsExtractor,
) -> BandoArricchito:
    content_raw = riga.get("content") if isinstance(riga, dict) else None
    content_html = content_raw.get("rendered", "") if isinstance(content_raw, dict) else ""
    body_text = strip_html(content_html)

    pdf_urls_grezzi = _PDF_LINK_RE.findall(content_html)
    pdf_urls_sicuri, note_host = _filtra_pdf_stesso_host(base, pdf_urls_grezzi)
    pdf_urls_unique = list(dict.fromkeys(pdf_urls_sicuri))

    pdf_segments, pdf_notes, pdf_skipped, _illegible, _ocr_deferred = collect_pdf_segments(
        client, base, pdf_urls_unique
    )
    corpus, boundary_segments, visible_segments = build_corpus(
        body_text=body_text, page_url=bando.url, pdf_segments=pdf_segments
    )

    raw_hash = _raw_hash(bando.url, content_html, pdf_urls_unique)

    requirements = Requirements()
    confidence = Confidence.INFERRED
    notes: list[str] = [*note_host, *pdf_notes]
    scadenza: str | None = None
    scadenza_verificata = False

    outcome = extractor.extract(
        text=corpus,
        title=bando.titolo,
        raw_hash=raw_hash,
        visible_segments=visible_segments,
        full_segments=boundary_segments,
    )
    if outcome is not None:
        requirements, extraction_notes, confidence = outcome
        notes.extend(extraction_notes)
        # `RequirementsExtractor.extract` non espone `deadline_iso` (non è
        # quote-gated in `to_requirements` — vedi llm.py): lo si legge dalla
        # stessa cache appena popolata (hit o call live, indifferentemente) e
        # si applica QUI il quote-gate D-07, ma consapevole del formato-data
        # (`quote_appears_in` su una data ISO di 10 caratteri è sotto la
        # soglia fuzzy: tornerebbe sempre False, gate morto — vedi
        # `_scadenza_nel_corpus`).
        raw_result = extractor.cache.get(raw_hash)
        data_dichiarata = raw_result.deadline_iso if raw_result is not None else None
        if data_dichiarata and _scadenza_nel_corpus(data_dichiarata, visible_segments):
            scadenza = data_dichiarata
            scadenza_verificata = True
    else:
        notes.append(
            "Estrazione non eseguita (nessuna cache disponibile e provider "
            "non disponibile in questo momento)."
        )

    opportunity = Opportunity(
        id=f"bandi_live:{comune.codice_istat}:{raw_hash[:16]}",
        kind=OpportunityKind.BANDO,
        targets=[TargetGroup.TUTTI],
        title=bando.titolo,
        summary=body_text[:400] or None,
        body=body_text or None,
        requirements=requirements,
        source=Source(
            ente=comune.nome,
            ente_codice_istat=comune.codice_istat,
            connector="bandi_live",
            url=bando.url,
            fetched_at=datetime.now(timezone.utc),
            raw_hash=raw_hash,
        ),
        confidence=confidence,
        extraction_notes=notes,
        pdfs_linked=len(pdf_urls_unique),
        pdfs_opened=len(pdf_segments),
        pdfs_skipped=pdf_skipped,
        chars_processed=len(corpus),
    )

    return BandoArricchito(
        opportunity=opportunity,
        scadenza=scadenza,
        scadenza_verificata=scadenza_verificata,
        # Stessi PDF già contati in `pdfs_linked`, ora esposti come link diretti
        # (stesso-host, ripuliti, capati): TIQ porta al documento, non lo legge.
        documenti=_documenti_da_pdf(base, pdf_urls_unique),
    )


def _arricchisci_scoperto(
    comune: ComuneNoto,
    scoperto: BandoScoperto,
    extractor: RequirementsExtractor,
) -> BandoArricchito:
    """Arricchisce un `BandoScoperto` del terzo gradino (`alberatura`, B1).

    Le agevolazioni (vendor `wp`) riusano la stessa pipeline quote-gated di
    `_arricchisci`, ma sul solo testo disponibile: l'anteprima REST (~280
    caratteri), non l'HTML pieno — quel gradino non porta la pagina intera,
    quindi niente PDF da aprire qui.

    I concorsi (vendor `halley`) NON passano MAI dall'estrattore: `anteprima`
    è sempre `None` per quel listing (nessuna colonna descrizione), e
    inventare criteri da un solo titolo sarebbe una cifra generata dal
    modello (D-06 — «il verbalizzatore corrompe le cifre», stessa guardia
    qui a monte). Si copia solo ciò che il portale mostra: titolo tal quale
    e, per la scadenza, la colonna strutturale «Data scadenza» del listing
    (`bando.data`) — un campo dichiarato dalla tabella, non inferito, quindi
    verificato per costruzione, non da quote-match nel corpus.
    """
    bando = scoperto.bando
    body_text = bando.anteprima or ""
    raw_hash = _raw_hash(bando.url, body_text, [])

    if scoperto.tipo == "concorso":
        requirements = Requirements()
        confidence = Confidence.INFERRED
        notes = [
            "Concorso pubblico: titolo e data copiati dal listing del portale, "
            "nessuna estrazione automatica dei criteri."
        ]
        scadenza = bando.data or None
        scadenza_verificata = bool(bando.data)
        corpus = body_text
        # Estensione multi-piattaforma: la scheda concorso Halley `/zf/` porta
        # allegati veri (bando, esito) dietro endpoint `/download-.../bando/N`.
        # Un solo fetch guardato per scheda, degrada a vuoto se irraggiungibile.
        documenti = _documenti_scheda_halley(bando.url)
    else:
        corpus, boundary_segments, visible_segments = build_corpus(
            body_text=body_text, page_url=bando.url, pdf_segments=[]
        )
        requirements = Requirements()
        confidence = Confidence.INFERRED
        notes = []
        scadenza = None
        scadenza_verificata = False
        documenti = []  # agevolazione wp: solo anteprima REST, nessun HTML da cui linkare
        outcome = extractor.extract(
            text=corpus,
            title=bando.titolo,
            raw_hash=raw_hash,
            visible_segments=visible_segments,
            full_segments=boundary_segments,
        )
        if outcome is not None:
            requirements, extraction_notes, confidence = outcome
            notes.extend(extraction_notes)
            raw_result = extractor.cache.get(raw_hash)
            data_dichiarata = raw_result.deadline_iso if raw_result is not None else None
            if data_dichiarata and _scadenza_nel_corpus(data_dichiarata, visible_segments):
                scadenza = data_dichiarata
                scadenza_verificata = True
        else:
            notes.append(
                "Estrazione non eseguita (nessuna cache disponibile e provider "
                "non disponibile in questo momento)."
            )

    opportunity = Opportunity(
        id=f"bandi_live:{comune.codice_istat}:{raw_hash[:16]}",
        kind=OpportunityKind.BANDO,
        targets=[TargetGroup.TUTTI],
        title=bando.titolo,
        summary=body_text[:400] or None,
        body=body_text or None,
        requirements=requirements,
        source=Source(
            ente=comune.nome,
            ente_codice_istat=comune.codice_istat,
            connector="bandi_live",
            url=bando.url,
            fetched_at=datetime.now(timezone.utc),
            raw_hash=raw_hash,
        ),
        confidence=confidence,
        extraction_notes=notes,
        pdfs_linked=0,
        pdfs_opened=0,
        pdfs_skipped=[],
        chars_processed=len(corpus),
    )

    return BandoArricchito(
        opportunity=opportunity,
        scadenza=scadenza,
        scadenza_verificata=scadenza_verificata,
        tipo=scoperto.tipo,
        documenti=documenti,
    )


def _ordina_per_tipo(bandi: list[BandoArricchito]) -> list[BandoArricchito]:
    """A5: agevolazioni prima dei concorsi. Ordinamento stabile — a parità di
    `tipo` (inclusi i `None` dei gradini cpt/pages) l'ordine del portale
    resta intatto."""
    return sorted(bandi, key=lambda b: 1 if b.tipo == "concorso" else 0)


# --- Entry point --------------------------------------------------------------


def bandi_arricchiti(
    codice_istat: str | None, *, usa_cache: bool = True, timeout: float = 10.0
) -> BandiLiveEsito:
    """Bandi di un comune, scoperti dal vivo su tre gradini REST (cpt, pages,
    alberatura) e arricchiti con requisiti quote-gated. Funzione SYNC (sonda
    + parse LLM sono bloccanti): chi la chiama da un contesto async lo fa con
    `asyncio.to_thread` (mai `provider.parse` dentro un loop async).

    Con cache calda (entro `TTL_ORE`) torna l'esito già scritto, senza alcuna
    rete né chiamata LLM. `esito="comune_ignoto"` se `codice_istat` non è un
    comune noto (`comune_per_codice`, `sonda_live`).
    """
    comune = comune_per_codice(codice_istat)
    if comune is None:
        return BandiLiveEsito(
            codice_istat=codice_istat or "",
            comune_nome="",
            esito="comune_ignoto",
            gradino=None,
            verificato_il=_ora_iso(),
            bandi=[],
        )

    if usa_cache:
        cached = _da_cache(comune.codice_istat)
        if cached is not None:
            return cached

    # AT-aware routing (B5/ciclo16, dispatch ciclo18a B3): sapere QUALE
    # connettore AT si userebbe per questo comune (informativo, invariato) E
    # quali gradini di SCOPERTA una `piattaforma_at` catalogata e fresca
    # autorizza a saltare. `gradini` è `_TUTTI_I_GRADINI` (cascata cieca,
    # comportamento identico a prima di questo brief) ogni volta che il
    # catalogo tace, non è mai stato scritto, o è oltre
    # `TTL_CATALOGO_AT_GIORNI` — un dato vecchio non deve mai poter spegnere
    # una sonda che potrebbe ancora rispondere (D-05/D-06).
    piattaforma_at, connettore_at, ultima_scansione_at = _piattaforma_e_connettore_at(
        comune.codice_istat
    )
    gradini = _gradini_da_tentare(piattaforma_at, ultima_scansione_at)

    base = _base_con_schema(comune.sito)
    if base is None:
        esito = _esito_vuoto(
            comune, "non_coperto", None,
            piattaforma_at=piattaforma_at, connettore_at=connettore_at,
        )
        _in_cache(esito)
        return esito

    rest_gradino: Literal["cpt", "pages"] | None = None
    rest_ha_risposto = False  # il REST ha coperto, anche a zero bandi (D-B7)
    rest_bandi: list[BandoArricchito] = []
    rest_tentato = False
    scoperti: list[BandoScoperto] | None = None
    alberatura_tentata = False

    def _prova_rest() -> None:
        """Cascata interna cpt→pages (`_scopri_bandi` sceglie da sola quale
        dei due risponde, D-03: il dispatch autorizza il TENTATIVO, mai la
        scelta fra i due). Chiamata al più una volta per invocazione."""
        nonlocal rest_gradino, rest_ha_risposto, rest_bandi, rest_tentato
        rest_tentato = True
        with _Sonda(timeout=timeout) as sonda:
            scoperta = _scopri_bandi(sonda, base, codice_istat=comune.codice_istat)
            if scoperta is None:
                return
            rest_ha_risposto = True
            righe, rest_gradino = scoperta  # type: ignore[assignment]
            coppie = [
                (riga, bando)
                for riga in righe
                if (bando := _bando_da_riga(base, riga)) is not None
            ]

            if coppie:
                _prune_cache(comune.codice_istat)
                extractor = RequirementsExtractor(
                    CACHE_DIR / comune.codice_istat / "estrazioni",
                    provider=load_provider(role="extract"),
                )
                client = sonda._client
                rest_bandi = [
                    _arricchisci(client, base, comune, riga, bando, extractor)
                    for riga, bando in coppie[:MAX_BANDI_ARRICCHITI]
                ]

    def _prova_alberatura() -> None:
        nonlocal scoperti, alberatura_tentata
        alberatura_tentata = True
        scoperti = alberatura.estrai_bandi(comune.codice_istat, timeout=timeout)

    if "cpt" in gradini or "pages" in gradini:
        _prova_rest()

    # `alberatura` gira solo quando cpt/pages non hanno GIA' prodotto bandi
    # — stesso short-circuit di prima di questo brief: se il REST ha già
    # trovato qualcosa non si spende una sonda in più. Quando invece cpt/pages
    # coprono a vuoto (Benevento, D-03), `alberatura.estrai_bandi` è la fonte
    # che combina agevolazioni WP e concorsi Halley — vedi il modulo.
    if not rest_bandi and "alberatura" in gradini:
        _prova_alberatura()

    # Rete di sicurezza (D-05/D-06): i gradini catalogati sono usciti a
    # vuoto E il dispatch aveva effettivamente ristretto il ventaglio
    # (`gradini` è un sottoinsieme proprio) — tenta i gradini mancanti prima
    # di arrendersi. Una classificazione di catalogo sbagliata o
    # incompleta non deve mai produrre un `non_coperto` che una sonda in
    # più avrebbe smentito. Con le voci odierne di `_GRADINI_PER_PIATTAFORMA_AT`
    # (sempre il ventaglio pieno) questo ramo non ha nulla da aggiungere:
    # resta pronto per quando una voce futura taglierà davvero un gradino.
    if not rest_bandi and not scoperti and gradini != _TUTTI_I_GRADINI:
        mancanti = tuple(g for g in _TUTTI_I_GRADINI if g not in gradini)
        if ("cpt" in mancanti or "pages" in mancanti) and not rest_tentato:
            _prova_rest()
        if not rest_bandi and "alberatura" in mancanti and not alberatura_tentata:
            _prova_alberatura()

    if rest_bandi:
        esito = BandiLiveEsito(
            codice_istat=comune.codice_istat,
            comune_nome=comune.nome,
            esito="coperto_con_bandi",
            gradino=rest_gradino,
            verificato_il=_ora_iso(),
            bandi=_ordina_per_tipo(rest_bandi),
            piattaforma_at=piattaforma_at,
            connettore_at=connettore_at,
        )
        _in_cache(esito)
        return esito

    # cpt/pages non hanno prodotto bandi — coperto a zero (D-B7) o muto del
    # tutto. `scoperti` è già stato tentato sopra (`_prova_alberatura`,
    # gated dal dispatch + dalla rete di sicurezza): non solo quando
    # cpt/pages non coprono, ma anche come fonte aggiuntiva quando coprono a
    # vuoto — Benevento è il caso reale: il WordPress in apice risponde
    # (`pages`, coperto_senza_bandi) ma i concorsi veri vivono su un
    # sottodominio Halley separato, invisibile a cpt/pages per costruzione.
    if scoperti:
        _prune_cache(comune.codice_istat)
        extractor = RequirementsExtractor(
            CACHE_DIR / comune.codice_istat / "estrazioni",
            provider=load_provider(role="extract"),
        )
        esito = BandiLiveEsito(
            codice_istat=comune.codice_istat,
            comune_nome=comune.nome,
            esito="coperto_con_bandi",
            gradino="alberatura",
            verificato_il=_ora_iso(),
            bandi=_ordina_per_tipo(
                [
                    _arricchisci_scoperto(comune, scoperto, extractor)
                    for scoperto in scoperti[:MAX_BANDI_ARRICCHITI]
                ]
            ),
            piattaforma_at=piattaforma_at,
            connettore_at=connettore_at,
        )
        _in_cache(esito)
        return esito

    if rest_ha_risposto:
        # cpt/pages hanno coperto a zero e alberatura non aggiunge nulla
        # (rami assenti o zero bandi): il verdetto onesto resta quello che
        # ha davvero risposto, cacheabile (D-B7 — copertura confermata).
        esito = _esito_vuoto(
            comune, "coperto_senza_bandi", rest_gradino,
            piattaforma_at=piattaforma_at, connettore_at=connettore_at,
        )
        _in_cache(esito)
        return esito

    if scoperti is not None:
        # alberatura ha coperto (rami letti) ma zero bandi, e cpt/pages non
        # hanno coperto affatto: comunque una copertura confermata.
        esito = _esito_vuoto(
            comune, "coperto_senza_bandi", "alberatura",
            piattaforma_at=piattaforma_at, connettore_at=connettore_at,
        )
        _in_cache(esito)
        return esito

    # Nessuno dei tre gradini ha risposto: portale non leggibile ORA (blip di
    # rete o davvero assente) — non possiamo sostenerlo per TTL_ORE, quindi
    # non lo cristallizziamo in cache. Esito onesto ma volatile, riverificato
    # alla prossima domanda (principio fondante: mai un verdetto che non
    # possiamo sostenere).
    return _esito_vuoto(
        comune, "non_coperto", None,
        piattaforma_at=piattaforma_at, connettore_at=connettore_at,
    )
