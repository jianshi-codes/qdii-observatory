SHELL := /bin/sh
PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
PNPM ?= pnpm
UNIVERSE ?= examples/universe.sample.csv
FUND_CODE ?=
COMPOSE ?= docker compose --env-file .env
COMPOSE_EXTERNAL ?= docker compose --env-file .env -f compose.yaml -f compose.external.yaml

.PHONY: setup init doctor docker-up docker-up-external docker-down docker-restart docker-daily docker-reset migrate dev-backend \
	dev-frontend dev-worker import-universe validate-universe demo sync-reports parse-reports sync-daily \
	reconcile-public-funds coverage analyze-fund backup restore lint typecheck test build check

setup:
	$(PIP) install -e '.[dev]'
	cd frontend && $(PNPM) install --frozen-lockfile

init:
	$(PYTHON) -m backend.app.cli init

doctor:
	$(PYTHON) -m backend.app.cli doctor

docker-up:
	$(COMPOSE) up --build -d

docker-up-external:
	$(COMPOSE_EXTERNAL) run --build --rm database-provision
	$(COMPOSE_EXTERNAL) up --build -d backend worker frontend

docker-down:
	$(COMPOSE) down

docker-restart:
	$(COMPOSE) restart

docker-daily:
	$(COMPOSE) exec backend qdii sync-daily

docker-reset:
	@echo "This removes the project database volume. Run explicitly: docker compose --env-file .env down --volumes"
	@exit 2

migrate:
	$(PYTHON) -m alembic upgrade head

dev-backend:
	$(PYTHON) -m uvicorn backend.app.main:app --reload --host "$${QDII_BIND_HOST:-127.0.0.1}" --port "$${QDII_BACKEND_PORT:-8000}"

dev-worker:
	$(PYTHON) -m backend.app.operation_worker

dev-frontend:
	cd frontend && $(PNPM) dev

validate-universe:
	$(PYTHON) -m backend.app.cli validate-universe --file "$(UNIVERSE)"

import-universe:
	$(PYTHON) -m backend.app.cli import-universe --file "$(UNIVERSE)"

reconcile-public-funds:
	$(PYTHON) -m backend.app.cli reconcile-public-funds

demo: import-universe
	$(PYTHON) -m backend.app.cli load-demo

sync-reports:
	$(PYTHON) -m backend.app.cli sync-reports --latest-quarter

parse-reports:
	$(PYTHON) -m backend.app.cli parse-reports --latest-quarter

sync-daily:
	$(PYTHON) -m backend.app.cli sync-daily

coverage:
	$(PYTHON) -m backend.app.cli coverage --latest-quarter

analyze-fund:
	@test -n "$(FUND_CODE)" || (echo "Set FUND_CODE=123456" && exit 2)
	$(PYTHON) -m backend.app.cli analyze-fund --fund-code "$(FUND_CODE)" --latest-report

backup:
	$(PYTHON) -m backend.app.cli backup

restore:
	@echo "Use qdii restore --file <backup> --confirm after reading docs/operations.md"
	@exit 2

lint:
	$(PYTHON) -m ruff check backend tests
	cd frontend && $(PNPM) lint

typecheck:
	$(PYTHON) -m mypy backend
	cd frontend && $(PNPM) typecheck

test:
	$(PYTHON) -m pytest
	cd frontend && $(PNPM) test -- --run

build:
	cd frontend && $(PNPM) build

check: lint typecheck test build
	git diff --check
	docker compose --env-file .env.example config --quiet
	QDII_EXTERNAL_DATABASE_URL=postgresql+psycopg://user:password@db.example:5432/qdii_observatory QDII_EXTERNAL_ADMIN_DATABASE_URL=postgresql+psycopg://admin:password@db.example:5432/postgres QDII_AUTO_CREATE_DATABASE=true docker compose --env-file .env.example -f compose.yaml -f compose.external.yaml config --quiet
