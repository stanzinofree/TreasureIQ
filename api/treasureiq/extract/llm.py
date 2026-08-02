"""LLM-backed extraction of eligibility criteria from Italian public-sector prose.

Why this exists: measured on Comune di Albano Laziale's 32 published services,
ten are means-tested but only two state their ISEE threshold in a form the
regex extractor can recover. The rest bury it in sentences like "possono
accedere i nuclei familiari con attestazione ISEE in corso di validità non
superiore ad euro quindicimila/00". Regexes lose that; a language model does
not.

Three design commitments, all downstream of one fact — a citizen may act on
what this returns:

1. The model may only report what the text states. A threshold that is not
   written down must come back as null, never as a plausible default. The
   prompt says so and `ExtractionResult.quote` makes it checkable: every
   structured value carries the source sentence it came from.

2. Results are cached on disk keyed by the source record's hash, and the cache
   is committed to the repository. Without an API key TreasureIQ still runs
   with real extractions — the demo is reproducible for anyone who clones it,
   and re-running ingestion costs nothing for unchanged records.

3. Extraction never blocks ingestion. An API failure downgrades a record to
   its regex-derived requirements rather than dropping it.
"""

from __future__ import annotations

import difflib
import logging
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, Field

from treasureiq.extract.providers import LLMProvider, load_provider
from treasureiq.schema import Confidence, EmploymentStatus, Requirements

logger = logging.getLogger(__name__)

# Bumped whenever the prompt or schema changes in a way that would produce
# different output for the same input. Part of the cache key, so a prompt
# revision invalidates stale entries instead of silently serving them.
# Bumped to "2" for the move to the provider abstraction (Ollama default,
# Anthropic optional): the prompt is unchanged, but the extraction path is
# not, and cache entries are cheap to regenerate.
EXTRACTOR_VERSION = "2"

SYSTEM_PROMPT = """\
Sei un estrattore di requisiti di accesso da testi della Pubblica \
Amministrazione italiana. Ricevi la descrizione di un servizio, un'agevolazione \
o un bando comunale e restituisci i criteri di eleggibilità in forma \
strutturata.

# Regola fondamentale

Estrai SOLO ciò che il testo afferma. Se un requisito non è dichiarato, il \
campo corrispondente deve essere null. Non dedurre, non completare con valori \
tipici, non usare conoscenze esterne sulla normativa italiana.

Questa regola non è negoziabile. Un cittadino può presentare domanda sulla base \
di ciò che restituisci: una soglia inventata gli fa perdere tempo e fiducia. \
Un campo null è un risultato corretto e utile — segnala che il dato manca alla \
fonte, che è precisamente l'informazione che ci serve.

# Distinzione critica

"Il testo non dichiara il requisito" e "il requisito non esiste" sono cose \
diverse. Restituisci sempre null per il primo caso. Non usare mai un valore \
che rappresenti "nessun vincolo".

# Campi

- isee_max: soglia ISEE massima in euro. Solo se il testo indica un valore \
numerico esplicito. Attenzione: gli importi in lettere ("quindicimila") sono \
valori validi da convertire in cifre. Se il testo cita l'ISEE come documento \
da presentare ma non indica alcuna soglia, isee_max resta null e lo segnali in \
`isee_mentioned_without_threshold`.
- isee_min: soglia ISEE minima, raro ma esiste in alcune graduatorie.
- eta_min / eta_max: età in anni compiuti. "over 65" significa eta_min=65. \
"minori di 18 anni" significa eta_max=17.
- nucleo_min: numero minimo di componenti del nucleo familiare.
- figli_minori_required: true solo se la presenza di figli minorenni è \
condizione di accesso, non se è solo un criterio di punteggio in graduatoria.
- disabilita_required: true solo se una condizione di disabilità certificata è \
condizione di accesso.
- employment_status: stati occupazionali ammessi, tra occupato, disoccupato, \
studente, pensionato, inabile. Lista vuota se il testo non pone vincoli.
- residenza_required: true se è richiesta la residenza nel comune. Nota che \
molti bandi comunali la danno per scontata senza dichiararla: in quel caso \
lascia null, non true.
- other: criteri reali ma non riconducibili ai campi sopra, uno per voce, \
formulati in modo conciso. Esempi: iscrizione a una scuola specifica, possesso \
di un veicolo, titolarità di partita IVA. Non inserire qui documenti da \
allegare né passaggi procedurali.
- quote: per OGNI campo valorizzato (diverso da null e da lista vuota), \
riporta la frase esatta del testo originale da cui l'hai ricavato, senza \
parafrasarla. Serve al cittadino per verificare. Se non riesci a indicare una \
citazione letterale, allora il campo va lasciato null.
- deadline_iso: scadenza per la presentazione della domanda, formato \
YYYY-MM-DD, solo se una data esplicita è presente nel testo.
- notes: cosa è rimasto ambiguo, in italiano, rivolto al cittadino. Vuota se \
tutto era chiaro.

# Cosa NON è un requisito di accesso

Documenti da allegare, modalità di presentazione della domanda, uffici di \
riferimento, orari di sportello, riferimenti normativi, criteri di formazione \
della graduatoria. Questi non vanno in `other`.
"""


class FieldQuote(BaseModel):
    """Ties one extracted value back to the sentence that justifies it."""

    field: str = Field(description="Nome del campo estratto.")
    text: str = Field(description="Frase letterale dal testo originale.")


@dataclass(frozen=True)
class Segment:
    """One boundary-tracked unit of the assembled corpus.

    Either the page body itself (`page_number=None`) or a single page of one
    PDF attachment (`page_number` 1-based, matching what a citizen sees if
    they open the PDF). `start` is the character offset of this segment
    within the *pre-truncation* corpus the connector assembled — callers must
    slice `text` down to whatever the model actually saw (D-15's
    `MAX_CORPUS_CHARS` cap) before handing segments to `attribute_quote`, so a
    quote can never be attributed to text the model never read.
    """

    kind: str  # "pagina" | "allegato"
    url: str
    page_number: int | None
    start: int
    text: str


#: Normalisation differences (whitespace collapse, curly vs straight quotes,
#: accents, case) are common between what the model returns and what `pypdf`
#: or `strip_html` produced, and are not evidence of a wrong source — so they
#: are ignored for comparison only. The stored quote itself is never touched.
def _normalise_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("«", '"')
        .replace("»", '"')
    )
    text = text.lower()
    return " ".join(text.split())


#: Fuzzy fallback threshold: the longest common substring, on normalised
#: text, must cover at least this fraction of the *quote's* own length. High
#: on purpose — the invariant is "unattributed beats wrong source", so a
#: near-match that isn't overwhelmingly the quote itself must not land on a
#: document. Combined with a minimum absolute length so a short quote can't
#: be satisfied by a coincidental fragment.
_FUZZY_MIN_RATIO = 0.92
_FUZZY_MIN_MATCH_CHARS = 20


def attribute_quote(quote_text: str, segments: Sequence[Segment]) -> Segment | None:
    """Find which segment a quote-gated quote actually came from.

    Tries an exact (normalised) substring match first. Falls back to the
    longest common substring on normalised text, accepted only above
    `_FUZZY_MIN_RATIO`. If more than one segment reaches that bar — exact or
    fuzzy — the match is ambiguous and this returns `None` rather than guess:
    per the invariant, "unattributed" is always preferred to a wrong
    citation. Returns `None` immediately if the quote itself is blank.
    """
    normalised_quote = _normalise_for_match(quote_text)
    if not normalised_quote:
        return None

    candidates = [seg for seg in segments if seg.text]

    exact_matches = [
        seg for seg in candidates if normalised_quote in _normalise_for_match(seg.text)
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        # The same phrase turns up verbatim in more than one segment (short
        # quotes, boilerplate) — attributing to either would be a guess, and
        # the invariant is "unattributed" over "maybe wrong".
        return None

    best_segment: Segment | None = None
    best_ratio = 0.0
    ambiguous = False
    for seg in candidates:
        normalised_page = _normalise_for_match(seg.text)
        matcher = difflib.SequenceMatcher(None, normalised_quote, normalised_page, autojunk=False)
        match = matcher.find_longest_match(0, len(normalised_quote), 0, len(normalised_page))
        if match.size < _FUZZY_MIN_MATCH_CHARS:
            continue
        ratio = match.size / len(normalised_quote)
        if ratio < _FUZZY_MIN_RATIO:
            continue
        if ratio > best_ratio:
            best_ratio = ratio
            best_segment = seg
            ambiguous = False
        elif ratio == best_ratio and best_segment is not None:
            ambiguous = True

    if ambiguous:
        return None
    return best_segment


class ExtractionResult(BaseModel):
    """Raw model output, before validation into a `Requirements`.

    Kept separate from `Requirements` on purpose: this is what the model
    claims, which is not yet what the system is willing to assert. The
    conversion in `to_requirements` is where claims get checked.
    """

    isee_max: float | None = None
    isee_min: float | None = None
    isee_mentioned_without_threshold: bool = False

    eta_min: int | None = None
    eta_max: int | None = None
    nucleo_min: int | None = None

    figli_minori_required: bool | None = None
    disabilita_required: bool | None = None
    residenza_required: bool | None = None

    employment_status: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)

    quotes: list[FieldQuote] = Field(default_factory=list)
    deadline_iso: str | None = None
    notes: list[str] = Field(default_factory=list)

    def quoted_fields(self) -> set[str]:
        return {q.field for q in self.quotes}

    def to_requirements(self) -> tuple[Requirements, list[str]]:
        """Convert to the internal schema, dropping unsupported claims.

        A numeric value without a supporting quote is discarded rather than
        trusted. This is the cheapest available guard against a confident
        fabrication: the model has to point at the text, and if it cannot, the
        value does not survive. Discards are reported in the notes so the gap
        is visible instead of silent.
        """
        notes = list(self.notes)
        quoted = self.quoted_fields()
        req = Requirements()

        def supported(field: str, value: object) -> bool:
            if value is None:
                return False
            if field not in quoted:
                notes.append(
                    f"Valore per '{field}' scartato: il modello non ha saputo "
                    f"indicare la frase di origine nel testo."
                )
                return False
            return True

        if supported("isee_max", self.isee_max):
            req.isee_max = Decimal(str(self.isee_max)).quantize(Decimal("0.01"))
        if supported("isee_min", self.isee_min):
            req.isee_min = Decimal(str(self.isee_min)).quantize(Decimal("0.01"))
        if supported("eta_min", self.eta_min):
            req.eta_min = self.eta_min
        if supported("eta_max", self.eta_max):
            req.eta_max = self.eta_max
        if supported("nucleo_min", self.nucleo_min):
            req.nucleo_min = self.nucleo_min
        if supported("figli_minori_required", self.figli_minori_required):
            req.figli_minori_required = self.figli_minori_required
        if supported("disabilita_required", self.disabilita_required):
            req.disabilita_required = self.disabilita_required

        # `residenza_required` defaults to True in the schema because municipal
        # benefits nearly always require residency. Only an explicit statement
        # in the text moves it, and only downward — an unstated requirement is
        # not evidence that it doesn't apply.
        if self.residenza_required is False and "residenza_required" in quoted:
            req.residenza_required = False

        for raw in self.employment_status:
            try:
                req.employment_status.append(EmploymentStatus(raw.strip().lower()))
            except ValueError:
                notes.append(f"Stato occupazionale non riconosciuto: '{raw}'.")

        req.other = [item.strip() for item in self.other if item.strip()]

        if self.isee_mentioned_without_threshold and req.isee_max is None:
            req.other.append("Richiesta attestazione ISEE (soglia non pubblicata)")
            notes.append(
                "Il servizio richiede l'ISEE ma non pubblica la soglia: "
                "verifica sulla pagina del comune."
            )

        return req, notes


class ExtractionCache:
    """On-disk cache of extraction results, committed to the repository.

    Keyed by the source record's content hash plus the extractor version, so
    an unchanged record is never re-extracted and a prompt change invalidates
    the affected entries. One JSON file per entry rather than a single blob:
    entries then diff readably in review, which matters because these files
    are the evidence that the demo's numbers are real.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, raw_hash: str) -> Path:
        return self.directory / f"{raw_hash}.v{EXTRACTOR_VERSION}.json"

    def get(self, raw_hash: str) -> ExtractionResult | None:
        path = self._path(raw_hash)
        if not path.exists():
            return None
        try:
            return ExtractionResult.model_validate_json(path.read_text("utf-8"))
        except Exception as exc:
            # A corrupt entry must not take the run down; drop it and re-extract.
            logger.warning("discarding unreadable cache entry %s: %s", path.name, exc)
            return None

    def put(self, raw_hash: str, result: ExtractionResult) -> None:
        self._path(raw_hash).write_text(
            result.model_dump_json(indent=1, exclude_none=False), encoding="utf-8"
        )


class RequirementsExtractor:
    """Extracts eligibility criteria, preferring cache over API calls."""

    def __init__(self, cache_dir: Path, *, provider: LLMProvider | None = None) -> None:
        self.cache = ExtractionCache(cache_dir)
        self._provider = provider or load_provider(role="extract")
        self.stats = {"cache_hits": 0, "api_calls": 0, "failures": 0, "skipped": 0}

    @property
    def available(self) -> bool:
        """Whether live extraction is possible in this environment."""
        return self._provider.available

    def extract(
        self, *, text: str, title: str, raw_hash: str
    ) -> tuple[Requirements, list[str], Confidence] | None:
        """Extract requirements for one record.

        Returns None when extraction could not run at all — no cache entry and
        no API key, or the call failed. The caller keeps whatever the regex
        extractor produced rather than losing the record.
        """
        cached = self.cache.get(raw_hash)
        if cached is not None:
            self.stats["cache_hits"] += 1
            req, notes = cached.to_requirements()
            return req, notes, Confidence.EXTRACTED

        if not self.available:
            self.stats["skipped"] += 1
            return None

        try:
            # This runs from the (synchronous) ingestion CLI, never from an
            # async context, so the sync wrapper is the correct call here.
            result = self._provider.parse(
                system=SYSTEM_PROMPT,
                user=f"# Servizio\n{title}\n\n# Testo pubblicato dal comune\n{text}",
                output_model=ExtractionResult,
            )
        except Exception as exc:
            # Ingestion continues on regex results. Logged loudly because a
            # silent downgrade would quietly degrade the readiness figures.
            logger.warning("extraction failed for %s: %s", title[:60], exc)
            self.stats["failures"] += 1
            return None

        self.cache.put(raw_hash, result)
        self.stats["api_calls"] += 1
        req, notes = result.to_requirements()
        return req, notes, Confidence.EXTRACTED

    def report(self) -> str:
        s = self.stats
        return (
            f"extraction: {s['cache_hits']} cached, {s['api_calls']} live, "
            f"{s['failures']} failed, {s['skipped']} skipped (no API key)"
        )


def load_extractor(repo_root: Path | None = None) -> RequirementsExtractor:
    """Build an extractor pointed at the repository's committed cache."""
    root = repo_root or Path(__file__).resolve().parents[3]
    return RequirementsExtractor(root / "data" / "extraction-cache")
