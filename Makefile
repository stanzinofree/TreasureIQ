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

.PHONY: help up down restart rebuild build logs ps status \
        ollama-check \
        scan-nazionale scan-misurabili sweep sweep-worker sweep-worker-once sweep-worker-stop registro-nazionale registro-scan registro-list \
        backup restore

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
	@echo "  make scan-nazionale     censimento asse-A su tutti i comuni -> storico.db (pesante, resumable)"
	@echo "  make scan-misurabili    pass profondo + aderenza sui comuni leggibili gia' nel db"
	@echo "  make sweep              censimento+registro per un set in un run: ISTAT='058057'"
	@echo "  make sweep-worker       worker Docker continuo: BATCH=20 INTERVAL=120"
	@echo "  make sweep-worker-once  esegue un solo batch del worker"
	@echo "  make sweep-worker-stop  ferma il worker dello sweep"
	@echo "  make registro-nazionale popola data-live/registro per i comuni leggibili"
	@echo "  make registro-scan      scan di uno o piu' comuni: ISTAT='058057'"
	@echo "  make registro-list      elenca i record nel registro"
	@echo "  make backup             tar di storico.db + data-live/ in backups/"
	@echo "  make restore            ripristina un backup: FILE=backups/....tgz"

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

rebuild: backup build up

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

# --- Test ---------------------------------------------------------------
# Girano nello stage `dev` del Dockerfile, non nell'immagine di runtime: quella
# serve i cittadini e non deve portarsi dietro un test runner (vedi Dockerfile).

.PHONY: test
test: ## Esegue la suite nello stage dev
	docker build -q -t treasureiq-api-dev --target dev api
	docker run --rm \
		-v "$(PWD)/api:/src" -v "$(PWD)/data:/data:ro" \
		--tmpfs /test-state:rw,exec,nosuid,nodev \
		-e TREASUREIQ_DATA_DIR=/data \
		-e TREASUREIQ_CONVERSATION_DB=/test-state/conversations.sqlite3 -w /src \
		treasureiq-api-dev sh -c \
		"python -m pytest -q && python tiq_intent/parity_check.py --no-benchmark"

.PHONY: parity
parity: ## Gate parità crate Rust vs oracolo Python (35/35), senza benchmark
	docker build -q -t treasureiq-api-dev --target dev api
	docker run --rm -v "$(PWD)/api:/src" -w /src \
		treasureiq-api-dev python tiq_intent/parity_check.py --no-benchmark

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

.PHONY: verify-frame
verify-frame: ## Verifica (dura) data/comuni-istat.json contro il suo manifest
	docker compose run --rm -T -v "$(PWD)/data:/data:ro" api \
		python -m treasureiq.ingest.comuni_istat --verifica /data/comuni-istat.json

.PHONY: frame-diff
frame-diff: ## Report transizioni: confronta il frame con l'elenco ISTAT fresco (solo lettura)
	docker compose run --rm -T -v "$(PWD)/data:/scrivibile" api \
		python -m treasureiq.ingest.comuni_istat --diff /scrivibile/comuni-istat.json

.PHONY: censimento
censimento: ## Rifa' la misura T0 sul campione: make censimento N=400
	docker compose run --rm -T -v "$(PWD)/data:/scrivibile" api \
		python -m treasureiq.ingest.censimento --campione $(or $(N),400) --seme 2026 \
		--out /scrivibile/censimento-esiti.json

.PHONY: scan-nazionale
scan-nazionale: ## Censimento asse-A su TUTTI i comuni -> storico.db + catalog/ (gentile e resumable)
	docker compose run --rm -T -v "$(PWD)/data:/scrivibile" api \
		python -m treasureiq.ingest.censimento --tutti --db /scrivibile/storico.db \
		--lavoratori $(or $(LAVORATORI),6)

.PHONY: scan-misurabili
scan-misurabili: ## Pass profondo + aderenza AgID sui comuni leggibili gia' nel db
	docker compose run --rm -T -v "$(PWD)/data:/scrivibile" api \
		python -m treasureiq.ingest.censimento --solo-misurabili --aderenza \
		--db /scrivibile/storico.db --lavoratori $(or $(LAVORATORI),6)

.PHONY: sweep
sweep: ## Censimento+registro+catalogo per un set: make sweep ISTAT='058057' | vuoto=coperti
	docker compose run --rm -T -v "$(PWD)/data:/scrivibile" api \
		python -m treasureiq.registro_cli sweep $(if $(ISTAT),$(ISTAT),--coperti) \
		--db /scrivibile/storico.db $(if $(ADERENZA),--aderenza,) \
		--lavoratori $(or $(LAVORATORI),6) --delay $(or $(DELAY),1.5)

.PHONY: sweep-worker
sweep-worker: ## Avvia il worker incrementale (batch da 20, pausa 2 minuti; configurabile)
	$(COMPOSE) --profile sweep up -d --build sweep-worker

.PHONY: sweep-worker-once
sweep-worker-once: ## Esegue un solo batch del worker e termina
	$(COMPOSE) --profile sweep run --rm -T sweep-worker python -m treasureiq.sweep_worker --once

.PHONY: sweep-worker-stop
sweep-worker-stop: ## Ferma solo il worker dello sweep
	$(COMPOSE) --profile sweep stop sweep-worker

.PHONY: registro-nazionale
registro-nazionale: ## Popola data-live/registro per i comuni leggibili trovati nel censimento
	docker compose exec -T api python -m treasureiq.registro_cli scan --da-censimento --only-missing

.PHONY: registro-scan
registro-scan: ## Scansiona uno o piu' comuni: make registro-scan ISTAT='058057'
	docker compose exec -T api python -m treasureiq.registro_cli scan $(if $(ISTAT),$(ISTAT),--coperti)

.PHONY: registro-list
registro-list: ## Elenca i record presenti in data-live/registro (read-only)
	docker compose exec -T api python -m treasureiq.registro_cli list

# --- Backup ---------------------------------------------------------------
# data-live/ e data/storico.db sono bind mount: già persistenti ai rebuild
# (compose.yml). Questo backup e' la cintura extra, non la sola garanzia.

.PHONY: backup
backup: ## Copia storico.db + data-live/ in backups/treasureiq-<timestamp>.tgz
	@mkdir -p backups
	@stamp=$$(date -u +%Y%m%dT%H%M%SZ); \
	tar_path="backups/treasureiq-$$stamp.tgz"; \
	if [ -f data/storico.db ]; then \
		tar -czf "$$tar_path" data/storico.db data-live; \
	else \
		echo "data/storico.db assente, backup solo di data-live/"; \
		tar -czf "$$tar_path" data-live; \
	fi; \
	echo "backup: $$tar_path"

.PHONY: restore
restore: ## Ripristina un backup: make restore FILE=backups/treasureiq-....tgz
	@test -n "$(FILE)" || { echo "manca FILE, es. make restore FILE=backups/treasureiq-20260810T120000Z.tgz"; exit 1; }
	@test -f "$(FILE)" || { echo "file non trovato: $(FILE)"; exit 1; }
	@echo "questo sovrascrive data/storico.db e data-live/ con il contenuto di $(FILE):"
	@tar -tzf "$(FILE)"
	tar -xzf "$(FILE)" -C .
