#!/usr/bin/env python3
"""Read-only root/work preparation; never admit, claim or release real work."""
import argparse
import json
from pathlib import Path, PurePosixPath
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_core.identity import Denied, Policy, exact, strict_json
from relay_core.work_ownership import SCHEMA, WATCHDOG_HANDOFFS


def configuration(raw):
    exact(raw, {"schema", "enabled", "automatic_turns_enabled", "scope", "broker_policy_path", "state_dir"})
    if raw["schema"] != "ccrelay.work_config.v1" or raw["enabled"] is not False or raw["automatic_turns_enabled"] is not False or raw["scope"] != "platform-owner-only":
        raise Denied("only disabled single-owner work preparation is supported")
    for key in ("broker_policy_path", "state_dir"):
        value = raw[key]
        if type(value) is not str or not value.startswith("/") or ".." in value.split("/") or "\x00" in value or "\\" in value or \
                value == "/" or str(PurePosixPath(value)) != value:
            raise Denied("explicit canonical protected path required")
    return raw


def plan():
    folder = Path(__file__).resolve().parents[1] / "deploy/wsl/identities"
    cfg = configuration(strict_json((folder / "work-config.json.example").read_bytes()))
    policy = Policy(strict_json((folder / "broker-policy.json.example").read_bytes()))
    return {"schema": "ccrelay.work_plan.v1", "mode": "read-only-examples", "component_schema": SCHEMA,
            "enabled": False, "automatic_turns_enabled": False, "state_changes": False, "native_calls": False,
            "state_dir": cfg["state_dir"], "scope": cfg["scope"], "identity_values_are_examples": True,
            "protected_owner_uid": policy.broker_uid, "policy_digest": policy.digest,
            "initial_watchdog_completed_handoffs": WATCHDOG_HANDOFFS, "task_limits_configured": False,
            "evidence_verifier_available": False, "all_writer_verifier_available": False, "admission_available": False,
            "pending": ["trusted owner/root creation and inherited-root controller integration",
                        "real criteria/progress/completed-result evidence and fingerprinted diagnosis",
                        "protected resource identity/alias inventory and all-source writer/descendant fences",
                        "PR 9 activity/pacing admission and broker/publication fence checks",
                        "company boundaries, joined encrypted restore and distinct-UID WSL acceptance"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(plan(), sort_keys=True))
