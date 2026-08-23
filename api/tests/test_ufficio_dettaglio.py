"""Arricchimento on-demand dell'ufficio dalla scheda-dettaglio (Ramo 1, drill→v1).

Slice 1: la funzione pura di acquisizione `arricchisci_ufficio`. Replica il
comportamento display/fonte del vecchio `_orari_ufficio_live` (che verrà poi
delegato a questa nel wiring chat), ma restituendo una copia arricchita
dell'`UfficioConnettore` invece di una tupla — così i campi letti fluiscono per
proiezione fino al `DataBatch`. Copre: forma normalizzata + fonte verbatim
(D-07), ripiego verbatim senza schema, ripiego sul catalogo, assenza di URL,
recapiti d'indice preservati, e i campi additivi (indirizzo/responsabile)
ancora `None` finché non arrivano gli estrattori per famiglia.
"""

from __future__ import annotations

import treasureiq.ufficio_dettaglio as ud
from treasureiq.connettore import Responsabile, UfficioConnettore
from treasureiq.orari_schema import Fascia, OrarioSettimanale, RigaOrario
from treasureiq.orari_ufficio import OrariUfficio

URL_UFFICIO = (
    "https://comune.albanolaziale.rm.it/amministrazione/"
    "unita_organizzativa/ufficio-anagrafe-e-leva/"
)


def _ufficio(*, url: str = URL_UFFICIO, orari: str | None = None) -> UfficioConnettore:
    return UfficioConnettore(
        nome="Ufficio Anagrafe e Leva",
        url=url,
        telefoni=["06 12345"],
        email=["anagrafe@comune.it"],
        pec=[],
        orari=orari,
        source_typed=True,
        letto_il="2026-08-12T00:00:00+00:00",
    )


def _voce(*, orari, schema=None, indirizzo=None, responsabile=None) -> OrariUfficio:
    return OrariUfficio(
        codice_istat="058003",
        slug="ufficio-anagrafe-e-leva",
        url=URL_UFFICIO,
        orari=orari,
        orario_schema=schema,
        indirizzo=indirizzo,
        responsabile=responsabile,
        letto_il="2026-08-12T00:00:00+00:00",
    )


_SCHEMA = OrarioSettimanale(
    righe=[RigaOrario(giorni=[0], etichetta="Lunedì", fasce=[Fascia(apertura="9:00", chiusura="12:00")])],
    testo_grezzo="lunedì 9:00-12:00",
    reso="Lunedì: 9:00–12:00",
)


def test_schema_mostra_reso_e_affianca_verbatim(monkeypatch) -> None:
    # Pagina normalizzabile: card = forma pulita, fonte = citazione verbatim (D-07).
    monkeypatch.setattr(
        ud, "leggi_orari_ufficio",
        lambda *, codice_istat, url, piattaforma=None: _voce(orari="lunedì 9:00-12:00", schema=_SCHEMA),
    )
    arr = ud.arricchisci_ufficio(codice_istat="058003", ufficio=_ufficio())
    assert arr.ufficio.orari == "Lunedì: 9:00–12:00"
    assert arr.orari_fonte == "lunedì 9:00-12:00"


def test_senza_schema_orari_verbatim_senza_fonte(monkeypatch) -> None:
    # Nessuno schema: l'orario verbatim è già la forma da mostrare, niente fonte.
    monkeypatch.setattr(
        ud, "leggi_orari_ufficio",
        lambda *, codice_istat, url, piattaforma=None: _voce(orari="Orari: lunedì 9-12"),
    )
    arr = ud.arricchisci_ufficio(codice_istat="058003", ufficio=_ufficio())
    assert arr.ufficio.orari == "Orari: lunedì 9-12"
    assert arr.orari_fonte is None


def test_pagina_muta_ripiega_su_orari_catalogo(monkeypatch) -> None:
    # Pagina raggiunta ma senza orario: si ripiega sull'orario già catalogato.
    monkeypatch.setattr(
        ud, "leggi_orari_ufficio", lambda *, codice_istat, url, piattaforma=None: _voce(orari=None)
    )
    arr = ud.arricchisci_ufficio(
        codice_istat="058003", ufficio=_ufficio(orari="Sportello: mar 10-12")
    )
    assert arr.ufficio.orari == "Sportello: mar 10-12"
    assert arr.orari_fonte is None


def test_reader_none_ripiega_su_catalogo(monkeypatch) -> None:
    # URL non interrogabile dal reader (None): l'orario catalogato resta.
    monkeypatch.setattr(ud, "leggi_orari_ufficio", lambda *, codice_istat, url, piattaforma=None: None)
    arr = ud.arricchisci_ufficio(
        codice_istat="058003", ufficio=_ufficio(orari="Sportello: mar 10-12")
    )
    assert arr.ufficio.orari == "Sportello: mar 10-12"
    assert arr.orari_fonte is None


def test_senza_url_non_legge_e_torna_invariato(monkeypatch) -> None:
    # Nessuna URL: niente da leggere, nessun fetch, ufficio invariato.
    chiamato = {"n": 0}

    def _spy(*, codice_istat, url, piattaforma=None):  # pragma: no cover - non deve essere chiamato
        chiamato["n"] += 1
        return None

    monkeypatch.setattr(ud, "leggi_orari_ufficio", _spy)
    ufficio = _ufficio(url="", orari="dal catalogo")
    arr = ud.arricchisci_ufficio(codice_istat="058003", ufficio=ufficio)
    assert arr.ufficio is ufficio
    assert arr.orari_fonte is None
    assert chiamato["n"] == 0


def test_recapiti_indice_preservati_e_campi_additivi_ancora_none(monkeypatch) -> None:
    # I recapiti vengono dall'indice, non dalla scheda: sopravvivono intatti.
    # indirizzo/responsabile restano None: gli estrattori sono lo step dopo.
    monkeypatch.setattr(
        ud, "leggi_orari_ufficio",
        lambda *, codice_istat, url, piattaforma=None: _voce(orari="lunedì 9:00-12:00", schema=_SCHEMA),
    )
    arr = ud.arricchisci_ufficio(codice_istat="058003", ufficio=_ufficio())
    assert arr.ufficio.telefoni == ["06 12345"]
    assert arr.ufficio.email == ["anagrafe@comune.it"]
    assert arr.ufficio.indirizzo is None
    assert arr.ufficio.responsabile is None


def test_indirizzo_e_responsabile_letti_entrano_nella_copia(monkeypatch) -> None:
    # La scheda pubblica indirizzo e responsabile: fluiscono nella copia
    # arricchita (e da lì, per proiezione, fino al DataBatch).
    resp = Responsabile(nome="Mario Rossi", ruolo="Responsabile")
    monkeypatch.setattr(
        ud, "leggi_orari_ufficio",
        lambda *, codice_istat, url, piattaforma=None: _voce(
            orari="lunedì 9:00-12:00", schema=_SCHEMA,
            indirizzo="Piazza Roma, 1 - 00041 Albano Laziale (RM)", responsabile=resp,
        ),
    )
    arr = ud.arricchisci_ufficio(codice_istat="058003", ufficio=_ufficio(), piattaforma="openpa")
    assert arr.ufficio.indirizzo == "Piazza Roma, 1 - 00041 Albano Laziale (RM)"
    assert arr.ufficio.responsabile == resp
    assert arr.ufficio.responsabile.email is None


def test_campi_additivi_assenti_non_sovrascrivono(monkeypatch) -> None:
    # La scheda non li pubblica: None non cancella ciò che l'ufficio già aveva.
    ufficio = _ufficio().model_copy(
        update={"indirizzo": "Via Catalogo, 9", "responsabile": Responsabile(nome="Anna Bianchi")}
    )
    monkeypatch.setattr(
        ud, "leggi_orari_ufficio",
        lambda *, codice_istat, url, piattaforma=None: _voce(orari="lunedì 9:00-12:00", schema=_SCHEMA),
    )
    arr = ud.arricchisci_ufficio(codice_istat="058003", ufficio=ufficio, piattaforma="isweb")
    assert arr.ufficio.indirizzo == "Via Catalogo, 9"
    assert arr.ufficio.responsabile.nome == "Anna Bianchi"


def test_piattaforma_inoltrata_al_reader(monkeypatch) -> None:
    # arricchisci deve passare la piattaforma al reader (dispatch per famiglia).
    visto = {}

    def _cattura(*, codice_istat, url, piattaforma=None):
        visto["piattaforma"] = piattaforma
        return _voce(orari="lunedì 9:00-12:00", schema=_SCHEMA)

    monkeypatch.setattr(ud, "leggi_orari_ufficio", _cattura)
    ud.arricchisci_ufficio(codice_istat="058003", ufficio=_ufficio(), piattaforma="peopleweb")
    assert visto["piattaforma"] == "peopleweb"
