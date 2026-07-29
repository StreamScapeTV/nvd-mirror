#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
MIN_BASELINE_YEAR="${MIN_BASELINE_YEAR:-2002}"
MAX_BASELINE_YEAR="${MAX_BASELINE_YEAR:-$(date -u +%Y)}"
REQUIRE_MIRROR_FILES="${REQUIRE_MIRROR_FILES:-true}"

failures=0
warnings=0
pass(){ echo "[PASS] $1"; }
warn(){ echo "[WARN] $1"; warnings=$((warnings+1)); }
fail(){ echo "[FAIL] $1"; failures=$((failures+1)); }

for cmd in curl jq; do command -v "$cmd" >/dev/null || { echo "[ERROR] Missing command: $cmd"; exit 2; }; done

years_json="$(curl -fsS "$API_BASE_URL/dashboard/api/years?validate=true")"
baseline_json="$(curl -fsS "$API_BASE_URL/dashboard/api/baseline")"
baseline_date="$(jq -r '.baseline.snapshotDate' <<<"$baseline_json")"
[[ -n "$baseline_date" && "$baseline_date" != null ]] && pass "baseline snapshot is $baseline_date" || fail "baseline snapshot date is missing"

while IFS=$'\t' read -r year minimum; do
  (( year < MIN_BASELINE_YEAR || year > MAX_BASELINE_YEAR )) && continue
  row="$(jq -c --argjson y "$year" '.years[] | select(.year == $y)' <<<"$years_json")"
  if [[ -z "$row" ]]; then fail "$year is missing from dashboard years"; continue; fi
  valid="$(jq -r '.mirrorValid' <<<"$row")"
  complete="$(jq -r '.mirrorComplete' <<<"$row")"
  total="$(jq -r '.mirrorTotalResults // "null"' <<<"$row")"
  array="$(jq -r '.mirrorArrayLength // "null"' <<<"$row")"
  if [[ "$valid" == true ]]; then pass "$year mirror validates"; elif [[ "$REQUIRE_MIRROR_FILES" == true ]]; then fail "$year mirror is missing or invalid"; else warn "$year mirror is missing or invalid"; continue; fi
  [[ "$complete" == true ]] && pass "$year arrayLength equals totalResults ($total)" || fail "$year arrayLength ($array) differs from totalResults ($total)"
  if [[ "$total" == null || -z "$total" ]]; then fail "$year totalResults is missing"; elif (( total < minimum )); then fail "$year is below baseline ($total < $minimum)"; else pass "$year meets baseline ($total >= $minimum)"; fi
done < <(jq -r '.baseline.years | to_entries[] | [.key, .value.minimumTotalResults] | @tsv' <<<"$baseline_json")

below="$(jq '[.years[] | select(.meetsBaseline == false)] | length' <<<"$baseline_json")"
[[ "$below" == 0 ]] && pass "database meets all baseline year minimums" || fail "$below database year(s) are below baseline"

(( warnings > 0 )) && echo "[WARN] $warnings warning(s)."
if (( failures == 0 )); then echo "[OK] Local mirror and database meet the checked-in baseline."; else echo "[ERROR] $failures check(s) failed."; exit 1; fi
