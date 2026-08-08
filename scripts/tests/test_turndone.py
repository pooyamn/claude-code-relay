#!/usr/bin/env python3
"""Unit tests for relay-turn-done's session-key resolution.

The Stop hook writes the marker the watcher waits on. If it keys that marker by
the raw `cwd`, a session whose working directory sits in a SUBDIRECTORY of the
bound folder (a monorepo subproject, a worktree) writes to cr-<md5(subdir)> while
the watcher keeps reading cr-<md5(bound)>. The marker is never seen, every turn
falls back to scraping the pane -- and the TUI's pane is an alternate screen with
zero scrollback, so any reply longer than the visible ~50 lines arrives cropped
from the top, mid-table.
"""
import importlib.util, os, sys, tempfile
from importlib.machinery import SourceFileLoader

DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(DIR)
loader = SourceFileLoader("turndone", os.path.join(SCRIPTS, "relay-turn-done"))
spec = importlib.util.spec_from_loader("turndone", loader)
t = importlib.util.module_from_spec(spec)
loader.exec_module(t)

fails = 0
def check(desc, cond):
    global fails
    print(("[ok  ] " if cond else "[FAIL] ") + desc)
    if not cond:
        fails += 1

# TMUX_PANE would short-circuit to the real tmux session; drop it so these tests
# exercise the walk-up path deterministically.
os.environ.pop("TMUX_PANE", None)

base = tempfile.mkdtemp()
bound = os.path.join(tempfile.mkdtemp(), "project")
os.makedirs(os.path.join(bound, "sub", "deeper"), exist_ok=True)
bound_key = t._key_for(bound)
open(os.path.join(base, f"target-{bound_key}.json"), "w").write('{"chat":"-100","thread":"1"}')

check("bound folder resolves to itself",
      t.resolve_key(bound, base) == bound_key)
check("subdirectory resolves to the BOUND folder",
      t.resolve_key(os.path.join(bound, "sub"), base) == bound_key)
check("deeper subdirectory resolves to the BOUND folder",
      t.resolve_key(os.path.join(bound, "sub", "deeper"), base) == bound_key)

# An unbound path has no ancestor target file: fall back to hashing cwd rather
# than walking to / and picking up an unrelated session.
other = tempfile.mkdtemp()
check("unbound path falls back to its own hash",
      t.resolve_key(other, base) == t._key_for(other))
check("unbound path does NOT borrow the bound key",
      t.resolve_key(other, base) != bound_key)

print()
print("turndone: " + ("all passed" if not fails else f"{fails} failed"))
sys.exit(1 if fails else 0)
