# TreasureIQ — dev environment.
#
# Requires:
#   - Docker runtime (this repo targets OrbStack: `orbctl start`)
#   - Ollama on :11434 for the full chat path (deterministic fallback works
#     without it, but the model-backed answers do not)
#
# First run:   make up        (builds the api/web images, then starts them)
# After edits: make restart   (or make rebuild if the image itself changed)

COMPOSE   := docker compose
COMPOSE_PROFILE_INGEST := docker compose --profile ingest

.PHONY: help up down restart rebuild build logs ps status \
        up-ingest down-ingest ollama-check

.DEFAULT_GOAL := help

help:
	@echo "TreasureIQ targets"
	@echo "  make up             build (first run) + start api:8010, web:3000"
	@echo "  make restart        stop + start the stack again"
	@echo "  make down           stop the stack (containers removed)"
	@echo "  make rebuild        rebuild images from source, then up"
	@echo "  make build          rebuild images only (no start)"
	@echo "  make logs           tail api + web logs (ctrl-c to stop)"
	@echo "  make ps             container status"
	@echo "  make up-ingest      start the ingestion-only searxng service"
	@echo "  make down-ingest    stop searxng"

ollama-check:
	@if curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then \
		echo "ollama:  up   (chat answers will be model-backed)"; \
	else \
		echo "ollama:  DOWN — chat falls back to deterministic answers (run \`ollama serve\` for the full demo)"; \
	fi

up: ollama-check
	$(COMPOSE) up -d --build api web
	@echo
	@echo "  API  → http://localhost:8010"
	@echo "  web  → http://localhost:3000"
	@$(COMPOSE) ps

restart: down up

rebuild: build up

build:
	$(COMPOSE) build api web

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

status: ollama-check
	$(COMPOSE) ps
	@curl -s --max-time 3 http://localhost:8010/api/health && echo "  ← api /api/health" || echo "api /api/health: unreachable"

up-ingest:
	$(COMPOSE_PROFILE_INGEST) up -d searxng

down-ingest:
	$(COMPOSE_PROFILE_INGEST) down
