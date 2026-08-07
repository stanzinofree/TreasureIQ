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

# --- Test ---------------------------------------------------------------
# Girano nello stage `dev` del Dockerfile, non nell'immagine di runtime: quella
# serve i cittadini e non deve portarsi dietro un test runner (vedi Dockerfile).

.PHONY: test
test: ## Esegue la suite nello stage dev
	docker build -q -t treasureiq-api-dev --target dev api
	docker run --rm \
		-v "$(PWD)/api:/src" -v "$(PWD)/data:/data:ro" \
		-e TREASUREIQ_DATA_DIR=/data -w /src \
		treasureiq-api-dev python -m pytest -q

# --- Dati ---------------------------------------------------------------

.PHONY: stato-dati
stato-dati: ## Cosa c'e' nei dati curati e in quelli letti dal vivo
	docker compose exec -T api python -m treasureiq.dati_cli stato

.PHONY: promuovi
promuovi: ## Prepara la voce enti.json di un comune gia' letto: make promuovi COMUNE='Arquata Scrivia'
	@test -n "$(COMUNE)" || { echo "manca COMUNE, es. make promuovi COMUNE='Arquata Scrivia'"; exit 1; }
	docker compose exec -T api python -m treasureiq.dati_cli promuovi "$(COMUNE)"

.PHONY: scalda-cache
scalda-cache: ## Sonda ora i comuni della demo: make scalda-cache COMUNI='Trento "Arquata Scrivia"'
	@test -n "$(COMUNI)" || { echo "manca COMUNI, vedi demo/copione.md"; exit 1; }
	docker compose exec -T api sh -c "python -m treasureiq.sonda_live $(COMUNI)"

.PHONY: frame-nazionale
frame-nazionale: ## Ricostruisce data/comuni-istat.json da ISTAT e IPA (scarica ~10 MB)
	docker compose run --rm -T -v "$(PWD)/data:/scrivibile" api \
		python -m treasureiq.ingest.comuni_istat --out /scrivibile/comuni-istat.json

.PHONY: censimento
censimento: ## Rifa' la misura T0 sul campione: make censimento N=400
	docker compose run --rm -T -v "$(PWD)/data:/scrivibile" api \
		python -m treasureiq.ingest.censimento --campione $(or $(N),400) --seme 2026 \
		--out /scrivibile/censimento-esiti.json
