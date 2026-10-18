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


# Dedicated "Responsabile" section (`id="responsabile"` / `id="manager"`):
# trimmed from real pages, one per DOM variant seen across the family. The
# section heading already says the role, so no "responsabile" keyword is
# needed on the person.


def test_openweb_sezione_manager_testo_semplice() -> None:
    # Montepulciano 052015, Servizi Demografici: plain text, no person link.
    pagina = (
        '<section class="it-page-section mb-30"><h2 class="mb-3" id="manager">Responsabile</h2>'
        '<div class="richtext-wrapper lora"> Loredana Banini </div></section>'
        '<section class="it-page-section mb-30"><h2 class="mb-3" id="contacts">Contatti</h2>'
        '<div class="card"><h3 class="card-title h5"><a href="/punti">Servizi Demografici</a></h3></div></section>'
    )
    resp = estrai_responsabile(pagina, piattaforma="openweb")
    assert resp is not None
    assert (resp.nome, resp.ruolo) == ("Loredana Banini", None)


def test_openweb_sezione_responsabile_card_title_con_ruolo() -> None:
    # Barga 046003: card-teaser with a.card-title + small role.
    pagina = (
        '<section id="responsabile"><h2 class="title-xlarge mb-2">Responsabile</h2>'
        '<div class="card card-teaser"><div class="card-body p-3">'
        '<a class="card-title h6" href="https://www.comune.barga.lu.it/persona_pubblica/mariateresa-di-natale/"'
        ' aria-label="Vai alla pagina di: Mariateresa Di Natale"> Mariateresa Di Natale </a>'
        '<small class="m-0"> Responsabile Area Amministrativa Cultura </small></div></div></section>'
    )
    resp = estrai_responsabile(pagina, piattaforma="openweb")
    assert resp is not None
    assert (resp.nome, resp.ruolo) == ("Mariateresa Di Natale", "Responsabile Area Amministrativa Cultura")


def test_openweb_sezione_responsabile_chip() -> None:
    # Pedavena 025036: <article> with a chip-label, heading in h6/small/b.
    pagina = (
        '<article id="responsabile" class="it-page-section anchor-offset">'
        '<h6><small><b>Responsabile</b></small></h6><ul class="d-flex"><li>'
        '<a class="chip chip-simple" href="https://comune.pedavena.bl.it/persona_pubblica/elena-moretton/">'
        '<span class="chip-label">Elena Moretton</span></a></li></ul></article>'
        '<article id="tipo-organizzazione"><h6>Tipo</h6></article>'
    )
    resp = estrai_responsabile(pagina, piattaforma="openweb")
    assert resp is not None
    assert resp.nome == "Elena Moretton"


def test_openweb_sezione_responsabile_titolo_con_link() -> None:
    # Sant'Ippolito 041058: name is the link inside an h4.
    pagina = (
        '<section id="responsabile" class="it-page-section mb-4">'
        '<h3 class="my-2">Responsabile</h3><div class="richtext-wrapper lora"><div class="card-body">'
        '<h4 class="titillium"><a href="https://comune.santippolito.pu.it/persona_pubblica/paola-carpineti/">'
        'Paola Carpineti</a></h4> Responsabile ufficio tributi </div></div></section>'
    )
    resp = estrai_responsabile(pagina, piattaforma="openweb")
    assert resp is not None
    assert resp.nome == "Paola Carpineti"


def test_openweb_sezione_responsabile_p_card_title() -> None:
    # Casamarciano 063018: id on the heading, name in p.card-title.
    pagina = (
        '<h4 id="responsabile">Responsabile</h4><div class="row"><div class="card-body">'
        '<a href="https://www.comune.casamarciano.na.it/amministrazione/uffici/ufficio-protocollo/antonietta-buonaguro">'
        '<p class="card-title h5 no-bold"> Antonietta Buonaguro </p></a>'
        '<a class="read-more" href="#"><span class="text">Vai alla Pagina</span></a></div></div>'
        '<h4 id="persone">Persone</h4>'
    )
    resp = estrai_responsabile(pagina, piattaforma="openweb")
    assert resp is not None
    assert resp.nome == "Antonietta Buonaguro"


def test_openweb_sezione_responsabile_vuota_o_non_nome_resta_none() -> None:
    vuota = '<section id="responsabile"><h2>Responsabile</h2><div class="richtext-wrapper"></div></section>'
    frase = (
        '<section id="manager"><h2>Responsabile</h2><div class="richtext-wrapper">'
        'Per informazioni rivolgersi al numero 0578 712303</div></section>'
    )
    assert estrai_responsabile(vuota, piattaforma="openweb") is None
    assert estrai_responsabile(frase, piattaforma="openweb") is None


def test_openweb_sezione_con_due_responsabili_non_ne_sceglie_uno() -> None:
    pagina = (
        '<section id="responsabile"><h2>Responsabile</h2>'
        '<span class="chip-label">Mario Rossi</span><span class="chip-label">Anna Bianchi</span></section>'
    )
    assert estrai_responsabile(pagina, piattaforma="openweb") is None


def test_wordpress_agid_usa_la_stessa_sezione_dedicata() -> None:
    # Ospitale di Cadore 025035, Ufficio Tecnico (WordPress Design Comuni).
    pagina = (
        '<section id="responsabile"><h3>Responsabile</h3><div class="card-body">'
        '<a class="card-title" href="https://www.comune.ospitaledicadore.bl.it/persona_pubblica/paolo-de-lorenzi/">'
        'Paolo De Lorenzi</a><small>Responsabile dell\u2019Area Tecnica</small></div></section>'
    )
    resp = estrai_responsabile(pagina, piattaforma="wordpress_agid")
    assert resp is not None
    assert (resp.nome, resp.ruolo) == ("Paolo De Lorenzi", "Responsabile dell\u2019Area Tecnica")


def test_openweb_link_di_navigazione_non_e_una_sezione() -> None:
    # The in-page nav links `href="#responsabile"`: only an `id=` opens the section.
    pagina = '<a class="nav-link" href="#responsabile"><span>Responsabile</span></a><p>Mario Rossi</p>'
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
