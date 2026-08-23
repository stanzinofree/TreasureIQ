# TreasureIQ API
#
# Runs as an unprivileged user and installs no build toolchain into the final
# image: this container reads public data and serves a citizen-facing endpoint,
# so it should carry the minimum needed to do that and nothing else.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, in their own layer: application code changes far more
# often than requirements.txt, so this keeps rebuilds fast during development.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY treasureiq/ ./treasureiq/

# taxonomy.toml is the shared data source for the Python intent oracle
# (intent_scorer.py) AND the Rust tiq_intent crate built in the rust-builder
# stage below. Copying just this file (not the whole tiq_intent/ crate
# source) keeps the base/runtime image tiny. TIQ_TAXONOMY_PATH pins the
# lookup to this baked-in copy so it resolves regardless of CWD, and — for
# the dev stage's parity harness — regardless of a bind mount overlaying
# /src at `docker run` time (env vars survive that mount; this file does
# too, since it lives outside /src at /app).
COPY tiq_intent/taxonomy.toml ./tiq_intent/taxonomy.toml

# The committed snapshots live outside this build context (they are shared with
# the ingestion tooling), so they are mounted at /data by compose rather than
# copied in. The application resolves them relative to this variable.
ENV TREASUREIQ_DATA_DIR=/data \
    PYTHONPATH=/app \
    TIQ_TAXONOMY_PATH=/app/tiq_intent/taxonomy.toml

RUN useradd --create-home --uid 10001 treasureiq
USER treasureiq

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/status',timeout=2).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "treasureiq.api:app", "--host", "0.0.0.0", "--port", "8000"]


# --- Rust intent crate builder (perf/accumula-filtri-cache-intent-rust) -
#
# Builds tiq_intent (PyO3, mirrors chat/intent_scorer.py) as a wheel in its
# own stage, on its own base image, so the ~1GB Rust toolchain never touches
# the base/runtime image above — only the dev stage below installs the
# wheel it produces here. Reads the taxonomy at RUNTIME from disk (see
# tiq_intent/src/lib.rs), so nothing about the crate's DATA needs to be
# baked in at build time here; only its source is copied in.
FROM python:3.12-slim AS rust-builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --profile minimal --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

RUN pip install --no-cache-dir maturin

WORKDIR /build/tiq_intent
COPY tiq_intent/ ./
RUN maturin build --release --out /wheels


# --- Test stage ---------------------------------------------------------
#
# Kept out of the runtime image on purpose: the base stage above states that
# this container should carry the minimum needed to serve citizens and nothing
# else, and a test runner is not that. `make test` builds this target instead,
# so the image that faces the public never grows a dependency it does not use.
FROM base AS dev

USER root
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

# tiq_intent (Rust/PyO3): installed into site-packages, not /src, so that a
# `docker run -v $PWD/api:/src ...` bind mount (used by the parity harness)
# never shadows it — only files under /src get overlaid by that mount.
COPY --from=rust-builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl

# it_core_news_lg (ciclo 11, D-06): the ~500MB spaCy model chat/filtri.py
# loads lazily for negation scoping ("non sono disabile"). Deliberately not
# in requirements.txt (see its comment) so the base/runtime image never pays
# for it — only this test stage does, and only to exercise the real path
# instead of the cue-list fallback. spaCy models are versioned per spaCy
# release, so the wheel is pinned to the exact release that matches the
# `spacy>=3.8,<3.9` pin in requirements.txt. A failed download must not fail
# the build: filtri.py IS wired into production (B3), but its production
# path deliberately runs on the cue-list fallback, not this model — it
# degrades on its own, honestly, when the model is missing (L-5).
RUN pip install --no-cache-dir \
    "https://github.com/explosion/spacy-models/releases/download/it_core_news_lg-3.8.0/it_core_news_lg-3.8.0-py3-none-any.whl" \
    || echo "it_core_news_lg non scaricato: i test di filtri.py restano sul fallback a cue-list"
USER treasureiq

CMD ["python", "-m", "pytest", "-q"]
