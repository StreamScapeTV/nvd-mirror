# Contributing

Contributions are welcome through issues and pull requests.

## Source checkout

```bash
git clone https://github.com/StreamScapeTV/nvd-mirror.git
cd nvd-mirror
cp .env.example .env
mkdir -p volumes/database volumes/nvd-feed-mirror-data volumes/certs
```

The normal `docker-compose.yml` is intentionally a deployment manifest that pulls the published GHCR image. Use the contributor override when developing from source:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  up -d --build
```

The Makefile uses the same two-file Compose configuration:

```bash
make up
make bootstrap
make logs
```

## Local validation

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
pytest -q
python -m compileall -q app tests
bash -n scripts/*.sh
```

Container-based tests use the source-build override:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  --profile test run --rm test
```

Helm validation:

```bash
helm lint charts/nvd-mirror \
  --set-string postgresql.auth.password=dev-password \
  --set bootstrap.enabled=false
helm template nvd-mirror charts/nvd-mirror \
  --set-string postgresql.auth.password=dev-password \
  --set bootstrap.enabled=false >/tmp/nvd-mirror.yaml
```

Please keep changes focused, add regression coverage, avoid live NVD calls in deterministic tests, preserve `.meta`-first synchronization and atomic replacement, document environment variables, and never commit secrets or runtime data.

Changes to `/rest/json/cves/2.0` must state whether behavior matches the official API or is a local best-effort implementation.
