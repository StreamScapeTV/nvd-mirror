IMAGE ?= nvd-mirror:local
VERSION ?= 0.2.1
GHCR_IMAGE ?= ghcr.io/mimranfaruqi/nvd-mirror:$(VERSION)
COMPOSE_DEV = docker compose -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: help init up down logs ps health bootstrap sync-modified mirror-all stats-backfill test test-docker build push clean

help:
	@printf '%s\n' 'make init' 'make up' 'make bootstrap' 'make sync-modified' 'make mirror-all' 'make stats-backfill' 'make test' 'make test-docker' 'make build' 'make push'

init:
	@test -f .env || cp .env.example .env
	@mkdir -p volumes/database volumes/nvd-feed-mirror-data volumes/certs

up: init
	$(COMPOSE_DEV) up -d --build

down:
	$(COMPOSE_DEV) down

logs:
	$(COMPOSE_DEV) logs -f api scheduler

ps:
	$(COMPOSE_DEV) ps

health:
	curl -fsS http://localhost:8000/health && printf '\n'
	curl -fsS http://localhost:8000/ready && printf '\n'

bootstrap:
	$(COMPOSE_DEV) --profile manual run --rm bootstrap

sync-modified:
	$(COMPOSE_DEV) --profile manual run --rm sync-modified

mirror-all:
	$(COMPOSE_DEV) --profile manual run --rm mirror-all

stats-backfill:
	$(COMPOSE_DEV) --profile manual run --rm stats-backfill

test:
	PYTHONPATH=. pytest -q

test-docker:
	$(COMPOSE_DEV) --profile test run --rm test

build:
	docker build --build-arg APP_VERSION=$(VERSION) -t $(IMAGE) .

push:
	docker buildx build --platform linux/amd64,linux/arm64 --build-arg APP_VERSION=$(VERSION) -t $(GHCR_IMAGE) --push .

clean:
	$(COMPOSE_DEV) down -v --remove-orphans
	rm -rf .pytest_cache __pycache__ app/__pycache__ tests/__pycache__
