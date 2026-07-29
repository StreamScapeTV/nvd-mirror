#!/usr/bin/env bash
set -euo pipefail
OFFICIAL_API_BASE="${OFFICIAL_API_BASE:-https://services.nvd.nist.gov/rest/json/cves/2.0}"
CACHE_API_BASE="${CACHE_API_BASE:-http://localhost:8000/rest/json/cves/2.0}"
OFFICIAL_API_KEY="${OFFICIAL_API_KEY:-}"
DELAY="${OFFICIAL_REQUEST_DELAY_SECONDS:-6}"
for cmd in curl jq sleep; do command -v "$cmd" >/dev/null || { echo "[ERROR] Missing command: $cmd"; exit 2; }; done
headers=(-H 'User-Agent: nvd-mirror-parity-test/0.1.0')
[[ -n "$OFFICIAL_API_KEY" ]] && headers+=(-H "apiKey: $OFFICIAL_API_KEY")
fetch_official(){ curl -fsS "${headers[@]}" "$1"; sleep "$DELAY"; }
local_total="$(curl -fsS "$CACHE_API_BASE?resultsPerPage=1&startIndex=0" | jq -r '.totalResults')"
official_total="$(fetch_official "$OFFICIAL_API_BASE?resultsPerPage=1&startIndex=0" | jq -r '.totalResults')"
echo "Local total:    $local_total"
echo "Official total: $official_total"
echo "Delta:          $((local_total-official_total))"
for id in CVE-1999-0095 CVE-2021-44228 CVE-2024-3094; do
  local_json="$(curl -fsS "$CACHE_API_BASE?cveId=$id")"
  official_json="$(fetch_official "$OFFICIAL_API_BASE?cveId=$id")"
  [[ "$(jq -r '.vulnerabilities[0].cve.id // empty' <<<"$local_json")" == "$id" ]] || { echo "[FAIL] Local mirror missing $id"; exit 1; }
  [[ "$(jq -r '.vulnerabilities[0].cve.id // empty' <<<"$official_json")" == "$id" ]] || { echo "[FAIL] Official API missing $id"; exit 1; }
  local_modified="$(jq -r '.vulnerabilities[0].cve.lastModified' <<<"$local_json")"
  official_modified="$(jq -r '.vulnerabilities[0].cve.lastModified' <<<"$official_json")"
  [[ "$local_modified" == "$official_modified" ]] && echo "[PASS] $id lastModified matches" || echo "[WARN] $id differs: local=$local_modified official=$official_modified"
done
echo '[OK] Official parity sampling completed.'
