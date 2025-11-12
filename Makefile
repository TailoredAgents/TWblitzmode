COMPOSE=docker compose -f blitz/docker-compose.yml
API_URL?=http://localhost:8888

.PHONY: up down rebuild logs ps wait health startup-check preflight-providers migrate dev-up clean

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

rebuild:
	$(COMPOSE) build --no-cache

logs:
	$(COMPOSE) logs -f api worker

ps:
	$(COMPOSE) ps

wait:
	@echo "Waiting for API to respond at $(API_URL)/api/health ..."; \
	for i in $$(seq 1 60); do \
		if curl -fsS $(API_URL)/api/health >/dev/null 2>&1; then \
			echo "API healthy"; exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "API not responding after timeout"; exit 1

health:
	@echo "GET $(API_URL)/api/health" && curl -fsS $(API_URL)/api/health || (echo "Health check failed"; exit 1)

startup-check:
	$(COMPOSE) exec -T api python blitz/scripts/startup_check.py || true

preflight-providers:
	$(COMPOSE) exec -T api python blitz/scripts/provider_preflight.py || true

migrate:
	$(COMPOSE) exec -T api python - <<'PY'
from api.database import run_migrations, DatabaseConnection, bootstrap_postgres_schema
try:
    run_migrations()
except Exception as e:
    print("[warn] run_migrations raised:", e)
conn = DatabaseConnection()
conn.connect()
bootstrap_postgres_schema(conn)
print("[ok] Schema bootstrap completed")
PY

dev-up: up wait startup-check health

clean:
	$(COMPOSE) down -v

