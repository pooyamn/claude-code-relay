#!/usr/bin/env python3
"""Drive a persistent interactive `claude` TUI in tmux: send a prompt, wait for
the turn, return Claude's reply as clean text. Subscription-billed (the TUI runs
on the Max plan; we just drive it).

Multi-choice support: when Claude shows a selection menu (model picker, plan
approval, any numbered question), we DON'T scrape it as a reply. We return the
options formatted for Telegram and remember a menu is open; the user's next
message (a number) is sent back as an arrow+Enter selection into the TUI.
"""
import subprocess, sys, time, hashlib, re, os, json, shutil

SESSION = os.environ.get("CLAUDE_RELAY_SESSION", "clauderelay")
CHAT_ID = os.environ.get("RELAY_CHAT_ID", "")     # telegram chat id (numeric)
THREAD_ID = os.environ.get("RELAY_THREAD_ID", "")  # forum topic id, if any
STREAM = os.environ.get("RELAY_STREAM", "1") != "0"  # live-edit progress; 0 disables
TG_LIMIT = 4096                                    # telegram message hard cap
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "relay-work")
STATE = os.path.join(STATE_DIR, f"menu-{SESSION}.json")
STREAM_LOG = os.path.join(STATE_DIR, f"stream-{SESSION}.log")
DEBUG = os.path.exists(os.path.join(STATE_DIR, "DEBUG"))  # opt-in frame logging (off by default)
TARGET = os.path.join(STATE_DIR, f"target-{SESSION}.json")    # persisted chat/thread for the watcher
LASTPROMPT = os.path.join(STATE_DIR, f"prompt-{SESSION}.txt")  # last typed prompt (reply anchoring)
DELIVERED = os.path.join(STATE_DIR, f"delivered-{SESSION}.txt")  # last delivered reply hash (dup guard across restarts)
TURNDONE = os.path.join(STATE_DIR, f"turndone-{SESSION}.json")  # Stop-hook 'turn finished' marker (deterministic delivery)
# Persistent-watcher delivery model: a single long-lived watcher per session
# tails the pane and delivers EVERY turn (incl. long/slow ones and out-of-band
# output), while per-message calls only inject. Opt-in via env or a sentinel
# file so the default synchronous path is untouched until you flip it on.
WATCH = (os.environ.get("RELAY_WATCH") == "1"
         or os.path.exists(os.path.join(STATE_DIR, "WATCH")))
# Native-streaming model: emit Claude `stream-json` JSONL on stdout and let
# OpenClaw stream it to the channel with its OWN fast in-process edit loop (the
# backend must be configured output:"jsonl" + jsonlDialect:"claude-stream-json").
# No tg_* calls -- OpenClaw owns delivery. Opt-in via env or a sentinel file.
JSONL = (os.environ.get("RELAY_JSONL") == "1"
         or os.path.exists(os.path.join(STATE_DIR, "JSONL")))

def _thread_args():
    return ["--thread-id", THREAD_ID] if THREAD_ID else []

MSG_OPS = os.path.join(STATE_DIR, "msg-ops.log")

def _oplog(op, mid, text, r=None):
    """Audit trail of EVERY outbound Telegram op (send/edit/delete/buttons) with
    its actual CLI result, so we can see exactly what the relay did and whether
    Telegram accepted it. Always on."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        res = ""
        if r is not None:
            out = (r.stdout or "").strip().replace("\n", " ")
            res = f" rc={r.returncode} out={out[:240]}"
            errs = (r.stderr or "").strip().replace("\n", " ")
            if errs:
                res += f" ERR={errs[:160]}"
        preview = (text or "").replace("\n", "\\n")[:70]
        with open(MSG_OPS, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {op:11} mid={mid or '-':<6} "
                    f"chat={CHAT_ID} thr={THREAD_ID or '-'} len={len(text or '')} "
                    f"text='{preview}'{res}\n")
    except Exception:
        pass

def tg_buttons(question, options):
    """Send native Telegram inline buttons for a menu. Returns the message id.

    The full option text ALSO goes in the message body: Telegram truncates long
    button labels to a single narrow line ("Persiste…"), so the body is what
    keeps every option fully readable. The buttons are just the tap targets."""
    body = "\n".join([question or "Choose an option:", ""]
                     + [f"{i}. {o}" for i, o in enumerate(options, 1)])
    # ONE button per row: OpenClaw groups buttons within a single "buttons" block
    # into rows of 3 (TELEGRAM_INTERACTIVE_ROW_SIZE). Emitting a separate block
    # per button forces a full-width, one-per-line layout, so longer labels fit
    # before Telegram truncates them.
    pres = {"blocks": [
        {"type": "buttons", "buttons": [{"label": f"{i+1}. {o}"[:60], "value": f"ccsel:{i+1}"}]}
        for i, o in enumerate(options)]}
    r = subprocess.run(["openclaw", "message", "send", "--channel", "telegram",
                        "--target", CHAT_ID, *_thread_args(),
                        "--message", body[:TG_LIMIT],
                        "--presentation", json.dumps(pres), "--json"],
                       capture_output=True, text=True)
    try:
        mid = str(json.loads(r.stdout).get("payload", {}).get("messageId", ""))
    except Exception:
        mid = ""
    _oplog("SEND-BTNS", mid, body, r)
    return mid

def tg_remove_buttons(msg_id, note):
    """Edit the button message text; a text-only edit drops the inline keyboard
    (Telegram removes reply_markup when it isn't re-specified)."""
    if not (msg_id and CHAT_ID):
        return
    r = subprocess.run(["openclaw", "message", "edit", "--channel", "telegram",
                        "--target", CHAT_ID, *_thread_args(), "--message-id", str(msg_id),
                        "--message", note],
                       capture_output=True, text=True)
    _oplog("EDIT-BTNS", msg_id, note, r)

def tg_send(text, silent=False):
    """Send a plain text message to the bound chat/topic. Returns the message id.

    `silent=True` (Telegram --silent) delivers without a push notification --
    used for the live progress message so the user is pinged only once, by the
    final answer."""
    cmd = ["openclaw", "message", "send", "--channel", "telegram",
           "--target", CHAT_ID, *_thread_args(),
           "--message", text[:TG_LIMIT], "--json"]
    if silent:
        cmd.append("--silent")
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        mid = str(json.loads(r.stdout).get("payload", {}).get("messageId", ""))
    except Exception:
        m = re.search(r"Message ID:\s*(\d+)", r.stdout or "")
        mid = m.group(1) if m else ""
    _oplog("SEND" + ("-SILENT" if silent else ""), mid, text, r)
    return mid

def tg_send_media(path, caption=""):
    """Send a local image/file as media (used for TUI screenshots). --force-document
    keeps full resolution so the small terminal text stays legible -- a compressed
    Telegram photo blurs it. Returns the message id."""
    cmd = ["openclaw", "message", "send", "--channel", "telegram",
           "--target", CHAT_ID, *_thread_args(),
           "--media", path, "--force-document", "--json"]
    if caption:
        cmd += ["--message", caption[:TG_LIMIT]]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        mid = str(json.loads(r.stdout).get("payload", {}).get("messageId", ""))
    except Exception:
        mid = ""
    _oplog("SENDMEDIA", mid, path, r)
    return mid

def tg_delete(msg_id):
    """Best-effort delete of a message (the live progress bubble)."""
    if not (msg_id and CHAT_ID):
        return
    r = subprocess.run(["openclaw", "message", "delete", "--channel", "telegram",
                        "--target", CHAT_ID, "--message-id", str(msg_id)],
                       capture_output=True, text=True)
    _oplog("DELETE", msg_id, "", r)

def tg_edit(msg_id, text):
    if not (msg_id and CHAT_ID):
        return
    r = subprocess.run(["openclaw", "message", "edit", "--channel", "telegram",
                        "--target", CHAT_ID, *_thread_args(), "--message-id", str(msg_id),
                        "--message", text[:TG_LIMIT]],
                       capture_output=True, text=True)
    _oplog("EDIT", msg_id, text, r)

EDIT_SERVER = os.path.join(os.path.dirname(STATE_DIR), "relay-ws-edit-server.mjs")

class _WS:
    """Fast Telegram transport over the gateway websocket (one persistent Node
    helper, ~0.5s edits vs the ~2.8s CLI cold-start), so the live progress
    message can hold a real ~1s cadence. Falls back gracefully: if it can't
    connect, .ok is False and the caller uses the normal return path."""
    def __init__(self, target, thread):
        self.ok = False
        self._n = 0
        try:
            self.proc = subprocess.Popen(
                ["node", EDIT_SERVER, str(target), str(thread or "")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        except Exception:
            self.proc = None
            return
        self.ok = self._ready()

    def _ready(self, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            line = self.proc.stdout.readline()
            if not line:
                return False
            try:
                m = json.loads(line)
            except Exception:
                continue
            if m.get("ready"):
                return True
            if m.get("error"):
                return False
        return False

    def send(self, text, silent=False):
        if not self.ok:
            return ""
        self._n += 1; rid = f"s{self._n}"
        try:
            self.proc.stdin.write(json.dumps({"op": "send", "text": text[:TG_LIMIT],
                                              "silent": silent, "reqid": rid}) + "\n")
            self.proc.stdin.flush()
            end = time.time() + 8
            while time.time() < end:
                line = self.proc.stdout.readline()
                if not line:
                    break
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                if m.get("reqid") == rid:
                    return m.get("messageId") or ""
        except Exception:
            pass
        return ""

    def edit(self, mid, text):
        if not (self.ok and mid):
            return
        try:
            self.proc.stdin.write(json.dumps({"op": "edit", "mid": str(mid),
                                              "text": text[:TG_LIMIT]}) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    def delete(self, mid):
        if not (self.ok and mid):
            return
        try:
            self.proc.stdin.write(json.dumps({"op": "delete", "mid": str(mid)}) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    def close(self):
        try:
            self.proc.stdin.write(json.dumps({"op": "quit"}) + "\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=2)
        except Exception:
            try: self.proc.kill()
            except Exception: pass

def progress_snapshot(p, started, prompt=""):
    """Build a live 'thought process' view from the TUI pane while a turn runs:
    the spinner/status line plus the tail of the streaming output, chrome
    stripped, capped to Telegram's limit.

    `prompt` is the user's current message: when it's still visible in the pane
    (short turns) we trim everything up to and including its echoed line, so the
    stream never replays the user's own prompt or prior-turn text back at them.
    No-op once the prompt has scrolled off the top (long turns)."""
    lines = p.splitlines()
    needle = (prompt.strip().splitlines() or [""])[0][:60]
    if needle:
        cut = -1
        for i, l in enumerate(lines):
            if needle in l and not l.lstrip().startswith("⏺"):
                cut = i
        if cut >= 0:
            lines = lines[cut + 1:]
    # The footer chrome ("⏵⏵ bypass permissions… esc to interrupt", "? for
    # shortcuts") also matches the busy markers, so exclude it explicitly and
    # take the real spinner/token line ("✻ Cooked for 1m3s · ↓ 4.2k tokens").
    NOISE = re.compile(r"bypass permissions|shift\+tab|to cycle|for shortcuts|for agents", re.I)
    BORDER = re.compile(r"^[─▔━_│╭╮╰╯├┤┬┴┼┌┐└┘═╞╪╡╔╗╚╝║▕▏▎>·✻✶✢✽✳✺*\s]+$")
    # Claude's file/diff display rows are prefixed with a line number ("219 +  code",
    # "232  // ctx", bare "231"). In a progress bubble these are a wall of reflowed
    # code — collapse any run of them into a single ⋯ marker.
    LINENO = re.compile(r"^\d+(\s|$)")
    raw_status = ""
    for l in lines:
        if NOISE.search(l):
            continue
        if re.search(r"tokens|esc to interrupt|esc to cancel", l, re.I):
            raw_status = l.strip()
    # tidy the status: drop leading spinner glyph and the trailing "· esc to …"
    status = re.sub(r"^[✻✶✢✽✳✺·\s]+", "", raw_status)
    status = re.sub(r"\s*·?\s*esc to (interrupt|cancel).*$", "", status, flags=re.I).strip()
    body = []
    for l in lines:
        s = l.strip()
        if not s or BUSY.search(s) or READY.search(s) or NOISE.search(s) or s == raw_status:
            continue
        if re.search(r"tokens|esc to interrupt", s, re.I):
            continue
        if BORDER.match(s):                  # pure box-drawing / separator rows
            continue
        if LINENO.match(s):                  # code/diff dump row → collapse the run
            if body and body[-1] == "⋯":
                continue
            body.append("⋯")
            continue
        body.append(s)
    elapsed = int(time.time() - started)
    head = f"⏳ {status}" if status else f"⏳ working… ({elapsed}s)"
    tail = "\n".join(body[-30:])
    # Neutralise backticks: without the code-block wrapper an unbalanced one
    # (mid-render code) would swallow the rest into an inline code span.
    out = f"{head}\n\n{tail}".strip().replace("`", "'")
    return (out[: TG_LIMIT - 1] or "✶ thinking…")

def raw_view(p, started):
    """Live progress = the REAL terminal: the last ~4000 chars of the actual TUI
    pane (chrome and all, 'the way it shows up in the terminal'), backticks
    neutralised, wrapped in a code block so it fits in one Telegram message."""
    s = p.rstrip().replace("`", "'")
    if not s.strip():
        return f"⏳ working… ({int(time.time()-started)}s)"
    s = s[-4000:]
    nl = s.find("\n")          # start on a clean line (drop a partial first line)
    if 0 <= nl < 200:
        s = s[nl + 1:]
    return "```\n" + s + "\n```"

def _slog(tag, mid, text, raw=None):
    """Append exactly what we push to Telegram (plus the raw TUI pane), so the
    rendered frames can be reviewed later and progress_snapshot() tuned against
    what the user actually saw. Off unless relay-work/DEBUG exists. Best-effort;
    never breaks the relay."""
    if not DEBUG:
        return
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(STREAM_LOG, "a") as f:
            f.write(f"\n===== {time.strftime('%H:%M:%S')} {tag} mid={mid} len={len(text)} =====\n{text}\n")
            if raw is not None:
                f.write(f"----- raw pane -----\n{raw}\n----- end raw -----\n")
    except Exception:
        pass

class _Stream:
    """The live PROGRESS message: one silent Telegram message edited ~every 1s
    over the fast WS transport, showing the real terminal while the turn runs."""
    def __init__(self, prompt="", ws=None):
        self.started = time.time()
        self.last = 0.0
        self.id = None
        self.sent = None
        self.prompt = prompt
        self.ws = ws
        try:
            self.id = ws.send("✶ thinking…", silent=True) if ws else None
        except Exception:
            self.id = None

    def update(self, p):
        if not (self.id and self.ws):
            return
        now = time.time()
        # Flat 5s cadence: well under Telegram's per-message edit flood limit, so
        # the progress stream never goes stale (sustained 1s editing trips it).
        if now - self.last < 5.0:
            return
        snap = raw_view(p, self.started)  # real terminal, code-block, whole ~4000 chars
        if snap == self.sent:
            return
        self.last = now
        self.sent = snap
        try:
            self.ws.edit(self.id, snap)
        except Exception:
            pass

def tmux(*args, capture=False):
    cmd = ["tmux", *args]
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True).stdout
    subprocess.run(cmd, check=False)

def pane(scroll=0):
    # -J joins wrapped lines so long replies aren't chopped mid-sentence.
    args = ["capture-pane", "-t", SESSION, "-p", "-J"]
    if scroll:
        args += ["-S", f"-{scroll}"]
    return tmux(*args, capture=True)

BUSY = re.compile(r"esc to interrupt", re.I)        # shown ONLY while a turn runs
READY = re.compile(r"for agents|for shortcuts")     # input box footer = idle
SURVEY = re.compile(r"How is Claude doing")         # periodic satisfaction popup
# The permission/hint footer is present whenever the normal input prompt is up
# (idle OR mid-turn). A full-screen overlay (/workflows, /config, a stray dialog)
# REPLACES that footer -- so its absence, on a stable non-menu pane, means a modal
# is blocking ALL keyboard input and a relay-bound topic is wedged behind it.
INPUTBAR = re.compile(r"shift\+tab|bypass permissions|accept edits|plan mode|"
                      r"for agents|for shortcuts|for commands", re.I)

# --- menu detection ----------------------------------------------------------
OPT = re.compile(r'^\s*(❯)?\s*(\d+)\.\s+(.*\S)\s*$')
MENU_CURSOR = re.compile(r'^\s*❯\s*\d+\.\s')
MENU_FOOTER = re.compile(r"Esc to cancel|Enter to |to adjust|↑/↓|to select|use this session", re.I)

def parse_menu(text):
    """Return {'question','options':[...],'cursor':idx} ONLY for a REAL selection
    menu: a ❯ cursor in a cleanly-numbered (1..n) block of options, FOLLOWED by an
    interactive menu footer ("Enter to select / ↑↓ to navigate / Esc to cancel").

    The footer is what distinguishes a real picker from a prose numbered list, so
    requiring it lets us tolerate the description/separator/blank lines that
    AskUserQuestion interleaves BETWEEN options (a simple permission menu has none;
    AskUserQuestion puts a help line under every option). A prose "1. do X / 2. do
    Y" in an answer has no ❯ cursor AND no footer, so it is NEVER turned into
    buttons."""
    lines = text.splitlines()
    cur = next((i for i, l in enumerate(lines) if MENU_CURSOR.match(l)), None)
    if cur is None:
        return None
    # An interactive footer must appear at/below the cursor -> this is a picker.
    foot = next((i for i in range(cur, len(lines)) if MENU_FOOTER.search(lines[i])), None)
    if foot is None:
        return None
    # Walk up from the cursor (over interleaved description lines) to the "1." that
    # starts this option block; stop at a separator/prose boundary.
    top = None
    for i in range(cur, -1, -1):
        m = OPT.match(lines[i])
        if m and int(m.group(2)) == 1:
            top = i; break
        if re.match(r'^[─▔━_]{4,}\s*$', lines[i].strip()) or lines[i].strip().startswith('⏺'):
            break
    if top is None:
        return None
    # Collect the sequential 1..n numbered options between `top` and the footer,
    # skipping the non-option (description/separator/blank) lines between them.
    opts, cursor = [], 0
    for l in lines[top:foot]:
        m = OPT.match(l)
        if not m:
            continue
        if int(m.group(2)) != len(opts) + 1:    # numbering jumped -> end of menu
            break
        label = re.split(r'\s{2,}|·', m.group(3).strip())[0].strip()
        opts.append(label)
        if m.group(1):
            cursor = len(opts) - 1
    # Drop AskUserQuestion's trailing meta-affordances ("Type something…",
    # "Chat about this") -- they make no sense as tap targets. Keep them only if
    # removing them would leave fewer than 2 real choices.
    META = re.compile(r'^(type something|chat about this)', re.I)
    real = [o for o in opts if not META.match(o)]
    if len(real) >= 2:
        opts = real
        cursor = min(cursor, len(opts) - 1)
    if len(opts) < 2:
        return None
    # question = the non-empty lines just above the option block
    q, j = [], top - 1
    while j >= 0 and len(q) < 3:
        s = lines[j].strip()
        if not s:
            if q:
                break
            j -= 1; continue
        if re.match(r'^[─▔━_]{4,}$', s) or s.startswith('⏺'):
            break
        q.insert(0, s); j -= 1
    return {"question": " ".join(q).strip(), "options": opts, "cursor": cursor}

def format_menu(menu):
    lines = []
    if menu["question"]:
        lines.append(f"🔀 {menu['question']}")
    else:
        lines.append("🔀 Claude needs you to choose:")
    lines.append("")
    for i, o in enumerate(menu["options"], 1):
        lines.append(f"{i}. {o}")
    lines.append("")
    lines.append("Reply with the option number.")
    return "\n".join(lines)

def save_menu(menu, btn_msg_id=""):
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump({"options": menu["options"], "btn_msg_id": btn_msg_id}, open(STATE, "w"))

def load_menu():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}

def clear_menu():
    try: os.remove(STATE)
    except FileNotFoundError: pass

def menu_open():
    return os.path.exists(STATE)

# --- waiting -----------------------------------------------------------------
def dismiss_interrupts():
    if SURVEY.search(pane()):
        tmux("send-keys", "-t", SESSION, "0")
        time.sleep(0.6)

def wait_settled(timeout=180, stable_needed=2, poll=0.6, on_progress=None):
    """Wait until the TUI settles. Returns ('menu', pane) | ('idle', pane).

    A menu is returned the INSTANT it's detected (with one quick re-check to skip
    mid-render frames) -- we do NOT wait for pane stability, because Claude's
    question menus have a blinking cursor so the pane never hashes the same twice
    (that was making menus time out and fall through to 'idle'). Only the idle
    state needs stability.
    """
    last, stable = None, 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll)
        dismiss_interrupts()
        p = pane()
        if BUSY.search(p):
            last, stable = None, 0
            if on_progress:
                try:
                    on_progress(p)
                except Exception:
                    pass
            continue
        if parse_menu(p):
            time.sleep(0.3)
            if parse_menu(pane()):     # confirm it's a real, settled menu
                return "menu", pane()
            continue
        if READY.search(p):
            h = hashlib.md5(p.encode()).hexdigest()
            if h == last:
                stable += 1
                if stable >= stable_needed:
                    return "idle", p
            else:
                stable, last = 0, h
        else:
            last, stable = None, 0
    return "idle", pane()

# --- reply extraction --------------------------------------------------------
CHROME = re.compile(
    r"^\s*$|Claude Code v|Tips for getting started|Welcome back|What's new"
    r"|Auto mode is now|Plugins in|Added .claude|/release-notes|Claude Fable"
    r"|Opus 4.8 is here|Ask Claude to create|^[│╭╰─┌┐└┘▐▝▘▛▜█ ]+$|/effort"
    r"|^\s*[│╭╰╮╯┃┏┓┗┛].*"                     # banner/box rows (incl. text inside borders)
    r"|~/.openclaw/workspace"                    # Claude Code session header path line
    r"|● high|● medium|● low|· /effort"          # status/footer bits
    r"|tmux detected|scroll with PgUp|set -g (mouse|focus)|focus-events"  # tmux hints
    r"|\? for shortcuts|Try \"|esc to interrupt|Worked for")

def _reply_lines(prompt):
    full = pane(scroll=4000).splitlines()
    box = len(full)
    for i in range(len(full) - 1, -1, -1):
        if full[i].lstrip().startswith("❯"):
            box = i; break
    region = full[:box]
    needle = (prompt.strip().splitlines() or [""])[0][:60]
    midx = -1
    for i, ln in enumerate(region):
        if needle and needle in ln and not ln.lstrip().startswith("⏺"):
            midx = i
    start = None
    if midx >= 0:
        for k in range(midx + 1, len(region)):
            if "⏺" in region[k]:
                start = k; break
        if start is None:
            start = midx + 1
    if start is None:
        for k in range(len(region)):
            if "⏺" in region[k]:
                start = k
        if start is None:
            start = 0
    footer = re.compile(r"/effort|\? for shortcuts|esc to interrupt|accept edits|^\s*─{8,}\s*$")
    out = []
    for ln in region[start:]:
        s = ln.rstrip()
        if out and (footer.search(s) or s.lstrip().startswith("❯")):
            break
        if CHROME.search(s) or "✻" in s:
            continue
        s = s.replace("⏺", "").strip()
        if s:
            out.append(s)
    return out

def extract_reply(prompt):
    return reflow(_reply_lines(prompt)).strip()

def extract_stream(prompt):
    # Non-reflowed: capture-pane -J already gives logical (unwrapped) lines, so
    # the joined text grows append-monotonically as Claude types -- only the last
    # line is volatile. That makes clean forward deltas reliable. Reflow is saved
    # for the authoritative final result.
    return "\n".join(_reply_lines(prompt)).strip()

def reflow(lines):
    try:
        width = int(tmux("display-message", "-p", "-t", SESSION, "#{pane_width}", capture=True).strip())
    except Exception:
        width = 200
    thr = max(60, width - 12)
    bullet = re.compile(r"^\s*([-*•‣◦]|\d+[.)]|```|#{1,6}\s)")
    merged = []
    for ln in lines:
        if (merged and len(merged[-1]) >= thr
                and merged[-1].rstrip()[-1:] not in ".!?:;"
                and ln and not bullet.match(ln)):
            merged[-1] = merged[-1].rstrip() + " " + ln.lstrip()
        else:
            merged.append(ln)
    return "\n".join(merged)

def count_marker():
    return pane(scroll=4000).count("⏺")

# --- actions -----------------------------------------------------------------
def send(prompt):
    dismiss_interrupts()
    state, _ = wait_settled(timeout=30)
    if state == "menu":
        # A stray menu is open (e.g. left over). Dismiss it so the command/prompt
        # we're about to type doesn't get typed INTO the menu's filter.
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.4)
        clear_menu()
    tmux("set-option", "-t", SESSION, "history-limit", "100000")
    tmux("clear-history", "-t", SESSION)
    tmux("send-keys", "-t", SESSION, "C-u")
    time.sleep(0.2)
    tmux("send-keys", "-t", SESSION, "-l", prompt)
    time.sleep(0.4)
    tmux("send-keys", "-t", SESSION, "Enter")
    for _ in range(6):
        time.sleep(0.5)
        if BUSY.search(pane()):
            break
    # TWO messages, kept separate, over the fast WS transport (~1s):
    #  - a live PROGRESS message mirroring the real terminal (last ~4000 chars);
    #  - a separate FINAL message with the clean answer, sent once at the end.
    ws = None
    if STREAM and CHAT_ID:
        w = _WS(CHAT_ID, THREAD_ID)
        if w.ok:
            ws = w
        else:
            w.close()
    stream = _Stream(prompt, ws) if ws else None
    state, p = wait_settled(on_progress=(stream.update if stream else None))
    if state == "menu":
        if ws: ws.close()
        return present_menu(parse_menu(p))   # native buttons for a real menu
    clear_menu()
    if stream and stream.id:
        try: ws.edit(stream.id, raw_view(p, stream.started))   # final terminal frame
        except Exception: pass
    reply = extract_reply(prompt) or "(done)"
    if ws:
        if stream and stream.id and len(reply) <= TG_LIMIT:
            ws.send(reply)      # the answer, as its OWN message (this one notifies)
            ws.close()
            return ""
        ws.close()              # too long -> fall through to OpenClaw's send
    return reply

def present_menu(menu):
    """Show a menu to the user: native Telegram buttons if we know the chat id,
    else a numbered text list. Persists menu state either way. Returns the text
    OpenClaw should send ('' when buttons were sent out-of-band)."""
    if CHAT_ID:
        mid = tg_buttons(menu["question"], menu["options"])
        save_menu(menu, btn_msg_id=mid)
        return ""   # buttons delivered out-of-band; suppress the text bubble
    save_menu(menu)
    return format_menu(menu)

def select(n):
    """Resolve a menu pick RACE-FREE: dismiss the TUI menu and answer Claude in
    plain text with the chosen option's label.

    Injecting arrow/number keystrokes into the live menu is unreliable (timing
    races -> wrong option / the default gets picked). But Claude asked the
    question, so it accepts the answer as words. We Escape the menu and send the
    label as a normal message, which is plain text delivery and never races.
    """
    saved = load_menu()
    state, p = wait_settled(timeout=12)
    menu = parse_menu(p)
    opts = menu["options"] if menu else saved.get("options", [])
    if not opts or n < 1 or n > len(opts):
        clear_menu()
        return ("⚠️ Couldn't read that menu — send your request again, or use "
                "`claude-attach` to answer in the live session.")
    label = opts[n - 1]
    btn_msg_id = saved.get("btn_msg_id", "")
    # Dismiss the TUI menu so the next message isn't typed into it, then answer.
    if menu:
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
    clear_menu()
    tg_remove_buttons(btn_msg_id, f"✓ {label}")
    return send(label)

def parse_selection(prompt):
    """A button tap arrives as 'callback_data: ccsel:N'; a typed reply as 'N'."""
    m = re.search(r'ccsel:(\d+)', prompt)
    if m:
        return int(m.group(1))
    s = prompt.strip().rstrip(".)")
    return int(s) if s.isdigit() else None

# --- persistent watcher model (RELAY_WATCH / relay-work/WATCH) ----------------
# Instead of watching the TUI only during the message that triggered a turn, one
# long-lived watcher per session tails the pane and delivers EVERY new assistant
# turn -- including turns that finish after a long wait and any output that shows
# up outside the request/response window. The per-message call then only INJECTS
# (types the prompt / resolves a menu tap) and returns "" so OpenClaw sends
# nothing; the watcher owns all delivery. This removes the old gap where a slow
# "I'll report back" reply was missed because nothing was watching anymore.

def save_target(chat, thread):
    """Persist where the watcher should deliver (it has no inbound message)."""
    if not chat:
        return
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        json.dump({"chat": chat, "thread": thread}, open(TARGET, "w"))
    except Exception:
        pass

def dedup_key(text):
    """Hash a reply for delivery dedup, normalizing whitespace first so a trivial
    pane re-render (different wrapping / trailing spaces) doesn't read as a new
    reply and get sent again."""
    return hashlib.md5(re.sub(r"\s+", " ", text or "").strip().encode()).hexdigest()

def read_turndone():
    """(mtime, final_message) from the Stop-hook marker, or (None, None). The
    marker is written by relay-turn-done when Claude finishes a turn, giving the
    watcher a deterministic 'done' event + the exact reply text -- no pane scrape."""
    try:
        mt = os.path.getmtime(TURNDONE)
        msg = (json.load(open(TURNDONE)) or {}).get("message", "")
        return mt, msg
    except Exception:
        return None, None

def load_delivered():
    """Last reply hash we delivered, persisted so a RESTARTED watcher (gateway
    bounce, crash, manual relaunch) doesn't re-emit the reply already on screen."""
    try:
        return (open(DELIVERED).read().strip() or None)
    except Exception:
        return None

def save_delivered(h):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        open(DELIVERED, "w").write(h or "")
    except Exception:
        pass

def refresh_target():
    """Point CHAT_ID/THREAD_ID at the persisted per-session target."""
    global CHAT_ID, THREAD_ID
    try:
        t = json.load(open(TARGET))
        CHAT_ID = str(t.get("chat") or "")
        THREAD_ID = str(t.get("thread") or "")
    except Exception:
        pass

def write_last_prompt(p):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        open(LASTPROMPT, "w").write(p or "")
    except Exception:
        pass

def read_last_prompt():
    try:
        return open(LASTPROMPT).read()
    except Exception:
        return ""

def session_alive():
    return SESSION in tmux("list-sessions", "-F", "#{session_name}", capture=True)

def type_prompt(prompt):
    """Type a prompt into the TUI and submit it. No watching, no delivery.

    First Esc-peel any full-screen overlay (/workflows, /config, a stray
    dialog/menu): with no input bar on screen the typed text lands inside the
    overlay and wedges the whole topic. Esc one layer per pass until the input
    bar -- or a running turn -- is back, then type."""
    for _ in range(4):
        p = pane()
        if INPUTBAR.search(p) or BUSY.search(p):
            break
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
    tmux("set-option", "-t", SESSION, "history-limit", "100000")
    tmux("send-keys", "-t", SESSION, "C-u"); time.sleep(0.2)
    tmux("send-keys", "-t", SESSION, "-l", prompt); time.sleep(0.4)
    tmux("send-keys", "-t", SESSION, "Enter")

def deliver(text):
    """Send a finished reply (the notifying message), chunked over the TG cap."""
    if not text:
        return
    for i in range(0, len(text), TG_LIMIT):
        tg_send(text[i:i + TG_LIMIT])

# Resolve freeze to an ABSOLUTE path: the per-message relay process is spawned by
# the gateway with a minimal PATH that often lacks /opt/homebrew/bin, so a bare
# "freeze" subprocess call fails (FileNotFoundError) and screenshots silently fall
# back to text. shutil.which honours PATH when it works; the explicit paths cover
# the gateway case; bare "freeze" is the last-resort default for other installs.
FREEZE = (shutil.which("freeze")
          or next((p for p in ("/opt/homebrew/bin/freeze", "/usr/local/bin/freeze",
                               os.path.expanduser("~/bin/freeze")) if os.path.exists(p)),
                  "freeze"))

def screenshot_png():
    """Render the current TUI pane (ANSI colors and all) to a PNG via `freeze`.
    Returns the output path, or None if capture/render failed. This is how the
    relay surfaces what text can't -- full-screen overlays, colors, layout."""
    ansi = os.path.join(STATE_DIR, f"shot-{SESSION}.ansi")
    png = os.path.join(STATE_DIR, f"shot-{SESSION}.png")
    why = ""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        raw = tmux("capture-pane", "-ep", "-t", SESSION, capture=True)
        if not raw.strip():
            why = "empty capture"
        else:
            with open(ansi, "w") as f:
                f.write(raw)
            r = subprocess.run([FREEZE, ansi, "-o", png], capture_output=True, text=True)
            if r.returncode == 0 and os.path.exists(png):
                return png
            why = f"freeze rc={r.returncode} ({FREEZE}): {(r.stderr or '').strip()[:160]}"
    except Exception as e:
        why = f"{type(e).__name__}: {e}"
    # Record WHY a screenshot fell back -- silent None reads as "no overlay" when it
    # may be a broken renderer/PATH. Best-effort, never breaks the relay.
    try:
        with open(os.path.join(STATE_DIR, "shot-debug.log"), "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {SESSION} screenshot fail: {why}\n")
    except Exception:
        pass
    return None

def send_screenshot():
    """Capture the live TUI as an image and send it as a photo/document."""
    png = screenshot_png()
    if png:
        tg_send_media(png, "🖥 TUI screenshot")
    else:
        deliver("⚠️ Couldn't render a screenshot (freeze/capture failed).")

def overlay_screenshot(open_cmd):
    """Open a full-screen TUI overlay (e.g. /workflows, /config), image it, then
    Esc to close. Returns the PNG path (or None). Captures FAST: the watcher's
    overlay-guard Escs a non-input-bar pane after ~3 polls (~3s), so we grab the
    frame well inside that window and close it ourselves. Only opens the overlay
    when the pane is at the input bar (not mid-turn / not already in a modal)."""
    if not INPUTBAR.search(pane()):
        return None
    tmux("send-keys", "-t", SESSION, "C-u"); time.sleep(0.2)
    tmux("send-keys", "-t", SESSION, "-l", open_cmd); time.sleep(0.3)
    tmux("send-keys", "-t", SESSION, "Enter")
    time.sleep(1.4)                       # let the panel render, inside the guard window
    png = screenshot_png()
    tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.4)  # close the overlay
    return png

def workflow_status():
    """The /workflows viewer is interactive full-screen and can't render over the
    relay (it just auto-dismisses). Scrape the live per-workflow progress from the
    pane instead -- Claude Code keeps that status line on the normal screen while a
    background workflow runs -- and return it as a text snapshot."""
    rows, seen = [], set()
    for raw in pane().splitlines():
        s = raw.strip()
        if not s or s in seen:
            continue
        # Anchor each pattern to its leading TUI glyph so prose that merely
        # mentions "N/M agents done" or "/workflows" (e.g. this very chat in the
        # scrollback) can't be mistaken for a live status row.
        if (re.match(r"^[◯◉●▸▹‣]\s+\S", s)                              # per-workflow row
                or re.match(r"^[✻✶✢✽✳✺·]\s*Waiting for \d+\b.*workflow", s, re.I)  # waiting line
                or re.match(r"^⎿\s+Running in background\b.*/workflows", s, re.I)):  # bg note
            seen.add(s); rows.append(s)
    if not rows:
        return ("📋 No workflow is running right now.\n\n"
                "(The /workflows viewer is a full-screen TUI, so it can't be shown "
                "over the relay -- this is the live status instead. Re-send "
                "/workflows to refresh.)")
    return ("📋 Workflow status -- live scrape (the /workflows viewer can't render "
            "over the relay; re-send to refresh):\n\n" + "\n".join(rows[-15:]))

def inject(prompt):
    """Per-message path under the watcher model: type the prompt (or resolve a
    menu tap) into the TUI and return '' immediately. The watcher delivers the
    result, so this never blocks on the turn."""
    save_target(CHAT_ID, THREAD_ID)
    # /workflows (and /workflow) can't open their full-screen viewer over the relay
    # -> answer with a scraped text snapshot of live workflow progress instead of
    # opening (and then auto-dismissing) the overlay.
    if re.fullmatch(r"/workflows?", prompt.strip(), re.I):
        # Image the actual /workflows panel (faithful, full fidelity); fall back to
        # the scraped text status if the pane is busy or the render fails.
        png = overlay_screenshot("/workflows")
        if png:
            tg_send_media(png, "🖥 /workflows")
        else:
            deliver(workflow_status())
        return ""
    # /screenshot (/ss, /shot): image of the live TUI -- the faithful way to see
    # full-screen overlays, colors and layout that text scraping can't carry.
    if re.fullmatch(r"/(screenshot|ss|shot)", prompt.strip(), re.I):
        send_screenshot()
        return ""
    if menu_open():
        n = parse_selection(prompt)
        if n is not None:
            saved = load_menu()
            opts = saved.get("options", [])
            if opts and 1 <= n <= len(opts):
                label = opts[n - 1]
                if parse_menu(pane()):
                    tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
                clear_menu()
                tg_remove_buttons(saved.get("btn_msg_id", ""), f"✓ {label}")
                write_last_prompt(label)
                type_prompt(label)
                return ""
            clear_menu()
            return "⚠️ Couldn't read that menu — send your request again."
        # not a selection while a menu is open -> cancel it, treat as a new msg
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
        clear_menu()
    write_last_prompt(prompt)
    type_prompt(prompt)
    return ""

def watch():
    """Long-lived: tail the pane, stream the active turn into a silent bubble,
    and deliver each settled turn's reply exactly once (hash-dedup). Survives
    long/slow turns and out-of-band output; exits when the session dies."""
    refresh_target()
    # Seed 'delivered' from the persisted hash first (survives watcher restarts),
    # falling back to whatever reply is already on screen, so we never resend a
    # reply that predates the watcher starting.
    delivered = load_delivered()
    if delivered is None and not BUSY.search(pane()):
        r0 = extract_reply(read_last_prompt())
        delivered = dedup_key(r0) if r0 else None
    # Seed the Stop-hook marker mtime so a stale marker isn't re-delivered on
    # start. hook_active flips on once we've ever seen one (the session's Claude
    # has the Stop hook); after that the pane-scrape path is only a slow safety
    # net for the rare 'silent tool stop' the Stop hook misses.
    last_done_mt, _seed = read_turndone()
    hook_active = last_done_mt is not None
    last_done_mt = last_done_mt or 0
    stream, menu_sig, was_busy, idle_stable, overlay_stable = None, None, False, 0, 0
    while True:
        time.sleep(1.0)
        if not session_alive():
            return
        refresh_target()
        if not CHAT_ID:
            continue
        dismiss_interrupts()
        # Deterministic delivery: the Stop hook wrote a fresh marker -> the turn
        # is genuinely done and the marker holds the exact final message. Deliver
        # it (dedup-guarded) and freeze the bubble. Beats the idle heuristic and
        # carries clean text with no pane-scrape artifacts.
        mt, msg = read_turndone()
        if mt and mt != last_done_mt:
            last_done_mt, hook_active = mt, True
            h = dedup_key(msg) if msg else None
            if h and h != delivered:
                if stream and stream.ws:
                    stream.ws.close()
                deliver(msg)
                delivered = h
                save_delivered(h)
            stream, was_busy, idle_stable = None, False, 0
            continue
        p = pane()
        if BUSY.search(p):
            was_busy, idle_stable, menu_sig, overlay_stable = True, 0, None, 0
            if stream is None and STREAM:
                # Build the fast WS transport so the live bubble actually draws
                # (without a ws, _Stream.update is a no-op). Mirrors the sync path.
                w = _WS(CHAT_ID, THREAD_ID)
                stream = _Stream(read_last_prompt(), w if w.ok else None)
            if stream:
                stream.update(p)
            continue
        menu = parse_menu(p)
        if menu:
            sig = "|".join(menu["options"])
            if sig != menu_sig:
                # Freeze the progress bubble in place (don't delete it) and just
                # stop updating it; the question/menu posts as a new message below.
                if stream and stream.ws:
                    stream.ws.close()
                stream, menu_sig = None, sig
                present_menu(menu)      # buttons (notify) + save menu state
            was_busy, idle_stable, overlay_stable = False, 0, 0
            continue
        menu_sig = None
        # Wedge guard: a stable pane that's neither busy, nor a parseable menu, nor
        # showing the input bar = a full-screen overlay (/workflows, /config, a
        # dialog we can't button) blocking ALL input. Esc to peel one layer; the
        # next poll re-evaluates, so a menu hidden underneath then renders and gets
        # buttoned, and stacked overlays peel one layer per cycle. A MENU_FOOTER
        # means a picker is mid-render -> let parse_menu retry, don't Esc it away.
        if not INPUTBAR.search(p) and not MENU_FOOTER.search(p):
            overlay_stable += 1
            if overlay_stable >= 3:
                tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.4)
                overlay_stable = 0
            continue
        overlay_stable = 0
        # Idle: only deliver once the turn has ACTUALLY run (was_busy) and the
        # pane has stayed idle for several polls. Without the was_busy gate the
        # watcher delivers in the dead windows where no reply is being produced --
        # right after a prompt is injected but before Claude responds (it grabs
        # the echoed envelope, or re-grabs the PREVIOUS reply) -- and a too-short
        # idle count delivers a brief between-tool-steps frame as if it were the
        # final answer. Both were seen as spurious extra messages.
        idle_stable += 1
        if stream:
            stream.update(p)
        # When the Stop hook is active it delivers above; here we only act as a
        # slow safety net (long idle) for the rare silent-stop it misses, so we
        # never race the marker. Without the hook, the normal short threshold.
        thresh = 12 if hook_active else 4
        if not (was_busy and idle_stable >= thresh):
            continue
        reply = extract_reply(read_last_prompt())
        h = dedup_key(reply) if reply else None
        if h and h != delivered:
            # Leave the progress bubble in the chat as a frozen record of the
            # turn; deliver the clean answer as a separate, new message below it.
            # The next turn opens a fresh bubble.
            deliver(reply)
            delivered = h
            save_delivered(h)
        if stream and stream.ws:
            stream.ws.close()
        stream, was_busy = None, False

# --- native-streaming model (RELAY_JSONL / relay-work/JSONL) ------------------
# Emit Claude `stream-json` JSONL on stdout instead of sending to Telegram
# ourselves. OpenClaw parses the deltas and renders the live edits with its own
# fast (~1s, in-process) draft-stream loop, and uses our final `result` line as
# the authoritative reply. This retires the slow 2.8s-per-edit CLI path for the
# live stream. Requires the cliBackend configured output:jsonl + jsonlDialect.

def emit(obj):
    """Write one JSONL record to stdout and flush so OpenClaw streams it live."""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

def emit_delta(text):
    if text:
        emit({"type": "stream_event", "event": {"type": "content_block_delta",
              "delta": {"type": "text_delta", "text": text}}})

def emit_result(text):
    emit({"type": "result", "result": text})

def _jlog(msg):
    """Opt-in (relay-work/DEBUG) trace of what the JSONL stream emitted, so the
    delta cadence can be inspected against what the user actually saw."""
    if not DEBUG:
        return
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(os.path.join(STATE_DIR, f"jsonl-{SESSION}.log"), "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass

def send_jsonl(prompt):
    """Type the prompt, show one working indicator, then emit the final reply as
    a stream-json `result`. OpenClaw delivers it natively (no 2.8s CLI edit). We
    don't token-stream: a redrawing TUI can't map onto append-only deltas."""
    dismiss_interrupts()
    state, _ = wait_settled(timeout=30)
    if state == "menu":
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.4); clear_menu()
    type_prompt(prompt)
    for _ in range(6):
        time.sleep(0.5)
        if BUSY.search(pane()):
            break
    # We do NOT live-stream the reply text: Claude Code's TUI redraws
    # non-monotonically (tool/thinking blocks appear and collapse), but
    # stream-json deltas are append-only -- so scraped snapshots either repeat
    # (lenient) or never advance (strict). Instead we show one lightweight
    # working indicator and let OpenClaw render the authoritative `result` the
    # instant the turn settles: fast and clean, just not token-by-token.
    emit_delta("✶ working…")
    state, p = wait_settled()
    if state == "menu":
        menu = parse_menu(p); save_menu(menu)
        emit_result(format_menu(menu))      # text menu (native buttons TBD)
        _jlog("result=MENU")
        return
    clear_menu()
    final = extract_reply(prompt) or "(done)"
    emit_result(final)
    _jlog(f"result len={len(final)}")

def jsonl_main(prompt):
    if menu_open():
        n = parse_selection(prompt)
        if n is not None:
            saved = load_menu(); opts = saved.get("options", [])
            if opts and 1 <= n <= len(opts):
                label = opts[n - 1]
                if parse_menu(pane()):
                    tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
                clear_menu()
                send_jsonl(label); return
            clear_menu()
            emit_result("⚠️ Couldn't read that menu — send your request again.")
            return
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5); clear_menu()
    send_jsonl(prompt)

def main():
    args = [a for a in sys.argv[1:] if a != "--watch"]
    if "--watch" in sys.argv[1:]:
        watch(); return
    prompt = " ".join(args)
    if JSONL:
        jsonl_main(prompt); return
    if WATCH:
        print(inject(prompt)); return
    # Legacy synchronous path (default until the watcher is enabled).
    if menu_open():
        n = parse_selection(prompt)
        if n is not None:
            print(select(n)); return
        # not a selection while a menu is open -> cancel it, send as new message
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
        clear_menu()
    print(send(prompt))

if __name__ == "__main__":
    main()
