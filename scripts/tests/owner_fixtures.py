"""Synthetic owner/bootstrap fixtures. No credentials or Bot API calls."""
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
from unittest import mock

from relay_core.contracts import create, fingerprint, intent_payload
from relay_core.identity import Peer, Policy
from relay_core.owner_gate import OwnerLedger, OwnerPolicy
from relay_core.artifacts import ArtifactStore, BootstrapDeployer, DeploymentPolicy
from relay_core import screening


NOW = datetime(2026, 10, 2, 4, 0, tzinfo=timezone.utc)
EXPIRY = "2026-10-02T05:00:00Z"
ROOT = Peer(1, 0, 0)
INGRESS = Peer(10, 130, 132)
WORKER = Peer(11, 101, 121)
GATE = Peer(12, os.geteuid(), 132)


def broker_policy():
    role = create("role", id="builder", uid=101, enabled=True, capabilities=["message"], policy_digest=fingerprint({"fixture": 1}))
    return Policy({"schema": "ccrelay.broker_policy.v1", "broker_uid": 120, "client_gid": 121,
                   "roles": [role.to_dict()], "controllers": [{"uid": 0, "roles": ["builder"]}]})


def owner_fields():
    return {"schema": "ccrelay.owner_policy.v1", "enabled": True, "gate_uid": os.geteuid(), "ingress_uid": 130,
            "owner_id": 1001, "bot_id": 1002, "chat_id": -1003, "thread_id": 4}


def deployment_fields():
    return {"schema": "ccrelay.deployment_policy.v1", "bootstrap_enabled": True, "routine_enabled": False,
            "components": [{"id": "router", "credentialed": True, "routine_prefixes": ["render/"]},
                           {"id": "presentation", "credentialed": False, "routine_prefixes": ["render/"]}]}


def action(parameters=None, id="action-1", kind="fixture_external_action"):
    fields = {"id": id, "root_task_id": "root-1", "requested_by_session_id": "builder.fixture",
              "action_kind": kind, "parameters": {"test": "exact parameters"} if parameters is None else parameters}
    return create("external_action", **fields, state="stored", intent_digest=fingerprint(intent_payload("external_action", fields)),
                  attempt_id=None, receipt_id=None, outcome_evidence_id=None, authorization_id=None)


def receipt(message_id=5):
    return {"bot_id": 1002, "chat_id": -1003, "thread_id": 4, "message_id": message_id}


def update(data, *, update_id=6, callback_id="callback-7", message_id=5):
    return {"update_id": update_id, "callback_query": {"id": callback_id, "chat_instance": "fixture-chat-instance",
            "from": {"id": 1001, "is_bot": False, "first_name": "Synthetic Owner"}, "data": data,
            "message": {"message_id": message_id, "message_thread_id": 4, "date": 1790913600,
                        "from": {"id": 1002, "is_bot": True}, "chat": {"id": -1003, "type": "supergroup"}}}}


def source(body=b"fixture source", path="render/main.py"):
    return [{"path": path, "content": body, "executable": False}]


def screen_report(store, artifact_digest, verdict="clear", *, known_secrets=()):
    manifest, contents = store.verify(artifact_digest)
    masked = screening.payload(manifest, contents, known_secrets=known_secrets)
    return {"schema": "ccrelay.screening_report.v1", "artifact_digest": artifact_digest,
            "payload_digest": fingerprint(masked), "verdict": verdict, "evidence_id": "fixture-screen-1",
            "model": "fixture-jev-NOT-A-MODEL-CALL", "coverage_complete": not masked["incomplete_paths"]}


def open_ledger(folder, *, clock=lambda: NOW, fields=None):
    # Same explanation as PR 2 SQLite tests: Mac scratch has writable shared
    # ancestors. Only that path observation is mocked, never production logic.
    with mock.patch("relay_core.owner_gate.protected_path", side_effect=lambda path, **_: Path(path)):
        return OwnerLedger(folder, OwnerPolicy(owner_fields() if fields is None else fields, broker_policy()), clock=clock)


def open_store(folder):
    with mock.patch("relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path)):
        return ArtifactStore(folder, owner_uid=os.geteuid())


def writable_fixture_tree(folder):
    # Retain sealed modes throughout tests, relax ONLY for scratch teardown.
    root = Path(folder)
    for path in [root, *root.rglob("*")]:
        if path.is_dir() and not path.is_symlink():
            os.chmod(path, stat.S_IMODE(path.stat().st_mode) | 0o700)


def approved(ledger, intent, approval_id="approval-1", *, update_id=6, message_id=5):
    prompt = ledger.enroll(ROOT, intent.to_dict(), approval_id, EXPIRY)
    ledger.bind_prompt(INGRESS, intent.id, receipt(message_id))
    ledger.decide(INGRESS, update(prompt["approve_data"], update_id=update_id,
                                callback_id="callback-" + str(update_id), message_id=message_id))
    return prompt
