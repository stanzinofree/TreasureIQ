"""Golden tests for the guarded service fetcher adapter (Ramo 3, Slice 5, §1.1).

Pure, no network: a recording stub stands in for ``EsecutoreFetch``. Pin the
D-S5-6 contract — the adapter routes every fetch through the executor with the
official host as ``host_atteso`` (so host/redirect/SSRF discipline stays entirely
in ``fetch_guardato``, never duplicated here), distinct ``max_bytes`` for REST vs
HTML, UTF-8 decode, and honest misses: a policy refusal (``consentito=False``),
an unreachable resource (``fetched is None``) or malformed JSON all become a miss
with **no autonomous retry**.

Discovery goes through the WP strategy composed onto the common transport
(``.con(_WpDiscovery())``): ``base_url`` is the REST collection endpoint the WP
connector composes, so the neutral fetcher signature never sees ``rest_base``.
"""

from __future__ import annotations

import json

from treasureiq.catalog.fetch_runtime import EsitoFetch
from treasureiq.catalog.service_connectors.esecutore_fetcher import (
    _MAX_BYTES_HTML,
    _MAX_BYTES_REST,
    _TIMEOUT_S,
    EsecutoreServiceFetcher,
    _WpDiscovery,
)

_BASE = "https://www.comune.example.it"
_REST_BASE = "servizi"
#: The REST collection entry the WP connector composes and passes as base_url.
_ENTRY = f"{_BASE}/wp-json/wp/v2/{_REST_BASE}"


class _EsecutoreSpy:
    """Records esegui() calls and returns canned EsitoFetch instances."""

    def __init__(self, *esiti: EsitoFetch) -> None:
        self._esiti = list(esiti)
        self.chiamate: list[dict] = []

    def esegui(self, url, *, timeout=None, max_bytes=None, host_atteso=None, **kw) -> EsitoFetch:
        self.chiamate.append(
            {"url": url, "timeout": timeout, "max_bytes": max_bytes, "host_atteso": host_atteso}
        )
        return self._esiti.pop(0) if self._esiti else EsitoFetch(
            consentito=True, fetched=None, motivo="ok"
        )


def _wp(spy: _EsecutoreSpy):
    """Common transport composed with the WP discovery strategy."""
    return EsecutoreServiceFetcher(spy).con(_WpDiscovery())


def _ok(corpo: bytes) -> EsitoFetch:
    """A permitted fetch returning a 3-tuple (headers, bytes, final_url)."""
    return EsitoFetch(consentito=True, fetched=({}, corpo, "https://x"), motivo="ok")


def _json_lista() -> bytes:
    return json.dumps(
        [{"id": 42, "title": {"rendered": "Carta d'identità"}, "link": f"{_BASE}/servizi/cie"}]
    ).encode("utf-8")


# --- scopri_servizi (WP strategy) -------------------------------------------


def test_scopri_url_params_host_e_maxbytes():
    spy = _EsecutoreSpy(_ok(_json_lista()))
    got = _wp(spy).scopri_servizi(base_url=_ENTRY, term="carta", limit=5)
    assert len(got) == 1 and got[0].native_id == "42"
    assert str(got[0].url) == f"{_BASE}/servizi/cie"
    chiamata = spy.chiamate[0]
    # URL: wp-json REST path (from base_url entry) with baked params
    assert chiamata["url"].startswith(f"{_BASE}/wp-json/wp/v2/{_REST_BASE}?")
    assert "search=carta" in chiamata["url"]
    assert "per_page=5" in chiamata["url"]
    assert "_fields=id" in chiamata["url"]
    # host_atteso = official host WITHOUT www (delegates host/redirect to the guard)
    assert chiamata["host_atteso"] == "comune.example.it"
    assert chiamata["max_bytes"] == _MAX_BYTES_REST
    assert chiamata["timeout"] == _TIMEOUT_S


def test_scopri_rifiuto_politica_e_miss_senza_retry():
    # consentito=False (budget/rate-limit) → miss, and the adapter does NOT retry.
    spy = _EsecutoreSpy(EsitoFetch(consentito=False, fetched=None, motivo="budget_esaurito"))
    got = _wp(spy).scopri_servizi(base_url=_ENTRY, term="carta", limit=5)
    assert got == ()
    assert len(spy.chiamate) == 1  # single call, no autonomous retry


def test_scopri_fetched_none_e_miss():
    spy = _EsecutoreSpy(EsitoFetch(consentito=True, fetched=None, motivo="irraggiungibile"))
    got = _wp(spy).scopri_servizi(base_url=_ENTRY, term="carta", limit=5)
    assert got == ()


def test_scopri_json_malformato_e_miss():
    spy = _EsecutoreSpy(_ok(b"{ not json"))
    got = _wp(spy).scopri_servizi(base_url=_ENTRY, term="carta", limit=5)
    assert got == ()


def test_scopri_json_non_lista_e_miss():
    spy = _EsecutoreSpy(_ok(b'{"id": 42}'))  # object, not a list
    got = _wp(spy).scopri_servizi(base_url=_ENTRY, term="carta", limit=5)
    assert got == ()


def test_scopri_bytes_non_utf8_e_miss():
    spy = _EsecutoreSpy(_ok(b"\xff\xfe not utf8"))
    got = _wp(spy).scopri_servizi(base_url=_ENTRY, term="carta", limit=5)
    assert got == ()


def test_scopri_voce_malformata_scartata_non_alza():
    corpo = json.dumps(
        [
            {"id": "non-un-int", "title": {"rendered": "x"}, "link": "https://x"},
            {"id": 7, "title": {"rendered": "Buona"}, "link": f"{_BASE}/ok"},
        ]
    ).encode("utf-8")
    got = _wp(_EsecutoreSpy(_ok(corpo))).scopri_servizi(base_url=_ENTRY, term="x", limit=5)
    assert len(got) == 1 and got[0].native_id == "7"


# --- dialect B: the full-dump custom controller (recovery, guarded path) ----


def _dump_dialetto_b() -> bytes:
    # One dialect-B row: "ID"/"post_title"/"guid", no id/title.rendered/link.
    return json.dumps(
        [{"ID": 7, "post_title": "Calcolo IMU online",
          "guid": f"{_BASE}/?post_type=servizio&p=7"}]
    ).encode("utf-8")


def test_scopri_dialetto_b_recupera_senza_fields():
    # Slim search (with "_fields") answers [[], []] (dialect B voids _fields);
    # non-empty-but-0 → one re-read WITHOUT "_fields" parses the dialect-B row.
    spy = _EsecutoreSpy(_ok(b"[[],[]]"), _ok(_dump_dialetto_b()))
    got = _wp(spy).scopri_servizi(base_url=_ENTRY, term="imu", limit=5)
    assert len(got) == 1 and got[0].native_id == "7"
    assert str(got[0].url) == f"{_BASE}/?post_type=servizio&p=7"
    assert len(spy.chiamate) == 2  # slim, then the recovery re-read
    assert "_fields=id" in spy.chiamate[0]["url"]
    assert "_fields" not in spy.chiamate[1]["url"]
    # The recovery re-read keeps the same host guard as every other fetch.
    assert spy.chiamate[1]["host_atteso"] == "comune.example.it"


def test_scopri_lista_vuota_nessun_refetch():
    # A GENUINE `[]` is a real empty catalogue: honest miss, NO second read.
    spy = _EsecutoreSpy(_ok(b"[]"))
    got = _wp(spy).scopri_servizi(base_url=_ENTRY, term="imu", limit=5)
    assert got == ()
    assert len(spy.chiamate) == 1  # no "_fields"-free recovery on a real empty


# --- leggi_pagina (common transport) ----------------------------------------


def test_leggi_pagina_ok_html_maxbytes():
    spy = _EsecutoreSpy(_ok("<html>ciao</html>".encode("utf-8")))
    testo = EsecutoreServiceFetcher(spy).leggi_pagina(
        url=f"{_BASE}/servizi/cie", official_host="www.comune.example.it"
    )
    assert testo == "<html>ciao</html>"
    chiamata = spy.chiamate[0]
    assert chiamata["max_bytes"] == _MAX_BYTES_HTML
    assert chiamata["host_atteso"] == "comune.example.it"


def test_leggi_pagina_rifiuto_e_none():
    spy = _EsecutoreSpy(EsitoFetch(consentito=False, fetched=None, motivo="budget"))
    testo = EsecutoreServiceFetcher(spy).leggi_pagina(
        url=f"{_BASE}/x", official_host="comune.example.it"
    )
    assert testo is None


def test_leggi_pagina_bytes_non_utf8_e_none():
    spy = _EsecutoreSpy(_ok(b"\xff\xfe"))
    testo = EsecutoreServiceFetcher(spy).leggi_pagina(
        url=f"{_BASE}/x", official_host="comune.example.it"
    )
    assert testo is None
