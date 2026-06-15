#!/usr/bin/env python3
"""Unit tests for claude-relay-send.py PURE helpers (no tmux / Telegram).

Importing the module is side-effect-free (main() is guarded), so we can call
progress_snapshot / parse_menu / _thread_args directly.
"""
import os, sys, time, importlib.util

DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(DIR)
os.environ.setdefault("RELAY_CHAT_ID", "-100")
os.environ.setdefault("RELAY_THREAD_ID", "5")
spec = importlib.util.spec_from_file_location("relaysend", os.path.join(SCRIPTS, "claude-relay-send.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

fails = 0
def check(desc, cond):
    global fails
    print(("[ok  ] " if cond else "[FAIL] ") + desc)
    if not cond:
        fails += 1

# --- progress_snapshot: the live streamed view -------------------------------
raw = ("user prompt echo\n"
       "⏺ Looking into it\n"
       "✻ Combobulating… (12s · ↓ 3k tokens · esc to interrupt)\n"
       "reading files\n"
       "╭────╮\n│ >  │\n╰────╯\n"
       "  for shortcuts")
snap = m.progress_snapshot(raw, time.time() - 12)
check("snapshot keeps a content line", "reading files" in snap)
check("snapshot drops input-box chrome", ("│ >" not in snap) and ("╭" not in snap))
check("snapshot drops 'for shortcuts' footer", "for shortcuts" not in snap)
check("snapshot starts with a status header", snap.startswith("⏳"))

# --- parse_menu: numbered selection with a cursor ----------------------------
menu_pane = "Select a model:\n  1. Default\n❯ 2. Sonnet\n  3. Opus\n  Esc to cancel"
menu = m.parse_menu(menu_pane)
check("parse_menu extracts options", menu is not None and menu["options"] == ["Default", "Sonnet", "Opus"])
check("parse_menu None on prose", m.parse_menu("just a normal reply\nwith two lines") is None)

# --- addressing --------------------------------------------------------------
check("thread args from env", m._thread_args() == ["--thread-id", "5"])

print(f"\nsend-helpers: {'all passed' if not fails else str(fails) + ' failed'}")
sys.exit(1 if fails else 0)
