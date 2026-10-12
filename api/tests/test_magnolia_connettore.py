from treasureiq import magnolia


def test_uffici_magnolia_legge_card_e_scarta_link_fuori_host():
    pagina = """
    <div class="card">
      <h5 class="card-title">Ufficio Anagrafe</h5>
      <a href="tel:0123456789">0123456789</a>
      <a class="read-more" href="/home/amministrazione/uffici/Ufficio-1.html">Dettagli</a>
    </div>
    <div class="card">
      <h5 class="card-title">Ufficio Tributi</h5>
      <a class="read-more" href="https://altro.example/Ufficio-2.html">Dettagli</a>
    </div>
    """

    uffici = magnolia._uffici_da_html(
        pagina,
        "https://www.comune.example/home/amministrazione/uffici.html",
        "comune.example",
        "2026-10-11T00:00:00+00:00",
    )

    assert [(u.nome, u.url) for u in uffici] == [
        ("Ufficio Anagrafe", "https://www.comune.example/home/amministrazione/uffici/Ufficio-1.html")
    ]
