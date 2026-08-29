"""Sweep di MISURA (Fase 1): tassonomia esiti, zero-write, resume.

Nessuna rete: il connettore è uno stub che espone solo ``diagnostica`` con
conteggi predefiniti. La prova di «zero scritture» è strutturale — lo stub
esplode se qualcuno chiama ``retrieve`` (il solo metodo che persisterebbe via
resolver) — più il fatto che l'unico output su disco è la cartella scratch.
"""

from __future__ import annotations

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
