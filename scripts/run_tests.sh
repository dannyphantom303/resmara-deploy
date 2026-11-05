#!/usr/bin/env bash
# The project's test suite: every isolated check, in one command.
#
#   ./scripts/run_tests.sh              # uses `python3`
#   PYTHON=/path/to/.venv/bin/python ./scripts/run_tests.sh
#
# Exits non-zero on the first failure. Deliberately excludes tests/smoke_live.py,
# tests/real_build_once.py and tests/probe_report.py: those talk to a running server (and the
# last two spend nothing but do build real campaigns), so they belong to a deployment check —
# `scripts/selfcheck.py --base <url>` is that check.
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
export PYTHONPATH="$PWD"

fail=0
run() {
  local label="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    printf 'ok   %-26s %s\n' "$label" "$(printf '%s' "$out" | tail -1)"
  else
    printf 'FAIL %-26s\n' "$label"
    printf '%s\n' "$out" | tail -15
    fail=1
  fi
}

for t in tests/test_*.py; do
  run "$(basename "$t" .py)" "$PY" "$t"
done

if command -v node >/dev/null 2>&1; then
  run test_frontend_api node tests/test_frontend_api.js
  run test_deployed_ui  node tests/test_deployed_ui.js
else
  echo "skip node suites (node not installed)"
fi

[ "$fail" = 0 ] && echo "ALL SUITES PASSED" || echo "SUITE FAILURES"
exit "$fail"
