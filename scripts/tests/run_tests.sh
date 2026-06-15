#!/usr/bin/env bash
# Run the whole relay test suite. No network, no tmux, no Telegram.
#   bash tests/run_tests.sh
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
run "backend"       bash    "$DIR/test_backend.sh"

echo "============================================="
if [ "$rc" -eq 0 ]; then echo "ALL SUITES PASSED"; else echo "SOME SUITES FAILED"; fi
exit $rc
