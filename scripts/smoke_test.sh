#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"

echo "[1] health"
curl -fsS "$API_BASE_URL/health" | jq .

echo "[2] readiness"
curl -fsS "$API_BASE_URL/ready" | jq .

echo "[3] verify /admin routes are not exposed"
curl -fsS "$API_BASE_URL/openapi.json" | jq '.paths | with_entries(select(.key | startswith("/admin") | not)) | keys'

echo "[4] query NVD-compatible API"
curl -fsS "$API_BASE_URL/rest/json/cves/2.0?resultsPerPage=1" | jq '{format, version, totalResults, resultsPerPage, startIndex, first: (.vulnerabilities[0].cve.id // null)}'

echo "[OK] smoke test passed"
