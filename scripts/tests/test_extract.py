#!/usr/bin/env python3
"""Unit tests for relay-extract-message.py against real composed-prompt shapes.

Runs the actual script as a subprocess (stdin -> stdout), so it tests exactly
what the backend invokes. No network, no tmux, no Telegram.
"""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixtures import CASES

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "relay-extract-message.py")

def extract(prompt):
    r = subprocess.run(["python3", SCRIPT], input=prompt, capture_output=True, text=True)
    return r.stdout.strip()

def main():
    fails = 0
    for i, (prompt, expected) in enumerate(CASES, 1):
        got = extract(prompt)
        ok = got == expected
        if not ok:
            fails += 1
        status = "ok  " if ok else "FAIL"
        print(f"[{status}] case {i}: expected {expected!r}")
        if not ok:
            print(f"         got      {got!r}")
    total = len(CASES)
    print(f"\nextract: {total - fails}/{total} passed")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
