#!/usr/bin/env python3
"""Drive a persistent interactive `claude` TUI in tmux: send a prompt, wait for
the turn, return Claude's reply as clean text. Subscription-billed (the TUI runs
on the Max plan; we just drive it).

Multi-choice support: when Claude shows a selection menu (model picker, plan
approval, any numbered question), we DON'T scrape it as a reply. We return the
options formatted for Telegram and remember a menu is open; the user's next
message (a number) is sent back as an arrow+Enter selection into the TUI.
"""
import subprocess, sys, time, hashlib, re, os, json

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
        return str(json.loads(r.stdout).get("payload", {}).get("messageId", ""))
    except Exception:
        return ""

def tg_remove_buttons(msg_id, note):
    """Edit the button message text; a text-only edit drops the inline keyboard
    (Telegram removes reply_markup when it isn't re-specified)."""
    if not (msg_id and CHAT_ID):
        return
    subprocess.run(["openclaw", "message", "edit", "--channel", "telegram",
                    "--target", CHAT_ID, *_thread_args(), "--message-id", str(msg_id),
                    "--message", note],
                   capture_output=True, text=True)

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
        return str(json.loads(r.stdout).get("payload", {}).get("messageId", ""))
    except Exception:
        m = re.search(r"Message ID:\s*(\d+)", r.stdout or "")
        return m.group(1) if m else ""

def tg_delete(msg_id):
    """Best-effort delete of a message (the live progress bubble)."""
    if not (msg_id and CHAT_ID):
        return
    subprocess.run(["openclaw", "message", "delete", "--channel", "telegram",
                    "--target", CHAT_ID, "--message-id", str(msg_id)],
                   capture_output=True, text=True)

def tg_edit(msg_id, text):
    if not (msg_id and CHAT_ID):
        return
    subprocess.run(["openclaw", "message", "edit", "--channel", "telegram",
                    "--target", CHAT_ID, *_thread_args(), "--message-id", str(msg_id),
                    "--message", text[:TG_LIMIT]],
                   capture_output=True, text=True)

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
    status = ""
    for l in lines:
        if BUSY.search(l) or re.search(r"tokens|esc to interrupt", l, re.I):
            status = l.strip()
    body = []
    for l in lines:
        s = l.strip()
        if not s or BUSY.search(s) or READY.search(s) or s == status:
            continue
        if re.search(r"tokens|esc to interrupt", s, re.I):
            continue
        if re.match(r"^[─▔━_╭╮╰╯│>·✻✶✢*\s]+$", s):
            continue
        body.append(s)
    elapsed = int(time.time() - started)
    head = f"⏳ {status}" if status else f"⏳ working… ({elapsed}s)"
    tail = "\n".join(body[-30:])
    out = f"{head}\n\n{tail}".strip()
    return (out[: TG_LIMIT - 1] or "✶ thinking…")

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
    """One Telegram message, edited in place ~every 1.5s while the turn runs."""
    def __init__(self, prompt=""):
        self.started = time.time()
        self.last = 0.0
        self.id = None
        self.sent = None
        self.prompt = prompt
        try:
            # Silent: the progress bubble must NOT ping. Only the final answer
            # (a fresh, non-silent message) notifies the user.
            self.id = tg_send("✶ thinking…", silent=True)
        except Exception:
            self.id = None
        _slog("OPEN", self.id, "✶ thinking…")

    def update(self, p):
        if not self.id:
            return
        now = time.time()
        # Adaptive cadence: ~1.5s early (Telegram tolerates ~1s edits; OpenClaw's
        # own streaming throttles at 1s), backing off as the turn runs long.
        # Telegram flood-limits sustained editMessage calls, which froze the
        # stream on long turns ("pauses after a while"). Backing off keeps total
        # edits well under the limit while staying responsive at the start.
        elapsed = now - self.started
        interval = min(12.0, 1.5 + elapsed / 20.0)
        if now - self.last < interval:
            return
        snap = progress_snapshot(p, self.started, self.prompt)
        if snap == self.sent:   # unchanged -> skip (Telegram rejects "not modified")
            return
        self.last = now
        self.sent = snap
        _slog("EDIT", self.id, snap, raw=p)
        try:
            tg_edit(self.id, snap)
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

# --- menu detection ----------------------------------------------------------
OPT = re.compile(r'^\s*(❯)?\s*(\d+)\.\s+(.*\S)\s*$')
MENU_CURSOR = re.compile(r'^\s*❯\s*\d+\.\s')
MENU_FOOTER = re.compile(r"Esc to cancel|Enter to |to adjust|↑/↓|to select|use this session", re.I)

def parse_menu(text):
    """Return {'question','options':[...],'cursor':idx} ONLY for a REAL selection
    menu: a ❯ cursor sitting inside a CONTIGUOUS, cleanly-numbered (1..n) block of
    options. We anchor on the cursor line and take just the unbroken run of option
    lines around it, so a prose numbered list elsewhere in the pane (e.g. "1. do
    X / 2. do Y" in an answer) is NEVER turned into buttons. Buttons appear only
    when Claude is actually asking you to pick."""
    lines = text.splitlines()
    cur = next((i for i, l in enumerate(lines) if MENU_CURSOR.match(l)), None)
    if cur is None:
        return None
    top = bot = cur
    while top - 1 >= 0 and OPT.match(lines[top - 1]):
        top -= 1
    while bot + 1 < len(lines) and OPT.match(lines[bot + 1]):
        bot += 1
    opts, cursor = [], 0
    for l in lines[top:bot + 1]:
        m = OPT.match(l)
        if int(m.group(2)) != len(opts) + 1:    # must be cleanly numbered 1..n
            return None                          # broken sequence -> not a menu
        label = re.split(r'\s{2,}|·', m.group(3).strip())[0].strip()
        opts.append(label)
        if m.group(1):
            cursor = len(opts) - 1
    if len(opts) < 2:
        return None
    first_idx = top
    # question = the non-empty lines just above the option block
    q, j = [], first_idx - 1
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

def extract_reply(prompt):
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
    return reflow(out).strip()

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
    # Live-stream the turn into ONE Telegram message, edited in place ~every 2s.
    # Any streaming failure leaves stream.id None and we fall back to the normal
    # return path, so replies are never lost.
    stream = _Stream(prompt) if (STREAM and CHAT_ID) else None
    state, p = wait_settled(on_progress=(stream.update if stream else None))
    if state == "menu":
        # Drop the silent progress bubble; the buttons message (which DOES
        # notify) becomes the user's ping that Claude needs an answer.
        if stream and stream.id:
            tg_delete(stream.id)
        return present_menu(parse_menu(p))
    clear_menu()
    reply = extract_reply(prompt)
    if stream and stream.id:
        final = reply or "(done)"
        # The progress bubble was silent (no ping). Delete it and deliver the
        # answer as a FRESH message so the user gets exactly one notification,
        # telling them the turn is done.
        tg_delete(stream.id)
        if len(final) <= TG_LIMIT:
            _slog("FINAL", stream.id, final)
            tg_send(final)          # non-silent: this is the ping
            return ""               # delivered out-of-band; suppress OpenClaw's bubble
        _slog("FINAL-LONG", stream.id, final)
        # Too long for one message: let OpenClaw chunk it (also notifies).
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
    """Type a prompt into the TUI and submit it. No watching, no delivery."""
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

def inject(prompt):
    """Per-message path under the watcher model: type the prompt (or resolve a
    menu tap) into the TUI and return '' immediately. The watcher delivers the
    result, so this never blocks on the turn."""
    save_target(CHAT_ID, THREAD_ID)
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
    # Seed 'delivered' with what's already on screen so we never resend a reply
    # that predates the watcher starting.
    delivered = None
    if not BUSY.search(pane()):
        r0 = extract_reply(read_last_prompt())
        delivered = hashlib.md5(r0.encode()).hexdigest() if r0 else None
    stream, menu_sig, was_busy, idle_stable = None, None, False, 0
    while True:
        time.sleep(1.0)
        if not session_alive():
            return
        refresh_target()
        if not CHAT_ID:
            continue
        dismiss_interrupts()
        p = pane()
        if BUSY.search(p):
            was_busy, idle_stable, menu_sig = True, 0, None
            if stream is None and STREAM:
                stream = _Stream(read_last_prompt())
            if stream:
                stream.update(p)
            continue
        menu = parse_menu(p)
        if menu:
            sig = "|".join(menu["options"])
            if sig != menu_sig:
                if stream and stream.id:
                    tg_delete(stream.id)
                stream, menu_sig = None, sig
                present_menu(menu)      # buttons (notify) + save menu state
            was_busy, idle_stable = False, 0
            continue
        menu_sig = None
        # Idle: wait for a couple of stable frames before declaring done, so we
        # don't deliver a half-rendered frame the instant a spinner clears.
        idle_stable += 1
        if stream:
            stream.update(p)
        if idle_stable < 2:
            continue
        reply = extract_reply(read_last_prompt())
        h = hashlib.md5(reply.encode()).hexdigest() if reply else None
        if h and h != delivered:
            if stream and stream.id:
                tg_delete(stream.id)    # drop the silent bubble; deliver fresh
            deliver(reply)
            delivered = h
        elif was_busy and stream and stream.id:
            tg_delete(stream.id)        # turn ended with nothing new (interrupt)
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

def send_jsonl(prompt):
    """Type the prompt, stream the growing reply as text_delta records, then emit
    the final result. OpenClaw does all the Telegram editing natively."""
    dismiss_interrupts()
    state, _ = wait_settled(timeout=30)
    if state == "menu":
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.4); clear_menu()
    type_prompt(prompt)
    for _ in range(6):
        time.sleep(0.5)
        if BUSY.search(pane()):
            break
    sent = {"last": ""}
    def on_prog(_p):
        # Deltas are append-only; emit only a clean forward extension. Reflow/
        # rewrites are skipped live and corrected by the authoritative result.
        reply = extract_reply(prompt)
        if reply.startswith(sent["last"]) and len(reply) > len(sent["last"]):
            emit_delta(reply[len(sent["last"]):]); sent["last"] = reply
    state, p = wait_settled(on_progress=on_prog)
    if state == "menu":
        menu = parse_menu(p); save_menu(menu)
        emit_result(format_menu(menu))      # text menu (native buttons TBD)
        return
    clear_menu()
    emit_result(extract_reply(prompt) or "(done)")

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
