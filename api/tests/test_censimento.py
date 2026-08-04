"""Test sull'estrazione della prova.

Tutti i casi qui sotto sono difetti realmente occorsi durante la costruzione
del censimento, non ipotesi: ognuno ha prodotto, su un portale vero, una
citazione sbagliata che sarebbe finita davanti a un cittadino. Restano scritti
perché la citazione è l'unica cosa che autorizza TreasureIQ a mostrare un
orario, e un difetto lì non si vede — la risposta continua ad avere l'aria di
essere precisa.
"""

from __future__ import annotations

import pytest

from treasureiq.ingest.censimento import ORARIO_RE, _cita


def cita(testo: str) -> str | None:
    trovato = ORARIO_RE.search(testo)
    return _cita(testo, trovato) if trovato else None


def test_intervallo_completo_non_solo_apertura():
    """La prima versione citava «Venerdì: 08.30», leggibile come "chiude alle
    8:30". Una citazione troncata è peggio di nessuna citazione."""
    assert cita("Venerdì: 08.30 - 12.30.") == "Venerdì: 08.30 - 12.30"


def test_orario_settimanale_intero():
    """Fermarsi alla prima riga direbbe che l'ufficio apre solo il lunedì."""
    testo = "Orari lunedì 15.00 - 17.30, martedì 9.00 - 12.00, sabato 9.00 - 11.30."
    citazione = cita(testo)
    assert "15.00 - 17.30" in citazione
    assert "9.00 - 11.30" in citazione


def test_il_centralino_non_e_un_orario():
    """`60.04` dentro «+39.0143.60.04.05» ha la forma di un'ora e stava a
    poche decine di caratteri da «sabato»: finiva dentro la citazione."""
    citazione = cita("Orari sabato 9.00 - 11.30 Telefono +39.0143.60.04.05")
    assert "+39" not in citazione
    assert citazione.endswith("11.30")


def test_un_giorno_senza_ora_non_e_un_orario():
    """"lunedì" da solo compare in mezzo mondo."""
    assert cita("Il consiglio si riunisce il lunedì in sala consiliare.") is None


def test_una_ora_senza_giorno_non_e_un_orario():
    assert cita("Il contributo ammonta a 12.50 euro per nucleo.") is None


def test_la_citazione_parte_dall_etichetta_non_dall_indirizzo():
    """Senza l'ancoraggio, metà della prova era l'indirizzo del municipio."""
    testo = "Sede Via Fabbri, 10 26030 Tornata (CR) Orari di apertura martedì 9.00 - 12.30"
    citazione = cita(testo)
    assert "Fabbri" not in citazione
    # Il taglio si dichiara: una citazione accorciata che non lo dice finge di
    # essere completa.
    assert citazione == "[…] Orari di apertura martedì 9.00 - 12.30"


def test_i_campi_in_fila_non_sono_una_frase():
    """Le schede AGID possono non contenere un solo punto fermo: senza `|`
    come confine l'espansione partiva dall'inizio della pagina e tagliava via
    proprio l'orario."""
    testo = "Contatti | Piazza della Costituente 1 | Email: urp@x.it | ORARIO Lunedì: 08.30 - 11.00"
    citazione = cita(testo)
    assert "Piazza" not in citazione
    assert "08.30 - 11.00" in citazione


@pytest.mark.parametrize(
    "testo, atteso",
    [
        ("Apertura lunedì dalle 9:00 alle 13:00.", "9:00"),
        ("Ricevimento del pubblico mercoledì 9.00-13.00 e 14.00-16.00.", "14.00-16.00"),
    ],
)
def test_formati_diversi_della_stessa_cosa(testo: str, atteso: str):
    assert atteso in cita(testo)
