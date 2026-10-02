"""Native Codex model controls; no inference, relaunch or replacement thread.

Discovery comes from model/list. Updates use thread/settings/update and are
confirmed by thread/read. Lost acknowledgments are reported, never retried.
Picker receipts bind each button to one session, native thread and destination.
"""
import json
import os
from pathlib import Path
import re
import time
import uuid

RETIRED = {"kimi", "ik3", "k3", "ox", "oxa", "cox", "alpha", "ox-alpha"}


def retired(model):
    value = model.lower().strip()
    return value in RETIRED or "kimi" in value or "ox-alpha" in value or "x-preview-f-free" in value


class NativeRPC:
    def __enter__(self):
        from relay_ws import UnixWS
        self.ws = UnixWS(timeout=8)
        self.ws.sock.settimeout(8)
        self.seq = 0
        try:
            self("initialize", {"clientInfo": {"name": "relay-model-controls", "version": "1"},
                                "capabilities": {"experimentalApi": True}})
        except Exception:
            self.ws.close()
            raise
        return self

    def __exit__(self, *unused):
        self.ws.close()

    def __call__(self, method, params):
        self.seq += 1
        request = self.seq
        self.ws.write(json.dumps({"id": request, "method": method, "params": params}))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.ws.sock.settimeout(max(0.1, deadline - time.monotonic()))
            reply = json.loads(self.ws.recv())
            if reply.get("id") == request:
                if "error" in reply:
                    raise ValueError("Codex rejected the control; no model prompt was sent.")
                return reply["result"]
        raise TimeoutError("Codex control acknowledgment unavailable")


def models(rpc):
    result, cursor, seen = [], None, set()
    while True:
        page = rpc("model/list", {"includeHidden": False, "cursor": cursor})
        for model in page["data"]:
            if not model.get("hidden") and not retired(model["model"]):
                result.append(model)
        cursor = page.get("nextCursor")
        if not cursor:
            return result
        if cursor in seen or len(seen) >= 20:
            raise ValueError("Invalid model catalog pagination")
        seen.add(cursor)


def read_thread(rpc, tid):
    thread = rpc("thread/read", {"threadId": tid, "includeTurns": False})["thread"]
    if thread.get("id") != tid:
        raise ValueError("Native thread does not match this topic")
    return thread


def control(rpc, tid, name, argument):
    """Return text and (label, slash-command) choices; update only explicit input."""
    if not tid:
        return "This topic has no Codex thread yet. Send a message to start it, then use /model.", []
    thread = read_thread(rpc, tid)
    current, effort = thread.get("model"), thread.get("reasoningEffort")
    catalog = models(rpc)
    if name == "model" and argument.lower() in {"", "list", "status"}:
        choices = [(m["displayName"], "/model " + m["model"]) for m in catalog]
        return (f"Codex model: {current or 'not reported'}\nReasoning: {effort or 'default'}\n"
                "Choose a model below, or /model <model-id> [effort].\n"
                "Use /effort for reasoning, /backend to switch tools."), choices
    selected = next((m for m in catalog if m["model"] == current), None)
    if name == "effort" and not argument:
        if selected is None:
            return "The current model is absent from the live catalog. Select one with /model first.", []
        choices = [(e["reasoningEffort"] + " — " + e["description"], "/effort " + e["reasoningEffort"])
                   for e in selected["supportedReasoningEfforts"]]
        return f"Reasoning for {current}: {effort or 'default'}", choices
    parts = argument.split()
    if name == "model":
        if not 1 <= len(parts) <= 2:
            return "Use /model <model-id> [effort], or /model for choices.", []
        selected = next((m for m in catalog if parts[0] in {m["model"], m["id"]}), None)
        if selected is None:
            return "Unknown or retired model. Use /model to choose from the live Codex catalog.", []
        allowed = {e["reasoningEffort"] for e in selected["supportedReasoningEfforts"]}
        wanted = parts[1] if len(parts) == 2 else (effort if effort in allowed else selected["defaultReasoningEffort"])
    else:
        if selected is None or len(parts) != 1:
            return "Use /model first, then /effort <level>.", []
        allowed = {e["reasoningEffort"] for e in selected["supportedReasoningEfforts"]}
        wanted = parts[0]
    if wanted not in allowed:
        return "Supported reasoning levels: " + ", ".join(sorted(allowed)), []
    expected = {"model": selected["model"], "reasoningEffort": wanted}
    if any(thread.get(k) != v for k, v in expected.items()):
        try:
            rpc("thread/settings/update", {"threadId": tid, "model": selected["model"], "effort": wanted})
            observed = read_thread(rpc, tid)
        except Exception:
            return "Model change is unconfirmed. Use /model to read native status before making another change.", []
        if any(observed.get(k) != v for k, v in expected.items()):
            return "Codex has not confirmed the requested settings. Use /model to inspect native status.", []
    return (f"Codex: {selected['model']} · reasoning {wanted}. Applies to subsequent turns; "
            "the current turn and conversation are preserved."), []


def picker_path(state, key):
    return Path(state) / f"model-picker-{key}.json"


def save_picker(state, key, tid, destination, choices):
    nonce = uuid.uuid4().hex[:12]
    record = {"nonce": nonce, "thread": tid, "destination": destination,
              "expires": time.time() + 3600, "choices": choices}
    path = picker_path(state, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(record))
    os.replace(tmp, path)
    return [f"ccmodel:{nonce}:{i}" for i in range(len(choices))]


def resolve_picker(text, state, key, tid, destination):
    match = re.fullmatch(r"callback_data:\s*ccmodel:([a-f0-9]{12}):(\d+)", text.strip())
    if not match:
        raise ValueError("Invalid model button. Open /model again.")
    try:
        record = json.loads(picker_path(state, key).read_text())
        if record["nonce"] != match[1] or record["thread"] != tid or record["destination"] != destination or record["expires"] < time.time():
            raise ValueError("stale")
        return record["choices"][int(match[2])][1]
    except (OSError, ValueError, KeyError, IndexError):
        raise ValueError("This model picker is stale or belongs to another topic. Open /model again.")


def handle(sender, prompt):
    """Fresh per-message process, shared by both Telegram transports."""
    from relay_bot_commands import slash_command
    command = slash_command(prompt)
    callback = prompt.strip().startswith("callback_data: ccmodel:")
    if not callback and (not command or command["name"] not in {"model", "effort", "backend"}):
        return False
    destination = [str(sender.CHAT_ID), str(sender.THREAD_ID)]
    tid = sender.cxp().read_thread(sender.SESSION) if sender.is_codex() else ""
    if callback:
        try:
            prompt = resolve_picker(prompt, sender.STATE_DIR, sender.SESSION, tid, destination)
        except ValueError as error:
            sender.deliver(str(error))
            return True
    command = slash_command(prompt)
    if not command or command["name"] not in {"model", "effort", "backend"}:
        return False
    name, argument = command["name"], command["args"]
    if argument.split() and retired(argument.split()[0]):
        sender.deliver("Kimi Code and Ox Alpha are retired on both bots. Use /model or /backend.")
        return True
    if name == "backend":
        if not argument:
            text = "Choose the tool for this topic. /model changes the model within the current tool."
            choices = [("Claude Code", "/backend claude"), ("Codex", "/backend codex")]
        elif argument.lower() in {"claude", "codex"}:
            if sender.backend_name() == argument.lower():
                sender.deliver(f"This topic already uses {argument.title()}.")
            elif (sender.is_codex() and tid and _active(tid)) or (not sender.is_codex() and sender.BUSY.search(sender.pane())):
                sender.deliver("Finish or /cancel the current turn before switching tools; its conversation is preserved.")
            else:
                sender.restart_with_model("cx" if argument.lower() == "codex" else "opus")
            return True
        else:
            sender.deliver("Use /backend claude or /backend codex.")
            return True
    elif sender.is_codex():
        try:
            with NativeRPC() as rpc:
                text, choices = control(rpc, tid, name, argument)
        except Exception:
            sender.deliver("Codex model controls are unavailable; no prompt or backend switch was sent.")
            return True
    elif name == "effort":
        sender.deliver("/effort is a Codex control. Use /model for this Claude topic.")
        return True
    elif not argument:
        text = "Claude Code models. Use /backend to switch tools."
        choices = [("Opus", "/model opus"), ("Sonnet", "/model sonnet"), ("Haiku", "/model haiku")]
    else:
        if not re.fullmatch(r"[A-Za-z0-9._\[\]-]+", argument):
            sender.deliver("Use /model <name> or choose a model with /model.")
        elif sender.BUSY.search(sender.pane()):
            sender.deliver("Finish or /cancel the current turn before changing the Claude model.")
        else:
            sender.restart_with_model(argument)
        return True
    if choices:
        values = save_picker(sender.STATE_DIR, sender.SESSION, tid, destination, choices)
        sender.tg_buttons(text, [label for label, _ in choices], values=values)
    else:
        sender.deliver(text)
    return True


def _active(tid):
    with NativeRPC() as rpc:
        status = read_thread(rpc, tid).get("status", {})
        return status.get("type") == "active"
