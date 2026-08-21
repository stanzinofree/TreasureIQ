"""Cosa c'è dentro i dati, e come un comune passa da letto a coperto.

Due comandi, che insieme rispondono alla domanda che altrimenti spingerebbe
verso un database: *cosa abbiamo, e cosa dovremmo prendere dopo.*

`stato` conta le due popolazioni separatamente — i comuni curati, che stanno
in git, e quelli letti dal vivo, che stanno in `data-live/` e non ci entrano
mai da soli (D-33). Sommarli darebbe un numero più grande e falso.

`promuovi` non promuove fatti. Prepara la pratica: dal comune letto dal vivo
tira fuori la voce `enti.json` che un umano deve leggere, correggere e
committare. La verifica resta strutturale (`source_typed` più il quote gate) e
la decisione resta umana — questo comando toglie solo la trascrizione a mano
(D-34). Non scrive niente dentro `data/`: stampa, e basta.
"""

from __future__ import annotations

import argparse
import json
import sys

from treasureiq.integration import DATA_DIR, load_enti
from treasureiq.municipality_registry import FrameIOError, FrameInvalidError, get_registry
from treasureiq.sonda_live import LIVE_DIR, OrariLive, risolvi_comune


def _voci_live() -> list[OrariLive]:
    cartella = LIVE_DIR / "orari-urp"
    if not cartella.exists():
        return []
    voci = []
    for percorso in sorted(cartella.glob("*.json")):
        try:
            voci.append(OrariLive.model_validate_json(percorso.read_text("utf-8")))
        except Exception:  # noqa: BLE001 — una voce rotta si segnala, non ferma il conto
            print(f"  (voce illeggibile: {percorso.name})", file=sys.stderr)
    return voci


def _stato(_args: argparse.Namespace) -> int:
    enti = load_enti()
    print(f"COMUNI CURATI (data/, in git) : {len(enti)}")
    for ente in sorted(enti.values(), key=lambda e: e.ente):
        print(f"    {ente.codice_istat}  {ente.ente:32} {ente.access_mode.value}")

    frame = DATA_DIR / "comuni-istat.json"
    try:
        registry = get_registry(frame)
    except FrameIOError:
        # The report is intentionally best-effort: absence of the national
        # frame was historically represented by omitting this section.
        registry = None
    except FrameInvalidError as exc:
        print(
            "  (frame nazionale invalido: "
            + ", ".join(sorted({issue.code for issue in exc.report.blocking}))
            + ")",
            file=sys.stderr,
        )
        registry = None
    if registry is not None:
        comuni = registry.frame.tutti()
        con_sito = sum(1 for comune in comuni if comune.sito)
        print(f"\nFRAME NAZIONALE               : {len(comuni)} comuni, {con_sito} con sito")

    t0 = DATA_DIR / "censimento-t0.json"
    if t0.exists():
        misura = json.loads(t0.read_text("utf-8"))
        r = misura["risultati"]
        print(f"\nT0 ({misura['misurato_il']})              : {r['misurati']}/{r['campione']} misurati")
        print(f"    elenco uffici via API     : {r['asse_a_api_uffici']['pct']}%"
              f" ±{r['asse_a_api_uffici']['margine']}")
        print(f"    orario URP recuperabile   : {r['asse_b_orari_urp']['pct']}%"
              f" ±{r['asse_b_orari_urp']['margine']}")
        print(f"    in un campo tipizzato     : {r['orari_in_campo_tipizzato']}")

    voci = _voci_live()
    print(f"\nLETTI DAL VIVO (data-live/, mai in git) : {len(voci)}")
    if not voci:
        print("    nessuno — nessun cittadino ha ancora chiesto di un comune scoperto")
        return 0

    con_orari = [v for v in voci if v.ha_orari]
    date = sorted(v.letto_il for v in voci)
    print(f"    con orario leggibile      : {len(con_orari)}")
    print(f"    letti fra il {date[0][:10]} e il {date[-1][:10]}")
    print("\n    Questi sono i comuni che qualcuno ha chiesto e che non copriamo.")
    print("    È da qui che si decide chi onboardare, non da un elenco a tavolino:")
    for v in sorted(voci, key=lambda v: v.nome):
        marchio = "orario leggibile" if v.ha_orari else v.recuperabilita.value
        print(f"      {v.codice_istat}  {v.nome:28} {marchio}")
    return 0


def _promuovi(args: argparse.Namespace) -> int:
    comune = risolvi_comune(args.comune)
    if comune is None:
        print(f"nessun comune italiano riconosciuto in {args.comune!r}", file=sys.stderr)
        return 1

    percorso = LIVE_DIR / "orari-urp" / f"{comune.codice_istat}.json"
    if not percorso.exists():
        print(
            f"{comune.nome} non è mai stato letto dal vivo. Prima:\n"
            f"    make scalda-cache COMUNI='{comune.nome}'",
            file=sys.stderr,
        )
        return 1
    letto = OrariLive.model_validate_json(percorso.read_text("utf-8"))

    if comune.codice_istat in load_enti():
        print(f"{comune.nome} è già fra i comuni curati.", file=sys.stderr)
        return 1

    # Il modo di accesso è quello MISURATO, non uno scelto a mano: la scala
    # D-21 è un fatto sul portale, e questo comando non deve poterlo
    # addolcire mentre trascrive.
    modo = "M2_prosa_api" if letto.indirizzabilita.value == "api_uffici" else "M4_connettore"
    voce = {
        "ente": f"Comune di {comune.nome}",
        "codice_istat": comune.codice_istat,
        "access_mode": modo,
        "probe": {
            "method": "sonda live TreasureIQ: indice dei tipi di contenuto del portale "
                      "e, se esposto, pagina dell'ufficio",
            "dated": letto.letto_il[:10],
            "dettagli": {
                "portale": letto.sito or "ignoto",
                "ufficio letto": letto.ufficio or "nessun URP riconoscibile",
                "orario": letto.citazione or "non pubblicato in forma leggibile",
            },
        },
    }

    print(json.dumps(voce, ensure_ascii=False, indent=2))
    print(
        "\n--- da qui in poi decidi tu ---\n"
        "1. controlla la voce qui sopra sul portale del comune;\n"
        "2. aggiungila a mano a data/enti.json;\n"
        "3. lancia l'ingestione per questo comune e guarda cosa recupera;\n"
        "4. committa il diff.\n"
        "Nulla è stato scritto: promuovere un comune è una decisione, non un comando.",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m treasureiq.dati_cli",
        description="Stato dei dati e preparazione della copertura di un nuovo comune.",
    )
    sotto = parser.add_subparsers(dest="comando", required=True)

    sotto.add_parser("stato", help="Cosa c'è nei dati curati e in quelli letti dal vivo.")

    p = sotto.add_parser("promuovi", help="Prepara la voce enti.json di un comune già letto.")
    p.add_argument("comune", help="Nome del comune, es. 'Arquata Scrivia'.")

    args = parser.parse_args(argv)
    return _stato(args) if args.comando == "stato" else _promuovi(args)


if __name__ == "__main__":
    raise SystemExit(main())
