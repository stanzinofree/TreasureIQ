from treasureiq.catalog.contracts import Surface
from treasureiq.catalog.recognition_adapter import firma_da_registro
from treasureiq.ingest.piattaforma import Piattaforma


def _firma(html: str):
    return firma_da_registro(
        headers={}, html=html, surface=Surface.ORDINARY_DATA,
        source_id="033019", entrypoint_url="https://www.comune.farini.pc.it",
    )


def test_kibernetes_due_asset_riconosce_magnolia():
    html = '''<link href="/.resources/kibernetes/webresources/manifest.json">
      <link href="/.imaging/mte/kibernetes/stemma/dam/icons/logo.webp">'''
    firma = _firma(html)
    assert firma.piattaforma is Piattaforma.MAGNOLIA
    assert "Kibernetes" in firma.prova


def test_un_solo_asset_non_basta():
    firma = _firma('<link href="/.resources/kibernetes/webresources/manifest.json">')
    assert firma.piattaforma is Piattaforma.IGNOTA
