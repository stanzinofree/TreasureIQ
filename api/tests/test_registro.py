"""Test di `registro.py` (ciclo 14, brief B2): niente rete reale — store
isolato su `tmp_path` e trasporto HTTP finto per logo/SSRF, stesso stampo
di `test_connettore_contratto.py`."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import treasureiq.registro as registro_mod
from treasureiq.api import app
from treasureiq.connettore import (
    AmministrazioneTrasparente,
    EndpointiConnettore,
    EsitoConnettore,
    UfficioConnettore,
)
from treasureiq.ingest import host_guard as host_guard_mod
from treasureiq.ingest.piattaforma import Piattaforma
from treasureiq.registro import (
    MAX_LOGO_BYTES,
    RecordRegistro,
    _da_store,
    _estrai_logo_header,
    _host_su_cdn_vendor,
    _in_store,
    _url_logo_cdn,
    _scarica_logo,
    registra_scansione,
)
from treasureiq.sonda_live import ComuneNoto

ISTAT = "048052"
HOST = "comunefiv.it"

client = TestClient(app)

_FIXTURES = Path(__file__).parent / "fixtures"


def _leggi_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text("utf-8")


def _comune() -> ComuneNoto:
    return ComuneNoto(
        codice_istat=ISTAT, nome="Figline", provincia="FI", regione="Toscana", sito="www.comunefiv.it"
    )


def _ufficio(nome: str, *, telefoni: list[str] | None = None) -> UfficioConnettore:
    return UfficioConnettore(
        nome=nome,
        url=f"https://www.comunefiv.it/{nome.lower()}",
        telefoni=telefoni or [],
        source_typed=bool(telefoni),
        letto_il=datetime.now(timezone.utc).isoformat(),
    )


def _esito(
    *,
    uffici: list[UfficioConnettore] | None = None,
    at_url: str | None = None,
    piattaforma_at: str | None = None,
    endpoints: EndpointiConnettore | None = None,
) -> EsitoConnettore:
    return EsitoConnettore(
        codice_istat=ISTAT,
        piattaforma=Piattaforma.MUNICIPIUM.value,
        letto_il=datetime.now(timezone.utc).isoformat(),
        uffici=uffici or [],
        amministrazione_trasparente=(
            AmministrazioneTrasparente(indice_url=at_url, piattaforma_at=piattaforma_at)
            if at_url or piattaforma_at
            else None
        ),
        endpoints=endpoints,
    )


# --- Fingerprint / change-detection (D-03/R-04) ------------------------


def test_prima_scansione_niente_da_confrontare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(registro_mod, "_logo_one_shot", lambda comune: (None, None))

    record = registra_scansione(_comune(), _esito(uffici=[_ufficio("URP")]))
    assert record is not None
    assert record.prima_scansione is True
    assert record.cambiato is None
    assert len(record.scansioni) == 1


def test_seconda_scansione_dato_stabile_cambiato_rilevato(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(registro_mod, "_logo_one_shot", lambda comune: (None, None))

    registra_scansione(_comune(), _esito(uffici=[_ufficio("URP")]))
    record = registra_scansione(_comune(), _esito(uffici=[_ufficio("URP"), _ufficio("Anagrafe")]))

    assert record is not None
    assert record.prima_scansione is False
    assert record.cambiato is not None
    assert "servizi" in record.cambiato.campi
    assert len(record.scansioni) == 2


def test_seconda_scansione_dato_identico_nessun_cambiamento(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(registro_mod, "_logo_one_shot", lambda comune: (None, None))

    registra_scansione(_comune(), _esito(uffici=[_ufficio("URP", telefoni=["055123456"])]))
    record = registra_scansione(_comune(), _esito(uffici=[_ufficio("URP", telefoni=["055123456"])]))

    assert record is not None
    assert record.prima_scansione is False
    assert record.cambiato is None


def test_scansione_at_scoperta_registra_cambiato_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B5 (ciclo16): comparsa di una pagina AT prima assente è un cambio
    tracciato ("at" in `cambiato.campi`), stesso trattamento del logo — non
    un fingerprint, un valore scalare confrontato in `_campi_cambiati`."""
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(registro_mod, "_logo_one_shot", lambda comune: (None, None))

    registra_scansione(_comune(), _esito(uffici=[_ufficio("URP")]))
    record = registra_scansione(
        _comune(),
        _esito(
            uffici=[_ufficio("URP")],
            at_url="https://www.comunefiv.it/at",
            piattaforma_at=Piattaforma.JCITYGOV.value,
        ),
    )

    assert record is not None
    assert record.cambiato is not None
    assert "at" in record.cambiato.campi
    assert record.piattaforma_at == Piattaforma.JCITYGOV.value
    assert record.endpoints.at == "https://www.comunefiv.it/at"


def test_scansione_senza_at_eredita_at_precedente(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Una scansione che oggi non trova/classifica l'AT (pagina
    temporaneamente muta) NON deve far dimenticare un AT trovato ieri —
    onesto sull'assenza (D-16): il registro ripiega sull'ultimo valore
    noto in storico invece di azzerarlo."""
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(registro_mod, "_logo_one_shot", lambda comune: (None, None))

    registra_scansione(
        _comune(),
        _esito(
            uffici=[_ufficio("URP")],
            at_url="https://www.comunefiv.it/at",
            piattaforma_at=Piattaforma.JCITYGOV.value,
        ),
    )
    record = registra_scansione(_comune(), _esito(uffici=[_ufficio("URP")]))

    assert record is not None
    assert record.piattaforma_at == Piattaforma.JCITYGOV.value
    assert record.endpoints.at == "https://www.comunefiv.it/at"
    # nessuna nuova "scoperta AT": la coppia (url, piattaforma) è la stessa
    # di ieri, `_campi_cambiati` non deve segnalare "at" come cambiato.
    assert record.cambiato is None


# --- Endpoints sezione (B9, ciclo16): mappa/servizi/amministrazione -------


def test_registra_scansione_popola_endpoints_da_esito(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(registro_mod, "_logo_one_shot", lambda comune: (None, None))

    record = registra_scansione(
        _comune(),
        _esito(
            uffici=[_ufficio("URP")],
            endpoints=EndpointiConnettore(
                mappa="https://www.comunefiv.it/it/sitemap",
                servizi="https://www.comunefiv.it/it/menu/servizi",
                amministrazione="https://www.comunefiv.it/it/menu/amministrazione",
            ),
        ),
    )

    assert record is not None
    assert record.endpoints.mappa == "https://www.comunefiv.it/it/sitemap"
    assert record.endpoints.servizi == "https://www.comunefiv.it/it/menu/servizi"
    assert record.endpoints.amministrazione == "https://www.comunefiv.it/it/menu/amministrazione"


def test_registra_scansione_esito_senza_endpoints_null_no_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(registro_mod, "_logo_one_shot", lambda comune: (None, None))

    record = registra_scansione(_comune(), _esito(uffici=[_ufficio("URP")]))

    assert record is not None
    assert record.endpoints.mappa is None
    assert record.endpoints.servizi is None
    assert record.endpoints.amministrazione is None


def test_scansione_senza_endpoints_eredita_endpoints_precedenti(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Stesso trattamento onesto dell'AT (`test_scansione_senza_at_eredita_
    at_precedente`): uno sweep flaky che oggi non legge la sitemap non deve
    far dimenticare mappa/servizi/amministrazione letti ieri."""
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(registro_mod, "_logo_one_shot", lambda comune: (None, None))

    registra_scansione(
        _comune(),
        _esito(
            uffici=[_ufficio("URP")],
            endpoints=EndpointiConnettore(
                mappa="https://www.comunefiv.it/it/sitemap",
                servizi="https://www.comunefiv.it/it/menu/servizi",
                amministrazione="https://www.comunefiv.it/it/menu/amministrazione",
            ),
        ),
    )
    record = registra_scansione(_comune(), _esito(uffici=[_ufficio("URP")]))

    assert record is not None
    assert record.endpoints.mappa == "https://www.comunefiv.it/it/sitemap"
    assert record.endpoints.servizi == "https://www.comunefiv.it/it/menu/servizi"
    assert record.endpoints.amministrazione == "https://www.comunefiv.it/it/menu/amministrazione"
    # URL stabili di sezione: mai in `_campi_cambiati`, niente falso diff.
    assert record.cambiato is None


# --- Logo one-shot: size-cap streaming-con-abort + SSRF post-redirect --


class _StreamFinto:
    def __init__(self, status_code: int, url: str, headers: dict[str, str], chunks: list[bytes]) -> None:
        self.status_code = status_code
        self.url = url
        self.headers = headers
        self._chunks = chunks

    def __enter__(self) -> "_StreamFinto":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def iter_bytes(self):
        yield from self._chunks


class _ClientFinto:
    def __init__(self, stream_resp: _StreamFinto, **_kwargs: object) -> None:
        self._stream_resp = stream_resp

    def __enter__(self) -> "_ClientFinto":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def stream(self, method: str, url: str) -> _StreamFinto:
        return self._stream_resp


def test_logo_oltre_size_cap_ritorna_null_non_blocca(monkeypatch: pytest.MonkeyPatch) -> None:
    """Due chunk che sommati superano MAX_LOGO_BYTES: l'abort è
    streaming, il chiamante riceve (None, None), mai un'eccezione. La
    guardia SSRF vive ora in `host_guard.py` (B5, ciclo16): si patcha lì,
    e si aggira il DNS-check (host di test sintetico, non risolvibile)."""
    chunk = b"x" * (MAX_LOGO_BYTES // 2 + 1000)
    stream = _StreamFinto(200, "https://www.comunefiv.it/logo.png", {"content-type": "image/png"}, [chunk, chunk])
    monkeypatch.setattr(host_guard_mod, "host_risolve_a_ip_sicuro", lambda hostname: True)
    monkeypatch.setattr(
        host_guard_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs)
    )

    data_uri, logo_hash = _scarica_logo("https://www.comunefiv.it/logo.png", HOST)
    assert data_uri is None
    assert logo_hash is None


def test_logo_ssrf_redirect_fuori_host_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un redirect (302) fuori dal dominio del comune: scartato PER-HOP
    dalla guardia condivisa (`host_guard.fetch_guardato`, B5, ciclo16) —
    non solo dopo l'ultimo redirect come nella guardia precedente."""
    stream = _StreamFinto(
        302, "https://www.comunefiv.it/logo.png",
        {"location": "https://evil.example.com/logo.png"}, [],
    )
    monkeypatch.setattr(host_guard_mod, "host_risolve_a_ip_sicuro", lambda hostname: True)
    monkeypatch.setattr(
        host_guard_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs)
    )

    data_uri, logo_hash = _scarica_logo("https://www.comunefiv.it/logo.png", HOST)
    assert data_uri is None
    assert logo_hash is None


def test_logo_ok_sotto_cap_stesso_host(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _StreamFinto(
        200, "https://www.comunefiv.it/logo.png", {"content-type": "image/png"}, [b"dati-logo"]
    )
    monkeypatch.setattr(host_guard_mod, "host_risolve_a_ip_sicuro", lambda hostname: True)
    monkeypatch.setattr(
        host_guard_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs)
    )

    data_uri, logo_hash = _scarica_logo("https://www.comunefiv.it/logo.png", HOST)
    assert data_uri is not None
    assert data_uri.startswith("data:image/png;base64,")
    assert logo_hash is not None


def test_logo_cdn_vendor_municipium_scaricato(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eccezione stretta a D-S8: lo stemma Municipium sta su un CDN vendor noto
    (`municipiumapp.it`), host DIVERSO dal dominio del comune. Prima veniva
    scartato dal host-check; ora l'host atteso si pinna al CDN e lo stemma è
    scaricabile — la guardia SSRF resta intera, solo l'ancoraggio cambia."""
    cdn = "https://busto-arsizio-api.municipiumapp.it/media/stemma.jpg"
    stream = _StreamFinto(200, cdn, {"content-type": "image/jpeg"}, [b"dati-stemma"])
    monkeypatch.setattr(host_guard_mod, "host_risolve_a_ip_sicuro", lambda hostname: True)
    monkeypatch.setattr(
        host_guard_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs)
    )

    # HOST (comune) resta diverso dall'host del CDN: senza l'eccezione sarebbe None.
    data_uri, logo_hash = _scarica_logo(cdn, HOST)
    assert data_uri is not None
    assert data_uri.startswith("data:image/jpeg;base64,")
    assert logo_hash is not None


def test_logo_cdn_vendor_redirect_fuori_cdn_rifiutato(monkeypatch: pytest.MonkeyPatch) -> None:
    """L'eccezione CDN non indebolisce la guardia: un redirect DALL'host CDN
    verso un host non in allowlist resta scartato per-hop (host_atteso pinnato
    al CDN, non aperto a qualunque destinazione)."""
    cdn = "https://busto-arsizio-api.municipiumapp.it/media/stemma.jpg"
    stream = _StreamFinto(
        302, cdn, {"location": "https://evil.example.com/stemma.jpg"}, [],
    )
    monkeypatch.setattr(host_guard_mod, "host_risolve_a_ip_sicuro", lambda hostname: True)
    monkeypatch.setattr(
        host_guard_mod.httpx, "Client", lambda **kwargs: _ClientFinto(stream, **kwargs)
    )

    data_uri, logo_hash = _scarica_logo(cdn, HOST)
    assert data_uri is None
    assert logo_hash is None


def test_url_logo_cdn_riscrive_render_municipium_a_taglia_piccola() -> None:
    """Il render a taglia piena (~300KB octet-stream, sfonda il cap) viene
    riscritto verso il resize cloud del vendor a taglia piccola: un solo host in
    allowlist, nessun redirect, immagine reale sotto cap."""
    piena = "https://busto-arsizio-api.municipiumapp.it/s3/720x960/s3/1013/sito/stemma.jpg"
    assert _url_logo_cdn(piena) == (
        "https://cloud.municipiumapp.it/resize?key=s3/256x256/s3/1013/sito/stemma.jpg"
    )


def test_url_logo_cdn_lascia_invariato_un_url_non_render() -> None:
    """Un url che non è un render Municipium noto torna invariato (verrà
    scaricato com'è, sotto la stessa guardia)."""
    normale = "https://www.comunefiv.it/logo.png"
    assert _url_logo_cdn(normale) == normale


def test_host_su_cdn_vendor_confine_punto() -> None:
    """Match a confine-punto: l'host esatto e i suoi sottodomini passano, un
    dominio omografo (`evilmunicipiumapp.it`) NO."""
    assert _host_su_cdn_vendor("municipiumapp.it")
    assert _host_su_cdn_vendor("busto-arsizio-api.municipiumapp.it")
    assert not _host_su_cdn_vendor("evilmunicipiumapp.it")
    assert not _host_su_cdn_vendor("municipiumapp.it.evil.com")
    assert not _host_su_cdn_vendor("www.comunefiv.it")


def test_estrai_logo_header_marino_reale() -> None:
    """`header.html` reale di Marino: il logo NON è nella home, sta nel
    frammento statico (`<img alt="Stemma Comune">`, D-04 — asset reale del
    comune, non fabbricato)."""
    pagina = _leggi_fixture("egov_header_marino.html")
    logo_url = _estrai_logo_header(
        pagina, "https://www.comune.marino.rm.it/header.html", "comune.marino.rm.it"
    )
    assert logo_url == "https://www.comune.marino.rm.it/immagini/logo-comune.jpg"


def test_estrai_logo_header_scarta_src_fuori_host() -> None:
    """Un `src` fuori dal dominio del comune non diventa mai il logo —
    stessa guardia same-host del resto del file (SSRF)."""
    pagina = '<img class="me-3 icon" alt="Stemma Comune" src="https://evil.example.com/x.jpg">'
    logo_url = _estrai_logo_header(
        pagina, "https://www.comune.marino.rm.it/header.html", "comune.marino.rm.it"
    )
    assert logo_url is None


def test_estrai_logo_header_assente_ritorna_none() -> None:
    """`header.html` senza il markup atteso (es. Municipium, dove spesso
    404): `None` onesto, il chiamante ripiega su og:image/favicon."""
    assert _estrai_logo_header("<html><body>niente qui</body></html>", "https://x/", "x") is None


def test_logo_fallito_non_blocca_in_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Logo assente/fallito → `logo_b64: null`, ma il record si scrive
    comunque (D-11: il fallimento logo non blocca la persistenza)."""
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(registro_mod, "_logo_one_shot", lambda comune: (None, None))

    record = registra_scansione(_comune(), _esito(uffici=[_ufficio("URP")]))

    assert record is not None
    assert record.logo_b64 is None
    assert _da_store(ISTAT) is not None


# --- Store round-trip (analogo connettore._in_store/_da_store) --------


def test_store_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    assert _da_store(ISTAT) is None

    record = RecordRegistro(
        codice_istat=ISTAT,
        nome="Figline",
        dominio="www.comunefiv.it",
        piattaforma=Piattaforma.MUNICIPIUM.value,
        endpoints=registro_mod.EndpointsRegistro(),
        ultima_scansione=datetime.now(timezone.utc).isoformat(),
        prima_scansione=True,
        cambiato=None,
    )
    _in_store(record)
    riletto = _da_store(ISTAT)
    assert riletto is not None
    assert riletto.codice_istat == ISTAT
    assert riletto.nome == "Figline"


def test_file_corrotto_ritorna_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    percorso = tmp_path / "registro" / f"{ISTAT}.json"
    percorso.parent.mkdir(parents=True)
    percorso.write_text("{non e' json valido", "utf-8")
    assert _da_store(ISTAT) is None


# --- Route GET /api/registro/{istat} (CONTRATTO-O2) --------------------


def test_route_404_comune_assente(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    risposta = client.get("/api/registro/999999")
    assert risposta.status_code == 404


def test_route_serve_dal_disco_forma_contratto_o2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(registro_mod, "LIVE_DIR", tmp_path)
    monkeypatch.setattr(registro_mod, "_logo_one_shot", lambda comune: (None, None))

    registra_scansione(
        _comune(),
        _esito(
            uffici=[_ufficio("URP")],
            at_url="https://www.comunefiv.it/at",
            piattaforma_at=Piattaforma.WP_AMM_TRASP.value,
        ),
    )

    risposta = client.get(f"/api/registro/{ISTAT}")
    assert risposta.status_code == 200
    corpo = risposta.json()
    assert set(corpo.keys()) == {
        "codice_istat",
        "nome",
        "logo_b64",
        "dominio",
        "piattaforma",
        "piattaforma_at",
        "endpoints",
        "ultima_scansione",
        "uffici_snapshot",
        "prima_scansione",
        "cambiato",
        "recapiti",
    }
    assert corpo["prima_scansione"] is True
    assert corpo["cambiato"] is None
    # `recapiti` innestato a read-time dall'indice IPA: presente (fonte
    # IndicePA) o None se l'ente non è nell'indice — mai un guscio a metà.
    recapiti = corpo["recapiti"]
    if recapiti is not None:
        assert set(recapiti.keys()) == {"pec", "indirizzo", "codice_ipa", "fonte"}
        assert recapiti["fonte"] == "IndicePA"
        assert recapiti["pec"] or recapiti["indirizzo"]
    assert corpo["endpoints"]["at"] == "https://www.comunefiv.it/at"
    # B5 (ciclo16): `piattaforma_at` generale, da QUALSIASI connettore che la
    # classifichi — non solo Municipium.
    assert corpo["piattaforma_at"] == Piattaforma.WP_AMM_TRASP.value
    assert corpo["uffici_snapshot"] == [{"nome": "URP", "url": "https://www.comunefiv.it/urp"}]


def test_recapiti_ipa_join_e_degrado():
    """Il join IPA (`_recapiti_ipa`) risolve un comune presente nell'indice a
    PEC+indirizzo con fonte IndicePA, e degrada a `None` per un ISTAT assente —
    mai un recapito vuoto spacciato per dato."""
    from treasureiq.registro import _recapiti_ipa

    marino = _recapiti_ipa("058057")  # Marino (RM), presente in data/ipa-recapiti.json
    assert marino is not None
    assert marino.fonte == "IndicePA"
    assert marino.pec and "@" in marino.pec
    assert marino.indirizzo
    # Codice Univoco IPA innestato dallo stesso join, dall'elenco nazionale.
    assert marino.codice_ipa == "C_E958"

    assert _recapiti_ipa("000000") is None  # ISTAT inesistente


def test_codice_ipa_regge_da_solo(monkeypatch: pytest.MonkeyPatch):
    """Il Codice Univoco viene dall'elenco nazionale, non da `ipa-recapiti.json`:
    un comune assente dai recapiti ma presente nell'elenco espone comunque il
    codice — non deve degradare a `None` solo perché manca PEC/indirizzo."""
    from treasureiq import registro as registro_mod
    from treasureiq.registro import _recapiti_ipa

    monkeypatch.setattr(registro_mod, "_carica_ipa_recapiti", lambda: {})
    monkeypatch.setattr(registro_mod, "_carica_comuni_ipa", lambda: {"099999": "C_TEST"})

    solo_codice = _recapiti_ipa("099999")
    assert solo_codice is not None
    assert solo_codice.pec is None and solo_codice.indirizzo is None
    assert solo_codice.codice_ipa == "C_TEST"

    # Nulla su nessuno dei due indici: nessun record inventato.
    assert _recapiti_ipa("088888") is None
