"""Store di scansione per-comune: aderenza AgID calcolata dai probe, mai digitata.

Una scansione compone in un unico record ciò che gli altri moduli sondano
separatamente — mappa del connettore, contatti URP, orari uffici — e ci
aggiunge la sola cosa che nessuno di loro calcola da solo: l'aderenza AgID,
una checklist FISSA di 4 superfici REST (servizi/uffici/trasparenza/contatti)
letta dai campi già sondati di `MappaConnettore` (D-S1). Nessun input manuale
entra mai in questo numero, e ogni cifra porta con sé la sua provenienza
(D-S4).

Il record vive su disco (D-S5), stesso pattern cache atomico di
`mappa_connettore.py` (`_percorso_cache`/`_da_cache`/`_in_cache`, scrittura
`.tmp`+`replace`, voce illeggibile = voce assente). Niente sqlite, niente
dipendenze nuove.

Nessun job batch qui (D-S10 / RISK): il `--sonda`/`--invecchia` di questo
modulo sono utilità manuali per la demo, non uno scheduler.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

from treasureiq.mappa_connettore import MappaConnettore, mappa_connettore
from treasureiq.sonda_live import (
    LIVE_DIR,
    ContattiUrp,
    OrariLive,
    comune_per_codice,
    leggi_orari_urp,
    recupera_contatti,
)

logger = logging.getLogger(__name__)

#: Soglia di freschezza (D-S6): oltre questi giorni una scansione è stantia e
#: va rifatta prima di servirla come "gli attuali".
GIORNI_STANTIA = 6


class SuperficieAderenza(BaseModel):
    """Una delle 4 voci della checklist AgID, con la sua provenienza (D-S4)."""

    nome: str
    via: str  # "REST" | "scrape"


class AderenzaAgid(BaseModel):
    """Quante delle 4 superfici AgID (servizi/uffici/trasparenza/contatti) il
    portale espone via REST, con l'elenco di ognuna e la sua via.

    Costruita SOLO da `aderenza_agid`: il numero è sempre esposte/definite,
    mai una cifra digitata a mano (D-S1)."""

    percento: int
    esposte: int
    definite: int
    superfici: list[SuperficieAderenza]


def aderenza_agid(mappa: MappaConnettore) -> AderenzaAgid | None:
    """La checklist FISSA di 4 superfici, letta dai soli campi già sondati di
    `mappa` — mai un input esterno, mai una rilettura del portale.

    `None` se il connettore non è AgID (né servizi né uffici in REST): mai
    una percentuale fuori da questo tier (D-S2). La via di lettura scrape
    esiste come ripiego ma non incrementa mai `esposte` (D-S1) — è una via,
    non una copertura.
    """
    if not (mappa.servizi.esposto or mappa.uffici.esposto):
        return None
    superfici = [
        SuperficieAderenza(nome="servizi", via="REST" if mappa.servizi.esposto else "scrape"),
        SuperficieAderenza(nome="uffici", via="REST" if mappa.uffici.esposto else "scrape"),
        SuperficieAderenza(nome="trasparenza", via=mappa.amministrazione_trasparente_via),
        SuperficieAderenza(nome="contatti", via=mappa.contatti_via),
    ]
    definite = len(superfici)
    esposte = sum(1 for superficie in superfici if superficie.via == "REST")
    return AderenzaAgid(
        percento=round(100 * esposte / definite),
        esposte=esposte,
        definite=definite,
        superfici=superfici,
    )


def connettore_tipo(mappa: MappaConnettore) -> str:
    """Il tier testuale del connettore (D-S2): mai una percentuale fuori da
    `"agid"`.

    `mappa` non porta un segnale diretto di "wp-json vivo ma senza CPT AgID":
    si usa `sito` come proxy onesto — un comune senza sito noto non è mai
    stato sondabile, uno con sito ma senza CPT AgID è "solo-html".
    """
    if mappa.servizi.esposto or mappa.uffici.esposto:
        return "agid"
    if mappa.sito:
        return "solo-html"
    return "non-sondato"


class ScansioneComune(BaseModel):
    """Il record persistente di una scansione: quello che si mostra sulla
    scheda-comune viene SEMPRE da qui, mai da un `now()` al volo (D-S4)."""

    codice_istat: str
    scansionato_il: str  # ISO-8601 UTC
    mappa: MappaConnettore
    aderenza: AderenzaAgid | None = None
    contatti: ContattiUrp | None = None
    orari: OrariLive | None = None
    logo_url: str | None = None


def _percorso_cache(codice_istat: str) -> Path:
    return LIVE_DIR / "scansioni" / f"{codice_istat}.json"


def _da_cache(codice_istat: str) -> ScansioneComune | None:
    percorso = _percorso_cache(codice_istat)
    if not percorso.exists():
        return None
    try:
        return ScansioneComune.model_validate_json(percorso.read_text("utf-8"))
    except Exception:  # noqa: BLE001 — un record illeggibile è un record assente
        logger.warning("scansione illeggibile: %s", percorso)
        return None


def _in_cache(record: ScansioneComune) -> None:
    """Scrittura atomica: un lettore concorrente vede il record vecchio o il
    nuovo, mai un record a metà. Il mount live può mancare in sviluppo/test:
    il record è già pronto in memoria e non deve dipendere dal disco."""
    percorso = _percorso_cache(record.codice_istat)
    try:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(record.model_dump_json(indent=1), "utf-8")
        provvisorio.replace(percorso)
    except OSError as exc:
        logger.warning("store scansioni non scrivibile (%s): %s", percorso, exc)


def aggiorna_scansione(codice_istat: str | None) -> ScansioneComune | None:
    """Sonda tutto adesso — mappa, contatti, orari — e scrive il record.

    `None` se il comune non è noto. Ogni sotto-probe segue le sue regole di
    degrado muto: un portale storto non fa fallire l'intera scansione.
    """
    comune = comune_per_codice(codice_istat)
    if comune is None:
        return None
    mappa = mappa_connettore(comune.codice_istat, usa_cache=False)
    if mappa is None:
        return None
    record = ScansioneComune(
        codice_istat=comune.codice_istat,
        scansionato_il=datetime.now(timezone.utc).isoformat(),
        mappa=mappa,
        aderenza=aderenza_agid(mappa),
        contatti=recupera_contatti(comune.codice_istat),
        orari=leggi_orari_urp(comune, usa_cache=False),
        logo_url=mappa.logo_url,
    )
    _in_cache(record)
    return record


def carica_scansione(codice_istat: str | None) -> ScansioneComune | None:
    """Legge il record esistente, senza sondare. `None` se non c'è ancora —
    chi chiama decide se e quando far partire un `aggiorna_scansione`."""
    if not codice_istat:
        return None
    return _da_cache(codice_istat)


def scansione_stantia(record: ScansioneComune, *, giorni: int = GIORNI_STANTIA) -> bool:
    """Vero se il record ha più di `giorni` (D-S6, soglia di default 6).

    Un `scansionato_il` non parsabile è trattato come stantio: meglio un
    refresh di troppo che un dato silenziosamente vecchio."""
    try:
        eta = datetime.now(timezone.utc) - datetime.fromisoformat(record.scansionato_il)
    except ValueError:
        return True
    return eta > timedelta(days=giorni)


def _cli() -> None:
    """Utilità manuale sullo store (D-S10: nessuno scheduler qui).

    `--sonda ISTAT` scalda un record adesso. `--invecchia ISTAT --giorni N`
    retrodata `scansionato_il` di un record esistente, per mostrare dal vivo
    il refresh-on-search di B6 senza aspettare N giorni veri — trasparente,
    non un trucco nascosto.
    """
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.scansioni",
        description=(
            "Utilità manuali sullo store di scansione: sonda un comune ora, "
            "o invecchia un record esistente per la demo refresh-on-search."
        ),
    )
    gruppo = parser.add_mutually_exclusive_group(required=True)
    gruppo.add_argument("--sonda", metavar="ISTAT", help="sonda e scrive il record ora")
    gruppo.add_argument(
        "--invecchia", metavar="ISTAT", help="retrodata scansionato_il di un record esistente"
    )
    parser.add_argument(
        "--giorni",
        type=int,
        default=GIORNI_STANTIA + 2,
        help=f"giorni da retrodatare con --invecchia (default {GIORNI_STANTIA + 2})",
    )
    args = parser.parse_args()

    if args.sonda:
        record = aggiorna_scansione(args.sonda)
        if record is None:
            print(f"comune sconosciuto: {args.sonda}")
            raise SystemExit(1)
        percento = record.aderenza.percento if record.aderenza else None
        print(f"scansionato {args.sonda}: aderenza={percento}")
        return

    record = carica_scansione(args.invecchia)
    if record is None:
        print(f"nessun record per {args.invecchia}: sondalo prima con --sonda")
        raise SystemExit(1)
    vecchio = datetime.now(timezone.utc) - timedelta(days=args.giorni)
    record.scansionato_il = vecchio.isoformat()
    _in_cache(record)
    print(f"{args.invecchia} invecchiato di {args.giorni} giorni: scansionato_il={record.scansionato_il}")


if __name__ == "__main__":
    _cli()
