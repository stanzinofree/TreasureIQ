"""Contract test: `OfficeAnswer` → `OfficeOut` carries the Ramo 1 additive
fields (indirizzo, responsabile) all the way to the web payload — and honest
degradation (`None`) when the office card does not publish them (D-05).

`to_info_out` is the single seam between the chat's `InfoAnswer` and the HTTP
`InfoOut`: pinning it here guards against a future field-by-field rewrite that
would silently drop the accountability/address the drill projected.
"""

from __future__ import annotations

from treasureiq.api import to_info_out
from treasureiq.chat.respond import InfoAnswer, OfficeAnswer
from treasureiq.connettore import Responsabile


def _info(office: OfficeAnswer) -> InfoAnswer:
    return InfoAnswer(
        document=None,
        office=office,
        coverage_count=0,
        diagnosis=[],
        integration_cost=[],
        web_results=[],
    )


def test_office_out_carries_indirizzo_e_responsabile():
    office = OfficeAnswer(
        nome="Anagrafe",
        telefono="+39 06 000000",
        email="anagrafe@comune.prova.it",
        orari=None,
        indirizzo="Piazza del Comune 1",
        responsabile=Responsabile(
            nome="Mario Rossi", ruolo="Dirigente", email=None
        ),
    )

    out = to_info_out(_info(office))

    assert out.office is not None
    assert out.office.indirizzo == "Piazza del Comune 1"
    assert out.office.responsabile is not None
    assert out.office.responsabile.nome == "Mario Rossi"
    assert out.office.responsabile.ruolo == "Dirigente"
    # Email personale non pubblicata → resta None onesto (D-05), non inventata.
    assert out.office.responsabile.email is None


def test_office_out_absent_fields_are_none_not_invented():
    """Un ufficio la cui scheda non pubblica indirizzo/responsabile deve
    arrivare al payload con `None`, mai con un valore riempito."""
    office = OfficeAnswer(
        nome="Protocollo",
        telefono=None,
        email=None,
        orari=None,
    )

    out = to_info_out(_info(office))

    assert out.office is not None
    assert out.office.indirizzo is None
    assert out.office.responsabile is None
