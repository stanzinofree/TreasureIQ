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
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel

from treasureiq.extract.corpus import build_corpus, collect_pdf_segments
from treasureiq.extract.llm import RequirementsExtractor, Segment
from treasureiq.extract.providers import load_provider
from treasureiq.ingest.censimento import _Sonda
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


class BandiLiveEsito(BaseModel):
    """Esito di una scansione bandi-live per un comune: cosa si è trovato,
    e su quale gradino REST."""

    codice_istat: str
    comune_nome: str
    esito: Literal["coperto_con_bandi", "coperto_senza_bandi", "non_coperto", "comune_ignoto"]
    #: Quale gradino REST ha coperto il comune. `None` su `non_coperto` (nessuno
    #: dei due) e su `comune_ignoto` (non si è nemmeno sondato).
    gradino: Literal["cpt", "pages"] | None
    verificato_il: str
    bandi: list[BandoArricchito] = []


def _ora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _esito_vuoto(comune: ComuneNoto, esito: str, gradino: str | None) -> BandiLiveEsito:
    return BandiLiveEsito(
        codice_istat=comune.codice_istat,
        comune_nome=comune.nome,
        esito=esito,  # type: ignore[arg-type]
        gradino=gradino,  # type: ignore[arg-type]
        verificato_il=_ora_iso(),
        bandi=[],
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


def _rung1_cpt(sonda: _Sonda, base: str) -> list[dict[str, Any]] | None:
    """Amministrazione Trasparente via CPT AgID.

    Stessa catena di `mappa_connettore.bandi_criteri` (riga 754): riusa la
    LOGICA importandone gli helper, senza toccare il modulo. `None` se il
    portale non espone la tassonomia, o il term dei bandi non si risolve —
    esattamente quando `bandi_criteri` stesso tornerebbe `None`.
    """
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


def _scopri_bandi(sonda: _Sonda, base: str) -> tuple[list[dict[str, Any]], str] | None:
    """Prova rung1, poi rung2. `None` se nessuno dei due copre il portale.

    NIENTE terzo gradino: lo scraper (Tier 3) è deferred, per esplicito
    scope-cut di questo brief.
    """
    righe_cpt = _rung1_cpt(sonda, base)
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

    pdf_segments, pdf_notes, pdf_skipped, _illegible = collect_pdf_segments(
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
    )


# --- Entry point --------------------------------------------------------------


def bandi_arricchiti(
    codice_istat: str | None, *, usa_cache: bool = True, timeout: float = 10.0
) -> BandiLiveEsito:
    """Bandi di un comune, scoperti dal vivo su due gradini REST e arricchiti
    con requisiti quote-gated. Funzione SYNC (sonda + parse LLM sono
    bloccanti): chi la chiama da un contesto async lo fa con
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

    base = _base_con_schema(comune.sito)
    if base is None:
        esito = _esito_vuoto(comune, "non_coperto", None)
        _in_cache(esito)
        return esito

    with _Sonda(timeout=timeout) as sonda:
        scoperta = _scopri_bandi(sonda, base)
        if scoperta is None:
            # `_scopri_bandi` torna None SOLO quando nessun gradino REST ha
            # risposto: o il portale non ha davvero una sezione bandi, oppure
            # è un WordPress irraggiungibile in questo istante. Non possiamo
            # distinguere i due casi da qui — quindi NON cristallizziamo un
            # "non coperto" in cache per TTL_ORE: sarebbe una bugia durevole
            # su un blip di rete. Esito onesto ma volatile, riverificato alla
            # prossima domanda (principio fondante: mai un verdetto che non
            # possiamo sostenere).
            return _esito_vuoto(comune, "non_coperto", None)

        righe, gradino = scoperta
        coppie = [
            (riga, bando)
            for riga in righe
            if (bando := _bando_da_riga(base, riga)) is not None
        ]

        if not coppie:
            esito = _esito_vuoto(comune, "coperto_senza_bandi", gradino)
            _in_cache(esito)
            return esito

        _prune_cache(comune.codice_istat)
        extractor = RequirementsExtractor(
            CACHE_DIR / comune.codice_istat / "estrazioni",
            provider=load_provider(role="extract"),
        )

        client = sonda._client
        arricchiti = [
            _arricchisci(client, base, comune, riga, bando, extractor)
            for riga, bando in coppie[:MAX_BANDI_ARRICCHITI]
        ]

    esito = BandiLiveEsito(
        codice_istat=comune.codice_istat,
        comune_nome=comune.nome,
        esito="coperto_con_bandi",
        gradino=gradino,  # type: ignore[arg-type]
        verificato_il=_ora_iso(),
        bandi=arricchiti,
    )
    _in_cache(esito)
    return esito
