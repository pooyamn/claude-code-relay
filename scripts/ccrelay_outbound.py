#!/usr/bin/env python3
"""Read-only target outbound preparation, not a live sender or activation path.

No credentials, network, state creation, installs or service changes. Trusted
producer bridges/exclusive send ownership and real Khadang receipts must pass
acceptance before a later reviewed artifact exposes effectful startup.
"""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_core.identity import Denied, exact, strict_json
from relay_core.telegram_outbound import OutboundPolicy, LANES, METHODS


SEND_OWNER_ROOT = "/var/lib/ccrelay-sendowners"  # one host-wide registry, not per-config


def configuration(raw):
    exact(raw, {"schema", "enabled", "test_bot", "policy_path", "state_dir", "asset_dir", "source_grant_dir"})
    if raw["schema"] != "ccrelay.telegram_outbound_config.v2" or raw["enabled"] is not False or raw["test_bot"] != "khadang":
        raise Denied("only disabled Khadang preparation is supported; no live activation path")
    for key in ("policy_path", "state_dir", "asset_dir", "source_grant_dir"):
        path = raw[key]
        if type(path) is not str or not path.startswith("/") or ".." in path.split("/") or "\x00" in path:
            raise Denied("explicit protected target path required")
    if len({raw["state_dir"], raw["asset_dir"], raw["source_grant_dir"]}) != 3:
        raise Denied("distinct state, source grant and immutable asset directories required")
    return raw


def plan():
    folder = Path(__file__).resolve().parents[1] / "deploy" / "wsl" / "identities"
    cfg = configuration(strict_json((folder / "outbound-config.json.example").read_bytes()))
    policy = OutboundPolicy(strict_json((folder / "outbound-policy.json.example").read_bytes()))
    return {"schema": "ccrelay.telegram_outbound_plan.v1", "mode": "read-only-examples", "enabled": False,
            "test_bot": cfg["test_bot"], "identity_and_timing_are_placeholders": True,
            "network_calls": False, "state_changes": False, "policy_digest": policy.digest,
            "send_owner_registry": SEND_OWNER_ROOT, "priority_lanes": LANES, "method_ceiling": sorted(METHODS),
            "source_grant_directory": cfg["source_grant_dir"], "dispatch_contract": "ccrelay.guarded_telegram_request.v1",
            "restore_components": ["consistent outbound SQLite snapshot", "sealed response bodies and attempt envelopes",
                                  "immutable assets and original names/MIME metadata", "pinned policy/adapter artifact",
                                  "trusted watcher stream mappings and externally reconciled offsets",
                                  "consistent source grant snapshot and complete revocation/renewal history"],
            "pending": ["target WSL private owner/lock/filesystem durability", "exclusive verified Khadang transport and UI receipts",
                        "authenticated producer and split-UID current source/company/root grant wiring", "real owner-prompt acceptance",
                        "all live sender/watcher paths under one owner",
                        "pinned repair rejection characterization and protected runtime authorizer", "owner-authorized canary and deployment"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(plan(), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (Denied, OSError, ValueError):
        print("outbound preparation rejected; inspect protected examples", file=sys.stderr)
        raise SystemExit(64)
