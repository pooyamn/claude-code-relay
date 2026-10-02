"""Native, thread-scoped Codex goal controls. No prompt or model fallback.

The legacy Mac watcher owns RPCs; this inbox records an ambiguous write BEFORE
dispatch and never replays it. This is not the target PC's human/grant boundary
or admission controller. Enabling native continuations there requires PRs 7–9.
"""
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import uuid


COMMAND = re.compile(r"^\s*(?:/|/?cc\s+)?goal(?:@(?P<bot>\w+))?(?:\s+(?P<argument>[\s\S]*))?\s*$", re.I)
STATUSES = {"active", "paused", "blocked", "usageLimited", "budgetLimited", "complete"}
HELP = "Use /goal <objective>, /goal pause, /goal resume, /goal status or /goal clear."


def parse_command(text):
    """Recognize only a whole explicit command, never quoted/model prose."""
    match = COMMAND.fullmatch(text)
    if not match:
        return None
    arg = (match.group("argument") or "").strip()
    if not arg or arg.lower() == "status":
        return {"action": "status"}
    if arg.lower() in {"pause", "resume", "clear"}:
        return {"action": arg.lower()}
    if arg.lower() == "set":
        raise ValueError(HELP)
    objective = re.sub(r"^set\s+", "", arg, flags=re.I).strip()
    if not objective or len(objective) > 4000:
        raise ValueError("Goal objective must contain 1–4000 characters.")
    return {"action": "set", "objective": objective}


def safe_text(text):
    from relay_codex_bubble import redact
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(text))
    return redact(" ".join(text.split())).translate(
        {ord(c): None for c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"})


def goal_value(value, thread_id):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("threadId") != thread_id \
            or value.get("status") not in STATUSES \
            or not isinstance(value.get("objective"), str) \
            or not 1 <= len(value["objective"]) <= 4000:
        raise ValueError("Goal response does not match the bound thread or supported schema.")
    for field in ("tokensUsed", "timeUsedSeconds", "createdAt", "updatedAt"):
        if type(value.get(field)) is not int or value[field] < 0:
            raise ValueError("Invalid native goal accounting.")
    budget = value.get("tokenBudget")
    if budget is not None and (type(budget) is not int or budget <= 0):
        raise ValueError("Invalid native goal budget.")
    return dict(value)


class GoalView:
    """Native evidence only; an old read cannot overwrite a newer notification."""
    def __init__(self, thread_id=""):
        self.lock = threading.RLock()
        self.thread_id, self.goal, self.known, self.error, self.revision = thread_id, None, False, "", 0

    def bind(self, thread_id):
        with self.lock:
            if self.thread_id != thread_id:
                self.thread_id, self.goal, self.known, self.error = thread_id, None, False, ""
                self.revision += 1

    def apply(self, value, thread_id, expected_revision=None):
        validated = goal_value(value, thread_id)
        with self.lock:
            if thread_id != self.thread_id or (expected_revision is not None and expected_revision != self.revision):
                return False
            self.goal, self.known, self.error = validated, True, ""
            self.revision += 1
            return True

    def observe(self, event):
        method, params = event.get("method"), event.get("params") or {}
        if method not in {"thread/goal/updated", "thread/goal/cleared"} or params.get("threadId") != self.thread_id:
            return False
        try:
            value = params["goal"] if method == "thread/goal/updated" else None
            return self.apply(value, self.thread_id)
        except (KeyError, ValueError):
            return False

    def line(self):
        with self.lock:
            if self.error:
                return "Goal: status unavailable (last observation not current)"
            if not self.known:
                return "Goal: status not yet verified"
            if self.goal is None:
                return ""
            status = {"usageLimited": "usage limited", "budgetLimited": "budget limited"}.get(
                self.goal["status"], self.goal["status"])
            objective = safe_text(self.goal["objective"])
            objective = objective[:219] + "…" if len(objective) > 220 else objective
            # Literal text: an objective cannot inject a link/fence into the footer.
            objective = re.sub(r"([\\`*_{}\[\]()#+.!|>~])", r"\\\1", objective)
            return f"Goal: {status} — {objective}"


class GoalControl:
    def __init__(self, view, rpc):
        self.view, self.rpc = view, rpc

    def read(self):
        with self.view.lock:
            tid, revision = self.view.thread_id, self.view.revision
        try:
            reply = self.rpc("thread/goal/get", {"threadId": tid})
            if isinstance(reply, dict) and "error" in reply:
                raise ValueError("Native goal read rejected: " + safe_text(json.dumps(reply["error"], ensure_ascii=False)))
            if not isinstance(reply, dict) or not isinstance(reply.get("result"), dict) \
                    or "goal" not in reply["result"]:
                raise ValueError("Native goal status unavailable; no goal control was dispatched.")
            value = goal_value(reply["result"]["goal"], tid)
        except (ValueError, OSError):
            with self.view.lock:
                if self.view.thread_id == tid and self.view.revision == revision:
                    self.view.error = "unavailable"
            raise
        self.view.apply(value, tid, expected_revision=revision)
        with self.view.lock:
            if self.view.thread_id != tid:
                raise ValueError("Native goal thread changed during the read.")
            return None if self.view.goal is None else dict(self.view.goal)

    def execute(self, command):
        action = command["action"]
        tid = self.view.thread_id
        try:
            goal = self.read()
        except (ValueError, OSError) as error:
            return "rejected", "No goal change was sent. " + safe_text(error)
        if tid != self.view.thread_id:
            return "rejected", "Goal command rejected: native thread changed during status verification."
        if action == "status":
            return "confirmed", self.view.line() or "No ongoing goal in this Codex thread."
        if action in {"pause", "resume"}:
            if goal is None or goal["status"] == "complete":
                return "rejected", "No resumable goal in this thread. Set a goal explicitly first."
            params = {"threadId": tid, "status": "paused" if action == "pause" else "active"}
        elif action == "set":
            objective = command.get("objective")
            if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 4000:
                return "rejected", HELP
            params = {"threadId": tid, "objective": objective, "status": "active"}
        elif action == "clear":
            params = {"threadId": tid}
        else:
            return "rejected", HELP
        method = "thread/goal/clear" if action == "clear" else "thread/goal/set"
        with self.view.lock:
            mutation_revision = self.view.revision
        try:
            reply = self.rpc(method, params)
        except OSError:
            reply = None
        if not isinstance(reply, dict) or ("result" not in reply and "error" not in reply):
            with self.view.lock:
                if self.view.thread_id == tid and self.view.revision == mutation_revision:
                    self.view.error = "mutation outcome unknown"
            return "unknown", "Goal change outcome unconfirmed; not retried. Use /goal status to inspect the native state."
        if "error" in reply:
            return "rejected", "Codex rejected goal control: " + safe_text(json.dumps(reply["error"], ensure_ascii=False))
        try:
            if action == "clear":
                self.read()  # Read back; a racing new goal must not be hidden.
                return "confirmed", "Goal clear acknowledged. " + (self.view.line() or "No goal remains.")
            value = goal_value(reply["result"]["goal"], tid)
            self.view.apply(value, tid, expected_revision=mutation_revision)
            if value["status"] != params["status"] or (action == "set" and value["objective"] != params["objective"]):
                return "unknown", "Goal control acknowledged but the requested state was not returned. " + self.view.line() + " Use /goal status; no automatic replay."
        except (KeyError, TypeError, ValueError, OSError):
            return "unknown", "Goal control acknowledged but state could not be verified. Use /goal status; no automatic replay."
        note = " Pause acknowledged; the current turn was not interrupted." if action == "pause" else ""
        return "confirmed", "Goal control acknowledged. " + self.view.line() + note


class GoalInbox:
    """Separate from prompt intake; each exact-thread request dispatches at most once.

    Common-user legacy state is not role authentication. The target must replace
    this ingress with the protected intake, membership and admission controllers.
    """
    def __init__(self, directory, key):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key):
            raise ValueError("Invalid goal inbox key.")
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / ("codex-goals-" + key + ".sqlite")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, 1}:
            self.db.close()
            raise ValueError("Unsupported goal inbox schema; preserve state for migration.")
        self.db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, thread TEXT NOT NULL, command TEXT NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL DEFAULT '')")
        self.db.execute("PRAGMA user_version=1")
        self.db.commit()

    def close(self):
        self.db.close()

    def enqueue(self, thread_id, command):
        if not thread_id:
            raise ValueError("No existing Codex thread is bound. Start the conversation before setting a goal.")
        request_id = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO requests(id,thread,command,state) VALUES (?,?,?,'queued')",
                            (request_id, thread_id, json.dumps(command)))
        return request_id

    def run_one(self, conn, bound_thread):
        self.db.execute("BEGIN IMMEDIATE")
        row = self.db.execute("SELECT id,thread,command FROM requests WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
        if row is None:
            self.db.commit()
            return None
        request_id, thread, command = row
        # Persist uncertainty before even a read RPC; a death on either side of
        # the write cannot return this command to the eligible queue.
        self.db.execute("UPDATE requests SET state='unknown', message=? WHERE id=?",
                        ("Unconfirmed goal command; inspect native status before another change.", request_id))
        self.db.commit()
        if thread != bound_thread or conn.tid != thread or conn.goal_view.thread_id != thread:
            state, message = "rejected", "Goal command rejected: the topic's native thread binding changed."
        else:
            try:
                state, message = conn.goal_control.execute(json.loads(command))
            except Exception as error:
                # A broken adapter may raise after the native effect. Keep the
                # precommitted hold and surface the type, not sensitive RPC data.
                state, message = "unknown", f"Goal adapter failed ({type(error).__name__}); outcome held without replay. Use /goal status."
        with self.db:
            self.db.execute("UPDATE requests SET state=?,message=? WHERE id=?", (state, message, request_id))
        return request_id, state, message

    def unknown_count(self):
        return self.db.execute("SELECT COUNT(*) FROM requests WHERE state='unknown'").fetchone()[0]
