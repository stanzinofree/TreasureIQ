"""Test sul riconoscimento della piattaforma.

Come per la citazione degli orari, i casi qui sotto non sono ipotesi: sono
quello che hanno risposto portali veri durante la costruzione dell'asse C.
Un errore di classificazione non si vede — la riga del censimento resta bella
piena — ma sposta un comune dalla colonna "si legge già" a "serve un
connettore", e quelle colonne sono la base di ogni stima di costo.
"""

from __future__ import annotations

from pathlib import Path

from treasureiq.ingest.piattaforma import (
    Piattaforma,
    classifica_risposta,
    firma_da_risposta,
    raffina_wordpress,
)

_FIXTURE_AT = Path(__file__).parent / "fixtures" / "at"


def firma(html: str = "", **headers: str):
    return firma_da_risposta(headers=headers, html=html)


def test_link_at_outbound_su_home_non_vince_su_wordpress_base():
    """Peveragno: home WordPress con link outbound alla pagina AT jcitygov.
    In contesto BASE (`includi_at=False`, come fa lo sweep sul comune e il
    connettore) il link outbound non deve eleggere JCITYGOV — deve vincere
    il vendor reale della home, WordPress. La firma jcitygov scattata resta
    visibile in `scattate` come diagnostica, solo non può vincere."""
    html = (_FIXTURE_AT / "peveragno_home_at_links.html").read_text(encoding="utf-8")
    esito = classifica_risposta(headers={}, html=html, includi_at=False)
    assert esito.vincitore.piattaforma is Piattaforma.WORDPRESS_GENERICO
    assert any(s.piattaforma is Piattaforma.JCITYGOV for s in esito.scattate)


def test_header_drupal_vince_senza_leggere_html():
    """Torino risponde `x-drupal-cache: HIT` e non dichiara altro. L'header lo
    mette il server: mente meno di un meta tag lasciato da un tema copiato."""
    esito = firma("<html><head></head></html>", **{"x-drupal-cache": "HIT"})
    assert esito.piattaforma is Piattaforma.DRUPAL
    assert "x-drupal-cache" in (esito.prova or "")


def test_meta_generator_specifico_batte_wordpress():
    """Alcuni temi civici dichiarano sia WordPress sia il proprio motore.
    Vincere il più specifico è ciò che tiene separate due voci di costo."""
    html = '<meta name="generator" content="Drupal 10 (https://www.drupal.org)">'
    assert firma(html).piattaforma is Piattaforma.DRUPAL


def test_wordpress_senza_generator_riconosciuto_dagli_asset():
    """Albano Laziale non espone né `generator` né il link all'API REST: le
    installazioni irrobustite li tolgono. Restano gli asset in `/wp-content/`.

    Senza questo livello un comune che TreasureIQ *già legge* finiva in
    `IGNOTA`, e la voce "quanta strada resta" si gonfiava proprio dei portali
    che erano i più facili di tutti.
    """
    html = '<html><head><link rel="stylesheet" href="/wp-content/themes/x/s.css"></head>'
    esito = firma(html)
    assert esito.piattaforma is Piattaforma.WORDPRESS_GENERICO
    assert "wp-content" in (esito.prova or "")


def test_asset_non_sovrascrive_una_dichiarazione_esplicita():
    """Un Drupal che serve un file da un percorso somigliante resta Drupal:
    l'indizio debole non deve poter smentire quello forte."""
    html = (
        '<meta name="generator" content="Drupal 10">'
        '<link href="/wp-content/legacy.css">'
    )
    assert firma(html).piattaforma is Piattaforma.DRUPAL


def test_portale_muto_resta_ignota_non_wordpress():
    """Ciampino non ha nessuna firma. `IGNOTA` è la risposta giusta: indovinare
    qui significherebbe contare fra i facili un portale che non lo è."""
    esito = firma("<html><body>Comune di Ciampino</body></html>")
    assert esito.piattaforma is Piattaforma.IGNOTA
    assert esito.prova is None


def test_non_misurata_e_ignota_non_sono_la_stessa_cosa():
    """`NON_MISURATA` vuol dire che non si è guardato, `IGNOTA` che si è
    guardato senza riconoscere. Sommarle nasconderebbe i portali caduti."""
    assert Piattaforma.NON_MISURATA is not Piattaforma.IGNOTA


def test_raffina_promuove_solo_con_post_type_civico():
    base = firma('<link rel="stylesheet" href="/wp-content/x.css">')
    promosso = raffina_wordpress(
        firma=base, tipi_noti=["post", "page", "servizio"], rest_base="servizi"
    )
    assert promosso.piattaforma is Piattaforma.WP_DESIGN_COMUNI
    assert "servizio" in (promosso.prova or "")


def test_raffina_lascia_stare_wordpress_senza_servizi():
    base = firma('<link rel="stylesheet" href="/wp-content/x.css">')
    identico = raffina_wordpress(firma=base, tipi_noti=["post", "page"], rest_base=None)
    assert identico.piattaforma is Piattaforma.WORDPRESS_GENERICO


def test_raffina_non_tocca_chi_non_e_wordpress():
    """La raffinazione non deve poter promuovere un Drupal per distrazione."""
    base = firma("", **{"x-drupal-cache": "HIT"})
    identico = raffina_wordpress(firma=base, tipi_noti=["servizio"], rest_base="servizi")
    assert identico.piattaforma is Piattaforma.DRUPAL


def test_la_prova_resta_verbatim_e_troncata():
    """La prova serve a rileggere una classificazione fra un anno, non ad
    archiviare la pagina."""
    lungo = "Drupal " + "x" * 400
    esito = firma(f'<meta name="generator" content="{lungo}">')
    assert esito.prova is not None
    assert len(esito.prova) <= 121
    assert esito.prova.startswith("generator: Drupal")


def test_peopleweb_riconosciuto_dagli_asset_con_backslash():
    """PeopleWeb di Siscom non si nomina mai: né generator, né header, né una
    riga nel markup. Resta il tema Bootstrap Italia servito da percorsi con i
    backslash di Windows, che nessuno scrive per farsi riconoscere."""
    html = r'<link href="assets\bootstrap-italia\dist\css/bootstrap-italia-comuni.min.css">'
    esito = firma(html)
    assert esito.piattaforma is Piattaforma.PEOPLEWEB
    assert "bootstrap-italia" in (esito.prova or "")


def test_comweb_si_dichiara_nel_generator():
    html = '<meta name="generator" content="ComWeb - www.epublic.it">'
    assert firma(html).piattaforma is Piattaforma.COMWEB


def test_generator_sconosciuto_resta_ignota_ma_conserva_il_nome():
    """Il difetto che teneva nascosto ComWeb: un generator non riconosciuto
    veniva scartato, e un fornitore che si presenta con nome e cognome
    diventava indistinguibile da un portale muto.

    Conservarlo verbatim è ciò che permette ai fornitori nuovi di raggrupparsi
    da soli interrogando lo storico, senza rifare un giro sull'Italia.
    """
    esito = firma('<meta name="generator" content="PortaleXY 4.2 di FornitoreIgnoto">')
    assert esito.piattaforma is Piattaforma.IGNOTA
    assert esito.prova is not None
    assert "PortaleXY" in esito.prova


def test_portale_muto_non_inventa_una_prova():
    """Chi non dichiara niente non deve ricevere una prova finta: la
    differenza fra 'non si è presentato' e 'si è presentato con un nome che
    non conosco' è tutta la mappa dei fornitori da scoprire."""
    assert firma("<html><body>Comune</body></html>").prova is None


def test_da_impronta_riconosce_le_famiglie_dai_segnali_grezzi():
    from treasureiq.ingest.piattaforma import da_impronta

    casi = [
        ("server=HGATE; rotte=hbl", None, Piattaforma.HGATE),
        ("asset=argomenti|content|extension|novita", None, Piattaforma.OPENPA),
        ("cookie=csrf; asset=.imaging|.resources|dam|home", None, Piattaforma.MAGNOLIA),
        ("asset=css|js|portals", None, Piattaforma.DOTNETNUKE),
    ]
    for impronta, regione, atteso in casi:
        firma = da_impronta(impronta=impronta, regione=regione)
        assert firma is not None and firma.piattaforma is atteso, impronta


def test_piattaforma_regionale_richiede_anche_la_regione():
    """`nginx` con una directory `assets` non identifica niente da solo: è la
    coincidenza con la regione a renderlo una firma.

    Applicare quella regola fuori dal Friuli attribuirebbe a una piattaforma
    regionale comuni che non ci sono mai stati.
    """
    from treasureiq.ingest.piattaforma import da_impronta

    impronta = "server=nginx; rotte=php; asset=assets"
    dentro = da_impronta(impronta=impronta, regione="Friuli-Venezia Giulia")
    assert dentro is not None and dentro.piattaforma is Piattaforma.REGIONE_FVG
    assert da_impronta(impronta=impronta, regione="Sicilia") is None


def test_node_modules_da_solo_non_nomina_niente():
    """`node_modules` e' una directory di build, non un fornitore.

    85 comuni in Veneto e 70 in Emilia-Romagna, e in nessun'altra regione,
    con vocabolari di rotte diversi fra loro: sono due piattaforme regionali
    distinte. Dargli un nome unico inventerebbe un'azienda inesistente, e
    fuori da quelle due regioni non prova niente del tutto.
    """
    from treasureiq.ingest.piattaforma import da_impronta

    assert da_impronta(impronta="asset=node_modules", regione="Lazio") is None
    assert da_impronta(impronta="asset=node_modules") is None


def test_da_impronta_tace_invece_di_indovinare():
    from treasureiq.ingest.piattaforma import da_impronta

    assert da_impronta(impronta=None) is None
    assert da_impronta(impronta="server=Apache/2.4.37") is None


def test_pageobject_serve_tre_segnali_insieme():
    """`Microsoft-IIS` da solo non identifica niente: è la coincidenza con le
    rotte `.aspx` e col tema Bootstrap Italia a fare la firma.

    La rotta `/pageobject/Uffici` è stata verificata su sei comuni di tre
    regioni diverse — quindi è un prodotto, non una piattaforma regionale, e
    non porta condizione geografica.
    """
    from treasureiq.ingest.piattaforma import da_impronta

    piena = "server=Microsoft-IIS/10.0; cookie=ASP.NET_SessionId; rotte=aspx|jsp; asset=bootstrap-italia"
    assert da_impronta(impronta=piena).piattaforma is Piattaforma.PAGEOBJECT
    assert da_impronta(impronta="server=Microsoft-IIS/10.0") is None


def test_node_modules_separato_dalla_regione():
    """La stessa directory di build in due regioni, con vocabolari di rotte
    diversi: due piattaforme regionali, non una. Fuori da quelle due regioni
    resta senza nome, perché lì `node_modules` non prova niente."""
    from treasureiq.ingest.piattaforma import da_impronta

    assert da_impronta(impronta="asset=node_modules", regione="Veneto").piattaforma is (
        Piattaforma.REGIONE_VENETO
    )
    assert da_impronta(
        impronta="server=nginx/1.18.0; asset=node_modules", regione="Emilia-Romagna"
    ).piattaforma is Piattaforma.RETE_CIVICA_LEPIDA
    assert da_impronta(impronta="asset=node_modules", regione="Lazio") is None


def test_municipium_riconosciuto_dall_host_degli_asset():
    """Municipium non si dichiara in nessun tag: serve gli asset da
    `municipiumapp.it`.

    La prima versione dell'impronta guardava solo i percorsi relativi, quindi
    ignorava gli host esterni — e novecentotrentuno comuni, il gruppo piu'
    grande d'Italia, sono rimasti "non riconosciuti" per mezza giornata.
    """
    html = '<link href="https://cdn.municipiumapp.it/assets/css/app.css">'
    esito = firma(html)
    assert esito.piattaforma is Piattaforma.MUNICIPIUM
    assert "municipium" in (esito.prova or "").lower()


def test_classifica_risposta_ritorna_scattate_ordinate_per_score():
    """La batteria non butta via i runner-up: un generator dichiarato che
    perde solo contro l'header è un segnale diverso da nessun runner-up."""
    esito = classifica_risposta(
        headers={"x-drupal-cache": "HIT"},
        html='<meta name="generator" content="WordPress 6.4">',
    )
    assert esito.vincitore.piattaforma is Piattaforma.DRUPAL
    assert len(esito.scattate) == 2
    scores = [s.score for s in esito.scattate]
    assert scores == sorted(scores, reverse=True)
    assert esito.scattate[0].piattaforma is Piattaforma.DRUPAL
    assert esito.scattate[1].piattaforma is Piattaforma.WORDPRESS_GENERICO


def test_classifica_risposta_vincitore_uguale_a_firma_da_risposta():
    """`firma_da_risposta` resta un wrapper: stesso vincitore, sempre."""
    html = '<meta name="generator" content="ComWeb - www.epublic.it">'
    assert classifica_risposta(headers={}, html=html).vincitore == firma_da_risposta(
        headers={}, html=html
    )


def test_collisione_vince_la_classe_forte_anche_se_scansionata_dopo():
    """Collisione vera, non un travestimento del vecchio first-match.

    La tavola `_GENERATOR` viene scansionata PRIMA di `_HOST_PRODOTTO`
    (rango 2 contro 5): un generator `WordPress` da solo scatta subito, ed
    e' esattamente il caso che il vecchio first-match avrebbe restituito
    senza guardare oltre. Ma quel generator e' un nome generico che milioni
    di siti dichiarano (EURISTICO), mentre l'host `municipiumapp.it` che
    arriva DOPO, nella scansione, e' una prova funzionale di un vendor
    specifico (DEFINITIVO). Se la formula fosse ancora un alias dell'ordine
    di scansione, vincerebbe WordPress (tavola 2, prima) — invece vince
    Municipium (tavola 5, dopo) perche' la classe di forza-prova prevale
    sulla posizione. Questo e' impossibile da far passare con la vecchia
    monotonia punteggio=ordine-tavola."""
    html = (
        '<meta name="generator" content="WordPress 6.4">'
        '<link href="https://cdn.municipiumapp.it/assets/css/app.css">'
    )
    esito = classifica_risposta(headers={}, html=html)
    assert esito.vincitore.piattaforma is Piattaforma.MUNICIPIUM
    assert len(esito.scattate) == 2
    assert esito.scattate[0].piattaforma is Piattaforma.MUNICIPIUM
    assert esito.scattate[0].score > esito.scattate[1].score
    assert esito.scattate[1].piattaforma is Piattaforma.WORDPRESS_GENERICO


def test_agenda_smart_non_ruba_i_comuni_di_openpa():
    """Le due famiglie hanno entrambe `argomenti` fra le directory: a
    distinguerle e' cio' che segue. L'ordine delle regole non e' un dettaglio
    di stile — invertirle darebbe a OpenPA comuni che non sono suoi."""
    from treasureiq.ingest.piattaforma import da_impronta

    assert (
        da_impronta(impronta="asset=argomenti|content|extension|novita").piattaforma
        is Piattaforma.OPENPA
    )
    assert (
        da_impronta(impronta="asset=argomenti|bootstrap-italia|css|js").piattaforma
        is Piattaforma.AGENDA_SMART
    )


def test_hypersic_riconosciuto_dall_host_degli_asset():
    """Hypersic non si dichiara in nessun tag: gli asset di servizi-online/AT
    arrivano da `hspromilaprod.hypersicapp.net`. Mono-campione (Rignano
    Flaminio), prova reale letta dal sito."""
    html = (_FIXTURE_AT / "rignano_flaminio_hypersic_head.html").read_text(encoding="utf-8")
    esito = firma(html)
    assert esito.piattaforma is Piattaforma.HYPERSIC
    assert "hypersicapp.net" in (esito.prova or "").lower()


def test_portale33_riconosciuto_dal_meta_layout():
    """e-pal.it non nomina il proprio host nel body: l'unico segnale è
    `<meta name="layout" content="portale33"/>`. Mono-campione (Marano sul
    Panaro, pagina di Amministrazione Trasparente)."""
    html = (_FIXTURE_AT / "marano_panaro_portale33_head.html").read_text(encoding="utf-8")
    esito = firma(html)
    assert esito.piattaforma is Piattaforma.PORTALE33
    assert "portale33" in (esito.prova or "").lower()


def test_portale33_senza_marker_non_scatta():
    """Nessun marker `portale33` nel body: niente da riconoscere. Non si
    inventa una prova che non c'e'."""
    html = '<meta name="layout" content="qualcosa-altro"/>'
    esito = firma(html)
    assert esito.piattaforma is not Piattaforma.PORTALE33


def test_soluzionipa_riconosciuto_dall_host_openweb():
    """OpenWeb servito come superficie AT sotto `melito.soluzionipa.it`,
    path `/openweb/`. Mono-campione (Melito), prova reale letta dal sito."""
    html = (_FIXTURE_AT / "melito_soluzionipa_head.html").read_text(encoding="utf-8")
    esito = firma(html)
    assert esito.piattaforma is Piattaforma.SOLUZIONIPA
    assert "soluzionipa.it" in (esito.prova or "").lower()


def test_hgate_landing_at_riconosciuta_solo_dall_header_server():
    """Le landing AT di Halley "hgate" (Adelfia, Scansano) non portano
    nessun marker nel body — né `var ente`, né kamaleonte, né `/zf/` — solo
    l'header di prodotto del server. Senza guardare l'header, questa pagina
    reale finirebbe IGNOTA nonostante sia perfettamente riconoscibile."""
    html = (_FIXTURE_AT / "adelfia_hgate_landing_head.html").read_text(encoding="utf-8")
    esito = firma(html, server="HGATE")
    assert esito.piattaforma is Piattaforma.HGATE
    assert "hgate" in (esito.prova or "").lower()


def test_famiglia_at_nuove_non_vincono_su_base_senza_includi_at():
    """HYPERSIC, PORTALE33 e SOLUZIONIPA sono AT-only (`_FAMIGLIA_AT`): un
    link outbound verso la loro superficie non deve poter eleggere una di
    queste piattaforme quando il chiamante è BASE (`includi_at=False`) — deve
    vincere il CMS di base, come per JCITYGOV a Peveragno."""
    casi = (
        (
            '<link href="https://cdn.hypersicapp.net/x.css">'
            '<link href="/wp-content/themes/x/s.css">',
            Piattaforma.HYPERSIC,
        ),
        (
            '<meta name="layout" content="portale33"/>'
            '<link href="/wp-content/themes/x/s.css">',
            Piattaforma.PORTALE33,
        ),
        (
            '<script src="https://melito.soluzionipa.it/openweb/js/x.js"></script>'
            '<link href="/wp-content/themes/x/s.css">',
            Piattaforma.SOLUZIONIPA,
        ),
    )
    for html, piattaforma_at in casi:
        esito = classifica_risposta(headers={}, html=html, includi_at=False)
        assert esito.vincitore.piattaforma is Piattaforma.WORDPRESS_GENERICO
        assert any(s.piattaforma is piattaforma_at for s in esito.scattate)
