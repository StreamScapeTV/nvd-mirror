# NVD Mirror

[![CI](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/ci.yml/badge.svg)](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/ci.yml)
[![Container](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/container.yml/badge.svg)](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/container.yml)
[![Helm](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/helm.yml/badge.svg)](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/helm.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`nvd-mirror` is a self-hosted mirror for the NIST National Vulnerability Database (NVD) JSON 2.0 CVE feeds. It stores validated feed files, imports CVEs into PostgreSQL, exposes a read-only NVD CVE API-compatible endpoint, serves the raw mirror files, and provides an operational dashboard.

Clients can preserve the official API path and change only the host:

```text
Official: https://services.nvd.nist.gov/rest/json/cves/2.0
Mirror:   https://nvd.example.org/rest/json/cves/2.0
```

> This project is independent and is not affiliated with or endorsed by NIST or the NVD.

## Published release artifacts

Release versions are aligned across the application, container image, and Helm chart.

| Artifact | Version/reference |
|---|---|
| GitHub release | `v0.2.0` |
| Docker/OCI image | `ghcr.io/streamscapetv/nvd-mirror:0.2.0` |
| Convenience image tag | `ghcr.io/streamscapetv/nvd-mirror:latest` |
| OCI Helm chart | `oci://ghcr.io/streamscapetv/charts/nvd-mirror` with `--version 0.2.0` |
| Docker Compose release assets | `docker-compose.yml` and `nvd-mirror.env.example` |

Use the versioned image and chart in production. The `latest` image tag is provided for convenience, but it is not immutable.

## Run with Docker Compose without cloning the source

Only Docker Compose and two small release files are required. The deployment Compose file pulls the published image; it does not build the application locally.

```bash
mkdir nvd-mirror
cd nvd-mirror

curl -fL -o docker-compose.yml \
  https://github.com/StreamScapeTV/nvd-mirror/releases/latest/download/docker-compose.yml
curl -fL -o .env \
  https://github.com/StreamScapeTV/nvd-mirror/releases/latest/download/nvd-mirror.env.example

mkdir -p volumes/database volumes/nvd-feed-mirror-data volumes/certs
```

Edit `.env` before starting. At minimum, replace `change-me` in both of these values with the same strong password:

```env
POSTGRES_PASSWORD=replace-with-a-strong-password
DATABASE_URL=postgresql+psycopg://nvd:replace-with-a-strong-password@postgres:5432/nvd
```

The downloaded environment file already selects the matching release image:

```env
NVD_MIRROR_IMAGE=ghcr.io/streamscapetv/nvd-mirror:0.2.0
```

Start the service:

```bash
docker compose pull
docker compose up -d
```

Populate a new database with all historical yearly feeds once:

```bash
docker compose --profile manual run --rm bootstrap
```

Check the service:

```bash
docker compose ps
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

Open the dashboard at:

```text
http://localhost:8000/dashboard
```

Useful operational commands:

```bash
docker compose logs -f api scheduler
docker compose --profile manual run --rm sync-modified
docker compose --profile manual run --rm mirror-all
docker compose --profile manual run --rm stats-backfill
docker compose down
```

Persistent data is stored under:

```text
./volumes/database               PostgreSQL data
./volumes/nvd-feed-mirror-data   NVD .meta and .json.gz files
./volumes/certs                  optional CA and TLS files
```

## Run with Kubernetes and Helm

Install the published OCI chart directly from GitHub Container Registry:

```bash
helm upgrade --install nvd-mirror \
  oci://ghcr.io/streamscapetv/charts/nvd-mirror \
  --version 0.2.0 \
  --namespace nvd-mirror \
  --create-namespace \
  --set-string postgresql.auth.password='replace-with-a-strong-password'
```

Chart `0.2.0` uses image `ghcr.io/streamscapetv/nvd-mirror:0.2.0` by default.

The default installation creates:

- one Deployment containing the API and scheduler containers;
- a persistent raw-feed mirror PVC;
- a single-instance PostgreSQL StatefulSet and database PVC;
- a resumable historical bootstrap init container;
- a ClusterIP Service;
- an optional Ingress.

The Deployment uses the `Recreate` strategy to avoid `ReadWriteOnce` multi-attach failures. A completion marker on the mirror PVC and a database count check prevent an already completed historical bootstrap from running again unnecessarily.

For an existing populated database, disable the initial bootstrap:

```bash
--set bootstrap.enabled=false
```

For an external PostgreSQL database:

```bash
kubectl create namespace nvd-mirror --dry-run=client -o yaml | kubectl apply -f -
kubectl -n nvd-mirror create secret generic nvd-mirror-database \
  --from-literal=DATABASE_URL='postgresql+psycopg://user:password@postgres.example:5432/nvd'

helm upgrade --install nvd-mirror \
  oci://ghcr.io/streamscapetv/charts/nvd-mirror \
  --version 0.2.0 \
  --namespace nvd-mirror \
  --set postgresql.enabled=false \
  --set database.existingSecret=nvd-mirror-database \
  --set bootstrap.enabled=false
```

Ingress example:

```bash
helm upgrade --install nvd-mirror \
  oci://ghcr.io/streamscapetv/charts/nvd-mirror \
  --version 0.2.0 \
  --namespace nvd-mirror \
  --create-namespace \
  --set-string postgresql.auth.password='replace-with-a-strong-password' \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set ingress.hosts[0].host=nvd.example.org \
  --set ingress.tls[0].secretName=nvd-example-tls \
  --set ingress.tls[0].hosts[0]=nvd.example.org
```

See the [chart documentation](charts/nvd-mirror/README.md) and [`values.yaml`](charts/nvd-mirror/values.yaml) for persistent storage, existing claims, external secrets, private registries, certificates, resources, and scheduling options.

## Upgrades

### Docker Compose

Download the newest release environment file or update `NVD_MIRROR_IMAGE` to the desired immutable version, then run:

```bash
docker compose pull
docker compose up -d
```

The PostgreSQL and feed-mirror bind mounts remain intact.

### Helm

Upgrade both the chart and its matching default image together:

```bash
helm upgrade nvd-mirror \
  oci://ghcr.io/streamscapetv/charts/nvd-mirror \
  --version 0.2.0 \
  --namespace nvd-mirror \
  --reuse-values
```

Review changed values before using `--reuse-values` across future releases.

## Features

- `.meta`-first NVD JSON 2.0 feed synchronization;
- interrupted-download retries and atomic file replacement;
- gzip, compressed-size, uncompressed-size, SHA-256, and record-count validation;
- PostgreSQL-backed CVE storage;
- read-only `/rest/json/cves/2.0` endpoint;
- raw `/mirror/nvd/*` feed endpoint;
- read-only operational dashboard;
- built-in scheduler for `modified`, `recent`, and yearly feed checks;
- materialized and resumable dashboard statistics;
- Docker Compose deployment using the published image;
- Kubernetes Helm chart with optional PostgreSQL and Ingress;
- multi-version Python, container, Compose, Helm 3, and Helm 4 validation in GitHub Actions.

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

## Synchronization

Default behavior:

- scheduler startup: one `modified` sync;
- hourly at minute `25`: check/import `modified` and refresh raw `recent` files;
- daily at `03:15 America/New_York`: check all yearly feeds plus `modified` and `recent`;
- six-second minimum delay between upstream requests;
- unchanged `.json.gz` files are never downloaded.

NVD documents that yearly feeds update daily, while `modified` and `recent` update approximately every two hours. The mirror checks `.meta` first and downloads `.json.gz` only when the upstream metadata changes.

## Configuration

Docker Compose uses `.env` as its single configuration entry point. The Helm chart exposes equivalent settings under `config`, Secrets, and database values.

Important variables:

```env
NVD_MIRROR_IMAGE=ghcr.io/streamscapetv/nvd-mirror:0.2.0
DATABASE_URL=postgresql+psycopg://nvd:password@postgres:5432/nvd
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
| `remote` | Direct upstream download/import behavior |

`NVD_FEED_UPSTREAM_BASE_URL`, when set, overrides `NVD_MIRROR_BASE_URL`.

The optional `NVD_API_KEY` is used only for lightweight live API total checks in the dashboard. Feed downloads do not require it. Live totals are cached server-side for five minutes.

Validation controls:

```env
VALIDATE_META=true
VALIDATE_GZ_SIZE=true
VALIDATE_UNCOMPRESSED_SIZE=true
VALIDATE_UNCOMPRESSED_SHA256=true
```

An invalid or incomplete download never replaces an existing valid local file.

Most deployments should terminate public TLS at a reverse proxy or Ingress. Private upstream CAs can be mounted under `/certs` and selected with `UPSTREAM_CA_BUNDLE`.

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

This is not a complete implementation of every NVD CVE API parameter or every nuanced search semantic. ID, date filtering, sorting, pagination, and response-envelope behavior are regression-tested. Text and CPE search use local JSON text matching and should be validated for each client.

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

New imports update these incrementally. For a database created before materialized statistics were available, run the resumable `stats-backfill` Compose profile or the corresponding application command. Partial breakdowns remain hidden until coverage is complete.

## Development and contribution

End users do not need the source tree. Source checkout, local builds, tests, and contributor Compose instructions are documented in [CONTRIBUTING.md](CONTRIBUTING.md). The full deterministic validation checklist is in [docs/VALIDATION.md](docs/VALIDATION.md).

## Security

Never commit `.env`, credentials, API keys, private CAs, TLS private keys, database files, or downloaded feeds. Keep PostgreSQL bound to loopback unless external access is intentional. Protect the API and dashboard with network controls or a reverse proxy when exposed outside a trusted network. See [SECURITY.md](SECURITY.md).

## License

The source code is licensed under the [MIT License](LICENSE).

NVD data, NIST services, and third-party components retain their own terms. See [NOTICE.md](NOTICE.md) for attribution and project-disclaimer details.
