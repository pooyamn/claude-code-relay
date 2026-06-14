#!/usr/bin/env python3
import os as _os
BASE = _os.environ.get("RELAY_DIR") or _os.path.dirname(_os.path.abspath(__file__))
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
CHAT_ID = os.environ.get("RELAY_CHAT_ID", "")   # telegram chat id, for native buttons
STATE_DIR = "" + BASE + "/relay-work"
STATE = os.path.join(STATE_DIR, f"menu-{SESSION}.json")

def tg_buttons(question, options):
    """Send native Telegram inline buttons for a menu. Returns the message id."""
    pres = {"blocks": [{"type": "buttons", "buttons":
            [{"label": f"{i+1}. {o}"[:60], "value": f"ccsel:{i+1}"} for i, o in enumerate(options)]}]}
    r = subprocess.run(["openclaw", "message", "send", "--channel", "telegram",
                        "--target", CHAT_ID, "--message", question or "Choose an option:",
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
                    "--target", CHAT_ID, "--message-id", str(msg_id),
                    "--message", note],
                   capture_output=True, text=True)

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
    """Return {'question','options':[...],'cursor':idx} if the pane shows a
    selection menu (a ❯ cursor sitting on a numbered option), else None."""
    lines = text.splitlines()
    if not any(MENU_CURSOR.match(l) for l in lines):
        return None
    opts, cursor, first_idx = [], 0, None
    for i, l in enumerate(lines):
        m = OPT.match(l)
        if not m:
            continue
        num = int(m.group(2))
        if not opts and num != 1:
            continue
        if opts and num != len(opts) + 1:
            continue
        label = re.split(r'\s{2,}|·', m.group(3).strip())[0].strip()
        opts.append(label)
        if m.group(1):
            cursor = len(opts) - 1
        if first_idx is None:
            first_idx = i
    if len(opts) < 2:
        return None
    # question = the non-empty lines just above the first option
    q, j = [], (first_idx or 0) - 1
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

def wait_settled(timeout=180, stable_needed=2, poll=0.6):
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
    state, p = wait_settled()
    if state == "menu":
        return present_menu(parse_menu(p))
    clear_menu()
    return extract_reply(prompt)

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

def main():
    prompt = " ".join(sys.argv[1:])
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
