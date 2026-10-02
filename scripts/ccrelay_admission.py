#!/usr/bin/env python3
"""Read-only shared admission plan; no state, source probe or model execution."""
import argparse
import json
from pathlib import Path, PurePosixPath
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_core.identity import Denied, exact, integer, strict_json
from relay_core.model_admission import SCHEMA
from relay_core.capacity_journal import SCHEMA as CAPACITY_SCHEMA
from relay_core.model_dispatch import SCHEMA as DISPATCH_SCHEMA
from relay_core.quota_estimates import SCHEMA as ESTIMATE_SCHEMA


def configuration(raw):
    exact(raw, {"schema", "enabled", "automatic_turns_enabled", "scope", "broker_policy_path", "work_state_dir", "minimum_gap_ms", "quota_max_age_ms", "activity_max_age_ms"})
    if raw["schema"] != "ccrelay.admission_config.v1" or raw["enabled"] is not False or raw["automatic_turns_enabled"] is not False or raw["scope"] != "platform-owner-only":
        raise Denied("only disabled single-owner admission preparation is supported")
    for key in ("broker_policy_path", "work_state_dir"):
        value = raw[key]
        if type(value) is not str or not value.startswith("/") or ".." in value.split("/") or "\x00" in value or "\\" in value or value == "/" or str(PurePosixPath(value)) != value:
            raise Denied("explicit canonical protected path required")
    for key in ("minimum_gap_ms", "quota_max_age_ms", "activity_max_age_ms"):
        if raw[key] is not None:
            integer(raw[key])
    return raw


def plan():
    path = Path(__file__).resolve().parents[1] / "deploy/wsl/identities/admission-config.json.example"
    cfg = configuration(strict_json(path.read_bytes()))
    return {"schema": "ccrelay.admission_plan.v1", "component_schema": SCHEMA, "mode": "read-only-examples", "scope": cfg["scope"],
            "enabled": False, "automatic_turns_enabled": False, "state_changes": False, "native_calls": False, "quota_calls": False,
            "active_cap": 3, "owner_reserve_percent": 10, "work_state_dir": cfg["work_state_dir"],
            "pacing_values_configured": all(cfg[key] is not None for key in ("minimum_gap_ms", "quota_max_age_ms", "activity_max_age_ms")),
            "all_source_fence_available": False, "quota_adapter_available": False, "source_verifier_available": False, "stop_verifier_available": False,
            "capacity_journal_schema": CAPACITY_SCHEMA, "capacity_retry_activated": False, "capacity_verifier_available": False,
            "diagnostic_admission_activated": False,
            "dispatch_schema": DISPATCH_SCHEMA, "owner_priority_activated": False, "dispatch_policy_values_configured": False,
            "quota_estimate_schema": ESTIMATE_SCHEMA, "quota_estimates_activated": False,
            "estimate_policy_values_configured": False, "usage_bound_verifier_available": False,
            "pending": ["protected owner/company source grants and task/native controller integration",
                        "all-source native-app/goal pre-turn fence and independently observed tool quiescence",
                        "pinned account/model/window quota provenance and explicit pacing/estimate policy",
                        "protected dispatch producer/loop and explicit pending-offer bound, protected usage ceiling/estimate policy and passive status bridge",
                        "protected diagnostic producers/results and real capacity/steering/continuation/native-retry adapters",
                        "joined encrypted recovery, distinct-UID WSL and real provider acceptance"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(plan(), sort_keys=True))
