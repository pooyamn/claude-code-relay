"""Triage for platform issues and health findings: kind, priority, target agent.

Jev (TypeSafe's fast decision model) through Vercel AI Gateway's free tier when
a key is configured, plain rules otherwise or when the call fails. Jev only ever
sees the text it is given; callers pass masked text.

Key file: ~/.config/ccrelay/vercel.env with AI_GATEWAY_API_KEY=...
"""
import json
import os
import re
import urllib.request

KEY_FILE = os.path.expanduser(os.environ.get("CCRELAY_VERCEL_ENV", "~/.config/ccrelay/vercel.env"))
URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
MODEL = "typesafe-ai/jev"
KINDS = ("bug", "improvement", "feature")
PRIOS = ("P1", "P2", "P3")


def _key():
    try:
        for line in open(KEY_FILE):
            k, _, v = line.strip().partition("=")
            if k == "AI_GATEWAY_API_KEY" and v:
                return v.strip()
    except OSError:
        pass
    return None


_P1 = re.compile(r"(?i)\b(down|dead|not (responding|responsive|answering)|lost|crash(ed)?|"
                 r"every (topic|session)|all topics|no messages?)\b")


def rules(kind, title, details):
    text = f"{title}\n{details}"
    k = kind if kind in KINDS else ("bug" if re.search(r"(?i)\b(error|fail|broken|bug|stuck|not)\b", text)
                                    else "improvement")
    prio = "P1" if k == "bug" and _P1.search(text) else ("P2" if k == "bug" else "P3")
    target = "support" if k == "bug" else "cto"
    return {"kind": k, "priority": prio, "target": target, "by": "rules"}


def jev(kind, title, details, timeout=8):
    key = _key()
    if not key:
        return None
    prompt = (
        "Classify this report about an agent platform (Telegram relay, Claude/Codex sessions, "
        "inter-session messaging). Answer with JSON only: "
        '{"kind": "bug|improvement|feature", "priority": "P1|P2|P3"}. '
        "P1 = platform down, messages lost or a topic dead; P2 = a bug with a workaround; "
        "P3 = everything else.\n\n"
        f"Reporter's kind: {kind}\nTitle: {title}\nDetails: {details[:1500]}")
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0}).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json",
                                             "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)["choices"][0]["message"]["content"]
        d = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
        k = d.get("kind") if d.get("kind") in KINDS else None
        p = d.get("priority") if d.get("priority") in PRIOS else None
        if not (k and p):
            return None
        return {"kind": k, "priority": p, "target": "support" if k == "bug" else "cto", "by": "jev"}
    except Exception:
        return None


def triage(kind, title, details):
    """Rules are a floor: Jev may raise the priority, never lower it. Otherwise a
    model reply of "P3" would silently override the rule that marks "relay down /
    every topic / messages lost" as P1 and suppress the alert (finding from the
    2026-10-01 survey of jev-gate, which applies the same "only tighten" rule)."""
    r = rules(kind, title, details)
    j = jev(kind, title, details)
    if not j:
        return r
    prio = min(r["priority"], j["priority"])          # "P1" < "P2" < "P3"
    k = "bug" if "bug" in (r["kind"], j["kind"]) and prio != "P3" else j["kind"]
    return {"kind": k, "priority": prio, "target": "support" if k == "bug" else "cto",
            "by": "jev+rules" if prio == r["priority"] != j["priority"] else "jev"}
