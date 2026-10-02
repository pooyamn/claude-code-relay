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
from relay_core.native_setup import SCHEMA as SETUP_SCHEMA
from relay_core.native_resume import ADAPTER as RESUME_ADAPTER
from relay_core.native_rpc import TRANSPORT as RPC_TRANSPORT
from relay_core.native_ws import TRANSPORT as WS_TRANSPORT
from relay_core.native_peer import SCHEMA as PEER_SCHEMA
from relay_core.native_image import SCHEMA as IMAGE_SCHEMA
from relay_core.native_settings import SCHEMA as SETTINGS_SCHEMA


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
            "setup_journal_schema": SETUP_SCHEMA, "setup_helper_activated": False,
            "resume_adapter": RESUME_ADAPTER, "resume_adapter_activated": False,
            "rpc_transport": RPC_TRANSPORT, "rpc_transport_activated": False,
            "websocket_transport": WS_TRANSPORT, "websocket_transport_activated": False,
            "kernel_peer_schema": PEER_SCHEMA, "kernel_peer_activated": False,
            "executable_schema": IMAGE_SCHEMA, "executable_check_activated": False,
            "resume_permissions_schema": SETTINGS_SCHEMA, "resume_permissions_check_activated": False,
            "role_profiles_not_active_sessions": sorted(policy.roles), "admission_available": False,
            "pending": ["pinned protected Codex and Claude observation/transports and exact-ID resume",
                        "target UID/cgroup/process-generation and role-isolated subscription topology",
                        "protected dispatch/writer fences and target acceptance of worker-UID worktree setup",
                        "protected bundle export/dispatch, target setup acceptance and native loading proof",
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
