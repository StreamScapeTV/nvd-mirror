#!/usr/bin/env bash
set -euo pipefail
API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
OFFICIAL_FEED_BASE_URL="${OFFICIAL_FEED_BASE_URL:-https://nvd.nist.gov/feeds/json/cve/2.0}"
FROM_YEAR="${FROM_YEAR:-2002}"
TO_YEAR="${TO_YEAR:-$(date -u +%Y)}"
DELAY="${OFFICIAL_REQUEST_DELAY_SECONDS:-6}"
for cmd in curl awk; do command -v "$cmd" >/dev/null || { echo "[ERROR] Missing command: $cmd"; exit 2; }; done
failures=0
for year in $(seq "$FROM_YEAR" "$TO_YEAR"); do
  official="$(curl -fsS -H 'User-Agent: nvd-mirror-live-check/0.1.0' "$OFFICIAL_FEED_BASE_URL/nvdcve-2.0-$year.meta")"
  local_meta="$(curl -fsS "$API_BASE_URL/mirror/nvd/nvdcve-2.0-$year.meta" || true)"
  official_sha="$(awk -F: '/^sha256:/ {print toupper($2)}' <<<"$official")"
  local_sha="$(awk -F: '/^sha256:/ {print toupper($2)}' <<<"$local_meta")"
  if [[ -n "$local_sha" && "$official_sha" == "$local_sha" ]]; then echo "[PASS] $year metadata matches"; else echo "[FAIL] $year metadata differs or is missing"; failures=$((failures+1)); fi
  sleep "$DELAY"
done
(( failures == 0 )) || { echo "[ERROR] $failures live feed check(s) failed."; exit 1; }
echo '[OK] Local yearly mirror metadata matches live NVD.'
