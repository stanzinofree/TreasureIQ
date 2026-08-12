"""Il normalizzatore deterministico degli orari (`orari_schema`).

Copre: recall dei giorni abbreviati (il caso comweb/Aglié che sfuggiva al
riconoscitore del censimento), la resa in forma normalizzata, la distinzione
intervallo-vs-lista, i doppi turni, le cifre tenute verbatim, e la non-cattura
di numeri che non sono orari (telefoni).
"""

from __future__ import annotations

from treasureiq.orari_schema import estrai_orario_strutturato as E


def test_giorni_abbreviati_compatti_estrae_e_rende() -> None:
    # Il caso reale di Aglié (comweb): giorni abbreviati concatenati da trattini
    # + una fascia. Il riconoscitore del censimento (nomi interi) lo mancava.
    r = E("<div>Orario Lun-Mar-Mer-Gio-Ven-Sab 09.00 - 12.00</div>")
    assert r is not None
    assert r.reso == "Lun–Sab: 09.00–12.00"
    assert len(r.righe) == 1
    assert r.righe[0].giorni == [0, 1, 2, 3, 4, 5]
    assert r.righe[0].fasce[0].apertura == "09.00"
    assert r.righe[0].fasce[0].chiusura == "12.00"


def test_fonte_verbatim_conserva_le_cifre_dalla_pagina() -> None:
    # D-07: i token orari sono sottostringhe byte-identiche della pagina, e la
    # fonte verbatim resta ricontrollabile.
    r = E("<p>Lun-Ven 9.00-13.00</p>")
    assert r is not None
    assert "9.00-13.00" in r.testo_grezzo
    assert r.righe[0].fasce[0].apertura == "9.00"  # non normalizzato a 09:00


def test_due_giorni_col_trattino_e_intervallo() -> None:
    r = E("<p>Lunedì-Venerdì 08:30-13:00</p>")
    assert r is not None
    assert r.righe[0].giorni == [0, 1, 2, 3, 4]  # espanso lun..ven
    assert r.reso == "Lun–Ven: 08:30–13:00"


def test_giorni_sparsi_restano_lista_non_intervallo() -> None:
    # «Lun-Mer-Ven» (tre giorni concatenati) è una lista letterale, non
    # lun..ven: espanderlo direbbe che l'ufficio apre anche mar e gio.
    r = E("<p>Lun-Mer-Ven 9.00-12.00</p>")
    assert r is not None
    assert r.righe[0].giorni == [0, 2, 4]
    assert r.reso == "Lun, Mer, Ven: 9.00–12.00"


def test_giorni_con_e_sono_lista() -> None:
    r = E("<p>Martedì e Venerdì: 08.30 - 11.00</p>")
    assert r is not None
    assert r.righe[0].giorni == [1, 4]
    assert r.reso == "Mar, Ven: 08.30–11.00"


def test_doppio_turno_due_fasce() -> None:
    r = E("<p>Lunedì-Venerdì 08:30-13:00 e 14:00-17:00</p>")
    assert r is not None
    assert len(r.righe[0].fasce) == 2
    assert r.reso == "Lun–Ven: 08:30–13:00 e 14:00–17:00"


def test_righe_distinte_giorni_diversi() -> None:
    r = E("<p>Lunedì 10:00-13:00 – Giovedì 15:00-17:00</p>")
    assert r is not None
    assert len(r.righe) == 2
    assert r.reso == "Lunedì: 10:00–13:00 · Giovedì: 15:00–17:00"


def test_giorno_singolo_nome_intero() -> None:
    r = E("<p>Ricevimento il martedì 09:00-12:00</p>")
    assert r is not None
    assert r.reso == "Martedì: 09:00–12:00"


def test_apertura_senza_chiusura_e_onesta() -> None:
    r = E("<p>Sabato ore 9:00</p>")
    assert r is not None
    assert r.righe[0].fasce[0].apertura == "9:00"
    assert r.righe[0].fasce[0].chiusura is None
    assert r.reso == "Sabato: 9:00"


def test_numero_di_telefono_non_e_un_orario() -> None:
    # Nessun giorno vicino: «+39.0143.60.04.05» non deve diventare una fascia.
    assert E("<p>telefono +39.0143.60.04.05, nessun orario</p>") is None


def test_pagina_senza_orari_ritorna_none() -> None:
    assert E("<p>Questa pagina non pubblica alcun orario.</p>") is None


def test_ora_lontana_dal_giorno_non_fa_riga() -> None:
    # Un giorno e, sessanta caratteri più in là, un'ora slegata: non è un
    # orario di quel giorno.
    testo = "<p>Il lunedì " + ("x" * 70) + " costo 12.50 euro</p>"
    assert E(testo) is None
