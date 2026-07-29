IMAGE ?= nvd-mirror:local
VERSION ?= 0.1.0
GHCR_IMAGE ?= ghcr.io/streamscapetv/nvd-mirror:$(VERSION)
.PHONY: help init up down logs ps health bootstrap sync-modified mirror-all stats-backfill test test-docker build push clean
help:
	@printf '%s\n' 'make init' 'make up' 'make bootstrap' 'make sync-modified' 'make mirror-all' 'make stats-backfill' 'make test' 'make test-docker' 'make build' 'make push'
init:
	@test -f .env || cp .env.example .env
	@mkdir -p volumes/database volumes/nvd-feed-mirror-data volumes/certs
up: init
	docker compose up -d --build
down:
	docker compose down
logs:
	docker compose logs -f api scheduler
ps:
	docker compose ps
health:
	curl -fsS http://localhost:8000/health && printf '\n'
	curl -fsS http://localhost:8000/ready && printf '\n'
bootstrap:
	docker compose --profile manual run --rm bootstrap
sync-modified:
	docker compose --profile manual run --rm sync-modified
mirror-all:
	docker compose --profile manual run --rm mirror-all
stats-backfill:
	docker compose --profile manual run --rm stats-backfill
test:
	PYTHONPATH=. pytest -q
test-docker:
	docker compose --profile test run --rm test
build:
	docker build --build-arg APP_VERSION=$(VERSION) -t $(IMAGE) .
push:
	docker buildx build --platform linux/amd64,linux/arm64 --build-arg APP_VERSION=$(VERSION) -t $(GHCR_IMAGE) --push .
clean:
	docker compose down -v --remove-orphans
	rm -rf .pytest_cache __pycache__ app/__pycache__ tests/__pycache__
