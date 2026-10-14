"""Separate private profiles; no upstream fetches and no changes to Home VPN.

Optional per-entry Home transport overrides are prepared/tested source only.
The October14 live helper has not been upgraded to this candidate; repeated
network validation is required before any override is installed.
"""
import copy
import hmac
import json
import re
import urllib.parse

HIDE = " \u00a7hide\u00a7"


def profile_for(directory, path):
    token_path = directory / "ava98-profile-token.txt"
    if not token_path.is_file():
        return None
    token = token_path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    path = urllib.parse.urlsplit(path).path
    for name in ("ava98.json", "ava98-home.json"):
        if hmac.compare_digest(path, "/sub/" + token + "/" + name):
            return name
    return None


def normalize(source):
    nodes = []
    for original in source["outbounds"]:
        if original.get("server") == "1":
            continue
        node = copy.deepcopy(original)
        if node["type"] not in ("vless", "shadowsocks"):
            raise ValueError("Unsupported AVA98 node type")
        tls = node.get("tls", {})
        if isinstance(tls.get("alpn"), str):
            tls["alpn"] = [tls["alpn"]]
        if tls.get("reality", {}).get("enabled"):
            tls.pop("insecure", None)
        transport = node.get("transport")
        if transport and transport["type"] == "ws":
            transport.setdefault("path", "/")
            transport["headers"] = {"Host": transport["headers"].get("Host", transport["headers"].get("host"))}
        nodes.append(node)
    if len(nodes) != 9 or len({n["tag"] for n in nodes}) != 9:
        raise ValueError("Expected nine distinct AVA98 nodes")
    return nodes


def groups(title, tags):
    auto = title + " Auto"
    return [
        {"type": "selector", "tag": title, "outbounds": [auto] + tags, "default": auto},
        {"type": "urltest", "tag": auto, "outbounds": tags,
         "url": "https://www.gstatic.com/generate_204", "interval": "3m", "tolerance": 50},
    ]


def build_profile(directory, profile, home_builder):
    nodes = normalize(json.loads((directory / "ava98-source.json").read_text(encoding="utf-8")))
    extras_path = directory / "free-tested-extras.json"
    if extras_path.exists():
        extras = json.loads(extras_path.read_text(encoding="utf-8"))["outbounds"]
        if len(extras) != 5:
            raise ValueError("Expected five measured additional nodes")
        for node in extras:
            tls = node.get("tls", {})
            if (node.get("type") not in ("vless", "trojan") or
                    not node.get("server") or not isinstance(node.get("server_port"), int) or
                    not 1 <= node["server_port"] <= 65535 or
                    tls.get("enabled") is not True or tls.get("insecure") or
                    "detour" in node or "hide" in node.get("tag", "") or
                    not node.get("tag", "").startswith("Free tested ")):
                raise ValueError("Invalid measured additional node")
        nodes += copy.deepcopy(extras)
        if len({n["tag"] for n in nodes}) != len(nodes):
            raise ValueError("Duplicate profile node tags")
    if profile == "ava98.json":
        title = "AVA98"
        outbounds = groups(title, [n["tag"] for n in nodes]) + nodes
    elif profile == "ava98-home.json":
        title = "US Home via AVA98"
        home = home_builder()
        cloudflare = next(n for n in home["outbounds"] if n["tag"] == "Cloudflare - kk.fidior.com")
        overrides_path = directory / "ava98-home-overrides.json"
        overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
        if (not isinstance(overrides, dict) or any(
                key not in {node["tag"] for node in nodes if node["tag"].startswith("Free tested ")} or
                value not in ("Cloudflare", "Reality") for key, value in overrides.items())):
            raise ValueError("Invalid home transport override")
        reality = None
        if "Reality" in overrides.values():
            candidates = [node for node in home["outbounds"]
                          if node.get("type") == "vless" and node.get("tls", {}).get("reality", {}).get("enabled")]
            if len(candidates) != 1:
                raise ValueError("Exactly one existing authenticated Home Reality endpoint required")
            reality = candidates[0]
        hidden, chains = [], []
        for node in nodes:
            entry = copy.deepcopy(node)
            entry["tag"] = "AVA98 entry - " + node["tag"] + HIDE
            hidden.append(entry)
            transport = overrides.get(node["tag"], "Cloudflare")
            chain = copy.deepcopy(reality if transport == "Reality" else cloudflare)
            chain["tag"] = "US Home via " + node["tag"] + " - " + transport
            chain["detour"] = entry["tag"]
            chains.append(chain)
        # Hiddify discards imported selectors and builds its own. Only complete
        # home-exit chains remain visible; AVA98 entry nodes are not selectable.
        # Export the plain Hiddify proxy-list form. Hiddify supplies its own
        # automatic selector; no imported groups or Vision routes are required.
        return {"outbounds": chains + hidden}
    else:
        raise ValueError("Unknown profile")
    return {"log": {"level": "warn"}, "outbounds": outbounds, "route": {"final": title}}
