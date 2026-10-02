"""Thread-scoped Codex turn view and cumulative, restartable Telegram bubbles.

The native protocol/launcher stays separate. This adapter never starts a model
turn or answers an approval. Tool outputs and private reasoning aren't copied
into Telegram; the visible tool name/action, state and result are.
"""
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time


def kind(value):
    return re.sub(r"[_-]", "", str(value or "")).lower()


def redact(text):
    text = str(text or "")
    text = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot[REDACTED]", text)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]+)\b", "[REDACTED]", text)
    text = re.sub(r"(?i)(Bearer\s+)\S+", r"\1[REDACTED]", text)
    return re.sub(r"(?i)([\w-]*(?:token|password|secret|api[_-]?key)[\w-]*\s*[=:]\s*)"
                  r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r"\1[REDACTED]", text)


def text_of(item):
    return (item.get("text") or "".join(
        c.get("text") or "" for c in (item.get("content") or [])
        if isinstance(c, dict))).strip()


def action_label(item):
    k = kind(item.get("type"))
    if k == "commandexecution":
        labels = []
        for action in item.get("commandActions") or []:
            a = kind(action.get("type"))
            name = action.get("name") or action.get("path") or ""
            if a == "read":
                labels.append("Read " + str(name))
            elif a == "search":
                labels.append("Search " + str(action.get("query") or action.get("pattern") or name))
            elif a == "listfiles":
                labels.append("List files " + str(name))
        if labels:
            return "; ".join(labels)
        # No shell output or multiline scripts: those can contain secrets. Keep
        # the command's first line so 'running a command' isn't the only signal.
        command = redact(item.get("command") or "command").splitlines()[0]
        return "Run " + (command[:300] + "…" if len(command) > 300 else command)
    if k == "filechange":
        return "Edit " + ", ".join(str(c.get("path") or "file") for c in item.get("changes") or [])
    if k == "mcptoolcall":
        return "Tool " + ".".join(str(item[x]) for x in ("server", "tool") if item.get(x))
    if k in {"dynamictoolcall", "collabtoolcall"}:
        return "Tool " + str(item.get("tool") or item.get("agentStatus") or k)
    if k == "websearch":
        action = item.get("action") or {}
        return "Web search " + str(item.get("query") or action.get("query") or action.get("url") or "")
    if k == "imageview":
        return "View image " + str(item.get("path") or "")
    if k in {"contextcompaction", "todolist", "plan"}:
        return {"contextcompaction": "Compact context", "todolist": "Update plan", "plan": "Plan"}[k]
    return "Tool " + str(item.get("type") or "unknown")


class TurnView:
    def __init__(self, thread_id=""):
        self.thread_id, self.turn_id = thread_id, ""
        self.status, self.started_at = "idle", None
        self.items = OrderedDict()

    def bind(self, thread_id):
        if self.thread_id != thread_id:
            self.__init__(thread_id)

    def start(self, turn_id, started_at=None):
        if not turn_id:
            return False
        if turn_id != self.turn_id:
            self.turn_id, self.items = turn_id, OrderedDict()
            self.started_at = started_at
        self.status = "inProgress"
        return True

    def put(self, item, completed=False):
        item_id = item.get("id")
        k = kind(item.get("type"))
        if not item_id or k in {"reasoning", "functioncalloutput"}:
            return
        old = self.items.get(item_id, {})
        # A delayed start must not erase a completed item or its full text.
        if old.get("completed") and not completed:
            return
        if k in {"agentmessage", "usermessage"}:
            text = redact(text_of(item)) or old.get("text", "")
            if not text and not old:
                text = ""
            question = item.get("delivery") == "async" or bool(item.get("questions"))
            self.items[item_id] = {"type": k, "text": text,
                                   "question": question or old.get("question", False),
                                   "completed": completed}
        else:
            status = item.get("status") or ("completed" if completed else "inProgress")
            self.items[item_id] = {"type": k, "text": redact(action_label(item)),
                                   "status": status, "exit_code": item.get("exitCode"),
                                   "completed": completed}

    def hydrate(self, turn):
        turn_id = turn.get("id")
        if not turn_id or (self.turn_id and self.turn_id != turn_id):
            return  # don't replace a newer live turn with a stale resume snapshot
        previous_status = self.status
        self.start(turn_id, turn.get("startedAt"))
        # A snapshot is older than notifications received while resume was in
        # flight. Merge absent items only, then keep native snapshot ordering.
        live = self.items
        self.items = OrderedDict()
        for item in turn.get("items") or []:
            self.put(item, item.get("status") not in {"inProgress", "running"})
        self.items.update(live)
        self.status = previous_status if previous_status in {"completed", "failed", "interrupted"} else \
            turn.get("status") or "inProgress"
        if turn.get("error"):
            self.error(turn["error"])

    def error(self, error):
        message = error.get("message") if isinstance(error, dict) else str(error)
        if message:
            self.items["turn-error"] = {"type": "agentmessage", "text": "⚠️ " + redact(message),
                                        "completed": True}

    def observe(self, event):
        m, p = event.get("method"), event.get("params") or {}
        if not self.thread_id or p.get("threadId") != self.thread_id:
            return False
        turn = p.get("turn") or {}
        tid = p.get("turnId") or turn.get("id")
        if m == "turn/started":
            return self.start(tid, turn.get("startedAt"))
        if not self.turn_id or tid != self.turn_id:
            return False
        if m in {"item/started", "item/completed", "thread/realtime/item/started", "thread/realtime/item/completed"}:
            self.put(p.get("item") or {}, m.endswith("completed"))
        elif m == "item/agentMessage/delta":
            item_id = p.get("itemId")
            if item_id:
                if item_id not in self.items:
                    self.put({"id": item_id, "type": "agentMessage"})
                item = self.items[item_id]
                if not item.get("completed"):
                    item["text"] += p.get("delta") or ""
        elif m in {"item/tool/requestUserInput", "tool/requestUserInput"}:
            questions = p.get("questions") or []
            texts = []
            for q in questions:
                texts.append(str(q.get("question") or q.get("title") or "Question"))
                texts.extend("- " + str(o.get("label") if isinstance(o, dict) else o)
                             for o in q.get("options") or [])
            self.put({"id": p.get("itemId") or str(event.get("id")), "type": "agentMessage",
                      "text": "\n".join(texts), "delivery": "async"}, True)
        elif m in {"turn/completed", "turn/failed"}:
            self.status = turn.get("status") or ("failed" if m.endswith("failed") else "completed")
            self.error(turn.get("error") or p.get("error") or {})
        elif m == "error":
            self.error(p.get("error") or p)
        return True

    def render(self):
        parts = []
        for item in list(self.items.values()):
            text = item.get("text", "")
            if not text:
                continue
            if item["type"] in {"agentmessage", "usermessage"}:
                prefix = "💬 User\n" if item["type"] == "usermessage" else "❓ Question\n" if item.get("question") else ""
                parts.append(prefix + redact(text))
            else:
                status = item.get("status")
                mark = "✗" if status in {"failed", "declined"} else "✓" if item.get("completed") else "⏳"
                exit_code = item.get("exit_code")
                parts.append(mark + " " + text + (f" [exit {exit_code}]" if exit_code not in {None, 0} else ""))
        return "\n\n".join(parts)


def install(module):
    """Wrap the existing Conn without editing its user-owned launcher changes."""
    base = module.Conn

    class BubbleConn(base):
        def __init__(self, key, folder, cfg=None):
            super().__init__(key, folder, cfg)
            self.view = TurnView(module.read_thread(key))
            self._view_lock = threading.RLock()
            self._view_requests = {}
            from relay_codex_goal import GoalControl, GoalView
            self.goal_view = GoalView(self.view.thread_id)
            self.goal_control = GoalControl(self.goal_view, self._goal_rpc)

        def _goal_rpc(self, method, params):
            # Recheck the exact binding immediately before a native operation.
            if not self.alive() or not self.tid or params.get("threadId") != self.tid \
                    or module.read_thread(self.key) != self.tid:
                raise OSError("Native goal connection/binding changed")
            rid = self._send(method, params)
            return self._wait(rid, 10) if rid is not None else None

        def open(self):
            ok = super().open()
            if ok:
                try:
                    self.goal_control.read()
                except (ValueError, OSError):
                    pass  # Display unavailable; never simulate goals in text.
            return ok

        def _send(self, method, params, want_id=True):
            rid = super()._send(method, params, want_id)
            if rid is not None and want_id:
                self._view_requests[rid] = (method, params.get("threadId"))
            return rid

        def _wait(self, rid, secs=60):
            reply = super()._wait(rid, secs)
            method, expected = self._view_requests.pop(rid, (None, None))
            thread = (reply or {}).get("result", {}).get("thread") or {}
            if method in {"thread/resume", "thread/start", "thread/fork"} and thread.get("id") \
                    and (method != "thread/resume" or thread["id"] == expected):
                with self._view_lock:
                    self.view.bind(thread["id"])
                    self.goal_view.bind(thread["id"])
                    turns = thread.get("turns") or []
                    if turns:
                        self.view.hydrate(turns[-1])
                        self.turn_id = self.view.turn_id
                        self.busy = self.view.status == "inProgress"
            return reply

        def _on_notify(self, event):
            with self._view_lock:
                if event.get("method") in {"thread/goal/updated", "thread/goal/cleared"}:
                    self.goal_view.observe(event)
                    return  # Goal events aren't turn events and have no turn ID.
                if not self.view.observe(event):
                    return
                # The original parser keeps transport/steering flags. Only
                # exact-thread and exact-turn events are allowed to reach it.
                super()._on_notify(event)
                self.busy = self.view.status == "inProgress"

        def live_text(self):
            with self._view_lock:
                return self.view.render()

        def bubble_snapshot(self):
            with self._view_lock:
                return self.view.thread_id, self.view.turn_id, self.view.status, self.view.render()

        def goal_line(self):
            return self.goal_view.line()

        def goal_notice(self, request_id, text):
            with self._view_lock:
                if not self.view.turn_id:
                    return False
                self.view.put({"id": "relay-goal-" + request_id, "type": "agentMessage", "text": text}, completed=True)
                return True

    module.Conn = BubbleConn


class DeliveryUncertain(RuntimeError):
    pass


class PendingDelivery(RuntimeError):
    """The same request is still in flight; poll its receipt, never resend it."""
    def __init__(self, poll):
        super().__init__("gateway acknowledgment is still pending")
        self.poll = poll


class BubbleState:
    """Exact route + native turn -> acknowledged message IDs, never guessed."""
    def __init__(self, directory, thread_id, turn_id, chat, topic):
        self.scope = {"schema": "ccrelay.codex_bubble.v1", "thread_id": thread_id,
                      "turn_id": turn_id, "chat": str(chat), "topic": str(topic or "")}
        key = hashlib.sha256(json.dumps(self.scope, sort_keys=True).encode()).hexdigest()
        self.path = Path(directory) / ("codex-bubble-" + key + ".json")
        self.ids, self.pending_edit = [], None
        if self.path.exists():
            body = json.loads(self.path.read_text(encoding="utf-8"))
            if body != {**self.scope, "message_ids": body.get("message_ids"), "pending_edit": body.get("pending_edit")}:
                raise ValueError("bubble route/turn state mismatch")
            self.ids = body["message_ids"]
            self.pending_edit = body["pending_edit"]
            if not isinstance(self.ids, list) or any(i is not None and
                    (not isinstance(i, str) or not re.fullmatch(r"[1-9][0-9]*", i)) for i in self.ids):
                raise ValueError("invalid acknowledged bubble message IDs")

    def save(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + f".tmp-{os.getpid()}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump({**self.scope, "message_ids": self.ids, "pending_edit": self.pending_edit}, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(tmp, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if tmp.exists():
                tmp.unlink()


class BubblePages:
    """Edit acknowledged IDs, with one rolling live tail or full-history pages.

    `split` must produce HTML-budgeted source chunks; transport is injected.
    A missing send receipt is held across restarts, not silently sent again.
    Edits are safe to repeat on restart; local scheduling is NOT a Telegram ack.
    """
    def __init__(self, state, send, edit, split, clock=time.monotonic, reconcile_edits=False,
                 rolling=False, started_at=None, wall_clock=time.time):
        self.state, self.send, self.edit, self.split, self.clock = state, send, edit, split, clock
        self.sent, self.last = {}, None
        self.pending, self.reconcile_edits = None, reconcile_edits
        self.rolling, self.started_at, self.wall_clock = rolling, started_at, wall_clock
        self.started_clock = clock()

    def rolling_text(self, body, status, goal_line=""):
        from relay_tg import md_to_html
        started = self.started_at
        if started is not None:
            if started > 100000000000:
                started /= 1000
            elapsed = max(0, int(self.wall_clock() - started))
        else:
            elapsed = max(0, int(self.clock() - self.started_clock))
        hours, seconds = divmod(elapsed, 3600)
        minutes, seconds = divmod(seconds, 60)
        duration = (f"{hours}h " if hours else "") + (f"{minutes}m " if minutes or hours else "") + f"{seconds}s"
        label = {"inProgress": "Working", "completed": "Done", "failed": "Failed",
                 "interrupted": "Interrupted"}.get(status, str(status))
        footer = f"{label} ({duration})"
        if goal_line:
            footer += "\n" + goal_line
        if len(md_to_html(footer).encode("utf-16-le")) // 2 > 1500:
            raise ValueError("Goal footer exceeds its reserved message budget")
        body = body or "Waiting for Codex activity…"
        size = min(len(body), 3000)
        while True:
            start = len(body) - size
            # Keep the newest characters even for a single giant line. Restore
            # a fence when the retained suffix starts inside a code block.
            tail = ("…\n" if start else "") + ("```\n" if body[:start].count("```") % 2 else "") + body[start:]
            if tail.count("```") % 2:
                tail += "\n```"
            text = tail + "\n\n" + footer
            if len(md_to_html(text).encode("utf-16-le")) // 2 <= 3900:
                return text
            size = max(1, size // 2)

    def update(self, body, status="inProgress", force=False, goal_line=""):
        if self.pending is not None:
            operation, pos, text, poll = self.pending
            receipt = poll()
            if receipt is None:
                return False
            if receipt is False:
                self.pending = None
                raise DeliveryUncertain("gateway rejected the pending bubble operation; intent remains saved")
            if operation == "send":
                if not re.fullmatch(r"[1-9][0-9]*", str(receipt)):
                    raise DeliveryUncertain("invalid late bubble send receipt")
                self.state.ids[pos] = str(receipt)
            else:
                self.state.pending_edit = None
            self.state.save()
            self.sent[pos] = text
            self.pending = None
        now = self.clock()
        if not force and self.last is not None and now - self.last < 5:
            return False
        self.last = now
        if self.state.pending_edit is not None:
            if not self.reconcile_edits:
                raise DeliveryUncertain("unconfirmed bubble edit remains held; reconcile before a newer edit")
            intent = self.state.pending_edit
            # With the sole watcher as writer, replay ONLY this exact same-ID,
            # same-payload edit. It cannot duplicate messages or clobber a newer
            # edit: newer content stays fenced until this receipt is confirmed.
            if not self._edit(intent["position"], intent["text"]):
                return False
            self.sent[intent["position"]] = intent["text"]
        label = {"inProgress": "⏳ Working", "completed": "✓ Done", "failed": "⚠️ Failed",
                 "interrupted": "✋ Interrupted"}.get(status, "⏸ " + str(status))
        pieces = [self.rolling_text(body, status, goal_line)] if self.rolling else self.split(body or "Waiting for Codex activity…", 3900)
        for pos, piece in enumerate(pieces):
            text = piece if self.rolling else label + (f" · part {pos + 1}" if len(pieces) > 1 else "") + "\n\n" + piece
            if pos >= len(self.state.ids):
                self.state.ids.append(None)
                self.state.save()  # an effect may follow: persist ambiguity first
                try:
                    mid = self.send(text)
                except PendingDelivery as wait:
                    self.pending = ("send", pos, text, wait.poll)
                    return False
                if not mid or not re.fullmatch(r"[1-9][0-9]*", str(mid)):
                    raise DeliveryUncertain("bubble send has no verified message ID; reconcile before another send")
                self.state.ids[pos] = str(mid)
                self.state.save()
                self.sent[pos] = text
            elif self.state.ids[pos] is None:
                raise DeliveryUncertain("unconfirmed bubble send remains held; no automatic replay")
            elif self.sent.get(pos) != text:
                if not self._edit(pos, text):
                    return False
                self.sent[pos] = text
        # Earlier edits can shorten or move content between pages. Keep old
        # IDs as explicit continuations, rather than leaving duplicated text.
        for pos in range(len(pieces), len(self.state.ids)):
            if self.state.ids[pos] is None:
                raise DeliveryUncertain("unconfirmed bubble continuation remains held")
            text = label + "\n\nContent continues in the preceding bubble."
            if self.sent.get(pos) != text:
                if not self._edit(pos, text):
                    return False
                self.sent[pos] = text
        return True

    def _edit(self, pos, text):
        self.state.pending_edit = {"position": pos, "text": text}
        self.state.save()
        try:
            receipt = self.edit(self.state.ids[pos], text)
        except PendingDelivery as wait:
            self.pending = ("edit", pos, text, wait.poll)
            return False
        if receipt is not True:
            raise DeliveryUncertain("bubble edit was not confirmed; payload is retained and newer edits are held")
        self.state.pending_edit = None
        self.state.save()
        return True
