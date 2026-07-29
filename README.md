# NVD Mirror

[![CI](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/ci.yml/badge.svg)](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/ci.yml)
[![Container](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/container.yml/badge.svg)](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/container.yml)
[![Helm](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/helm.yml/badge.svg)](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/helm.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`nvd-mirror` is a self-hosted mirror for the NIST National Vulnerability Database (NVD) JSON 2.0 CVE feeds. It stores validated feed files locally, imports CVEs into PostgreSQL, exposes a read-only NVD CVE API-compatible endpoint for common automation workflows, and includes an operational dashboard.

```text
/rest/json/cves/2.0
```

A client can keep the official API path and change only the host:

```text
Official: https://services.nvd.nist.gov/rest/json/cves/2.0
Mirror:   https://nvd.example.org/rest/json/cves/2.0
```

> This project is not affiliated with or endorsed by NIST or the NVD. It mirrors public NVD data and implements a documented subset of the CVE API.

## Features

- `.meta`-first NVD JSON 2.0 feed synchronization;
- interrupted-download retries and atomic file replacement;
- gzip, compressed size, uncompressed size, SHA-256, and record-count validation;
- PostgreSQL-backed CVE storage;
- read-only `/rest/json/cves/2.0` endpoint;
- raw `/mirror/nvd/*` feed endpoint;
- read-only operational dashboard;
- built-in scheduler for `modified`, `recent`, and yearly feed checks;
- Docker Compose deployment;
- Kubernetes Helm chart with optional PostgreSQL, persistent storage, Ingress, and resumable bootstrap;
- multi-version Python, container, and Helm validation in GitHub Actions.

NVD documents that yearly feeds update daily, while `modified` and `recent` update approximately every two hours. NVD recommends checking `.meta` before downloading `.json.gz`: https://nvd.nist.gov/vuln/data-feeds

## Architecture

```text
NVD JSON 2.0 feeds
        |
        v
managed local feed mirror
  - fetch .meta first
  - skip unchanged feeds
  - validate before replacement
        |
        +--> /data/mirror/nvd/*.meta
        +--> /data/mirror/nvd/*.json.gz
        |
        v
PostgreSQL importer
        |
        +--> /rest/json/cves/2.0
        +--> /mirror/nvd/*
        +--> /dashboard
```

The API and scheduler share the same PostgreSQL database and raw-feed mirror. Docker Compose runs them as separate services. The Helm chart runs them as sidecars in one pod so a `ReadWriteOnce` mirror volume is mounted by only one pod.

## Docker Compose quick start

```bash
git clone https://github.com/StreamScapeTV/nvd-mirror.git
cd nvd-mirror
cp .env.example .env
```

Change the PostgreSQL password in `.env`, keeping `DATABASE_URL` consistent. Then:

```bash
mkdir -p volumes/database volumes/nvd-feed-mirror-data volumes/certs
docker compose up -d --build
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

Open:

```text
http://localhost:8000/dashboard
```

Populate a new or partial database once:

```bash
docker compose --profile manual run --rm bootstrap
```

Bootstrap imports every yearly feed from `DEFAULT_FROM_YEAR` through the current year, then imports `modified`.

## Kubernetes and Helm

The chart is stored in [`charts/nvd-mirror`](charts/nvd-mirror) and released as an OCI Helm artifact in GitHub Container Registry.

Install the published chart:

```bash
helm upgrade --install nvd-mirror \
  oci://ghcr.io/streamscapetv/charts/nvd-mirror \
  --version 0.1.0 \
  --namespace nvd-mirror \
  --create-namespace \
  --set-string postgresql.auth.password='replace-with-a-strong-password'
```

Install directly from a clone:

```bash
helm upgrade --install nvd-mirror ./charts/nvd-mirror \
  --namespace nvd-mirror \
  --create-namespace \
  --set-string postgresql.auth.password='replace-with-a-strong-password'
```

By default, the chart creates:

- one `nvd-mirror` Deployment containing the API and scheduler containers;
- a persistent raw-feed mirror PVC;
- a single-instance PostgreSQL StatefulSet and persistent database storage;
- a resumable bootstrap init container for the historical feeds;
- a ClusterIP Service;
- an optional Kubernetes Ingress.

The Deployment uses the `Recreate` strategy to avoid `ReadWriteOnce` multi-attach failures during upgrades. A marker on the mirror PVC and a database count check prevent a successful historical bootstrap from running again unnecessarily.

For an existing populated database, disable the initial bootstrap:

```bash
--set bootstrap.enabled=false
```

For an external PostgreSQL database, create a Secret containing `DATABASE_URL`, disable the included database, and reference the Secret:

```bash
kubectl -n nvd-mirror create secret generic nvd-mirror-database \
  --from-literal=DATABASE_URL='postgresql+psycopg://user:password@postgres.example:5432/nvd'

helm upgrade --install nvd-mirror \
  oci://ghcr.io/streamscapetv/charts/nvd-mirror \
  --version 0.1.0 \
  --namespace nvd-mirror \
  --create-namespace \
  --set postgresql.enabled=false \
  --set database.existingSecret=nvd-mirror-database \
  --set bootstrap.enabled=false
```

Ingress example:

```bash
helm upgrade --install nvd-mirror \
  oci://ghcr.io/streamscapetv/charts/nvd-mirror \
  --version 0.1.0 \
  --namespace nvd-mirror \
  --create-namespace \
  --set-string postgresql.auth.password='replace-with-a-strong-password' \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set ingress.hosts[0].host=nvd.example.org \
  --set ingress.tls[0].secretName=nvd-example-tls \
  --set ingress.tls[0].hosts[0]=nvd.example.org
```

See the [chart documentation](charts/nvd-mirror/README.md) and [`values.yaml`](charts/nvd-mirror/values.yaml) for persistent storage, existing claims, private registries, external secrets, private CAs, resource limits, scheduling, and all environment-backed settings.

## Synchronization

Default behavior:

- scheduler startup: one `modified` sync;
- hourly at minute `25`: check/import `modified` and refresh raw `recent` files;
- daily at `03:15 America/New_York`: check all yearly feeds plus `modified` and `recent`;
- six-second minimum delay between upstream requests;
- unchanged `.json.gz` files are never downloaded.

Manual Docker Compose commands:

```bash
docker compose --profile manual run --rm sync-modified
docker compose --profile manual run --rm mirror-all
docker compose run --rm --entrypoint python scheduler -m app.scheduler --print-plan
```

## Persistent data

Docker Compose uses:

```text
./volumes/database               PostgreSQL data
./volumes/nvd-feed-mirror-data   NVD .meta and .json.gz files
./volumes/certs                  optional CA and TLS files
```

The Helm chart uses separate persistent volumes for PostgreSQL and the raw feed mirror. Existing claims are supported through `postgresql.persistence.existingClaim` and `persistence.existingClaim`.

## Configuration

Docker Compose reads `.env` as its single configuration entry point. The Helm chart exposes equivalent settings under `config`, `database`, `nvdApiKey`, `postgresql`, and `persistence`.

Important environment settings:

```env
APP_NAME=nvd-mirror
APP_VERSION=0.1.0
NVD_MIRROR_IMAGE=nvd-mirror:local
DATABASE_URL=postgresql+psycopg://nvd:change-me@postgres:5432/nvd
NVD_MIRROR_BASE_URL=https://nvd.nist.gov/feeds/json/cve/2.0
NVD_FEED_SOURCE_MODE=managed
NVD_FEED_MIRROR_DIR=/data/mirror/nvd
NVD_UPSTREAM_REQUEST_DELAY_SECONDS=6
NVD_UPSTREAM_RETRIES=10
NVD_API_KEY=
```

Feed modes:

| Mode | Behavior |
|---|---|
| `managed` | Download locally, validate, then import |
| `local` | Use existing local files without upstream access |
| `remote` | Direct upstream download/import compatibility mode |

`NVD_FEED_UPSTREAM_BASE_URL`, when set, overrides `NVD_MIRROR_BASE_URL`.

The optional `NVD_API_KEY` is used only for lightweight live API total checks in the dashboard. Feed downloads do not require it. Live totals are cached server-side for five minutes.

### Validation

```env
VALIDATE_META=true
VALIDATE_GZ_SIZE=true
VALIDATE_UNCOMPRESSED_SIZE=true
VALIDATE_UNCOMPRESSED_SHA256=true
```

An invalid or incomplete download never replaces an existing valid local file.

### TLS

Most deployments should terminate public TLS at a reverse proxy or Kubernetes Ingress. To trust a private upstream CA:

```env
UPSTREAM_VERIFY_TLS=true
UPSTREAM_CA_BUNDLE=/certs/private-ca.pem
```

Optional application-level TLS:

```env
TLS_CERT_FILE=/certs/tls.crt
TLS_KEY_FILE=/certs/tls.key
```

## API compatibility

```text
GET /rest/json/cves/2.0
```

Supported parameters:

- `startIndex` and compatibility alias `StartIndex`;
- `resultsPerPage`;
- `cveId`;
- `pubStartDate` / `pubEndDate`;
- `lastModStartDate` / `lastModEndDate`;
- `keywordSearch`;
- `cpeName`;
- `virtualMatchString`;
- `noRejected`.

The endpoint is read-only and token-free. Incoming `apiKey` values are tolerated and ignored.

This is not a complete implementation of every NVD CVE API parameter or every nuanced search semantic. ID, date filtering, sorting, pagination, and response envelope behavior are regression-tested. Text and CPE search use local JSON text matching and should be validated for each client.

```bash
curl -fsS 'http://localhost:8000/rest/json/cves/2.0?resultsPerPage=1&startIndex=0' | jq
curl -fsS 'http://localhost:8000/rest/json/cves/2.0?cveId=CVE-2024-12345' | jq
```

## Raw feed endpoint

Already mirrored files are served without contacting NVD:

```text
GET /mirror/nvd/nvdcve-2.0-modified.meta
GET /mirror/nvd/nvdcve-2.0-modified.json.gz
GET /mirror/nvd/nvdcve-2.0-recent.meta
GET /mirror/nvd/nvdcve-2.0-YYYY.json.gz
```

## Dashboard and materialized statistics

The dashboard at `/dashboard` shows local and cached official totals, bootstrap completeness, live/local metadata, next sync, yearly counts, feed validation, recent CVEs, and exact breakdowns when derived statistics cover every local CVE.

Heavy statistics are not calculated during page load. They are materialized in:

```text
nvd_cve_derived_stats
nvd_dashboard_stats_snapshots
```

New imports update these incrementally. For an existing database created before materialized statistics were available, run the resumable backfill:

```bash
docker compose --profile manual run --rm stats-backfill
```

Partial breakdowns are hidden until coverage is complete.

## Tests and validation

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
pytest -q
python -m compileall -q app tests
bash -n scripts/*.sh
```

Docker test stage:

```bash
docker compose --profile test run --rm test
```

Helm validation:

```bash
helm lint charts/nvd-mirror \
  --set-string postgresql.auth.password=ci-password \
  --set bootstrap.enabled=false

helm template nvd-mirror charts/nvd-mirror \
  --namespace nvd-mirror \
  --set-string postgresql.auth.password=ci-password \
  --set bootstrap.enabled=false \
  > /tmp/nvd-mirror.yaml
```

Running-service checks:

```bash
API_BASE_URL=http://localhost:8000 ./scripts/smoke_test.sh
API_BASE_URL=http://localhost:8000 ./scripts/nvd_full_regression_test.sh
```

Completeness and optional live parity checks:

```bash
CACHE_API_BASE=http://localhost:8000/rest/json/cves/2.0 ./scripts/nvd_feed_baseline_test.sh
API_BASE_URL=http://localhost:8000 ./scripts/nvd_mirror_file_baseline_test.sh
CACHE_API_BASE=http://localhost:8000/rest/json/cves/2.0 OFFICIAL_FEED_BASE_URL=https://nvd.nist.gov/feeds/json/cve/2.0 ./scripts/nvd_live_feed_baseline_test.sh
```

Live comparison scripts contact NVD and should be run deliberately, not in every normal CI execution. See [docs/VALIDATION.md](docs/VALIDATION.md) for the deterministic checklist.

## Images and Helm releases

Build a local image:

```bash
docker build --build-arg APP_VERSION=0.1.0 -t nvd-mirror:0.1.0 .
```

Publish a multi-platform image manually:

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --build-arg APP_VERSION=0.1.0 \
  -t ghcr.io/your-org/nvd-mirror:0.1.0 \
  --push .
```

GitHub Actions test every change. Version tags such as `v0.1.0` publish the multi-platform application image and the matching OCI Helm chart to GitHub Container Registry.

## Security

Never commit `.env`, credentials, API keys, private CAs, TLS private keys, database files, or downloaded feeds. Keep PostgreSQL private unless external access is intentional. Protect the API/dashboard with network controls, a reverse proxy, or Ingress when exposed outside a trusted network. See [SECURITY.md](SECURITY.md).

For production installations, prefer existing Kubernetes Secrets or an external secret manager instead of putting passwords directly in Helm values.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

The source code is licensed under the [MIT License](LICENSE).

NVD data, NIST services, and third-party components retain their own terms. See [NOTICE.md](NOTICE.md) for attribution and project-disclaimer details.
