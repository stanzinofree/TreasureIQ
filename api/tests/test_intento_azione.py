"""Classificatore puro titolo → intento-azione (presentazione DISAMBIGUATION).

Funzione pura, senza rete: dato il titolo di un servizio, sceglie il bucket di
intento. Priorità = ordine di dichiarazione dell'enum (il primo che matcha vince).
Fallback esplicito ``ALTRO_INFORMAZIONI``: un titolo non-azione (guida, valori aree)
non viene scartato né forzato. ``raggruppa_per_intento`` è presentazione: ordine di
bucket fisso, bucket vuoti omessi, nessuna reference persa, service_id preservati.
"""

from __future__ import annotations

from datetime import datetime, timezone

from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.service_connectors.intento_azione import (
    IntentoAzione,
    classifica_intento,
    raggruppa_per_intento,
)
from treasureiq.catalog.service_contracts import (
    ServiceAccessMode,
    ServiceAccessOption,
    ServiceReference,
)

_ORA = datetime(2026, 9, 2, tzinfo=timezone.utc)


def _ref(service_id: str, title: str) -> ServiceReference:
    url = f"https://esempio.it/{service_id}"
    return ServiceReference(
        service_id=service_id,
        title=title,
        source_url=url,
        options=(
            ServiceAccessOption(
                mode=ServiceAccessMode.INFORMATION, url=url, source_url=url
            ),
        ),
        discovered_from=Surface.ORDINARY_DATA,
        provider_platform="openpa",
        discovered_at=_ORA,
    )


# -- classifica_intento: positivi per ogni bucket ---------------------------


def test_positivi_per_bucket() -> None:
    casi = {
        "Calcolatore IMIS": IntentoAzione.CALCOLATORE,
        "Simulatore acconto IMIS": IntentoAzione.CALCOLATORE,
        "IMIS — esenzione abitazione principale": IntentoAzione.AGEVOLAZIONE,
        "Riduzione IMIS per inagibilità": IntentoAzione.AGEVOLAZIONE,
        "Comunicazione di pertinenza IMIS": IntentoAzione.COMUNICAZIONE,
        "Dichiarazione IMIS": IntentoAzione.DICHIARAZIONE_ISTANZA,
        "Domanda di residenza": IntentoAzione.DICHIARAZIONE_ISTANZA,
        "Autocertificazione IMIS": IntentoAzione.DICHIARAZIONE_ISTANZA,
        "Versamento IMIS — acconto e saldo": IntentoAzione.VERSAMENTO_RIMBORSO,
        "Rimborso IMIS": IntentoAzione.VERSAMENTO_RIMBORSO,
        "Ravvedimento operoso F24": IntentoAzione.VERSAMENTO_RIMBORSO,
        "Modulistica IMIS": IntentoAzione.MODULISTICA,
        "Fac-simile IMIS": IntentoAzione.MODULISTICA,
    }
    for titolo, atteso in casi.items():
        assert classifica_intento(titolo) is atteso, titolo


def test_fallback_esplicito_per_non_azione() -> None:
    for titolo in (
        "IMIS Valori aree fabbricabili 2019",
        "Guida all'IMIS 2022",
        "IM.I.S. — informazioni generali",
        "",
    ):
        assert classifica_intento(titolo) is IntentoAzione.ALTRO_INFORMAZIONI, titolo


def test_priorita_ordine_enum_agevolazione_prima_di_istanza() -> None:
    # «Domanda» (istanza) ed «esenzione» (agevolazione) coesistono nel titolo:
    # vince il bucket dichiarato PRIMA nell'enum → AGEVOLAZIONE.
    assert (
        classifica_intento("Domanda di esenzione IMIS")
        is IntentoAzione.AGEVOLAZIONE
    )


# -- raggruppa_per_intento --------------------------------------------------


def test_raggruppa_ordine_fisso_e_bucket_non_vuoti() -> None:
    refs = [
        _ref("c:openpa:1", "Dichiarazione IMIS"),             # DICHIARAZIONE
        _ref("c:openpa:2", "Calcolatore IMIS"),               # CALCOLATORE
        _ref("c:openpa:3", "IMIS valori aree 2019"),          # ALTRO
    ]
    gruppi = raggruppa_per_intento(refs)
    intenti = [i for i, _ in gruppi]
    # Ordine = enum, non ordine d'ingresso: CALCOLATORE prima di DICHIARAZIONE.
    assert intenti == [
        IntentoAzione.CALCOLATORE,
        IntentoAzione.DICHIARAZIONE_ISTANZA,
        IntentoAzione.ALTRO_INFORMAZIONI,
    ]
    # Nessun bucket vuoto listato.
    assert all(refs_bucket for _, refs_bucket in gruppi)


def test_raggruppa_non_perde_reference_e_conserva_service_id() -> None:
    refs = [
        _ref("c:openpa:1", "Calcolatore IMIS"),
        _ref("c:openpa:2", "Simulatore IMIS"),
        _ref("c:openpa:3", "Rimborso IMIS"),
        _ref("c:openpa:4", "Guida IMIS"),
    ]
    gruppi = raggruppa_per_intento(refs)
    ids_out = {r.service_id for _, bucket in gruppi for r in bucket}
    assert ids_out == {r.service_id for r in refs}
    # Due nello stesso bucket restano DUE reference distinte (presentazione ≠ identità).
    calcolatore = dict(gruppi)[IntentoAzione.CALCOLATORE]
    assert [r.service_id for r in calcolatore] == ["c:openpa:1", "c:openpa:2"]


def test_raggruppa_vuoto() -> None:
    assert raggruppa_per_intento([]) == []
