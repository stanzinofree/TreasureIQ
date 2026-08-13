"""Suite e2e LIVE del flusso chat — colpisce i portali reali dei comuni.

NON fa parte della suite unit: la rete è lenta e i siti dei comuni cambiano.
È l'arnese di regressione/stabilità che si lancia a mano quando si vuole
verificare che il flusso chat regga end-to-end. Di default è SALTATA.

    # dentro il dev container (LLM su ollama raggiungibile, /live scrivibile):
    TREASUREIQ_E2E=1 python -m pytest tests/test_e2e_chat_live.py -v -s

Richiede:
  * `TREASUREIQ_E2E=1`      — altrimenti tutto skip.
  * un LLM raggiungibile    — extract_intent classifica kind/topic (ollama di
                              default; vedi OLLAMA_BASE_URL).
  * rete verso i comuni     — le letture del connettore sono live.
  * `/live` scrivibile      — così la scansione registra logo/piattaforma.

Il modello che verifichiamo, per ogni scenario:
  riconosci il connettore → se copre il logo lo troviamo → se espone gli uffici
  otteniamo gli orari (scheda ufficio) → se NON li espone, la risposta ripiega
  sulla ricerca web (M6). Le asserzioni sono STRUTTURALI e tolleranti alla
  deriva dei portali: verificano che il ramo giusto si accenda, non una stringa
  esatta di orario. Il dettaglio (piattaforma, logo, ufficio, access_mode,
  numero di fetch al comune) si legge nel report stampato con `-s`.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import httpx
import pytest
from starlette.testclient import TestClient

from treasureiq.integration import AccessMode

pytestmark = pytest.mark.skipif(
    os.environ.get("TREASUREIQ_E2E") != "1",
    reason="Suite e2e live: opt-in con TREASUREIQ_E2E=1 (rete verso i comuni + LLM).",
)

#: Il ramo web (M6) esiste SOLO con la chiave Brave (D-59): senza, la ricerca
#: live è assente e non viene mai sostituita — tutto degrada a M4/M5. Quindi il
#: baseline verde di questa suite dipende dall'ambiente: dove ci aspetteremmo
#: «ripiego web», senza chiave l'esito sano è il degrado onesto (connettore
#: visto, esito magro / nessun dato), non una scheda inventata.
_BRAVE = bool(os.environ.get("BRAVE_SEARCH_API_KEY"))

#: Modi d'accesso che significano «comune coperto, dato dallo store». Un comune
#: FUORI flotta non deve mai rispondere con uno di questi (sarebbe un leak).
_MODI_COPERTO = {
    AccessMode.M1_CAMPO_TIPIZZATO.value,
    AccessMode.M2_PROSA_API.value,
    AccessMode.M3_ALLEGATO.value,
}


# --- strumento: conta ogni fetch HTTP uscente, per host ------------------------

class _Contatore:
    """Patcha httpx per registrare ogni URL uscente durante una richiesta."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self._orig_send = httpx.Client.send
        self._orig_asend = httpx.AsyncClient.send

    def __enter__(self) -> "_Contatore":
        cont = self

        def _send(self, request, *a, **k):
            cont.urls.append(str(request.url))
            return cont._orig_send(self, request, *a, **k)

        async def _asend(self, request, *a, **k):
            cont.urls.append(str(request.url))
            return await cont._orig_asend(self, request, *a, **k)

        httpx.Client.send = _send
        httpx.AsyncClient.send = _asend
        return self

    def __exit__(self, *exc) -> None:
        httpx.Client.send = self._orig_send
        httpx.AsyncClient.send = self._orig_asend

    def verso(self, host: str) -> list[str]:
        return [u for u in self.urls if _host(u) == host]


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host or "?"
    except Exception:
        return "?"


# --- esito di uno scenario, in forma leggibile --------------------------------

@dataclass
class Esito:
    status: int
    reply: str
    access_mode: str | None
    office: bool
    orari: str | None
    esito_connettore: bool
    chiarimento: bool
    comuni_filtro: list[str]
    fetch_totali: int
    fetch_comune: int
    piattaforma: str | None = None
    logo: bool | None = None
    uffici_snapshot: int | None = None

    @property
    def ramo(self) -> str:
        # Ordine deliberato: la presenza di una scheda ufficio è il segnale più
        # forte, poi il chiarimento, poi i modi d'accesso. Un ufficio SENZA
        # orari è comunque il ramo UFFICIO (l'orario può non essere pubblicato).
        if self.office:
            return "UFFICIO"
        if self.chiarimento:
            return "CHIARIMENTO"                     # «quale ufficio?»
        if self.esito_connettore:
            return "ELENCO"                          # dump uffici, nessun match
        if self.access_mode == AccessMode.M6_WEB_APERTO.value:
            return "WEB"                             # ricerca web (serve Brave)
        if self.access_mode == AccessMode.M5_NESSUNO.value:
            return "NESSUNO"                         # nessun canale ha reso il dato
        if self.access_mode == AccessMode.M4_CONNETTORE.value:
            return "CONNETTORE"                      # connettore visto, esito magro
        if self.access_mode in (
            AccessMode.M1_CAMPO_TIPIZZATO.value,
            AccessMode.M2_PROSA_API.value,
            AccessMode.M3_ALLEGATO.value,
        ):
            return "COPERTO"                         # comune coperto, dato dallo store
        return "ALTRO"


def _esegui(client: TestClient, message: str, comune_istat: str, host_comune: str) -> Esito:
    with _Contatore() as cont:
        t0 = time.time()
        r = client.post("/api/chat", json={"message": message})
        dt = time.time() - t0

    body = r.json() if r.status_code == 200 else {}
    info = body.get("info") if isinstance(body.get("info"), dict) else {}
    office = (info or {}).get("office") if isinstance(info, dict) else None
    filtri = body.get("filtri") or []
    comuni = [f.get("valore") for f in filtri if f.get("chiave") == "comune"]

    es = Esito(
        status=r.status_code,
        reply=(body.get("reply") or "").strip(),
        access_mode=body.get("access_mode"),
        office=office is not None,
        orari=(office or {}).get("orari") if isinstance(office, dict) else None,
        esito_connettore=body.get("esito_connettore") is not None,
        chiarimento=body.get("chiarimento") is not None,
        comuni_filtro=comuni,
        fetch_totali=len(cont.urls),
        fetch_comune=len(cont.verso(host_comune)),
    )

    # scheda registro (logo/piattaforma) — best effort: la scansione la scrive
    # durante la chat, ma può 404 se /live non è scrivibile o il comune è muto.
    reg = client.get(f"/api/registro/{comune_istat}")
    if reg.status_code == 200:
        rb = reg.json()
        es.piattaforma = rb.get("piattaforma")
        es.logo = bool(rb.get("logo_b64"))
        es.uffici_snapshot = len(rb.get("uffici_snapshot") or [])

    _stampa(message, dt, es)
    return es


def _stampa(message: str, dt: float, es: Esito) -> None:
    print(f"\n┌─ {message}")
    print(f"│  ramo={es.ramo}  access_mode={es.access_mode}  wall={dt:.1f}s")
    print(f"│  piattaforma={es.piattaforma}  logo={es.logo}  uffici_snapshot={es.uffici_snapshot}")
    print(f"│  office={es.office}  orari={(es.orari or '')[:60]!r}  comuni_filtro={es.comuni_filtro}")
    print(f"│  fetch: totali={es.fetch_totali}  al_comune={es.fetch_comune}")
    print(f"└─ reply: {es.reply[:160]!r}")


# --- gli scenari --------------------------------------------------------------

@dataclass
class Scenario:
    id: str
    message: str
    istat: str
    host: str
    coperto: bool
    #: rami accettabili per questo scenario (il flusso può divergere per la
    #: deriva dei portali; qui diciamo quali esiti consideriamo "sano").
    rami_ok: tuple[str, ...]
    #: True se ci aspettiamo che il connettore esponga il logo alla scansione.
    logo_atteso: bool = False


# Rami sani condivisi. Con la chiave Brave si aggiunge WEB (ripiego live). Senza,
# per un comune non coperto l'esito sano è il degrado onesto: connettore visto
# ma esito magro (CONNETTORE) o nessun dato (NESSUNO).
_WEB = ("WEB",) if _BRAVE else ()
_UFFICIO_SANO = ("UFFICIO", "CHIARIMENTO", "ELENCO", "CONNETTORE", "NESSUNO") + _WEB

SCENARI = [
    Scenario(
        id="albano-leva",
        message="ciao sono mirella ho 42 anni e sono di Albano Laziale, cercavo gli orari dell'ufficio di leva",
        istat="058003",
        host="www.comune.albanolaziale.rm.it",
        coperto=True,
        # «leva» spesso non è un ufficio a sé: scheda ufficio, elenco, chiarimento
        # o (comune coperto) risposta dallo store — non un errore/vuoto.
        rami_ok=_UFFICIO_SANO + ("COPERTO",),
    ),
    Scenario(
        id="busto-leva",
        message="Ciao volevo sapere gli orari dell'ufficio di leva di Busto Arsizio",
        istat="012026",
        host="www.comune.bustoarsizio.va.it",
        coperto=False,
        rami_ok=_UFFICIO_SANO,
        # Municipium pubblica lo stemma, ma su CDN vendor (municipiumapp.it): il
        # host_guard lo scarta come fuori-host, quindi il registro NON lo espone.
        # Il logo qui è solo diagnostico, non atteso. (scoperta ciclo18i)
        logo_atteso=False,
    ),
    Scenario(
        id="calenzano-anagrafe",
        message="Ciao sono Andrea e cercavo gli orari dell'anagrafe di Calenzano",
        istat="048005",
        host="www.comune.calenzano.fi.it",
        coperto=False,
        rami_ok=_UFFICIO_SANO,
    ),
    Scenario(
        id="sesto-calende-anagrafe",
        message="Ciao vorrei gli orari dell'anagrafe di Sesto Calende",
        istat="012120",
        host="www.comune.sesto-calende.va.it",
        coperto=False,
        rami_ok=_UFFICIO_SANO,
    ),
    Scenario(
        id="ariccia-anagrafe-coperto",
        message="orari ufficio anagrafe di Ariccia",
        istat="058009",
        host="www.comune.ariccia.rm.it",
        coperto=True,  # comune "a caso" fra i coperti
        rami_ok=_UFFICIO_SANO + ("COPERTO",),
    ),
    Scenario(
        id="genzano-non-coperto-web",
        message="orari ufficio anagrafe di Genzano di Roma",
        istat="058043",
        host="www.comune.genzanodiroma.rm.it",
        # Fuori flotta connettori (Drupal+jcitygov, nessuno store). Con Brave deve
        # ripiegare sul web; senza, l'esito sano è il degrado onesto. In nessun
        # caso deve fingersi «coperto» (M1/M2/M3) — quello è il vero leak da
        # sorvegliare (asserito sotto, non via rami_ok).
        coperto=False,
        rami_ok=_UFFICIO_SANO,
    ),
]


@pytest.fixture(scope="module")
def client() -> TestClient:
    from treasureiq.api import app
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("sc", SCENARI, ids=[s.id for s in SCENARI])
def test_scenario(client: TestClient, sc: Scenario) -> None:
    es = _esegui(client, sc.message, sc.istat, sc.host)

    # 1) la richiesta non deve mai fallire né tornare vuota.
    assert es.status == 200, f"[{sc.id}] HTTP {es.status}"
    assert es.reply, f"[{sc.id}] reply vuota"

    # 2) il comune riconosciuto è quello nominato (nessun leak di un altro
    #    comune sotto la domanda — R-9). Tollerante se il filtro comune è muto
    #    (il comune può arrivare da profilo/tendina), ma se c'è deve combaciare.
    if es.comuni_filtro:
        assert sc.istat in es.comuni_filtro, (
            f"[{sc.id}] comune atteso {sc.istat}, filtri={es.comuni_filtro}"
        )

    # 3) il ramo del flusso è fra quelli sani per lo scenario.
    assert es.ramo in sc.rami_ok, (
        f"[{sc.id}] ramo {es.ramo} non atteso (ok: {sc.rami_ok}). "
        f"access_mode={es.access_mode}  brave={_BRAVE}"
    )

    # 4) un ufficio SENZA orari è legittimo (l'orario può non essere pubblicato:
    #    R-15, l'assenza di dato non è un errore). Non lo asseriamo come fallimento;
    #    resta visibile nel report. Ci basta che la scheda ci sia quando c'è.

    # 5) un comune FUORI copertura non deve MAI rispondere come «coperto»
    #    (M1/M2/M3 = dato dallo store): sarebbe un leak da comune sbagliato.
    if not sc.coperto:
        assert es.access_mode not in _MODI_COPERTO, (
            f"[{sc.id}] comune fuori flotta risponde come coperto "
            f"(access_mode={es.access_mode})"
        )

    # 6) logo: dove ce lo aspettiamo, la scansione deve averlo trovato.
    #    Soft: se il registro non è disponibile (es.logo is None) non fallisce.
    if sc.logo_atteso and es.logo is not None:
        assert es.logo, f"[{sc.id}] logo atteso ma non trovato nel registro"

    # 7) scenario web: con la chiave Brave, un comune fuori flotta deve ripiegare
    #    davvero sul web (o dichiarare nessun dato), mai inventare una scheda.
    if sc.id == "genzano-non-coperto-web" and _BRAVE:
        assert es.ramo in ("WEB", "NESSUNO"), (
            f"[{sc.id}] con Brave attivo atteso ripiego web, ramo={es.ramo}"
        )
