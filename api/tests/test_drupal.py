"""Connettore uffici per le card server-rendered Drupal Bootstrap Italia."""

from __future__ import annotations

from treasureiq.sonda_live import ComuneNoto


def test_leggi_drupal_segue_paginazione_ed_estrae_solo_schede_ufficio(monkeypatch):
    from treasureiq import drupal

    comune = ComuneNoto(
        codice_istat="001130",
        nome="Leini",
        provincia="TO",
        regione="Piemonte",
        sito="www.comune.leini.to.it",
    )
    indice = "https://www.comune.leini.to.it/amministrazione/uffici"
    pagine = {
        indice: '''
            <a href="/amministrazione/uffici">Indice</a>
            <h3 class="card-title"><a href="/amministrazione/uffici/anagrafe">Anagrafe</a></h3>
            <h3 class="card-title"><a href="/amministrazione/affari-generali" data-element="service-area">Affari generali</a></h3>
            <a href="https://altro.example/amministrazione/uffici/estraneo">Estraneo</a>
            <a href="?page=1">2</a>
        ''',
        f"{indice}?page=1": '''
            <h3 class="card-title"><a href="/amministrazione/uffici/tributi"><span>Tributi</span></a></h3>
            <a href="?page=0">1</a>
        ''',
    }
    letti: list[str] = []

    def fetch(url, _host, _timeout, _sonda):
        letti.append(url)
        pagina = pagine.get(url)
        return (pagina, url) if pagina else None

    monkeypatch.setattr(drupal, "_fetch", fetch)

    esito = drupal.leggi_drupal(comune, object())

    assert [(ufficio.nome, ufficio.url) for ufficio in esito.uffici] == [
        ("Anagrafe", f"{indice}/anagrafe"),
        ("Affari generali", "https://www.comune.leini.to.it/amministrazione/affari-generali"),
        ("Tributi", f"{indice}/tributi"),
    ]
    assert letti == [indice, f"{indice}?page=1"]
