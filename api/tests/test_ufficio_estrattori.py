"""Estrattori per famiglia di indirizzo/responsabile contro fixture reali.

Ogni caso è una scheda-dettaglio scaricata da un comune vero, una per forma di
DOM: openpa (Storo), openweb (Collegno), peopleweb vendor OpenWeb.NET (Airasca)
e vendor Siscom (Andrate), municipium (Pomezia). Verifica cosa la pagina
pubblica DAVVERO: nome+ruolo dove strutturati, `email` sempre `None`, indirizzo
= sede dell'ente. Piattaforma sconosciuta o campo assente → `None`, mai inventato.
"""

from __future__ import annotations

from pathlib import Path

from treasureiq.ufficio_estrattori import (
    estrai_indirizzo,
    estrai_persone,
    estrai_recapiti,
    estrai_responsabile,
    persone_ispezionate,
)

FIX = Path(__file__).parent / "fixtures"
POGGIO_URL = "https://comune.poggiomirteto.ri.it/amministrazione/unita_organizzativa/anagrafe/"


def _pagina(nome: str) -> str:
    return (FIX / f"{nome}_ufficio_dettaglio.html").read_text("utf-8", errors="replace")


def _municipium() -> str:
    return (FIX / "municipium" / "ufficio_demografici.html").read_text("utf-8", errors="replace")


# --------------------------- responsabile --------------------------------- #


def test_responsabile_openpa_nome_e_ruolo() -> None:
    resp = estrai_responsabile(_pagina("openpa_storo"), piattaforma="openpa")
    assert resp is not None
    assert resp.nome == "Benedetta Moneghini"
    assert resp.ruolo == "Responsabile"
    assert resp.email is None


def test_responsabile_openweb_nome_e_ruolo() -> None:
    resp = estrai_responsabile(_pagina("openweb_collegno"), piattaforma="openweb")
    assert resp is not None
    assert resp.nome == "Enza Augelli"
    assert resp.ruolo == "Responsabile Servizi Demografici e Generali"
    assert resp.email is None


def test_openweb_non_promuove_un_referente_a_responsabile() -> None:
    pagina = (
        '<section id="persone"><a class="card-title" href="/persona/mario">Mario Rossi</a>'
        '<small class="descrizione_breve">Referente</small></section>'
    )
    assert estrai_responsabile(pagina, piattaforma="openweb") is None


def test_openweb_due_responsabili_non_ne_sceglie_uno() -> None:
    pagina = (
        '<section id="persone">'
        '<a class="card-title" href="/persona/mario">Mario Rossi</a>'
        '<small class="descrizione_breve">Responsabile</small>'
        '<a class="card-title" href="/persona/anna">Anna Bianchi</a>'
        '<small class="descrizione_breve">Responsabile</small>'
        '</section>'
    )
    assert estrai_responsabile(pagina, piattaforma="openweb") is None


def test_responsabile_peopleweb_openweb_net_solo_nome() -> None:
    # Vendor OpenWeb.NET: la card espone il nome, non un ruolo strutturato.
    resp = estrai_responsabile(_pagina("peopleweb_airasca"), piattaforma="peopleweb")
    assert resp is not None
    assert resp.nome == "GRIOTTO Laura"
    assert resp.ruolo is None
    assert resp.email is None


def test_responsabile_peopleweb_siscom_preferisce_resp_su_dirigente() -> None:
    # Vendor Siscom: c'è sia il dirigente d'area sia il responsabile ufficio;
    # si prende il responsabile (#resp), non il dirigente.
    resp = estrai_responsabile(_pagina("peopleweb_andrate"), piattaforma="peopleweb")
    assert resp is not None
    assert resp.nome == "Manuela CHIAVETTO"
    assert resp.ruolo == "Responsabile"
    assert resp.email is None


def test_municipium_non_promuove_la_prima_persona_a_responsabile() -> None:
    resp = estrai_responsabile(_municipium(), piattaforma="municipium")
    assert resp is None


def test_responsabile_piattaforma_sconosciuta_none() -> None:
    assert estrai_responsabile(_pagina("openpa_storo"), piattaforma="isweb") is None
    assert estrai_responsabile(_pagina("openpa_storo"), piattaforma=None) is None


def test_responsabile_pagina_muta_none() -> None:
    assert estrai_responsabile("<html><body>niente</body></html>", piattaforma="openpa") is None


# ---------------------------- indirizzo ----------------------------------- #


def test_indirizzo_openpa_sede() -> None:
    assert estrai_indirizzo(_pagina("openpa_storo"), piattaforma="openpa") == (
        "Piazza Europa, 5 - 38089 Storo (TN)"
    )


def test_indirizzo_openweb_sede_principale() -> None:
    ind = estrai_indirizzo(_pagina("openweb_collegno"), piattaforma="openweb")
    assert ind is not None
    assert "Piazza del Municipio 1" in ind
    assert "10093" in ind


def test_indirizzo_peopleweb_openweb_net_in_chiaro() -> None:
    ind = estrai_indirizzo(_pagina("peopleweb_airasca"), piattaforma="peopleweb")
    assert ind is not None
    assert "Via Roma, 118" in ind
    assert "10060" in ind


def test_indirizzo_peopleweb_siscom_dopo_etichetta() -> None:
    ind = estrai_indirizzo(_pagina("peopleweb_andrate"), piattaforma="peopleweb")
    assert ind == "Via della Parrocchia n. 18"


def test_indirizzo_municipium_postal_address() -> None:
    assert estrai_indirizzo(_municipium(), piattaforma="municipium") == (
        "Piazza Indipendenza, 8 - 00071 Pomezia (RM)"
    )


def test_indirizzo_piattaforma_sconosciuta_none() -> None:
    assert estrai_indirizzo(_pagina("openpa_storo"), piattaforma="isweb") is None
    assert estrai_indirizzo(_pagina("openpa_storo"), piattaforma=None) is None


def test_wordpress_agid_anagrafe_persone_sede_e_recapiti() -> None:
    pagina = (FIX / "wordpress_agid_poggio_mirteto_anagrafe.html").read_text("utf-8")
    persone = estrai_persone(pagina, piattaforma="wordpress_agid", url=POGGIO_URL)
    assert [(p.nome, p.ruolo) for p in persone] == [
        ("Emiliano Armini", "Referente"),
        ("Simonetta Caramignoli", "Referente"),
    ]
    assert [p.url for p in persone] == [
        "https://comune.poggiomirteto.ri.it/persona_pubblica/emiliano-armini/",
        "https://comune.poggiomirteto.ri.it/persona_pubblica/simonetta-caramignoli/",
    ]
    assert estrai_responsabile(pagina, piattaforma="wordpress_agid") is None
    assert estrai_indirizzo(pagina, piattaforma="wordpress_agid") == (
        "Piazza Martiri della Libertà n. 40"
    )
    assert estrai_recapiti(pagina, piattaforma="wordpress_agid") == (
        ["+390765545209", "+390765545230"],
        ["anagrafe.statocivile@comune.poggiomirteto.ri.it"],
    )


def test_wordpress_agid_albano_persone_con_ruolo_in_testo_libero() -> None:
    pagina = (FIX / "wordpress_agid_albano_anagrafe_persone.html").read_text("utf-8")
    url = "https://comune.albanolaziale.rm.it/amministrazione/unita_organizzativa/ufficio-anagrafe-e-leva/"
    persone = estrai_persone(pagina, piattaforma="wordpress_agid", url=url)
    assert len(persone) == 1
    assert persone[0].nome == "Simona Polizzano"
    assert persone[0].ruolo == (
        "Incarico di dirigente del settore III – politiche educative, sociali e culturali "
        "– demografici – Simona Polizzano"
    )
    assert persone[0].url == "https://comune.albanolaziale.rm.it/persona_pubblica/simona-polizzano/"


def test_openweb_collegno_persone_con_ruolo_verbatim() -> None:
    pagina = _pagina("openweb_collegno")
    url = "https://www.comune.collegno.to.it/amministrazione/unita_organizzativa/anagrafe/"
    persone = estrai_persone(pagina, piattaforma="openweb", url=url)
    assert [(p.nome, p.ruolo) for p in persone] == [
        ("Enza Augelli", "Responsabile Servizi Demografici e Generali"),
    ]
    assert persone[0].url == "https://www.comune.collegno.to.it/persona_pubblica/enza-augelli/"
    assert persone_ispezionate(pagina, piattaforma="openweb", persone=persone) is True


def test_peopleweb_airasca_elenca_responsabile_e_personale() -> None:
    pagina = _pagina("peopleweb_airasca")
    url = "https://www.comune.airasca.to.it/amministrazione/unita_organizzativa/anagrafe/"
    persone = estrai_persone(pagina, piattaforma="peopleweb", url=url)
    assert [(p.nome, p.ruolo) for p in persone] == [
        ("GRIOTTO Laura", "Responsabile"),
        ("CALÌ Maria Assunta", "Personale"),
        ("GRECO Filomena", "Personale"),
    ]
    assert persone_ispezionate(pagina, piattaforma="peopleweb", persone=persone) is True
    siscom = _pagina("peopleweb_andrate")
    assert estrai_persone(siscom, piattaforma="peopleweb", url=url) == []
    assert persone_ispezionate(siscom, piattaforma="peopleweb", persone=[]) is False


def test_openpa_storo_elenca_tutto_il_personale() -> None:
    pagina = _pagina("openpa_storo")
    url = "https://www.comune.storo.tn.it/Amministrazione/Uffici/Anagrafe"
    persone = estrai_persone(pagina, piattaforma="openpa", url=url)
    assert [(p.nome, p.ruolo) for p in persone] == [
        ("Benedetta Moneghini", "Responsabile"),
        ("Giuliana Bondoni", "Dipendente"),
        ("Cristina Radoani", "Dipendente"),
        ("Sara Serioli", "Dipendente"),
        ("Sonia Zanetti", "Dipendente"),
    ]
    assert all(p.url and p.url.startswith("https://www.comune.storo.tn.it/") for p in persone)
    assert persone_ispezionate(pagina, piattaforma="openpa", persone=persone) is True


def test_municipium_pomezia_persona_senza_ruolo_inventato() -> None:
    pagina = _municipium()
    url = "https://www.comune.pomezia.rm.it/it/organization/ufficio-demografici"
    persone = estrai_persone(pagina, piattaforma="municipium", url=url)
    assert [(p.nome, p.ruolo, p.url) for p in persone] == [
        ("Angelo Pizzoli", None, "https://www.comune.pomezia.rm.it/it/person/pizzoli-angelo"),
    ]
    assert persone_ispezionate(pagina, piattaforma="municipium", persone=persone) is True


def test_magnolia_farini_ruolo_da_sezione_esplicita() -> None:
    pagina = (FIX / "magnolia_farini_ufficio_persone.html").read_text("utf-8")
    url = "https://www.comune.farini.pc.it/home/amministrazione/uffici/Ufficio-1.html"
    persone = estrai_persone(pagina, piattaforma="magnolia", url=url)
    assert [(p.nome, p.ruolo, p.url) for p in persone] == [
        (
            "Dott.ssa Lorenzoni Anna", "Responsabile",
            "https://www.comune.farini.pc.it/home/amministrazione/personale/Persona-2.html",
        ),
    ]
    assert persone_ispezionate(pagina, piattaforma="magnolia", persone=persone) is True


def test_drupal_fiesole_persona_con_ruolo_verbatim() -> None:
    pagina = (FIX / "drupal_fiesole_ufficio_persone.html").read_text("utf-8")
    url = "https://www.comune.fiesole.fi.it/amministrazione/uffici/servizi-demografici-e-relazioni-con-il-pubblico"
    persone = estrai_persone(pagina, piattaforma="drupal", url=url)
    assert [(p.nome, p.ruolo, p.url) for p in persone] == [
        (
            "Mirella Maestrelli",
            "Responsabile Servizi Demografici e Relazioni con il Pubblico",
            "https://www.comune.fiesole.fi.it/amministrazione/personale-amministrativo/mirella-maestrelli",
        ),
    ]
    assert persone_ispezionate(pagina, piattaforma="drupal", persone=persone) is True


def test_persone_assenti_e_link_fuori_host_non_inventano_referenti() -> None:
    assert estrai_persone("<section id='contatti'></section>", piattaforma="wordpress_agid", url=POGGIO_URL) == []
    pagina = (
        '<section id="persone"><h4><a href="https://example.org/persona">Mario Rossi</a></h4>'
        '<p>Referente</p></section>'
    )
    assert estrai_persone(pagina, piattaforma="wordpress_agid", url=POGGIO_URL) == []
    assert persone_ispezionate(pagina, piattaforma="wordpress_agid", persone=[]) is False
    assert persone_ispezionate("<html></html>", piattaforma="wordpress_agid", persone=[]) is True
