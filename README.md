# NVD Mirror

[![CI](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/ci.yml/badge.svg)](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/ci.yml)
[![Container](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/container.yml/badge.svg)](https://github.com/StreamScapeTV/nvd-mirror/actions/workflows/container.yml)

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
- Docker Compose deployment and regression tests.

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

Docker Compose starts `postgres`, `api`, and `scheduler`. Manual profiles provide `bootstrap`, `sync-modified`, `mirror-all`, `stats-backfill`, and `test` jobs.

## Quick start

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

## Synchronization

Default behavior:

- scheduler startup: one `modified` sync;
- hourly at minute `25`: check/import `modified` and refresh raw `recent` files;
- daily at `03:15 America/New_York`: check all yearly feeds plus `modified` and `recent`;
- six-second minimum delay between upstream requests;
- unchanged `.json.gz` files are never downloaded.

Manual commands:

```bash
docker compose --profile manual run --rm sync-modified
docker compose --profile manual run --rm mirror-all
docker compose run --rm --entrypoint python scheduler -m app.scheduler --print-plan
```

## Persistent data

```text
./volumes/database              PostgreSQL data
./volumes/nvd-feed-mirror-data  NVD .meta and .json.gz files
./volumes/certs                 optional CA and TLS files
```

## Configuration

`.env` is the single configuration entry point. Important settings:

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
| `remote` | Legacy direct upstream import |

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

Most deployments should terminate public TLS at a reverse proxy. To trust a private upstream CA:

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

## Tests

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
pytest -q
```

Docker test stage:

```bash
docker compose --profile test run --rm test
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

Live comparison scripts contact NVD and should be run deliberately, not in every normal CI execution.

## Images

```bash
docker build --build-arg APP_VERSION=0.1.0 -t nvd-mirror:0.1.0 .
```

```bash
docker buildx build --platform linux/amd64,linux/arm64 --build-arg APP_VERSION=0.1.0 -t ghcr.io/your-org/nvd-mirror:0.1.0 --push .
```

GitHub Actions test the project and publish tagged/default-branch images to GitHub Container Registry.

## Security

Never commit `.env`, credentials, API keys, private CAs, TLS private keys, database files, or downloaded feeds. Keep PostgreSQL bound to loopback unless external access is intentional. Protect the API/dashboard with network controls or a reverse proxy when exposed outside a trusted network. See [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

No license has been selected yet. Until a license file is added, default copyright rules apply.
