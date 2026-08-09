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

# The committed snapshots live outside this build context (they are shared with
# the ingestion tooling), so they are mounted at /data by compose rather than
# copied in. The application resolves them relative to this variable.
ENV TREASUREIQ_DATA_DIR=/data \
    PYTHONPATH=/app

RUN useradd --create-home --uid 10001 treasureiq
USER treasureiq

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=2).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "treasureiq.api:app", "--host", "0.0.0.0", "--port", "8000"]


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
