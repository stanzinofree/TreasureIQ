"""Sweep di MISURA (Fase 1): tassonomia esiti, zero-write, resume.

Nessuna rete: il connettore è uno stub che espone solo ``diagnostica`` con
conteggi predefiniti. La prova di «zero scritture» è strutturale — lo stub
esplode se qualcuno chiama ``retrieve`` (il solo metodo che persisterebbe via
resolver) — più il fatto che l'unico output su disco è la cartella scratch.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

from treasureiq.catalog import measurement_sweep as ms
from treasureiq.catalog.service_connectors.connettore_base import DiagnosticaConnettore
from treasureiq.catalog.service_contracts import ServiceKey


class _MappaFinta:
    def __init__(self, codice_istat: str) -> None:
        self.codice_istat = codice_istat


class _RegistroFinto:
    def __init__(self, piattaforma: str) -> None:
        self.piattaforma = piattaforma


class _ConnettoreStub:
    """Espone ``diagnostica`` (+ ``entry_raggiungibile``). ``retrieve`` è una
    trappola: se lo sweep di misura lo chiamasse, persisterebbe → il test deve
    fallire subito.

    ``diags`` può essere una sequenza per simulare il retry: ogni chiamata a
    ``diagnostica`` consuma il prossimo (l'ultimo si ripete). ``entry`` è ciò che
    ``entry_raggiungibile`` ritorna (True/False/None)."""

    def __init__(self, diag, *, entry: bool | None = True) -> None:
        self._diags = list(diag) if isinstance(diag, list) else [diag]
        self._i = 0
        self._entry = entry
        self.chiamate_diag = 0
        self.chiamate_entry = 0

    def diagnostica(self, request, *, mappa) -> DiagnosticaConnettore:
        self.chiamate_diag += 1
        d = self._diags[min(self._i, len(self._diags) - 1)]
        self._i += 1
        return d

    def entry_raggiungibile(self, request, *, mappa) -> bool | None:
        self.chiamate_entry += 1
        return self._entry

    # Usati da ``_entry_host`` per la memoria di raggiungibilità (nessuna rete).
    def _service_key(self, request):
        return ServiceKey.TRIBUTI_IMU

    def _discovery_target(self, mappa, service_key):
        from types import SimpleNamespace
        return SimpleNamespace(
            official_host="host.example",
            entry_url="https://host.example/servizi",
            term="t",
        )

    def retrieve(self, *a, **k):  # pragma: no cover - trappola
        raise AssertionError("retrieve() chiamato: lo sweep di misura non deve risolvere/scrivere")


class _RegistryStub:
    def __init__(self, connettore) -> None:
        self._connettore = connettore

    def resolve(self, *, request, platform_id):
        return self._connettore


def _stubba_comune(monkeypatch, *, mappa_presente=True, piattaforma="wordpress_agid"):
    monkeypatch.setattr(
        ms, "_mappa_da_cache",
        lambda istat: _MappaFinta(istat) if mappa_presente else None,
    )
    # Sul cache-miss `_risolvi_mappa_live` sonderebbe live: nei test il comune è
    # ignoto al registro → nessuna rete, esito comune_non_risolto deterministico.
    monkeypatch.setattr(ms, "comune_per_codice", lambda istat: None)
    monkeypatch.setattr(
        ms, "leggi_registro",
        lambda istat: _RegistroFinto(piattaforma),
    )


_ESEC = None  # gli stub non raggiungono mai la sonda live → esecutore inutilizzato


COMUNE = ms.ComuneCampione("001001", "wordpress_agid", at_presente=True)


# --------------------------------------------------------------------------- #
# Tassonomia: ogni bucket richiesto dallo spec
# --------------------------------------------------------------------------- #
def test_fulfilled_un_confermato(monkeypatch):
    _stubba_comune(monkeypatch)
    reg = _RegistryStub(_ConnettoreStub(DiagnosticaConnettore(True, True, 3, 2, 1)))
    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC)
    assert m.esito == ms.ESITO_FULFILLED
    assert m.confermati == 1
    assert m.recognizer_ok is True


def test_ambiguita_due_confermati(monkeypatch):
    _stubba_comune(monkeypatch)
    reg = _RegistryStub(_ConnettoreStub(DiagnosticaConnettore(True, True, 5, 3, 2)))
    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC)
    assert m.esito == ms.ESITO_AMBIGUITA


def test_fonte_assente_zero_confermati(monkeypatch):
    _stubba_comune(monkeypatch)
    reg = _RegistryStub(_ConnettoreStub(DiagnosticaConnettore(True, True, 4, 0, 0)))
    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC)
    assert m.esito == ms.ESITO_FONTE_ASSENTE


def test_assenza_reale_entry_ok_zero_grezzi(monkeypatch):
    # 0 grezzi ma entry RAGGIUNGIBILE = servizio non pubblicato: fonte_assente,
    # nessun retry (niente da recuperare), nota assenza_reale.
    _stubba_comune(monkeypatch)
    stub = _ConnettoreStub(DiagnosticaConnettore(True, True, 0, 0, 0), entry=True)
    reg = _RegistryStub(stub)
    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC,
                         tentativi=2, backoff_s=0)
    assert m.esito == ms.ESITO_FONTE_ASSENTE
    assert m.note == "assenza_reale"
    assert stub.chiamate_diag == 1  # niente retry su assenza reale


def test_endpoint_muto_transient_non_assenza(monkeypatch):
    # 0 grezzi ed entry MUTO su tutti i retry = transient/infra, esito distinto.
    _stubba_comune(monkeypatch)
    stub = _ConnettoreStub(DiagnosticaConnettore(True, True, 0, 0, 0), entry=False)
    reg = _RegistryStub(stub)
    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC,
                         tentativi=2, backoff_s=0)
    assert m.esito == ms.ESITO_ENDPOINT_MUTO
    assert m.note == "endpoint_muto"
    assert stub.chiamate_diag == 3  # 1 iniziale + 2 retry


def test_transient_recuperato_diventa_fulfilled(monkeypatch):
    # 1° colpo 0 grezzi + entry muto → retry; il retry recupera 1 confermato.
    _stubba_comune(monkeypatch)
    stub = _ConnettoreStub(
        [DiagnosticaConnettore(True, True, 0, 0, 0),
         DiagnosticaConnettore(True, True, 3, 2, 1)],
        entry=False,
    )
    reg = _RegistryStub(stub)
    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC,
                         tentativi=2, backoff_s=0)
    assert m.esito == ms.ESITO_FULFILLED
    assert m.note == "transient_recuperato"
    assert m.confermati == 1


def test_host_raggiungibile_memoizzato_no_riprobe(monkeypatch):
    # Un host già noto raggiungibile non si ri-sonda sul 0-grezzi successivo.
    _stubba_comune(monkeypatch)
    stub = _ConnettoreStub(DiagnosticaConnettore(True, True, 0, 0, 0), entry=True)
    reg = _RegistryStub(stub)
    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    memo: dict[str, bool] = {}
    ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC,
                     tentativi=2, backoff_s=0, host_raggiungibili=memo)
    ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC,
                     tentativi=2, backoff_s=0, host_raggiungibili=memo)
    assert stub.chiamate_entry == 1  # 2ª coppia usa la memoria


def test_chiave_non_riconosciuta_probe_fuori_vocabolario(monkeypatch):
    _stubba_comune(monkeypatch)
    reg = _RegistryStub(_ConnettoreStub(DiagnosticaConnettore(True, True, 0, 0, 0)))
    probe = ms.Probe("unk", "prenotare un campo da tennis", None)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC)
    assert m.esito == ms.ESITO_CHIAVE_NON_RICONOSCIUTA
    assert m.recognizer_ok is True  # atteso None, riconosciuto None → coerente
    assert m.note == ""  # non è un miss: era fuori vocabolario di proposito


def test_miss_riconoscimento_annotato_non_forzato(monkeypatch):
    _stubba_comune(monkeypatch)
    reg = _RegistryStub(_ConnettoreStub(DiagnosticaConnettore(True, True, 0, 0, 0)))
    # Un probe che ci aspettiamo riconosciuto ma con testo che il recogniser
    # non marca: l'esito resta chiave_non_riconosciuta, MA annotato come miss.
    probe = ms.Probe("x", "qualcosa di totalmente non civico xyz", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC)
    assert m.esito == ms.ESITO_CHIAVE_NON_RICONOSCIUTA
    assert m.recognizer_ok is False
    assert m.note == "miss_riconoscimento"


def test_comune_non_risolto_senza_mappa(monkeypatch):
    _stubba_comune(monkeypatch, mappa_presente=False)
    reg = _RegistryStub(_ConnettoreStub(DiagnosticaConnettore(True, True, 1, 1, 1)))
    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC)
    assert m.esito == ms.ESITO_COMUNE_NON_RISOLTO


def test_connettore_non_disponibile_registry_vuoto(monkeypatch):
    _stubba_comune(monkeypatch)

    class _Vuoto:
        def resolve(self, *, request, platform_id):
            return None

    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=_Vuoto(), esecutore=_ESEC)
    assert m.esito == ms.ESITO_CONNETTORE_NON_DISPONIBILE


def test_connettore_non_disponibile_target_assente(monkeypatch):
    _stubba_comune(monkeypatch)
    reg = _RegistryStub(_ConnettoreStub(DiagnosticaConnettore(True, False, 0, 0, 0)))
    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC)
    assert m.esito == ms.ESITO_CONNETTORE_NON_DISPONIBILE
    assert m.note == "target_assente"


# --------------------------------------------------------------------------- #
# Tier catalogo/cache (resolver completo) e provenienza
# --------------------------------------------------------------------------- #
class _RegistryTrappola:
    """``resolve`` esplode: il tier live NON deve partire quando il catalogo serve.

    Prova strutturale che un hit di catalogo corto-circuita prima del live: se lo
    sweep interrogasse il registry live, il test fallirebbe subito.
    """

    def resolve(self, *, request, platform_id):  # pragma: no cover - trappola
        raise AssertionError("registry live interrogato nonostante un hit di catalogo")


def _scrivi_catalogo(base, istat, chiave_val, url):
    """Scrive ``{base}/catalog/{istat}.json`` con una ServiceReference valida.

    Stesso schema/costruzione della promozione: il test esercita il vero
    ``service_catalog.carica`` letto dal resolver, non un mock.
    """
    from datetime import datetime, timezone

    from treasureiq.catalog.contracts import Surface
    from treasureiq.catalog.service_contracts import (
        ServiceAccessMode,
        ServiceAccessOption,
        ServiceReference,
    )

    ref = ServiceReference(
        service_id=f"{istat}:comunibootstrapitalia:{chiave_val}",
        title="Servizio di prova",
        source_url=url,
        options=(ServiceAccessOption(
            mode=ServiceAccessMode.INFORMATION, url=url, official=True, source_url=url),),
        discovered_from=Surface.ORDINARY_DATA,
        provider_platform="comunibootstrapitalia",
        discovered_at=datetime.now(timezone.utc),
    )
    cartella = base / "catalog"
    cartella.mkdir(parents=True, exist_ok=True)
    doc = {"municipality_istat": istat, "services": {chiave_val: json.loads(ref.model_dump_json())}}
    (cartella / f"{istat}.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def test_csc_catalogo_standalone_fulfilled_zero_fetch(tmp_path, monkeypatch):
    # CSC: adapter FUORI dal registry, dati nel catalogo flat (ISTAT-keyed). Il
    # tier catalogo lo serve zero-rete; il registry live è una trappola → mai toccato.
    _scrivi_catalogo(tmp_path, "099001", "carta_identita",
                     "https://comune.example/servizio/carta-identita")
    monkeypatch.setenv("TREASUREIQ_DATA_DIR", str(tmp_path))
    _stubba_comune(monkeypatch, piattaforma="comunibootstrapitalia")
    probe = ms.Probe("carta", "carta d'identità", ServiceKey.CARTA_IDENTITA)
    comune = ms.ComuneCampione("099001", "comunibootstrapitalia", at_presente=False)
    m = ms.misura_coppia(comune, probe, registry=_RegistryTrappola(), esecutore=_ESEC)
    assert m.esito == ms.ESITO_FULFILLED
    assert m.provenienza == ms.PROV_CATALOG
    assert m.confermati == 1


def test_catalogo_miss_ripiega_sul_live(tmp_path, monkeypatch):
    # Nessun file di catalogo per questo comune: il tier catalogo manca e la misura
    # ripiega sul tier live (diagnostica), con provenienza `live`.
    monkeypatch.setenv("TREASUREIQ_DATA_DIR", str(tmp_path))  # catalog dir vuota
    _stubba_comune(monkeypatch)
    reg = _RegistryStub(_ConnettoreStub(DiagnosticaConnettore(True, True, 3, 2, 1)))
    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC)
    assert m.esito == ms.ESITO_FULFILLED
    assert m.provenienza == ms.PROV_LIVE


def test_magnolia_registry_via_retrieve_senza_diagnostica(tmp_path, monkeypatch):
    # Magnolia è nel registry ma NON espone `diagnostica`: la misura live lo risolve
    # read-only via `retrieve` diretto (nessun write-back del resolver). Cataloghi
    # vuoti (tmp) → il tier catalogo manca e si arriva al connettore live.
    from types import SimpleNamespace

    from treasureiq.catalog.service_connectors.magnolia_service import (
        MagnoliaServiceConnector,
    )

    monkeypatch.setenv("TREASUREIQ_DATA_DIR", str(tmp_path))
    _stubba_comune(monkeypatch, piattaforma="magnolia")

    def _lettore(istat):
        return SimpleNamespace(
            esito="ok",
            home="https://comune.example",
            servizi=[SimpleNamespace(
                service_key="CARTA_IDENTITA", titolo="Carta d'identità",
                url="/servizio/carta", host="comune.example", categoria="106")],
        )

    conn = MagnoliaServiceConnector(lettore=_lettore)
    assert not hasattr(conn, "diagnostica")  # precondizione del path retrieve
    probe = ms.Probe("carta", "carta d'identità", ServiceKey.CARTA_IDENTITA)
    comune = ms.ComuneCampione("099002", "magnolia", at_presente=False)
    m = ms.misura_coppia(comune, probe, registry=_RegistryStub(conn), esecutore=_ESEC)
    assert m.esito == ms.ESITO_FULFILLED
    assert m.provenienza == ms.PROV_LIVE
    assert m.note == ""  # via_retrieve solo sui non-fulfilled


def test_magnolia_not_supported_e_connettore_non_disponibile(tmp_path, monkeypatch):
    # variant B/URP: il lettore Magnolia non struttura → retrieve NOT_SUPPORTED →
    # connettore_non_disponibile (stesso significato di target_assente).
    from types import SimpleNamespace

    from treasureiq.catalog.service_connectors.magnolia_service import (
        MagnoliaServiceConnector,
    )

    monkeypatch.setenv("TREASUREIQ_DATA_DIR", str(tmp_path))
    _stubba_comune(monkeypatch, piattaforma="magnolia")
    conn = MagnoliaServiceConnector(
        lettore=lambda istat: SimpleNamespace(
            esito="variante_non_strutturata", home="https://comune.example", servizi=[]),
    )
    probe = ms.Probe("carta", "carta d'identità", ServiceKey.CARTA_IDENTITA)
    comune = ms.ComuneCampione("099003", "magnolia", at_presente=False)
    m = ms.misura_coppia(comune, probe, registry=_RegistryStub(conn), esecutore=_ESEC)
    assert m.esito == ms.ESITO_CONNETTORE_NON_DISPONIBILE
    assert m.note == "target_assente"


def _vieta_scrittura_cache(monkeypatch):
    """Rende ``service_cache.salva`` un'esplosione: qualunque write-back fallisce
    il test. Il resolver importa il modulo, quindi il patch lo copre."""
    from treasureiq.catalog import service_cache

    def _boom(*a, **k):  # pragma: no cover - deve restare mai chiamato
        raise AssertionError("scrittura service-cache vietata nella misura")

    monkeypatch.setattr(service_cache, "salva", _boom)


def test_catalog_miss_non_scrive_in_cache(tmp_path, monkeypatch):
    # Catalog miss → ripiego live via diagnostica: nessun write-back in service-cache.
    monkeypatch.setenv("TREASUREIQ_DATA_DIR", str(tmp_path))  # catalog dir vuota
    _vieta_scrittura_cache(monkeypatch)
    _stubba_comune(monkeypatch)
    reg = _RegistryStub(_ConnettoreStub(DiagnosticaConnettore(True, True, 3, 2, 1)))
    probe = ms.Probe("imu", "imu", ServiceKey.TRIBUTI_IMU)
    m = ms.misura_coppia(COMUNE, probe, registry=reg, esecutore=_ESEC)
    assert m.esito == ms.ESITO_FULFILLED
    assert m.provenienza == ms.PROV_LIVE  # salva() non è esploso → zero-write


def test_retrieve_path_read_only_non_scrive_in_cache(tmp_path, monkeypatch):
    # Connettore senza diagnostica misurato via retrieve diretto: il write-back sta
    # nel resolver (mai chiamato qui) → nessuna scrittura in service-cache.
    from types import SimpleNamespace

    from treasureiq.catalog.service_connectors.magnolia_service import (
        MagnoliaServiceConnector,
    )

    monkeypatch.setenv("TREASUREIQ_DATA_DIR", str(tmp_path))
    _vieta_scrittura_cache(monkeypatch)
    _stubba_comune(monkeypatch, piattaforma="magnolia")
    conn = MagnoliaServiceConnector(
        lettore=lambda istat: SimpleNamespace(
            esito="ok", home="https://comune.example",
            servizi=[SimpleNamespace(service_key="CARTA_IDENTITA",
                                     titolo="Carta d'identità", url="/servizio/carta",
                                     host="comune.example", categoria="106")]),
    )
    probe = ms.Probe("carta", "carta d'identità", ServiceKey.CARTA_IDENTITA)
    comune = ms.ComuneCampione("099004", "magnolia", at_presente=False)
    m = ms.misura_coppia(comune, probe, registry=_RegistryStub(conn), esecutore=_ESEC)
    assert m.esito == ms.ESITO_FULFILLED  # salva() non è esploso → zero-write


def test_report_compat_formato_precedente_senza_provenienza(tmp_path):
    # Checkpoint pre-tier (righe SENZA campo `provenienza`): il report non deve
    # rompersi e i fulfilled storici (tutti live) ricadono su provenienza `live`.
    checkpoint = tmp_path / "checkpoint.jsonl"
    vecchie = [
        {"codice_istat": "001", "base_famiglia": "wp", "at_presente": True,
         "probe_id": "imu", "raw": "imu", "atteso": "tributi_imu",
         "riconosciuto": "tributi_imu", "recognizer_ok": True,
         "esito": ms.ESITO_FULFILLED, "grezzi": 3, "filtrati": 2, "confermati": 1,
         "note": ""},  # NESSUN campo provenienza (formato vecchio)
        {"codice_istat": "002", "base_famiglia": "wp", "at_presente": False,
         "probe_id": "tari", "raw": "tari", "atteso": "tributi_tari",
         "riconosciuto": "tributi_tari", "recognizer_ok": True,
         "esito": ms.ESITO_FONTE_ASSENTE, "grezzi": 0, "filtrati": 0,
         "confermati": 0, "note": "assenza_reale"},
    ]
    checkpoint.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in vecchie) + "\n",
        encoding="utf-8",
    )
    report = ms.costruisci_report(checkpoint)
    assert report["esiti_riconoscibili"][ms.ESITO_FULFILLED] == 1
    assert report["fulfilled_per_provenienza"] == {ms.PROV_LIVE: 1}
    # Nessuna KeyError sulle chiavi storiche; lo stampatore regge il report vecchio+nuovo.
    ms._stampa_report(report)


def test_report_fulfilled_per_provenienza(tmp_path):
    # Il report separa i fulfilled per tier (catalog/cache/live).
    checkpoint = tmp_path / "checkpoint.jsonl"
    righe = [
        ms.Misura("099001", "csc", False, "carta", "carta d'identità",
                  "carta_identita", "carta_identita", True, ms.ESITO_FULFILLED,
                  0, 0, 1, provenienza=ms.PROV_CATALOG),
        ms.Misura("001", "wp", True, "imu", "imu", "tributi_imu", "tributi_imu",
                  True, ms.ESITO_FULFILLED, 3, 2, 1, provenienza=ms.PROV_LIVE),
    ]
    for r in righe:
        ms._append_checkpoint(checkpoint, r)
    report = ms.costruisci_report(checkpoint)
    assert report["fulfilled_per_provenienza"] == {ms.PROV_CATALOG: 1, ms.PROV_LIVE: 1}


# --------------------------------------------------------------------------- #
# Checkpoint / resume
# --------------------------------------------------------------------------- #
def test_resume_salta_le_coppie_gia_fatte(tmp_path: Path):
    checkpoint = tmp_path / "checkpoint.jsonl"
    riga = ms.Misura(
        codice_istat="001001", base_famiglia="wp", at_presente=True,
        probe_id="imu", raw="imu", atteso="tributi_imu", riconosciuto="tributi_imu",
        recognizer_ok=True, esito=ms.ESITO_FULFILLED, grezzi=1, filtrati=1, confermati=1,
    )
    ms._append_checkpoint(checkpoint, riga)
    fatte = ms._carica_fatte(checkpoint)
    assert ("001001", "imu") in fatte


def test_carica_fatte_ignora_righe_corrotte(tmp_path: Path):
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text(
        '{"codice_istat": "001", "probe_id": "imu"}\n'
        "riga-non-json\n"
        '{"manca": "chiavi"}\n',
        encoding="utf-8",
    )
    fatte = ms._carica_fatte(checkpoint)
    assert fatte == {("001", "imu")}


def test_report_aggrega_per_famiglia_e_flag(tmp_path: Path):
    checkpoint = tmp_path / "checkpoint.jsonl"
    righe = [
        ms.Misura("001", "wp", True, "imu", "imu", "tributi_imu", "tributi_imu",
                  True, ms.ESITO_FULFILLED, 1, 1, 1),
        ms.Misura("002", "comweb", False, "imu", "imu", "tributi_imu", "tributi_imu",
                  True, ms.ESITO_FONTE_ASSENTE, 2, 0, 0),
        ms.Misura("003", "wp", True, "x", "testo", "tributi_imu", None,
                  False, ms.ESITO_CHIAVE_NON_RICONOSCIUTA, 0, 0, 0, note="miss_riconoscimento"),
    ]
    for r in righe:
        ms._append_checkpoint(checkpoint, r)
    report = ms.costruisci_report(checkpoint)
    assert report["coppie_misurate"] == 3
    assert report["comuni"] == 3
    assert report["esiti_totali"][ms.ESITO_FULFILLED] == 1
    assert report["per_famiglia"]["wp"][ms.ESITO_FULFILLED] == 1
    assert len(report["recognizer_miss"]) == 1


# --------------------------------------------------------------------------- #
# Campionamento deterministico
# --------------------------------------------------------------------------- #
def test_campione_deterministico_e_stratificato(tmp_path: Path, monkeypatch):
    righe = (
        [("00%02d" % i, "wp", i % 2 == 0) for i in range(10)]
        + [("10%02d" % i, "comweb", False) for i in range(3)]
    )
    monkeypatch.setattr(ms, "_snapshot_corrente", lambda db: righe)
    a = ms.campiona(Path("x"), per_famiglia=4, seed=7)
    b = ms.campiona(Path("x"), per_famiglia=4, seed=7)
    assert [c.codice_istat for c in a] == [c.codice_istat for c in b]  # deterministico
    fam = {c.base_famiglia for c in a}
    assert fam == {"wp", "comweb"}
    assert sum(1 for c in a if c.base_famiglia == "wp") == 4  # cap per famiglia
    assert sum(1 for c in a if c.base_famiglia == "comweb") == 3  # meno del cap → tutti


# --------------------------------------------------------------------------- #
# Step 2: budget per dominio configurabile + budget effettivo nel report
# --------------------------------------------------------------------------- #
def test_nuovo_esecutore_budget_configurabile():
    # Default = costante; alzarlo cambia SOLO il tetto per dominio.
    assert ms._nuovo_esecutore()._politica._budget._massimo == ms._MASSIMO_PER_DOMINIO
    assert ms._nuovo_esecutore(budget_dominio=500)._politica._budget._massimo == 500


def test_report_registra_parametri_misura(tmp_path: Path):
    checkpoint = tmp_path / "checkpoint.jsonl"
    ms._append_checkpoint(checkpoint, ms.Misura(
        "001", "wp", True, "imu", "imu", "tributi_imu", "tributi_imu",
        True, ms.ESITO_FULFILLED, 1, 1, 1))
    par = {"budget_dominio": 500, "budget_dominio_default": 50, "classifica_fallite": True}
    report = ms.costruisci_report(checkpoint, parametri=par)
    assert report["parametri_misura"] == par
    # Compat: senza parametri il report li espone come {} (i vecchi non li avevano).
    assert ms.costruisci_report(checkpoint)["parametri_misura"] == {}


# --------------------------------------------------------------------------- #
# Step 2: ProbeFallita separata nelle 4 cause distinte (opt-in, read-only)
# --------------------------------------------------------------------------- #
def test_classifica_portale_fallito_quattro_cause():
    comune = types.SimpleNamespace(sito="http://comune.maddaloni.ce.it")
    # redirect off-host verso il dominio canonico DELLO STESSO comune, 200.
    assert ms._classifica_portale_fallito(
        comune, fetch=lambda b: ("comune.maddaloni.caserta.it", 200)
    ) == ms.NOTA_REDIRECT_URL_OBSOLETO
    # redirect verso dominio NON riconducibile al comune → vero off-host.
    assert ms._classifica_portale_fallito(
        comune, fetch=lambda b: ("sito-estraneo.com", 200)
    ) == ms.NOTA_RISPOSTA_INVALIDA
    # nessuna risposta (timeout/conn/DNS) → infra muta.
    assert ms._classifica_portale_fallito(
        comune, fetch=lambda b: None
    ) == ms.NOTA_ENDPOINT_MUTO_MAPPA
    # home 200 sull'host atteso ma non mappabile → classe storica non-sondabile.
    assert ms._classifica_portale_fallito(
        comune, fetch=lambda b: ("comune.maddaloni.ce.it", 200)
    ) == ms.NOTA_PORTALE_NON_SONDABILE


def test_classificatore_opt_in_non_altera_default(monkeypatch):
    # Sonda che fallisce sempre; il comune esiste e la cache è vuota.
    monkeypatch.setattr(ms, "_mappa_da_cache", lambda istat: None)
    monkeypatch.setattr(
        ms, "comune_per_codice",
        lambda istat: types.SimpleNamespace(sito="http://x.it", codice_istat=istat))

    def _fallisce(comune, *, esecutore):
        raise ms.ProbeFallita("boom")

    monkeypatch.setattr(ms, "_sonda_mappa", _fallisce)

    # Default (classificatore=None): comportamento storico invariato, nessuna rete.
    _, nota = ms._risolvi_mappa_live("001", esecutore=None)
    assert nota == ms.NOTA_PORTALE_NON_SONDABILE
    # Opt-in: la nota viene dal classificatore iniettato (qui uno stub, zero rete).
    _, nota = ms._risolvi_mappa_live(
        "001", esecutore=None,
        classificatore=lambda c: ms.NOTA_REDIRECT_URL_OBSOLETO)
    assert nota == ms.NOTA_REDIRECT_URL_OBSOLETO
