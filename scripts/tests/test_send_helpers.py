#!/usr/bin/env python3
"""Unit tests for claude-relay-send.py PURE helpers (no tmux / Telegram).

Importing the module is side-effect-free (main() is guarded), so we can call
progress_snapshot / parse_menu / _thread_args directly.
"""
import os, sys, time, importlib.util

DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(DIR)
# ASSIGN, don't setdefault: these tests are usually run from INSIDE a relay session,
# where RELAY_CHAT_ID/RELAY_THREAD_ID are already exported by claude-tui-backend-multi.
# setdefault left the real values in place, so "thread args from env" compared against
# the live topic id and failed everywhere except a clean shell.
os.environ["RELAY_CHAT_ID"] = "-100"
os.environ["RELAY_THREAD_ID"] = "5"
# Pin the OpenClaw config the module reads, so rich-vs-plain mode (and therefore the
# per-message cap) is a property of the test, not of the host's live settings.
_PLAIN_CFG = os.path.join(DIR, "cfg-plain.json")
_RICH_CFG = os.path.join(DIR, "cfg-rich.json")
open(_PLAIN_CFG, "w").write('{"channels": {"telegram": {}}}')
open(_RICH_CFG, "w").write('{"channels": {"telegram": {"richMessages": true}}}')
os.environ["RELAY_CFG"] = _PLAIN_CFG
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

# --- rich mode: bigger cap, and tables must survive untouched ----------------
def _mode(path):
    os.environ["RELAY_CFG"] = path
    m._RICH_CACHE.update(t=0.0, v=None)      # drop the TTL cache between modes
_mode(_RICH_CFG)
check("rich mode detected", m.rich_enabled() is True)
check("rich raises the cap", m.text_limit() == m.TG_RICH_LIMIT)
_tbl = "Intro\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nOutro"
check("rich passes a table through unfenced",
      m.render_reply(_tbl) == _tbl.strip() and "```" not in m.render_reply(_tbl))
sent.clear()
m.deliver("x" * 5000)
check("rich sends 5k as ONE message", len(sent) == 1)
_mode(_PLAIN_CFG)
check("plain mode detected", m.rich_enabled() is False)
check("plain keeps the 4096 cap", m.text_limit() == m.TG_LIMIT)
check("plain fences a table but keeps its rows",
      "```" in m.render_reply(_tbl) and "| A | B |" in m.render_reply(_tbl))

# --- box-drawing tables: the shape Claude Code actually emits -----------------
# The converter reads markdown only, so a box table passed through in rich mode
# lands in a proportional font with the columns collapsed -- worse than the fence
# it used to get. It must be converted, and never escape unfenced.
_box = "\u250c\u2500\u2500\u2500\u252c\u2500\u2500\u2500\u2510\n\u2502 a \u2502 b \u2502\n\u251c\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2524\n\u2502 1 \u2502 2 \u2502\n\u2514\u2500\u2500\u2500\u2534\u2500\u2500\u2500\u2518"
_mode(_RICH_CFG)
_rb = m.render_reply(_box)
check("rich converts a box table to markdown",
      _rb.startswith("| a | b |") and "|---|---|" in _rb)
check("no box glyphs survive in rich mode", "\u2502" not in _rb and "\u250c" not in _rb)
_art = "\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2510\n\u2502 ART  \u2502\n\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2518"
check("un-gridded box art falls back to a fence", "```" in m.render_reply(_art))
_mode(_PLAIN_CFG)
check("plain still fences a box table", "```" in m.render_reply(_box))

# --- CHROME must not eat table DATA rows -------------------------------------
# Regression: `│` was in the banner character class, so every "│ a │ b │" row was
# dropped as chrome while the ├─┼─┤ borders survived. A scraped table then arrived
# as a fence containing nothing but borders. A banner body has two bars, a table
# row has three or more.
_row = "  \u2502 Analog switches \u2502 19 x TS5A23157 \u2502 +$1.48 \u2502"
_bord = "  \u251c\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2524"
_banner = "  \u2502 Welcome back to Claude Code   \u2502"
_round = "  \u256d\u2500\u2500\u2500\u2500\u2500\u256e"
check("CHROME keeps a table data row", not m.CHROME.search(_row))
check("CHROME keeps a table border row", not m.CHROME.search(_bord))
check("CHROME still drops the banner body", bool(m.CHROME.search(_banner)))
check("CHROME still drops rounded banner rows", bool(m.CHROME.search(_round)))

# --- opencode backend --------------------------------------------------------
# Answer sits between the "+ Thought:" header and the "▣ Build ·" footer, with a
# right-hand sidebar painted on the SAME rows -- so the extractor must cut at the
# content width derived from the input box border, not read whole lines.
_bar = "  \u2579" + "\u2580" * 60
_oc_pane = "\n".join([
    "  \u2503  what is 2+2?                                                  Context",
    "     + Thought: 705ms                                                   13,834 tokens",
    "     2+2 equals 4.                                                      $0.00 spent",
    "     \u25a3  Build \u00b7 Ox Alpha Free (Unlimited) \u00b7 4.2s        LSP",
    _bar + "   scratchpad:main",
])
check("opencode answer extracted", m.opencode_reply_lines(_oc_pane, "what is 2+2?") == ["2+2 equals 4."])
check("opencode drops the sidebar", "tokens" not in " ".join(m.opencode_reply_lines(_oc_pane, "")))
check("opencode drops the echoed prompt", "what is 2+2?" not in " ".join(m.opencode_reply_lines(_oc_pane, "")))
check("no footer in the answer", "Build" not in " ".join(m.opencode_reply_lines(_oc_pane, "")))
check("cc model ox resolves to opencode",
      (m.backend_for_model("ox") or {}).get("backend") == "opencode")

# relay-alt-launch is the single resolver for BOTH `cc model <x>` and a folder's
# pinned default, so a token cannot mean two different commands.
import subprocess as _sp
_R = os.path.join(SCRIPTS, "relay-alt-launch")
def _alt(tok, folder=""):
    return _sp.run([sys.executable, _R, tok, folder], capture_output=True, text=True).stdout
check("alt-launch resolves ox to opencode", '"backend": "opencode"' in _alt("ox", "/tmp"))
check("alt-launch resolves ik3 to kimi", '"backend": "kimi"' in _alt("ik3", "/tmp"))
check("alt-launch ignores a claude model", _alt("opus", "/tmp").strip() == "")
# opencode's -c continues the last session GLOBALLY; an unknown folder must start
# clean rather than inherit another project's conversation.
check("alt-launch adds no resume for an unknown folder",
      " -s " not in _alt("ox", "/tmp/definitely-not-an-opencode-project"))
check("alt-launch never uses bare -c for opencode", " -c" not in _alt("ox", "/tmp"))

# --- a failed send must NOT be recorded as delivered ------------------------
# Recording it loses the reply permanently: the dedup guard then treats it as
# already sent and never retries. Seen live when a relinked ada-url left an older
# node unable to load libada.3.dylib and every send failed for ~20 minutes.
_real_send = m.tg_send
m.tg_send = lambda text, silent=False: ""          # simulate a failing send
check("deliver() reports failure", m.deliver("anything") is False)
m.tg_send = lambda text, silent=False: "12345"     # simulate success
check("deliver() reports success", m.deliver("anything") is True)
check("empty reply is not a success", m.deliver("") is False)

# --- remote control on by default for opencode -------------------------------
# opencode's TUI only serves an API when given --port; without it a session can
# only be driven from its terminal. The port is derived from the folder so it
# survives restarts, and bound to loopback so remote access goes via a tunnel.
_oc = _alt("ox", "/tmp/some-project")
check("opencode launches with a port", "--port " in _oc)
check("opencode binds loopback only", "--hostname 127.0.0.1" in _oc)
check("port is stable across calls", _alt("ox", "/tmp/some-project").split("--port")[1].split()[0]
                                      == _oc.split("--port")[1].split()[0])
check("different folders get different ports",
      _alt("ox", "/tmp/aaa").split("--port")[1].split()[0]
      != _alt("ox", "/tmp/bbb").split("--port")[1].split()[0])
check("kimi is unaffected by the port logic", "--port" not in _alt("ik3", "/tmp"))

# --- opencode with TOOL USE: the layout that silenced a live session ----------
# Interleaved text / tool lines / thinking, with "+ Thought:" landing immediately
# before the footer. Anchoring the start on the thinking header collapsed the range
# to nothing, so an idle, healthy session returned "" forever.
_W = 70          # content width; the sidebar must start AFTER it, as it does live
def _row(main, side=""):
    return main.ljust(_W) + "  " + side
_tool_pane = "\n".join([
    _row("  \u2503  render the sheets", "Context"),
    _row("     All 7 sheets rendered. Now the visual inspection:", "13,834 tokens"),
    _row("     \u2192 Read sheet-1.png", "$0.00 spent"),
    _row("     $ mkdir -p /tmp/out", "LSP"),
    _row("     One left \u2014 the MCU core sheet:", "LSPs are disabled"),
    _row("     + Thought: 19.2s"),
    _row("     \u25a3  Build \u00b7 Ox Alpha Free (Unlimited)"),
    "  \u2579" + "\u2580" * (_W - 3) + "   scratch:main",
])
_got = m.opencode_reply_lines(_tool_pane, "render the sheets")
check("tool-heavy turn still extracts the answer",
      _got == ["All 7 sheets rendered. Now the visual inspection:",
               "One left \u2014 the MCU core sheet:"])
check("tool invocation lines are dropped", not any(x.startswith("\u2192") for x in _got))
check("shell echo lines are dropped", not any(x.startswith("$") for x in _got))
check("thinking header is dropped", not any("Thought" in x for x in _got))


m.tg_send = _real_send
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
