"""Test del lettore servizi Magnolia (variant A) — net-free, su fixture reali.

Nessuna rete: ``fetch`` è iniettato e mappa gli URL sulle fixture catturate dai
comuni veri (Cervo variant A ricco, Moricone thin, Massa Marittima variant B).
Copre le quattro aree richieste: dedup, paginazione (indice completo pageSize=100),
URL/guardia host, gate esattamente-uno sulla variante.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from treasureiq import magnolia as M
from treasureiq.magnolia import (
    EsitoMagnoliaServizi,
    ServizioMagnolia,
    _dedup,
    _estrai_servizi,
    leggi_magnolia_servizi,
    service_key_di,
)

FIXTURES = Path(__file__).parent / "fixtures" / "magnolia"

#: host del comune → prefisso file fixture.
_COMUNE_PER_HOST = {
    "www.comune.cervo.im.it": "cervo",
    "www.comune.moricone.rm.it": "moricone",
    "www.comune.massamarittima.gr.it": "massamarittima",
}

_HOME = {
    "cervo": ("008017", "https://www.comune.cervo.im.it", "Cervo"),
    "moricone": ("058067", "https://www.comune.moricone.rm.it", "Moricone"),
    # Massa Marittima: home dichiarata con suffisso /home (trappola URL nota).
    "massamarittima": ("053015", "https://www.comune.massamarittima.gr.it/home", "Massa Marittima"),
}


def _leggi_fixture(nome: str) -> str | None:
    p = FIXTURES / nome
    if not p.exists():
        return None
    testo = p.read_text(encoding="utf-8")
    return testo if testo.strip() else None


def _fake_fetch_factory(chiamate: list[str] | None = None):
    """Costruisce un fetch che serve le fixture per host+categoria. Zero rete.

    Rispetta la firma di ``fetch_guardato``: ``(url, *, timeout, max_bytes, host_atteso)``
    → ``(meta, body_bytes, final_url)`` o ``None``. ``chiamate`` (se passata)
    registra ogni URL richiesto per gli assert di paginazione.
    """

    def fake(url, *, timeout, max_bytes, host_atteso):
        if chiamate is not None:
            chiamate.append(url)
        sp = urlsplit(url)
        key = _COMUNE_PER_HOST.get((sp.hostname or "").lower())
        if key is None:
            return None
        if ".rest/kibernetes" in url:
            cat = parse_qs(sp.query)["tipo"][0].rsplit("/", 1)[-1]
            body = _leggi_fixture(f"{key}_rest_{cat}.json")
            if body is None:
                return None
            return ("json", body.encode("utf-8"), url)
        if url.endswith("home/servizi.html"):
            body = _leggi_fixture(f"{key}_servizi_html.html")
            if body is None:
                return None
            return ("html", body.encode("utf-8"), url)
        return None

    return fake


def _leggi(key: str, chiamate: list[str] | None = None) -> EsitoMagnoliaServizi:
    istat, home, nome = _HOME[key]
    return leggi_magnolia_servizi(
        istat, home=home, comune=nome, fetch=_fake_fetch_factory(chiamate)
    )


# --------------------------------------------------------------------------- #
# Variant A ricco (Cervo)                                                      #
# --------------------------------------------------------------------------- #
def test_cervo_variant_a_indice_completo_sei_servicekey():
    e = _leggi("cervo")
    assert e.esito == "ok"
    assert e.variante == "strutturata"
    # tutte e sei le ServiceKey note presenti a catalogo
    assert e.service_keys == [
        "ACCESSO_ATTI", "CAMBIO_RESIDENZA", "CARTA_IDENTITA",
        "STATO_CIVILE", "TRIBUTI_IMU", "TRIBUTI_TARI",
    ]
    # totali reali per categoria (dal campo JSON `total`, indice completo)
    assert e.per_categoria == {"106": 17, "109": 5, "113": 11}
    # nessuna nota: TARI presente e nessun link scartato
    assert e.note == ()


def test_cervo_ogni_servizio_ha_url_e_categoria_valida():
    e = _leggi("cervo")
    assert e.servizi, "variant A ricco deve produrre servizi"
    for s in e.servizi:
        assert isinstance(s, ServizioMagnolia)
        assert s.categoria in M.CATEGORIE
        assert s.url, "ogni card canonica porta un href"


# --------------------------------------------------------------------------- #
# Paginazione: indice completo, pageSize=100, una chiamata per categoria       #
# --------------------------------------------------------------------------- #
def test_paginazione_pagesize_100_una_chiamata_per_categoria():
    chiamate: list[str] = []
    e = _leggi("cervo", chiamate)
    rest = [u for u in chiamate if ".rest/kibernetes" in u]
    # esattamente una chiamata REST per categoria richiesta (nessun paging a pagine)
    assert len(rest) == len(M.CATEGORIE)
    for u in rest:
        q = parse_qs(urlsplit(u).query)
        assert q["pageSize"] == ["100"], "indice completo in un colpo"
        assert q["page"] == ["1"]
        assert q["tipo"][0].startswith("/Servizi/")


def test_indice_completo_non_solo_featured():
    # n. servizi estratti (dopo dedup) coerente coi totali dichiarati: nessun
    # troncamento a "in evidenza". Cervo: 17+5+11=33 grezzi, 30 dopo dedup cross-cat.
    e = _leggi("cervo")
    somma_totali = sum(v for v in e.per_categoria.values() if v)
    assert somma_totali == 33
    assert len(e.servizi) == 30  # 3 duplicati cross-categoria rimossi


# --------------------------------------------------------------------------- #
# URL / guardia host                                                           #
# --------------------------------------------------------------------------- #
def test_host_guard_sibling_ammesso_crossdomain_scartato():
    cards = (
        # on-site relativo → ammesso
        '<a data-element="service-link" href="/servizi/anagrafe.html">Anagrafe</a>'
        # sibling SaaS stesso dominio registrabile → ammesso
        '<a data-element="service-link" href="https://servizi.comune.cervo.im.it/imu">IMU</a>'
        # host cross-dominio → scartato
        '<a data-element="service-link" href="https://tracker.evil.com/x">Spia</a>'
    )
    dentro, fuori = _estrai_servizi(cards, "109", "comune.cervo.im.it")
    titoli_dentro = {s.titolo for s in dentro}
    assert titoli_dentro == {"Anagrafe", "IMU"}
    assert [s.titolo for s in fuori] == ["Spia"]


def test_crossdomain_scartato_produce_nota():
    # host guard che scarta almeno un link → nota diagnostica nell'esito.
    def fetch_con_intruso(url, *, timeout, max_bytes, host_atteso):
        sp = urlsplit(url)
        if ".rest/kibernetes" in url and parse_qs(sp.query)["tipo"][0].endswith("106"):
            payload = (
                '{"total":1,"renderedPages":['
                '"<a data-element=\\"service-link\\" href=\\"https://ads.tracker.net/z\\">Carta d Identita</a>"]}'
            )
            return ("json", payload.encode(), url)
        # 109/113 vuoti ma strutturati
        return ("json", b'{"total":0,"renderedPages":[]}', url)

    e = leggi_magnolia_servizi(
        "008017", home="https://www.comune.cervo.im.it", comune="Cervo",
        fetch=fetch_con_intruso,
    )
    assert e.variante == "strutturata"
    assert any("scartati" in n for n in e.note)
    # il link cross-dominio non entra fra i servizi
    assert all("tracker" not in s.host for s in e.servizi)


# --------------------------------------------------------------------------- #
# Dedup                                                                        #
# --------------------------------------------------------------------------- #
def test_dedup_per_url_poi_per_titolo():
    servizi = [
        ServizioMagnolia("IMU", "https://x/imu", "x", "109", "TRIBUTI_IMU"),
        ServizioMagnolia("IMU (dup url)", "https://X/IMU", "x", "106", "TRIBUTI_IMU"),  # stesso url case-insensitive
        ServizioMagnolia("Solo titolo", "", "", "106", None),
        ServizioMagnolia("Solo titolo", "", "", "113", None),  # dup per titolo (url assente)
        ServizioMagnolia("Altro", "https://x/altro", "x", "106", None),
    ]
    out = _dedup(servizi)
    assert [s.titolo for s in out] == ["IMU", "Solo titolo", "Altro"]


def test_dedup_preserva_ordine_prima_occorrenza():
    a = ServizioMagnolia("A", "https://x/1", "x", "106", None)
    b = ServizioMagnolia("B", "https://x/2", "x", "106", None)
    a2 = ServizioMagnolia("A-again", "https://x/1", "x", "109", None)
    assert [s.titolo for s in _dedup([a, b, a2])] == ["A", "B"]


# --------------------------------------------------------------------------- #
# Gate esattamente-uno sulla variante                                          #
# --------------------------------------------------------------------------- #
_VARIANTI_VALIDE = {"strutturata", "non_strutturata", "irraggiungibile"}
_ESITI_VALIDI = {"ok", "vuoto", "variante_non_strutturata", "irraggiungibile"}


@pytest.mark.parametrize("key", ["cervo", "moricone", "massamarittima"])
def test_gate_variante_esattamente_una(key):
    e = _leggi(key)
    # esattamente una variante valida, dal dominio chiuso
    assert e.variante in _VARIANTI_VALIDE
    assert e.esito in _ESITI_VALIDI


def test_gate_coerenza_variante_esito():
    # strutturata ⇒ esito ok/vuoto; non_strutturata ⇒ variante_non_strutturata
    assert _leggi("cervo").esito in {"ok", "vuoto"}
    mm = _leggi("massamarittima")
    assert mm.variante == "non_strutturata"
    assert mm.esito == "variante_non_strutturata"


def test_variante_b_massa_marittima_fallback_urp():
    e = _leggi("massamarittima")
    assert e.variante == "non_strutturata"
    assert e.esito == "variante_non_strutturata"
    assert e.servizi == []
    assert any("variant B" in n or "URP" in n for n in e.note)


def test_endpoint_muto_e_home_morta_da_irraggiungibile():
    # nessuna fixture risponde → REST muto E home morta → irraggiungibile.
    def fetch_muto(url, *, timeout, max_bytes, host_atteso):
        return None

    e = leggi_magnolia_servizi(
        "008017", home="https://www.comune.cervo.im.it", comune="Cervo",
        fetch=fetch_muto,
    )
    assert e.variante == "irraggiungibile"
    assert e.esito == "irraggiungibile"
    assert e.servizi == []


# --------------------------------------------------------------------------- #
# Caso thin (Moricone) + TARI non forzata                                      #
# --------------------------------------------------------------------------- #
def test_moricone_thin_meno_servicekey():
    e = _leggi("moricone")
    assert e.variante == "strutturata"
    assert e.esito == "ok"
    # deployment thin: meno delle sei SK (nessuna TARI a catalogo)
    assert "TRIBUTI_TARI" not in e.service_keys
    assert 0 < len(e.service_keys) < 6


def test_tari_non_forzata_ma_nota_su_assenza():
    e = _leggi("moricone")
    assert "TRIBUTI_TARI" not in e.service_keys
    assert any("TARI" in n for n in e.note)


def test_service_key_di_riconosce_tari_reale_ma_non_indovina():
    # lessico esteso: varianti reali di TARI mappano; titoli neutri no.
    assert service_key_di("Pagamento TARI") == "TRIBUTI_TARI"
    assert service_key_di("Tassa sui rifiuti urbani") == "TRIBUTI_TARI"
    assert service_key_di("Gestione dei rifiuti solidi urbani") == "TRIBUTI_TARI"
    assert service_key_di("Dichiarazione IMU") == "TRIBUTI_IMU"
    assert service_key_di("Prenotazione appuntamento") is None


# --------------------------------------------------------------------------- #
# Registry standard                                                            #
# --------------------------------------------------------------------------- #
def test_registrazione_registry_per_piattaforma():
    from treasureiq.ingest.piattaforma import Piattaforma

    assert Piattaforma.MAGNOLIA.value in M.LETTORE_SERVIZI_PER_PIATTAFORMA
    assert M.LETTORE_SERVIZI_PER_PIATTAFORMA[Piattaforma.MAGNOLIA.value] is leggi_magnolia_servizi


def test_home_ignota_da_irraggiungibile_senza_rete():
    # home=None e istat inesistente: _risolvi_home ritorna vuoto → irraggiungibile,
    # senza toccare la rete (fetch mai chiamato).
    def fetch_esplode(url, **k):  # pragma: no cover
        raise AssertionError("nessun fetch atteso quando la home è ignota")

    e = leggi_magnolia_servizi("000000", home="", comune="Ignoto", fetch=fetch_esplode)
    assert e.esito == "irraggiungibile"
    assert e.variante == "irraggiungibile"
