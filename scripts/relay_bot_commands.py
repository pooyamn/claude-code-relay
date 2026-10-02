"""Session-aware command discovery for the legacy native Telegram bot.

Bot API command scopes have no topic ID. Build a stable per-chat union, never
change the whole forum's menu just because someone spoke in a different topic.
Menus confer no authority; protected PC integration remains separate work.
"""
from __future__ import annotations

import json
from pathlib import Path
import re


SLASH = re.compile(r"^\s*(?:/?cc\s+|/)(?P<name>[A-Za-z][A-Za-z0-9_-]*)(?:@(?P<bot>[A-Za-z0-9_]+))?(?:\s+(?P<args>[\s\S]*))?\s*$", re.I)
ALIASES = {"interrupt": "cancel", "esc": "cancel", "stop": "cancel", "unqueue": "unq", "commands": "help", "models": "model",
           "new-cc": "newcc", "new-claude-code": "newcc", "unbind-claude-code": "unbind",
           "cc-status": "ccstatus", "claude-code-status": "ccstatus"}
COMMON = (
    ("help", "Commands available in this topic"),
    ("model", "Choose a model; show current native model"),
    ("backend", "Switch this topic between Claude Code and Codex"),
    ("cancel", "Interrupt this topic's current turn"),
)
TOOLS = {
    "claude": (("clear", "Start a fresh Claude conversation"),
               ("compact", "Compact Claude context"),
               ("unq", "Remove pending Claude messages")),
    "codex": (("goal", "Goal: <objective>, status, pause, resume, clear"),
              ("effort", "Choose Codex reasoning depth")),
}
ADMIN = (("newcc", "Bind this topic: /newcc <6-digit code>"),
         ("unbind", "Unbind this topic"),
         ("ccstatus", "List relay bindings (owner only)"))
OWNED = {name for name, _ in (*COMMON, *ADMIN, *TOOLS["claude"], *TOOLS["codex"])}


def slash_command(text, username=None):
    """Return a normalized explicit command or None; preserve argument case.

    A foreign address is classified separately, so it cannot become a prompt.
    Quoted commands and ordinary prose never match.
    """
    match = SLASH.fullmatch(text)
    if not match:
        return None
    name, args = match.group("name").lower(), (match.group("args") or "").strip()
    foreign = bool(username is not None and match.group("bot") and
                   match.group("bot").lower() != username.lower())
    name = ALIASES.get(name, name)
    return {"name": name, "args": args, "foreign": foreign,
            "text": "/" + name + (" " + args if args else "")}


def backend_for_key(directory, key):
    """Read only relay markers; no native session, transcript, config or launch.

    The cx pin precedes the backend marker in claude-relay-group too. Missing
    or corrupt evidence is unknown, not proof of that launcher's Claude default.
    """
    root = Path(directory)
    try:
        if (root / f"default-model-{key}.txt").read_text().strip() == "cx":
            return "codex"
    except FileNotFoundError:
        pass
    except OSError:
        return "unknown"
    try:
        value = json.loads((root / f"backend-{key}.json").read_text())
    except FileNotFoundError:
        return "unknown"
    except (OSError, ValueError):
        return "unknown"
    backend = value.get("backend") if isinstance(value, dict) else None
    return backend if isinstance(backend, str) and backend else "unknown"


def catalog(backends, owner=True):
    """Only controls implemented by the relay, not every native CLI command."""
    if not owner:
        return [{"command": "help", "description": COMMON[0][1]}]
    types = set(backends)
    result = [{"command": name, "description": desc} for name, desc in COMMON]
    for tool in ("claude", "codex"):
        if tool in types:
            for name, desc in TOOLS[tool]:
                label = f"[{tool.title()}] " if types != {tool} else ""
                result.append({"command": name, "description": label + desc})
    result.extend({"command": name, "description": desc} for name, desc in ADMIN)
    if not types.intersection(TOOLS):
        result = [item for item in result if item["command"] != "cancel"]
    if not types:
        result = [item for item in result if item["command"] not in {"model", "cancel"}]
    return result


def command_error(text, backend):
    """Fence known tool-specific controls at execution as well as discovery."""
    command = slash_command(text)
    if not command:
        return ""
    name = command["name"]
    if backend == "unknown" and name not in {"model", "cancel", "help"}:
        return "Session type is unverified; no native control or model prompt was sent. Use /help."
    if name == "goal" and backend != "codex":
        return "Native goal controls require the Codex backend. No model prompt was sent."
    if backend == "codex" and name not in {"goal", "model", "backend", "effort", "cancel", "help"}:
        return (f"/{name} is not supported by this Codex relay adapter. "
                "No model prompt was sent; /help lists supported controls. "
                "/goal clear removes only a goal, not the conversation.")
    return ""


def help_text(backend, owner=True):
    if not owner:
        return (f"This topic uses {backend.title()}. Session controls require an authorized owner; "
                "the Telegram menu does not grant permission.")
    label = backend.title() if backend in TOOLS else f"{backend} (limited command discovery)"
    lines = [f"{label} topic commands:"]
    for item in catalog({backend}):
        lines.append(f"/{item['command']} — {item['description']}")
    if backend == "codex":
        lines.append("Goal examples: /goal Finish the board; /goal pause; /goal resume; /goal status; /goal clear.")
        lines.append("Native /clear and /compact are not wired to this relay adapter; they are never sent as model text.")
    lines.append("In a mixed forum the Telegram menu is shared across topics; this help matches the current topic.")
    return "\n".join(lines)


def menu_plan(bindings, owners, backend_of):
    """Exact chat/member scopes only. Never mutate global or administrator scope."""
    chats = {}
    for peer, folder in bindings.items():
        match = re.fullmatch(r"(-?[1-9][0-9]*)(?::topic:[1-9][0-9]*)?", str(peer))
        if not match or not isinstance(folder, str) or not folder:
            raise ValueError("Invalid command-menu binding; no global fallback.")
        chat = int(match.group(1))
        chats.setdefault(chat, set()).add(backend_of(folder))
    owners = sorted(set(owners))
    if any(type(uid) is not int or uid <= 0 for uid in owners):
        raise ValueError("Invalid command-menu owner ID.")
    plan = []
    for chat, types in sorted(chats.items()):
        if chat > 0:  # Private chats have no chat_member scope.
            plan.append({"scope": {"type": "chat", "chat_id": chat},
                         "language_code": "", "commands": catalog(types, chat in owners)})
            continue
        plan.append({"scope": {"type": "chat", "chat_id": chat},
                     "language_code": "", "commands": catalog(types, False)})
        for uid in owners:
            plan.append({"scope": {"type": "chat_member", "chat_id": chat, "user_id": uid},
                         "language_code": "", "commands": catalog(types)})
    return plan


class CommandMenus:
    """Read/merge/write/readback configuration, not a poller or inference path.

    A failed or lost write acknowledgment is checked on the next read, never
    blindly replayed. Unrelated commands at the same exact scope are retained.
    Existing more-specific/language menus may take precedence; no invented
    topic scope, global overwrite, webhook change or other-bot mutation.
    """
    def __init__(self, bot, username, expected_username, report=lambda message: None):
        if not isinstance(username, str) or not isinstance(expected_username, str) or not expected_username or username.lower() != expected_username.lower():
            raise ValueError("Bot identity mismatch; command menus were not changed.")
        self.bot, self.report = bot, report
        self.previous = {}

    @staticmethod
    def _key(scope):
        return json.dumps(scope, sort_keys=True)

    def reconcile(self, plan):
        # Validate the entire plan before any remote operation. Even a caller
        # mistake cannot broaden this helper to bot-global/admin/language scope.
        if not isinstance(plan, list):
            raise ValueError("Invalid command-menu plan.")
        for entry in plan:
            if not isinstance(entry, dict) or set(entry) != {"scope", "language_code", "commands"}:
                raise ValueError("Invalid command-menu entry.")
            scope = entry["scope"]
            if not isinstance(scope, dict) or scope.get("type") not in {"chat", "chat_member"} or \
                    set(scope) != ({"type", "chat_id", "user_id"} if scope["type"] == "chat_member" else {"type", "chat_id"}) or \
                    type(scope.get("chat_id")) is not int or not scope["chat_id"] or entry["language_code"] != "":
                raise ValueError("Command-menu scope must be an exact chat/member; no topic/global fallback.")
            if scope["type"] == "chat_member" and (scope["chat_id"] > 0 or type(scope["user_id"]) is not int or scope["user_id"] <= 0):
                raise ValueError("Invalid command-menu group/member scope.")
            commands = entry["commands"]
            if not isinstance(commands, list) or len(commands) > 100 or any(
                    not isinstance(item, dict) or set(item) != {"command", "description"} or
                    item.get("command") not in OWNED or not isinstance(item.get("description"), str) or
                    not 1 <= len(item["description"]) <= 256 for item in commands):
                raise ValueError("Invalid managed command catalog.")
        desired = {self._key(entry["scope"]): entry for entry in plan}
        # Retired bindings get explicit help-only scopes rather than exposing a
        # global fallback. Handler checks remain authoritative even if stale UI
        # survives process restart or a language/admin scope overrides this one.
        for key, entry in self.previous.items():
            if key not in desired:
                desired[key] = {**entry, "commands": catalog(set(), False)}
        self.previous = desired
        results = []
        for entry in desired.values():
            params = {"scope": entry["scope"], "language_code": entry["language_code"]}
            try:
                current = self.bot.call("getMyCommands", params, timeout=3, max_wait=0)
                if not isinstance(current, list) or any(not isinstance(item, dict) or
                        not isinstance(item.get("command"), str) or not isinstance(item.get("description"), str)
                        for item in current):
                    raise ValueError("Invalid command-menu readback.")
                merged = [item for item in current if item["command"] not in OWNED] + entry["commands"]
                if len(merged) > 100:
                    raise ValueError("Command menu exceeds Telegram's 100-command limit; original retained.")
                if current == merged:
                    results.append("unchanged")
                    continue
                acknowledged = self.bot.call("setMyCommands", {**params, "commands": merged}, timeout=3, max_wait=0)
                observed = self.bot.call("getMyCommands", params, timeout=3, max_wait=0)
                if acknowledged is not True or observed != merged:
                    raise ValueError("Command-menu write not verified.")
                results.append("confirmed")
            except Exception as error:
                results.append("unconfirmed")
                # URL errors can contain the bot credential: report type only.
                self.report(f"Command menu unconfirmed ({type(error).__name__}); no blind replay.")
        return results
