#!/usr/bin/env bash
# Inner legacy suite (uses mocks, but does not itself enforce OS isolation).
# Developer entry point: python3 scripts/tests/run_isolated.py
# That copies sources/state into scratch and runs this file in an OS sandbox.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
rc=0

run() {
  echo "==================== $1 ===================="
  "${@:2}" || rc=1
  echo
}

run "extract"       python3 "$DIR/test_extract.py"
run "send-helpers"  python3 "$DIR/test_send_helpers.py"
run "turndone"      python3 "$DIR/test_turndone.py"
run "backend"       bash    "$DIR/test_backend.sh"

echo "============================================="
if [ "$rc" -eq 0 ]; then echo "ALL SUITES PASSED"; else echo "SOME SUITES FAILED"; fi
exit $rc
