"""Politica di fetch per uno sweep gentile: backoff, rate-limit, budget.

Fase 2D-ii. Uno sweep nazionale bussa a migliaia di host: senza una politica
esplicita rischia di martellare un dominio lento (scortesia + ban) e di sprecare
richieste su endpoint morti. Qui vivono le tre decisioni, tenute **pure e
deterministiche** iniettando l'orologio (`now`) invece di leggerlo — così si
testano senza dormire e senza flakiness.

Tre pezzi componibili:
- `backoff_secondi`: quanto aspettare dopo N fallimenti di rete consecutivi
  (il contatore lo tiene `EndpointState`, 2D-i).
- `LimitatoreDominio`: intervallo minimo fra due richieste allo stesso dominio.
- `BudgetDominio`: tetto di richieste per dominio in una passata.

`PoliticaFetch` li fonde in una sola decisione, punto di aggancio per il worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit


def dominio_di(url: str) -> str:
    """Host normalizzato (minuscolo, senza `www.`) usato come chiave di dominio.

    `www.comune.x` e `comune.x` sono lo stesso host da rispettare: contarli
    separati raddoppierebbe il budget e dimezzerebbe la cortesia.
    """
    host = urlsplit(url).netloc.lower()
    if "@" in host:  # eventuale userinfo, non fa parte del dominio
        host = host.rsplit("@", 1)[1]
    if ":" in host:  # porta
        host = host.rsplit(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def backoff_secondi(
    fallimenti_consecutivi: int,
    *,
    base: float = 60.0,
    fattore: float = 2.0,
    cap: float = 3600.0,
) -> float:
    """Attesa esponenziale dopo `fallimenti_consecutivi` guasti di rete.

    Zero fallimenti → zero attesa. Poi `base`, `base·fattore`, `base·fattore²`…
    fino al `cap`, per non aspettare ore su un host semplicemente lento.
    """
    if fallimenti_consecutivi <= 0:
        return 0.0
    ritardo = base * (fattore ** (fallimenti_consecutivi - 1))
    return min(cap, ritardo)


class LimitatoreDominio:
    """Impone un intervallo minimo fra richieste allo stesso dominio.

    Stato mutabile (l'ultimo istante per dominio) ma deciso su un `now`
    iniettato: `attesa` non dorme, dice solo *quanto* dormire.
    """

    def __init__(self, *, intervallo_minimo_s: float = 1.0) -> None:
        self._intervallo = max(0.0, intervallo_minimo_s)
        self._ultimo: dict[str, datetime] = {}

    def attesa(self, url: str, now: datetime) -> float:
        """Secondi da aspettare prima di poter interrogare `url`, 0 se subito."""
        ultimo = self._ultimo.get(dominio_di(url))
        if ultimo is None:
            return 0.0
        trascorso = (now - ultimo).total_seconds()
        return max(0.0, self._intervallo - trascorso)

    def registra(self, url: str, now: datetime) -> None:
        """Segna che il dominio di `url` è stato interrogato a `now`."""
        self._ultimo[dominio_di(url)] = now


class BudgetDominio:
    """Tetto di richieste per dominio.

    Due semantiche, scelte da ``finestra_s``:

    - ``finestra_s=None`` (default): tetto **per-passata**, nessun reset — la
      semantica storica dello sweep, che vive una sola passata. Immutata.
    - ``finestra_s`` impostata: **finestra scorrevole per-dominio** — trascorsi
      ``finestra_s`` secondi dal primo consumo di un dominio, il **solo**
      conteggio di quel dominio si azzera. Serve al coordinatore di processo
      (Slice 5): un budget senza reset lo bloccherebbe per sempre una volta
      esaurito. Il reset tocca **solo** il budget: rate-limit e backoff sono
      discipline separate, gestite altrove.

    Le decisioni con finestra dipendono dall'orologio, quindi ``now`` va passato
    (iniettabile per il test). Senza finestra ``now`` è ignorato.
    """

    def __init__(self, *, massimo: int, finestra_s: float | None = None) -> None:
        if massimo < 1:
            raise ValueError("il budget per dominio deve essere >= 1")
        if finestra_s is not None and finestra_s <= 0:
            raise ValueError("la finestra del budget deve essere > 0 o None")
        self._massimo = massimo
        self._finestra_s = finestra_s
        self._conteggio: dict[str, int] = {}
        self._inizio_finestra: dict[str, datetime] = {}

    def _forse_reset(self, dominio: str, now: datetime | None) -> None:
        if self._finestra_s is None or now is None:
            return
        inizio = self._inizio_finestra.get(dominio)
        if inizio is None:
            self._inizio_finestra[dominio] = now
            return
        if (now - inizio).total_seconds() >= self._finestra_s:
            self._conteggio[dominio] = 0
            self._inizio_finestra[dominio] = now

    def rimanente(self, url: str, now: datetime | None = None) -> int:
        dominio = dominio_di(url)
        self._forse_reset(dominio, now)
        return max(0, self._massimo - self._conteggio.get(dominio, 0))

    def disponibile(self, url: str, now: datetime | None = None) -> bool:
        return self.rimanente(url, now) > 0

    def consuma(self, url: str, now: datetime | None = None) -> None:
        dominio = dominio_di(url)
        # Avvia la finestra al primo consumo così che possa poi scadere anche se
        # `disponibile` non è stata chiamata prima.
        if self._finestra_s is not None and now is not None:
            self._inizio_finestra.setdefault(dominio, now)
        self._conteggio[dominio] = self._conteggio.get(dominio, 0) + 1


@dataclass(frozen=True)
class DecisioneFetch:
    """Esito della politica: se interrogare, dopo quanta attesa, e perché no."""

    consentito: bool
    attesa_s: float
    motivo: str


class PoliticaFetch:
    """Fonde rate-limit, budget e backoff in una decisione sola.

    Punto di aggancio per il worker (2D wiring): prima di ogni fetch chiama
    `decidi`; se `consentito`, aspetta `attesa_s`, interroga, poi `registra`.
    """

    def __init__(
        self,
        *,
        intervallo_minimo_s: float = 1.0,
        massimo_per_dominio: int = 50,
        backoff_base_s: float = 60.0,
        backoff_cap_s: float = 3600.0,
        finestra_budget_s: float | None = None,
    ) -> None:
        self._limitatore = LimitatoreDominio(intervallo_minimo_s=intervallo_minimo_s)
        self._budget = BudgetDominio(
            massimo=massimo_per_dominio, finestra_s=finestra_budget_s
        )
        self._backoff_base = backoff_base_s
        self._backoff_cap = backoff_cap_s

    def decidi(
        self, url: str, now: datetime, *, fallimenti_consecutivi: int = 0
    ) -> DecisioneFetch:
        """Se e quando interrogare `url`. Non muta nulla: solo decide."""
        if not self._budget.disponibile(url, now):
            return DecisioneFetch(False, 0.0, "budget_esaurito")
        attesa = max(
            self._limitatore.attesa(url, now),
            backoff_secondi(
                fallimenti_consecutivi,
                base=self._backoff_base,
                cap=self._backoff_cap,
            ),
        )
        return DecisioneFetch(True, attesa, "ok")

    def registra(self, url: str, now: datetime) -> None:
        """Da chiamare **dopo** un fetch effettivo: consuma budget e rate-limit."""
        self._limitatore.registra(url, now)
        self._budget.consuma(url, now)
