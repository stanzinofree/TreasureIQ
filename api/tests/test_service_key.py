"""Golden tests for Ramo 3 Slice 1 — service_key recognition + request builder.

No network, no model: the recogniser is a pure function over a closed
vocabulary and the builder is a deterministic constructor.
"""

import pytest

from treasureiq.catalog.contracts import CAPABILITY_SERVICES, Surface
from treasureiq.catalog.planner import service_request
from treasureiq.catalog.service_contracts import ServiceKey
from treasureiq.chat.service_key import riconosci_service_key


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # hits
        ("mi serve il modulo della carta d'identità", ServiceKey.CARTA_IDENTITA),
        ("posso fare la CIE?", ServiceKey.CARTA_IDENTITA),
        ("voglio fare il cambio di residenza", ServiceKey.CAMBIO_RESIDENZA),
        # verbal form: "cambiare residenza" is the natural phrasing of an
        # actionable request and must confirm exactly like the noun form.
        ("voglio cambiare residenza", ServiceKey.CAMBIO_RESIDENZA),
        ("come cambio residenza", ServiceKey.CAMBIO_RESIDENZA),
        ("devo cambiare la residenza", ServiceKey.CAMBIO_RESIDENZA),
        ("come faccio l'accesso agli atti", ServiceKey.ACCESSO_ATTI),
        ("certificato di nascita", ServiceKey.STATO_CIVILE),
        ("stato civile", ServiceKey.STATO_CIVILE),
        ("certificato di matrimonio", ServiceKey.STATO_CIVILE),
        # TRIBUTI split per-tax: each tax names its own key; the generic
        # "tributi" is deliberately unrecognised (see negatives below).
        ("devo pagare la TARI", ServiceKey.TRIBUTI_TARI),
        ("informazioni sull'IMU", ServiceKey.TRIBUTI_IMU),
        ("tassa rifiuti non pagata", ServiceKey.TRIBUTI_TARI),
        # out of vocabulary → None (no nearest-neighbour fallback)
        ("vorrei un contributo per l'affitto", None),
        # generic "tributi" is NOT a marker after the split: it did not
        # discriminate a tax and its substring leaked onto "contributi" (grants,
        # a different service). Both stay honestly unrecognised.
        ("pagamento tributi comunali", None),
        ("Richiesta contributi per attività associazioni", None),
        # both taxes named at once → two keys → ambiguous → None
        ("devo pagare IMU e TARI", None),
        ("ciao", None),
        ("modulo per il passaporto", None),
        # generic 'residenza' alone is not a marker
        ("residenza", None),
        # bare 'matrimonio' is NOT a marker: a distinct sub-service must not
        # collapse into the generic civil-registry key.
        ("richiedere una pubblicazione di matrimonio", None),
        ("prenotazione sala matrimoni", None),
        ("matrimonio", None),
        # ambiguous: two distinct keys → None
        ("carta d'identità e cambio residenza", None),
        ("carta d'identità e accesso agli atti", None),
        # REAL connector title forms: titles arrive as HTML.  Entity-encoded
        # and typographic apostrophes must confirm exactly like the ASCII form —
        # these were live false-misses (Borgaro, Lesa, Meina) before the
        # normalizer.
        ("Carta d&#8217;identità elettronica (C.I.E)", ServiceKey.CARTA_IDENTITA),
        ("Essere Cittadino &#8211; Carta d&#8217;Identità", ServiceKey.CARTA_IDENTITA),
        ("Rilascio carta d’identità elettronica (CIE)", ServiceKey.CARTA_IDENTITA),
        ("Carta d&#39;Identità Elettronica", ServiceKey.CARTA_IDENTITA),
    ],
)
def test_riconosci_service_key_golden(message, expected):
    assert riconosci_service_key(message) is expected


def test_normalizzazione_idempotente_e_senza_falsi_positivi():
    # The normalizer only canonicalises (unescape + apostrophe fold): a clean,
    # unmarked string stays unmarked, and re-normalising an already-decoded
    # title is a no-op — no marker is ever added.
    from treasureiq.chat.service_key import _normalizza

    assert _normalizza("carta d'identità") == "carta d'identità"
    assert _normalizza("Carta d’Identità") == "carta d'identità"
    assert _normalizza("Carta d&#8217;Identità") == "carta d'identità"
    # unmarked text carries no key even after normalisation
    assert riconosci_service_key("&#8217;&#8211; nessun servizio &#8230;") is None


def test_riconoscimento_deterministico():
    message = "mi serve il modulo della carta d'identità"
    assert riconosci_service_key(message) is riconosci_service_key(message)


def test_esito_sempre_nel_vocabolario():
    for message in ("carta d'identità", "residenza", "qualcosa di strano", ""):
        esito = riconosci_service_key(message)
        assert esito is None or isinstance(esito, ServiceKey)


def test_cie_richiede_parola_intera():
    # 'cie' as a substring (società) must not trigger CARTA_IDENTITA.
    assert riconosci_service_key("apertura di una società") is None


def test_service_request_builder():
    request = service_request(source_id="058003", service_key=ServiceKey.CARTA_IDENTITA)
    assert request.surface is Surface.ORDINARY_DATA
    assert request.capability == CAPABILITY_SERVICES
    assert request.selection == {"service_key": "carta_identita"}
    assert request.request_id == "chat:058003:ordinary_data:carta_identita"
    # confine D-R3-2: mai la superficie del portale autenticato.
    assert request.surface is not Surface.SERVICE_PORTAL


def test_service_request_rifiuta_stringa_libera():
    # La firma accetta solo ServiceKey: nessun caller sintetizza un servizio
    # da testo libero.
    with pytest.raises((AttributeError, ValueError, TypeError)):
        service_request(source_id="058003", service_key="carta_identita")  # type: ignore[arg-type]
