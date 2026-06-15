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

# --- progress_snapshot: trims the echoed user prompt (and anything above it) --
PROMPT = "Msges should not contain text before my last prompt , its redundant"
echoed = ("⏺ stale prior-turn line\n"
          + PROMPT + "\n"
          "⏺ Let me check the extractor\n"
          "✻ Crunched (4s · esc to interrupt)\n"
          "fresh streaming output")
snap2 = m.progress_snapshot(echoed, time.time() - 4, PROMPT)
check("snapshot trims the echoed prompt line", "should not contain text" not in snap2)
check("snapshot trims prior-turn text above the prompt", "stale prior-turn line" not in snap2)
check("snapshot keeps output after the prompt", "fresh streaming output" in snap2)

# --- parse_menu: numbered selection with a cursor ----------------------------
menu_pane = "Select a model:\n  1. Default\n❯ 2. Sonnet\n  3. Opus\n  Esc to cancel"
menu = m.parse_menu(menu_pane)
check("parse_menu extracts options", menu is not None and menu["options"] == ["Default", "Sonnet", "Opus"])
check("parse_menu None on prose", m.parse_menu("just a normal reply\nwith two lines") is None)
# REGRESSION: a prose numbered list (in an answer) must NOT become buttons, even
# when a real menu is also on screen -- buttons only for the actual cursor menu.
check("parse_menu None on a prose numbered list (no cursor)",
      m.parse_menu("Steps to enable:\n1. config change\n2. touch sentinel\n3. restart") is None)
prose_plus_menu = ("Here are the steps:\n1. config change\n2. touch sentinel\n3. restart\n\n"
                   "Select a model:\n  1. Default\n❯ 2. Sonnet\n  3. Opus\nEsc to cancel")
pm = m.parse_menu(prose_plus_menu)
check("parse_menu ignores the prose list, keeps the real menu",
      pm is not None and pm["options"] == ["Default", "Sonnet", "Opus"])

# --- addressing --------------------------------------------------------------
check("thread args from env", m._thread_args() == ["--thread-id", "5"])

# --- persistent watcher model: target + last-prompt persistence --------------
m.save_target("-100200300", "42")
m.CHAT_ID, m.THREAD_ID = "", ""        # clear, then reload from the file
m.refresh_target()
check("target round-trips chat", m.CHAT_ID == "-100200300")
check("target round-trips thread", m.THREAD_ID == "42")
m.write_last_prompt("do the thing")
check("last prompt round-trips", m.read_last_prompt() == "do the thing")

# --- deliver(): chunks over the 4096 cap, never exceeds it -------------------
sent = []
m.tg_send = lambda text, silent=False: sent.append(text) or "id"
m.deliver("x" * (m.TG_LIMIT + 50))
check("deliver chunks a >cap reply", len(sent) == 2)
check("deliver chunks stay within cap", all(len(s) <= m.TG_LIMIT for s in sent))
sent.clear()
m.deliver("short")
check("deliver sends a short reply once", sent == ["short"])

# --- inject(): types + returns '' (watcher delivers), no menu open -----------
typed = []
m.tmux = lambda *a, **k: typed.append(a) or ""
m.clear_menu()                          # ensure no stray menu state
out = m.inject("hello there")
check("inject returns '' (out-of-band delivery)", out == "")
check("inject recorded the typed prompt", m.read_last_prompt() == "hello there")
check("inject submitted via tmux send-keys", any("send-keys" in a for a in typed))

print(f"\nsend-helpers: {'all passed' if not fails else str(fails) + ' failed'}")
sys.exit(1 if fails else 0)
