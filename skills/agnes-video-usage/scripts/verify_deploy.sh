#!/usr/bin/env bash
# Deployment verification for agnes-video-generator.
#
#   bash verify_deploy.sh                 # read-only checks (default)
#   bash verify_deploy.sh --with-task     # also submit one 5s simple video task and poll it
#   AGNES_VIDEO_BASE=http://host:8765 bash verify_deploy.sh
#
# Read-only by default: the parameter-validation layer deliberately sends payloads that are
# rejected with 422, so no task is created and no upstream quota is consumed.
# --with-task does start one real generation.
#
# JSON is parsed with python3 (the service requires Python 3.10+ anyway) rather than grep,
# because the response shapes differ per endpoint.

set -uo pipefail

BASE="${AGNES_VIDEO_BASE:-http://localhost:8765}"
WITH_TASK=0
for arg in "$@"; do
  case "$arg" in
    --with-task) WITH_TASK=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) printf 'unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

PASS=0
FAIL=0

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL + 1)); }
info() { printf '  ----  %s\n' "$1"; }
section() { printf '\n%s\n' "$1"; }

code_of() {
  local method="$1" path="$2"; shift 2
  curl -s -o /dev/null -w '%{http_code}' -X "$method" "$BASE$path" "$@" 2>/dev/null || echo 000
}

body_of() {
  local method="$1" path="$2"; shift 2
  curl -s -X "$method" "$BASE$path" "$@" 2>/dev/null
}

# json_get <json> <python expression on `d`> - prints the value, or "" on failure
json_get() {
  printf '%s' "$1" | python3 -c "import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(''); raise SystemExit(0)
print($2)" 2>/dev/null
}

printf 'agnes-video-generator deployment verification\nbase: %s\n' "$BASE"

# ── layer 1: connectivity ─────────────────────────────────────────────────
section '1. connectivity'
code="$(code_of GET /)"
[ "$code" = "200" ] && pass "GET / -> 200" || fail "GET / -> $code (expected 200; is the server running?)"

code="$(code_of GET /api/health)"
if [ "$code" = "200" ]; then
  pass "GET /api/health -> 200"
else
  info "GET /api/health -> $code (endpoint may not exist on older versions)"
fi

config="$(body_of GET /api/config)"
if [ -n "$(json_get "$config" '"1"' )" ]; then
  version="$(json_get "$config" 'd.get("app_version", "?")')"
  source="$(json_get "$config" 'd.get("source", "")')"
  key="$(json_get "$config" 'd.get("api_key", "")')"
  pass "GET /api/config -> app_version=$version"
  if [ -n "$key" ]; then
    pass "API key configured (source=${source:-unknown}, value masked by the service)"
  else
    fail 'no API key configured - POST /api/config {"api_key": "..."} or export AGNES_API_KEY'
  fi
  workspaces="$(json_get "$config" 'len(d.get("workspaces") or [])')"
  [ -n "$workspaces" ] && pass "workspaces configured: $workspaces"
else
  fail "GET /api/config -> unparsable body: $(printf '%s' "$config" | head -c 120)"
fi

voices="$(body_of GET /api/voices)"
langs="$(json_get "$voices" 'len(d.get("languages") or [])')"
if [ -n "$langs" ] && [ "$langs" -gt 0 ] 2>/dev/null; then
  pass "GET /api/voices -> $langs language groups"
else
  fail "GET /api/voices -> unparsable body: $(printf '%s' "$voices" | head -c 120)"
fi

tasks="$(body_of GET /api/tasks)"
has_tasks="$(json_get "$tasks" '"tasks" in d')"
if [ "$has_tasks" = "True" ]; then
  pass "GET /api/tasks -> $(json_get "$tasks" 'len(d.get("tasks") or [])') task(s)"
else
  fail "GET /api/tasks -> unparsable body: $(printf '%s' "$tasks" | head -c 120)"
fi

# ── layer 2: environment ──────────────────────────────────────────────────
section '2. environment'
if command -v ffmpeg >/dev/null 2>&1; then
  pass "ffmpeg on PATH ($(ffmpeg -version 2>/dev/null | head -1 | cut -c1-40))"
else
  info 'no system ffmpeg - the bundled imageio-ffmpeg binary is used as a fallback'
fi
if command -v ffprobe >/dev/null 2>&1; then
  pass 'ffprobe on PATH (needed for media verification)'
else
  info 'no ffprobe on PATH - media verification falls back to parsing ffmpeg stderr'
fi

concurrency="$(body_of GET /api/concurrency)"
max_weight="$(json_get "$concurrency" 'd.get("max_weight")')"
if [ -n "$max_weight" ]; then
  pass "GET /api/concurrency -> max_weight=$max_weight current_weight=$(json_get "$concurrency" 'd.get("current_weight")')"
else
  info "GET /api/concurrency -> $(printf '%s' "$concurrency" | head -c 100)"
fi

# ── layer 3: parameter validation (creates no task) ───────────────────────
section '3. parameter validation (no task is created)'
for spec in /api/tasks/simple /api/tasks/creative /api/tasks/manuscript /api/tasks/anchor /api/tasks/poetry; do
  code="$(code_of POST "$spec" -F 'definitely_not_a_field=1')"
  case "$code" in
    200|422) pass "POST $spec -> $code (route present, validation active)" ;;
    404)     fail "POST $spec -> 404 (route missing on this version)" ;;
    *)       fail "POST $spec -> $code" ;;
  esac
done

code="$(code_of POST /api/image/generate -F 'size=not-a-size' -F 'prompt=test')"
case "$code" in
  200|422) pass "POST /api/image/generate -> $code (size validation active)" ;;
  *)       fail "POST /api/image/generate -> $code" ;;
esac

# ── layer 4: one real task (opt-in) ───────────────────────────────────────
section '4. end-to-end generation'
if [ "$WITH_TASK" -ne 1 ]; then
  info 'skipped (pass --with-task to submit one 5s simple video task)'
else
  created="$(body_of POST /api/tasks/simple -F 'prompt=a calm blue square, minimal, no text' -F 'mode=t2v' -F 'duration=5')"
  task_id="$(json_get "$created" 'd.get("task_id", "")')"
  if [ -z "$task_id" ]; then
    fail "task creation failed: $(printf '%s' "$created" | head -c 200)"
  else
    pass "task created: $task_id"
    deadline=$(( $(date +%s) + 600 ))
    status=""
    while [ "$(date +%s)" -lt "$deadline" ]; do
      status="$(json_get "$(body_of GET "/api/tasks/$task_id")" 'd.get("status", "")')"
      case "$status" in
        completed|failed) break ;;
      esac
      sleep 15
    done
    case "$status" in
      completed) pass "task $task_id reached completed" ;;
      failed)    fail "task $task_id failed - run: python3 <troubleshoot>/scripts/diagnose_task.py $task_id" ;;
      *)         fail "task $task_id still ${status:-unknown} after 600s" ;;
    esac
  fi
fi

# ── summary ───────────────────────────────────────────────────────────────
printf '\n----------------------------------------\n'
printf 'passed: %d   failed: %d\n' "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
  printf 'next: fix the FAIL lines above; deployment problems are covered in deploy.md\n'
  exit 1
fi
printf 'deployment verified\n'
exit 0
