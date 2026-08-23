# Ramo Intent-Scorer — Slice 7: attivazione reale del crate Rust

Stato: PIANO (pre-implementazione)
Branch previsto: `feat/ramo3-sp-increment1` (o branch dedicato `fix/intent-rust-activation`)
Perimetro: `api/treasureiq/chat/intent.py`, `api/tests/test_intent_backend_scorer.py`,
`api/tiq_intent/parity_check.py`, `Makefile`. Nessun tocco a resolver/connettori/dispatcher.

---

## 1. Problema

Il crate `tiq_intent` (PyO3) è costruito, parity-tested (35/35) e installato nello stage
`dev` dell'immagine. Ma **a runtime non viene mai interrogato**, nemmeno dove il wheel
è presente.

Catena del difetto:

| Punto | File:riga | Cosa fa |
|---|---|---|
| Engine legge il backend | `engine.py:48-49` | `TREASUREIQ_ENGINE_INTENT_BACKEND` → `engine.backend="rust"` |
| Engine chiama l'estrattore | `engine.py:78` | `extract_intent(..., backend="rust")` (param) |
| Estrattore risolve il backend effettivo | `intent.py:741` | `effective_backend = (backend or _INTENT_BACKEND)` → `"rust"` ✔ |
| Ramo deterministico | `intent.py:743-747` | entra in `_intent_dallo_scorer(message)` ✔ |
| **Scelta del crate** | `intent.py:684` | `if _INTENT_BACKEND == "rust":` ✖ — legge la **costante di modulo**, non `effective_backend` |

`_INTENT_BACKEND` (`intent.py:654`) legge `TREASUREIQ_INTENT_BACKEND`, che **non è mai
settato** in nessuno stack (compose setta solo `_ENGINE_`). Default → `"model"`.
Quindi `_score_livello_a` salta sempre `import tiq_intent` e ripiega sullo scorer Python.

Output identico (parità garantita), ma il beneficio ~6-7x è perso: il wheel è peso morto.

Perché i test non lo hanno preso: il fixture `backend_rust` (test:54) patcha proprio
`_INTENT_BACKEND="rust"` e chiama `extract_intent` **senza** param. Così esercita il ramo
crate, ma **non riproduce il path reale** (param `backend` valorizzato, costante a "model")
e **non prova** che `tiq_intent.score` sia stato chiamato (nessuna spia).

### Nota di design (non è un bug)

Lo stage `base`/`runtime` **non** installa il wheel di proposito (evita ~1GB di toolchain
Rust nell'immagine pubblica). In prod `rust` → `ImportError` → scorer Python, **voluto**.
La Slice 7 NON cambia questa scelta: rende solo effettiva l'attivazione dove il wheel c'è
(stage `dev`, o un eventuale futuro runtime che scelga di imbarcarlo).

---

## 2. Obiettivo

Rendere l'attivazione del crate governata dal backend effettivo per-richiesta, non da una
costante di modulo scollegata; provarlo con un test-spia che gira in Docker; inchiodare la
parità in un gate riproducibile.

Invarianti (non devono cambiare):
- **I-1** Rust produce solo `(topic, kind, confidence)`. Niente comune, slot, ruolo, service_key.
- **I-2** Fallback `ImportError` → scorer Python, silenzioso, fail-safe, mai crash.
- **I-3** Parità byte-esatta Rust ↔ oracolo Python su tutti i casi.
- **I-4** La cintura deterministica a valle (`_confirm_*`, R-8/R-9) gira invariata.
- **I-5** Nessuna modifica a `service_key.py`, resolver, connettori, dispatcher.

---

## 3. Attivazione reale (fix)

Thread del backend effettivo fino al punto di scelta. Tre firme cambiano, ~5 righe.

```python
# intent.py

def _score_livello_a(message: str, backend: str) -> tuple[str, str]:
    if backend == "rust":                       # era: _INTENT_BACKEND
        try:
            import tiq_intent
            topic, kind, _conf = tiq_intent.score(message)
            return topic, kind
        except ImportError:
            pass                                 # I-2: giù allo scorer Python
    esito = score_intent(message)
    return esito.topic, esito.kind


def _intent_dallo_scorer(message: str, backend: str) -> "_ModelIntent":
    topic, kind = _score_livello_a(message, backend)
    ...  # invariato


# in extract_intent, ramo deterministico:
    parsed = _intent_dallo_scorer(message, effective_backend)
```

`_INTENT_BACKEND` resta come **default** quando `extract_intent` è chiamata senza param
(chiamate diirette, alcuni test): la precedenza è `param > _INTENT_BACKEND > "model"`.

Nessun altro cambiamento di logica. Il fixture `backend_rust` esistente continua a
funzionare: patcha `_INTENT_BACKEND`, `extract_intent` senza param lo usa come default →
`effective_backend="rust"` → threaded in `_score_livello_a`. Nessun test verde diventa rosso.

---

## 4. Test runtime (prova che il wheel è davvero interrogato)

Nuovi test in `test_intent_backend_scorer.py`. Chiave: passano `backend="rust"` come
**parametro** (come fa l'engine reale), non via costante di modulo.

| Test | Setup | Asserto |
|---|---|---|
| `test_rust_param_interroga_il_crate` | `importorskip("tiq_intent")`, spia su `tiq_intent.score`, `extract_intent(..., backend="rust")` | `score` chiamato ≥1 volta; topic/kind = oracolo |
| `test_python_backend_non_chiama_il_crate` | spia-che-esplode su `tiq_intent.score` (se importabile), `backend="scorer"` | `score` **non** chiamato; esito = oracolo Python |
| `test_rust_assente_ripiega_su_python` | `sys.modules["tiq_intent"]=None` (forza `ImportError`), `backend="rust"` | nessun crash; esito = scorer Python (I-2) |
| parità (35 casi, esistente) | invariato | topic/kind Rust = oracolo |

Note implementative:
- **Spia**: dopo `importorskip`, `monkeypatch.setattr(tiq_intent, "score", spy)` dove `spy`
  incrementa un contatore e delega all'originale (per non rompere la parità dell'output).
- **Non-chiamata**: se `tiq_intent` non è importabile sull'host, il test è comunque valido
  (il crate non può essere chiamato); se importabile, la spia-che-esplode prova il contrario.
- **Assenza**: `sys.modules["tiq_intent"]=None` fa alzare `ImportError` a `import tiq_intent`
  dentro la funzione — simula l'immagine `base`/runtime senza wheel.
- Il test-spia gira in Docker (stage `dev`, wheel presente) → è la prova che chiedi che il
  nativo sia realmente interrogato.

---

## 5. Parity gate (riproducibile, senza benchmark)

`parity_check.py` oggi esiste ma nessuno lo esegue in `make test`/CI.

- Aggiungere flag `--no-benchmark` a `parity_check.py`: il gate esegue solo i 35 casi e
  ritorna exit-code sulla sola parità. Il benchmark 6-7x resta disponibile a mano ma **fuori
  dal gate** (è variabile d'ambiente, non deve far fallire la CI).
- Il parity gate gira DENTRO `make test`, nello STESSO container (no doppio build): il
  `docker run` di `test` incatena pytest e parity —
  `sh -c "python -m pytest -q && python tiq_intent/parity_check.py --no-benchmark"`.
  Cosi' una regressione di parità fa fallire il test standard, senza una seconda immagine.
- Target `parity` autonomo mantenuto per l'esecuzione on-demand (build + run isolati):
  ```make
  parity:  ## Parity gate: crate Rust vs oracolo Python (35/35), no benchmark
      docker build -q -t treasureiq-api-dev --target dev api
      docker run --rm -v "$(PWD)/api:/src" -w /src treasureiq-api-dev \
          python tiq_intent/parity_check.py --no-benchmark
  ```
- Una CI che invochi `make test` ottiene la parità gratis; `make parity` resta il gancio
  esplicito per un check mirato.

Il gate fallisce solo se un caso diverge (I-3). Mai per la velocità.

---

## 6. Contratto delle variabili

Documentare in modo esplicito (docstring di `intent.py` + `engine.py`, riga compose) le due
variabili e la loro precedenza, per evitare che indichino backend diversi senza avviso.

| Variabile | Letta da | Ruolo |
|---|---|---|
| `TREASUREIQ_ENGINE_INTENT_BACKEND` | `engine.py` (`CivicChatEngine.__init__`) | **Autorità runtime.** È ciò che compose setta (`rust`). Diventa il param `backend` di ogni chiamata a `extract_intent`. |
| `TREASUREIQ_INTENT_BACKEND` | `intent.py` (`_INTENT_BACKEND`, costante import-time) | **Default di fallback** quando `extract_intent` è chiamata senza param. Non usato dal path engine. |

Precedenza effettiva: `param backend` (da ENGINE var) **>** `_INTENT_BACKEND` (da INTENT var)
**>** `"model"`.

Guardia opzionale (raccomandata): in `CivicChatEngine.__init__`, se **entrambe** le env sono
settate e **disaccordano**, emettere un `logger.warning` una volta. Non un errore: la
precedenza resta chiara, ma il disaccordo silenzioso è il rischio che hai segnalato.

---

## 7. Perimetro (cosa NON si tocca)

- `service_key.py` — riconoscimento `ServiceKey` resta separato e invariato (I-5).
- resolver, connettori, dispatcher — nessuna modifica.
- Rust continua a produrre solo `topic, kind, confidence` (I-1).
- La scelta di non imbarcare il wheel nel runtime prod resta (§1 nota di design).

---

## 8. Sequenza di consegna

1. Fix §3 (thread `effective_backend`).
2. Test §4 (3 nuovi + parità esistente).
3. `--no-benchmark` in `parity_check.py` + target `parity` §5.
4. Docstring/contratto variabili §6 (+ warning opzionale).
5. Suite completa in Docker (dev): tutti verdi, inclusi i nuovi test-spia con wheel presente.
6. `make parity` → 35/35.
7. Commit.

Verifiche obbligatorie prima del commit:
- **V-1** con `backend="rust"` param e wheel presente, la spia prova `tiq_intent.score` chiamato.
- **V-2** con `backend="scorer"`, il crate non è chiamato.
- **V-3** con `tiq_intent` assente (`sys.modules[...]=None`), nessun crash, esito = Python.
- **V-4** `make parity` verde 35/35, senza benchmark nel gate.
- **V-5** nessun file fuori perimetro §7 modificato.
