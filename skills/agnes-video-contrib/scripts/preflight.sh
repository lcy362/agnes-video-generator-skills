#!/usr/bin/env bash
# Local pre-flight for agnes-video-generator - mirrors what CI checks, in CI's order.
# Stops at the first failure.
#
#   bash preflight.sh                 # fast: compile, ruff, i18n, static check, tests
#   bash preflight.sh --full          # + CI-equivalent coverage gate + mock regression (slow)
#   bash preflight.sh --frontend      # + npm ci / npm test / npm run build
#
# Run it from the project root. Exit code 1 means do not push yet.

set -uo pipefail

FULL=0
FRONTEND=0
for arg in "$@"; do
  case "$arg" in
    --full) FULL=1 ;;
    --frontend) FRONTEND=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) printf 'unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

fail() { printf '\033[31mFAIL\033[0m %s\n' "$1"; exit 1; }
ok() { printf '\033[32mOK\033[0m   %s\n' "$1"; }
skip() { printf '\033[33mSKIP\033[0m %s\n' "$1"; }
step() { printf '\n== %s\n' "$1"; }

[ -f server.py ] || fail "run this from the project root (server.py not found)"

PY="python3"
[ -x .venv/bin/python ] && PY=".venv/bin/python"
command -v "$PY" >/dev/null 2>&1 || fail "no usable python interpreter"

# ── compile changed Python files ──────────────────────────────────────────
step "compile changed Python files"
changed_py=""
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  changed_py="$( { git diff --name-only HEAD -- '*.py' 2>/dev/null
                    git ls-files --others --exclude-standard -- '*.py' 2>/dev/null; } | sort -u )"
fi
if [ -n "$changed_py" ]; then
  count=0
  while IFS= read -r file; do
    [ -n "$file" ] || continue
    $PY -m py_compile "$file" || fail "py_compile failed: $file"
    count=$((count + 1))
  done <<< "$changed_py"
  ok "compiled $count changed file(s)"
else
  skip "no changed Python files detected"
fi

# ── ruff ──────────────────────────────────────────────────────────────────
step "ruff"
RUFF=""
if command -v ruff >/dev/null 2>&1; then
  RUFF="ruff"
elif $PY -m ruff --version >/dev/null 2>&1; then
  RUFF="$PY -m ruff"
fi
if [ -n "$RUFF" ]; then
  $RUFF check core/ web/ utils/ models/ scripts/ --output-format=concise || fail "ruff findings above"
  ok "ruff clean"
else
  skip "ruff not installed (pip install ruff)"
fi

# ── i18n completeness ─────────────────────────────────────────────────────
step "i18n completeness"
if [ -f scripts/i18n_check.py ]; then
  $PY scripts/i18n_check.py
  case $? in
    0) ok "all language files complete" ;;
    1) fail "i18n keys are missing (see the list above) - zh and en must both be complete" ;;
    *) fail "i18n check could not parse a language file" ;;
  esac
else
  skip "scripts/i18n_check.py not found"
fi

# ── frontend source vs committed build output ─────────────────────────────
step "static/ vs frontend/src"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  src_changed="$(git status --porcelain -- frontend/src 2>/dev/null | wc -l | tr -d ' ')"
  static_changed="$(git status --porcelain -- static 2>/dev/null | wc -l | tr -d ' ')"
  if [ "$src_changed" -gt 0 ] && [ "$static_changed" -eq 0 ]; then
    fail "frontend/src changed but static/ did not - run: cd frontend && npm run build, then stage static/"
  elif [ "$src_changed" -gt 0 ]; then
    ok "frontend/src and static/ both have changes (verify the rebuild with --frontend)"
  else
    ok "no frontend source changes"
  fi
else
  skip "not a git work tree"
fi

# ── tests ─────────────────────────────────────────────────────────────────
step "tests"
if [ "$FULL" -eq 1 ]; then
  $PY -m pytest tests/ \
      -o addopts="-ra -q" \
      --cov=core --cov=models --cov=utils --cov=web \
      --cov-report=term-missing --cov-fail-under=55 -q \
    || fail "tests or the 55% coverage gate failed"
  ok "tests + coverage gate passed (CI-equivalent)"
else
  $PY -m pytest tests/ -q || fail "tests failed"
  ok "tests passed (fast subset - add --full for the CI-equivalent run)"
fi

# ── mock regression (--full) ──────────────────────────────────────────────
if [ "$FULL" -eq 1 ]; then
  step "mock regression"
  if [ -x scripts/run_mock_regression.sh ]; then
    ./scripts/run_mock_regression.sh || fail "mock regression failed"
    ok "mock regression passed"
  else
    skip "scripts/run_mock_regression.sh not found or not executable"
  fi
fi

# ── frontend (--frontend) ─────────────────────────────────────────────────
if [ "$FRONTEND" -eq 1 ]; then
  step "frontend"
  [ -d frontend ] || fail "frontend/ not found"
  ( cd frontend && npm ci --ignore-scripts ) || fail "npm ci failed"
  ( cd frontend && npm test ) || fail "frontend unit tests failed"
  ( cd frontend && npm run build ) || fail "frontend build failed (type-check included)"
  ok "frontend tests and build passed"
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if [ -n "$(git status --porcelain -- static 2>/dev/null)" ]; then
      ok "static/ now has changes - stage them in the same commit"
    else
      ok "static/ is unchanged after the rebuild"
    fi
  fi
fi

printf '\nall pre-flight checks passed'
[ "$FULL" -eq 1 ] && printf ' (full)'
[ "$FRONTEND" -eq 1 ] && printf ' (with frontend)'
printf '\n'
exit 0
