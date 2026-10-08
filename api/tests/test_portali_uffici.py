"""Indici amministrativi Drupal/Magnolia: schede reali, paginazione e link AT."""

from __future__ import annotations

import pytest

from treasureiq import portali_uffici as P
from treasureiq.sonda_live import ComuneNoto
from treasureiq.unita_tipizzate import LetturaIncompleta


def _comune(sito: str) -> ComuneNoto:
    return ComuneNoto(
        codice_istat="000001", nome="Comune prova", provincia="TO", regione="Piemonte", sito=sito
    )


def _fetch(pagine, chiamate):
    def fake(url, *, timeout, max_bytes, host_atteso):
        chiamate.append((url, host_atteso))
        pagina = pagine.get(url)
        return ({}, pagina.encode(), url) if pagina is not None else None
    return fake


def test_magnolia_legge_indici_e_link_at_esterno_senza_fetch(monkeypatch):
    base = "https://www.comune.prova.it"
    home = '''
      <a href="/home/amministrazione/uffici.html">Uffici</a>
      <a href="/home/amministrazione/aree_amministrative.html">Aree amministrative</a>
      <a href="https://servizi.comune.prova.it/Trasparenza">Amministrazione Trasparente</a>
    '''
    pagine = {
        base + "/home/amministrazione/uffici.html": '''
          <a class="read-more" href="/home/amministrazione/uffici/Ufficio-1.html"
             title="Ulteriori dettagli per Segreteria">Ulteriori informazioni</a>
          <a href="https://altro.example/uffici/Ufficio-2.html">Esterna</a>
        ''',
        base + "/home/amministrazione/aree_amministrative.html": '''
          <a href="/home/amministrazione/aree_amministrative/Area-1.html">
            <h3>Area tecnica</h3></a>
        ''',
    }
    chiamate = []
    monkeypatch.setattr(P, "fetch_guardato", _fetch(pagine, chiamate))
    esito = P.leggi_magnolia(_comune("www.comune.prova.it"), home_html=home)
    assert [(u.nome, u.url) for u in esito.uffici] == [
        ("Segreteria", base + "/home/amministrazione/uffici/Ufficio-1.html")
    ]
    assert [a.nome for a in esito.aree_amministrative] == ["Area tecnica"]
    assert esito.amministrazione_trasparente.indice_url == (
        "https://servizi.comune.prova.it/Trasparenza"
    )
    assert len(chiamate) == 2
    assert {host for _, host in chiamate} == {"comune.prova.it"}


def test_drupal_unita_e_paginazione_senza_confondere_aree(monkeypatch):
    base = "https://www.comune.prova.it"
    home = '''
      <a href="/amministrazione/uffici">Uffici</a>
      <a href="/amministrazione/aree-amministrative">Aree amministrative</a>
      <a href="https://archivio.example/at">Amministrazione Trasparente Fino al 2023</a>
      <a href="https://attuale.example/at">Amministrazione Trasparente Dal 2024</a>
    '''
    pagine = {
        base + "/amministrazione/uffici": '''
          <a href="/unita-organizzativa/ufficio-tributi" data-element="service-area">
            <span>Ufficio Tributi</span></a>
          <a href="?page=1" rel="next">Pagina successiva</a>
        ''',
        base + "/amministrazione/uffici?page=1": '''
          <a href="/amministrazione/ufficio-anagrafe" data-element="service-area">
            Ufficio Anagrafe</a>
        ''',
        base + "/amministrazione/aree-amministrative": '''
          <a href="/unita-organizzativa/settore-tecnico">Settore tecnico</a>
          <a href="/amministrazione/settore-finanze">Settore Finanze</a>
        ''',
    }
    chiamate = []
    monkeypatch.setattr(P, "fetch_guardato", _fetch(pagine, chiamate))
    esito = P.leggi_drupal(_comune("www.comune.prova.it"), home_html=home)
    assert [u.nome for u in esito.uffici] == ["Ufficio Tributi", "Ufficio Anagrafe"]
    assert [a.nome for a in esito.aree_amministrative] == ["Settore tecnico", "Settore Finanze"]
    assert esito.amministrazione_trasparente.indice_url == "https://attuale.example/at"
    assert len(chiamate) == 3


def test_pagina_successiva_muta_non_salva_snapshot_parziale(monkeypatch):
    base = "https://www.comune.prova.it"
    home = '<a href="/amministrazione/uffici">Uffici</a>'
    pagine = {base + "/amministrazione/uffici": '''
      <a href="/unita-organizzativa/ufficio-tributi">Ufficio Tributi</a>
      <a href="?page=1" rel="next">Pagina successiva</a>
    '''}
    monkeypatch.setattr(P, "fetch_guardato", _fetch(pagine, []))
    with pytest.raises(LetturaIncompleta):
        P.leggi_drupal(_comune("www.comune.prova.it"), home_html=home)


def test_drupal_indice_con_quindici_pagine_dichiarate(monkeypatch):
    """Rimini dichiara 15 pagine (0..14): il cap non deve troncarle."""
    base = "https://www.comune.prova.it"
    pagine = {}
    for pagina in range(15):
        prossimo = (
            f'<a href="?page={pagina + 1}" rel="next">Pagina successiva</a>'
            if pagina < 14
            else ""
        )
        pagine[f"{base}/amministrazione/uffici" + (f"?page={pagina}" if pagina else "")] = (
            f'<a href="/amministrazione/uffici/ufficio-{pagina}">Ufficio {pagina}</a>{prossimo}'
        )
    monkeypatch.setattr(P, "fetch_guardato", _fetch(pagine, []))

    uffici = P._leggi_indice(
        base + "/amministrazione/uffici",
        base=base,
        famiglia="drupal",
        sezione="uffici",
        timeout=8,
    )

    assert len(uffici) == 15
    assert uffici[-1][0] == "Ufficio 14"


def test_home_non_dichiara_indici_ne_at_resta_vuota(monkeypatch):
    monkeypatch.setattr(P, "fetch_guardato", _fetch({}, []))
    esito = P.leggi_drupal(_comune("www.comune.prova.it"), home_html="<html></html>")
    assert esito.uffici == []
    assert esito.aree_amministrative == []
    assert esito.amministrazione_trasparente is None
