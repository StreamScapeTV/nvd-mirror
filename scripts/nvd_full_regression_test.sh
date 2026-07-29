#!/usr/bin/env bash
set -euo pipefail
API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
KNOWN_CVE="${KNOWN_CVE:-CVE-2021-44228}"
for cmd in curl jq; do command -v "$cmd" >/dev/null || { echo "[ERROR] Missing command: $cmd"; exit 2; }; done
failures=0
pass(){ echo "[PASS] $1"; }
fail(){ echo "[FAIL] $1"; failures=$((failures+1)); }
check(){ local name="$1" actual="$2" expected="$3"; [[ "$actual" == "$expected" ]] && pass "$name" || fail "$name: expected $expected, got $actual"; }
health="$(curl -fsS "$API_BASE_URL/health")"; check health "$(jq -r '.status' <<<"$health")" ok
ready="$(curl -fsS "$API_BASE_URL/ready")"; check readiness "$(jq -r '.status' <<<"$ready")" ready
openapi="$(curl -fsS "$API_BASE_URL/openapi.json")"
for path in /health /ready /rest/json/cves/2.0 /dashboard/api/summary /mirror/nvd/{filename}; do [[ "$(jq -r --arg p "$path" '.paths|has($p)' <<<"$openapi")" == true ]] && pass "OpenAPI has $path" || fail "OpenAPI missing $path"; done
[[ "$(jq '[.paths|keys[]|select(startswith("/admin"))]|length' <<<"$openapi")" == 0 ]] && pass 'no admin endpoints' || fail 'admin endpoints exposed'
base="$(curl -fsS "$API_BASE_URL/rest/json/cves/2.0?resultsPerPage=2&startIndex=0")"
check format "$(jq -r '.format' <<<"$base")" NVD_CVE
check version "$(jq -r '.version' <<<"$base")" 2.0
check startIndex "$(jq -r '.startIndex' <<<"$base")" 0
check returned "$(jq '.vulnerabilities|length' <<<"$base")" "$(jq '.resultsPerPage' <<<"$base")"
lookup="$(curl -fsS "$API_BASE_URL/rest/json/cves/2.0?cveId=$KNOWN_CVE")"
check known-CVE "$(jq -r '.vulnerabilities[0].cve.id // empty' <<<"$lookup")" "$KNOWN_CVE"
unknown="$(curl -fsS "$API_BASE_URL/rest/json/cves/2.0?cveId=CVE-2099-999999")"
check unknown-total "$(jq -r '.totalResults' <<<"$unknown")" 0
page1="$(curl -fsS "$API_BASE_URL/rest/json/cves/2.0?resultsPerPage=3&startIndex=0" | jq -r '.vulnerabilities[].cve.id')"
page2="$(curl -fsS "$API_BASE_URL/rest/json/cves/2.0?resultsPerPage=3&startIndex=3" | jq -r '.vulnerabilities[].cve.id')"
[[ -z "$(comm -12 <(sort <<<"$page1") <(sort <<<"$page2"))" ]] && pass 'pagination has no overlap' || fail 'pagination overlaps'
alias="$(curl -fsS "$API_BASE_URL/rest/json/cves/2.0?resultsPerPage=1&StartIndex=1")"; check StartIndex-alias "$(jq -r '.startIndex' <<<"$alias")" 1
for endpoint in /dashboard /dashboard/api/summary /dashboard/api/years /dashboard/api/feeds /dashboard/api/recent?limit=1 /dashboard/api/nvd-stats; do curl -fsS "$API_BASE_URL$endpoint" >/dev/null && pass "$endpoint" || fail "$endpoint"; done
(( failures == 0 )) || { echo "[ERROR] $failures regression check(s) failed."; exit 1; }
echo '[OK] All enabled NVD regression checks passed.'
