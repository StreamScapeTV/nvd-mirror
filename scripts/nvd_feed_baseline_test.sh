#!/usr/bin/env bash
set -euo pipefail
CACHE_API_BASE="${CACHE_API_BASE:-http://localhost:8000/rest/json/cves/2.0}"
BASELINE_FILE="${BASELINE_FILE:-$(dirname "$0")/../app/baselines/nvd_year_feed_baseline_2026-06-28.json}"
for cmd in curl jq; do command -v "$cmd" >/dev/null || { echo "[ERROR] Missing command: $cmd"; exit 2; }; done
minimum="$(jq -r '.minimumTotalResults' "$BASELINE_FILE")"
response="$(curl -fsS "$CACHE_API_BASE?resultsPerPage=1&startIndex=0")"
total="$(jq -r '.totalResults' <<<"$response")"
[[ "$(jq -r '.format' <<<"$response")" == NVD_CVE ]] || { echo '[FAIL] Invalid format'; exit 1; }
[[ "$(jq -r '.version' <<<"$response")" == 2.0 ]] || { echo '[FAIL] Invalid version'; exit 1; }
(( total >= minimum )) || { echo "[FAIL] Local total $total is below baseline $minimum"; exit 1; }
echo "[PASS] Local total meets baseline ($total >= $minimum)"
while IFS=$'\t' read -r year sample; do
  result="$(curl -fsS "$CACHE_API_BASE?cveId=$sample")"
  [[ "$(jq -r '.totalResults' <<<"$result")" == 1 ]] || { echo "[FAIL] Missing sample $sample for $year"; exit 1; }
  echo "[PASS] $year sample $sample"
done < <(jq -r '.years | to_entries[] | [.key,.value.sampleCveId] | @tsv' "$BASELINE_FILE")
echo '[OK] Database baseline checks passed.'
