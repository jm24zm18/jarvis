.PHONY: dev api test test-gates lint typecheck migrate setup doctor \
       web-install web-build web-dev web-lint web-typecheck web-test \
       hooks validate-agents test-migrations security docs-generate docs-check \
       preflight-dev-ports

dev: preflight-dev-ports
	docker compose up -d

preflight-dev-ports:
	python3 scripts/dev_preflight_ports.py

api:
	uv run uvicorn jarvis.main:app --reload --app-dir src

test:
	uv run pytest tests

test-gates:
	uv run ruff check src tests
	uv run mypy src
	uv run python scripts/validate_agents.py
	python3 scripts/test_migrations.py
	uv run pytest tests/unit -q
	uv run pytest tests/integration -q
	uv run pytest tests --cov=jarvis.orchestrator --cov=jarvis.policy --cov=jarvis.tools.runtime --cov-report=json:/tmp/jarvis_coverage.json -q
	uv run python scripts/check_coverage.py /tmp/jarvis_coverage.json

lint:
	uv run ruff check src tests

typecheck:
	uv run mypy src

migrate:
	uv run python -m jarvis.db.migrations.runner

setup:
	uv run jarvis setup

doctor:
	uv run jarvis doctor

hooks:
	uv run pre-commit install

validate-agents:
	uv run python scripts/validate_agents.py

test-migrations:
	python3 scripts/test_migrations.py

security:
	uv run bandit -r src/jarvis -c pyproject.toml -ll
	uv run pip-audit

web-install:
	cd web && npm install

web-build:
	cd web && npm run build

web-dev:
	cd web && npm run dev

web-lint:
	cd web && npm run lint

web-typecheck:
	cd web && npm run typecheck

web-test:
	cd web && npm test

docs-generate:
	uv run python scripts/generate_api_docs.py

docs-check:
	uv run python scripts/docs_check.py
