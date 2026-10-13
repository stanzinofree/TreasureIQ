# AGENTS.md — TreasureIQ

Instructions for coding agents and contributors. Humans start from `README.md`
(Italian); this file is commands and boundaries, not a tour. Security policy:
`SECURITY.md`; threat model and abuse limits: `docs/sicurezza.md`.

## Stack

Three parts, run together with Docker Compose:

| Part | Path | Tech |
|---|---|---|
| API, engine, connectors, ingestion | `api/` | Python, FastAPI, pytest |
| Intent scorer | `api/tiq_intent/` | Rust crate (PyO3), with an equivalent Python fallback |
| Web | `web/` | Next.js; proxies `/api` to the API |

The chat works without a model (deterministic engine text); Ollama or Anthropic
only narrate. LLM extraction in ingestion needs `ANTHROPIC_API_KEY`; web search
needs `BRAVE_SEARCH_API_KEY`.

## Commands

```bash
make up                      # build on first run, start api (:8010) and web (:3000)
make status                  # containers, GET /api/health, Ollama check
make test                    # pytest + Rust/Python intent parity, in the Dockerfile `dev` stage
make parity                  # Rust intent crate vs Python oracle only
cd api && uvx ruff check .   # lint, policy in api/ruff.toml
cd api/tiq_intent && cargo clippy
cd web && npm run build      # web check (ESLint is not configured yet)
```

`make help` lists every target.

## Network and data: ask first

These targets hit real municipal portals or rewrite local data. Never run them
unless the user asks explicitly:
`scalda-cache`, `sweep*`, `scan-misurabili`, `registro-*`, `frame-nazionale`,
`restore`, `rebuild`.
Crawling follows the courtesy rules in `docs/sicurezza.md` §2 (rate, robots, user agent).

## Where things go

| Adding… | Put it in | Note |
|---|---|---|
| municipal connector / site recognition | `api/` connector and plugin modules, with a test in `api/tests/` | follow the existing recognition plugins |
| intent / taxonomy | `api/tiq_intent/taxonomy.toml` | `make parity` must stay 100% |
| API endpoint | `api/` FastAPI app | degrade to deterministic text when the model is down |
| UI | `web/` | match the existing components and tokens |

## Invariants

- **Degradation contract** (see `api/ruff.toml`): the chat answers from engine
  text when the model is unreachable; a failed web search writes nothing. Broad
  `except` at those boundaries is intentional; do not narrow it.
- Rust intent crate and Python oracle must agree (`make parity`).
- Text scraped from portals is untrusted input: never let it become
  instructions to a model (prompt injection, `docs/sicurezza.md` §3).
- Citizen profile data goes to models only as needed and never to logs.
- SPID is simulated for the hackathon: no real credential is ever verified or stored.

## Never

- Read, print or commit `.env` or any API key.
- Commit `data-live/` content, local databases or backups. Never `git add -A`.
- Push to `main` directly: branch + PR.

## Done means

Baseline on 2026-10-13: `make test` has 15 known failures (data-driven tests in
`test_measurement_sweep`, `test_monitoraggio` and two recognition tests) and
ruff 0.17 reports 108 findings, mostly import order. Until that is cleaned up:

1. `make test`: no new failures beyond the baseline; parity unchanged.
2. `uvx ruff check` clean on every Python file you touched.
3. Rust change: `cargo clippy` clean. Web change: `npm run build` passes.
4. Public repo: no personal data, keys or internal hostnames in code, tests,
   commits or PR text.
