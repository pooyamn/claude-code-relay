#!/usr/bin/env python3
"""Read-only native registry preparation; never launch/resume/control a session."""
import argparse
import json
from pathlib import Path, PurePosixPath
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_core.identity import Denied, Policy, exact, strict_json
from relay_core.native_sessions import SCHEMA
from relay_core.native_launch import PACKAGE_SCHEMA
from relay_core.native_workspace import SCHEMA as WORKSPACE_SCHEMA


def configuration(raw):
    exact(raw, {"schema", "enabled", "automatic_turns_enabled", "scope", "broker_policy_path", "state_dir"})
    if raw["schema"] != "ccrelay.native_registry_config.v1" or raw["enabled"] is not False or \
            raw["automatic_turns_enabled"] is not False or raw["scope"] != "platform-owner-only":
        raise Denied("only disabled single-owner native preparation is supported")
    for key in ("broker_policy_path", "state_dir"):
        value = raw[key]
        if type(value) is not str or not value.startswith("/") or ".." in value.split("/") or \
                "\x00" in value or "\\" in value or value == "/" or str(PurePosixPath(value)) != value:
            raise Denied("explicit canonical protected target path required")
    return raw


def plan():
    folder = Path(__file__).resolve().parents[1] / "deploy/wsl/identities"
    cfg = configuration(strict_json((folder / "native-config.json.example").read_bytes()))
    policy = Policy(strict_json((folder / "broker-policy.json.example").read_bytes()))
    return {"schema": "ccrelay.native_registry_plan.v1", "mode": "read-only-examples", "enabled": False,
            "automatic_turns_enabled": False, "native_calls": False, "state_changes": False,
            "identity_values_are_examples": True, "state_dir": cfg["state_dir"], "protected_owner_uid": policy.broker_uid,
            "broker_policy_digest": policy.digest, "registry_schema": SCHEMA, "scope": cfg["scope"],
            "launch_package_schema": PACKAGE_SCHEMA, "launch_package_activated": False, "resource_limits_enforced": False,
            "workspace_journal_schema": WORKSPACE_SCHEMA, "workspace_helper_activated": False,
            "role_profiles_not_active_sessions": sorted(policy.roles), "admission_available": False,
            "pending": ["pinned protected Codex and Claude observation/transports and exact-ID resume",
                        "target UID/cgroup/process-generation and role-isolated subscription topology",
                        "protected dispatch/writer fences and target acceptance of worker-UID worktree setup",
                        "applying verified launch/instruction/skill bundles and native loading proof",
                        "measured target resource profiles and independently observed enforcement",
                        "independent native control receipts and actual app visibility",
                        "normalized native capacity/auth/quota/unknown outcomes",
                        "PR 8 root ownership and PR 9 all-source pre-turn admission",
                        "authenticated current company/context and PR 6 producer integration",
                        "joined encrypted component recovery and clean-machine acceptance"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(plan(), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (Denied, OSError, ValueError):
        print("native preparation rejected; inspect protected examples", file=sys.stderr)
        raise SystemExit(64)
