"""Strict v1 persistence contracts, independent of providers and filesystem state.

Records describe claims; decoding a role, approval or observation DOES NOT
authenticate it. Only the protected broker/launcher may establish those facts.
Unknown/legacy schemas require an explicit migration, never a default profile.
This module deliberately has no I/O, environment, clock or provider discovery.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Mapping


class ContractError(ValueError):
    """Malformed state must not become runnable or privileged state."""


class UnsupportedSchema(ContractError):
    """Keep the original bytes; explicit upgrade or compatible reader required."""


class StaleRevision(ContractError):
    """The caller's snapshot no longer owns the mutation."""


VERSION = 1
MAX_RECORD_BYTES = 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[a-f0-9]{64}\Z")
_SCHEMA = re.compile(r"ccrelay\.([a-z_]+)\.v([0-9]+)\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

DELIVERY_STATES = frozenset({"stored", "delivering", "submitted", "confirmed", "unknown", "failed"})
STATES = {
    "root_task": frozenset({"open", "active", "held", "completed", "cancelled"}),
    "execution": frozenset({"queued", "starting", "running", "waiting", "quiescing", "stopped", "failed", "unknown"}),
    "message": DELIVERY_STATES,
    "external_action": DELIVERY_STATES,
    "approval": frozenset({"pending", "granted", "denied", "consumed", "revoked", "expired"}),
    "component_snapshot": frozenset({"complete", "incomplete", "absent"}),
}
DESIRED_STATES = frozenset({"running", "paused", "stopped"})
OBSERVED_STATES = frozenset({"unknown", "starting", "running", "paused", "stopped", "failed"})
CAPABILITIES = frozenset({
    "message", "propose_memory", "curate_memory", "report_issue", "publish",
    "review", "request_merge", "request_action", "request_deploy", "owner_approve",
})

# All persisted fields are explicit. Absence and null have different meanings.
FIELDS = {
    "role": {"uid", "enabled", "capabilities", "policy_digest"},
    "session": {"root_task_id", "role_id", "provider", "provider_session_id", "worktree",
                "desired_state", "observed_state", "observation_id", "ready",
                "runtime_digest", "tool_contract_digest", "permission_digest", "active_turn_id"},
    "root_task": {"owner_role_id", "acceptance_criteria", "policy_digest", "state", "limits", "usage",
                  "verified_evidence_ids"},
    "execution": {"root_task_id", "work_item_id", "session_id", "state", "fencing_token",
                  "process", "observation_id"},
    "message": {"root_task_id", "from_session_id", "to_session_id", "body", "mode", "expected_turn_id",
                "state", "intent_digest", "attempt_id", "receipt_id", "outcome_evidence_id"},
    "external_action": {"root_task_id", "requested_by_session_id", "action_kind", "parameters",
                        "state", "intent_digest", "attempt_id", "receipt_id", "outcome_evidence_id",
                        "authorization_id"},
    "approval": {"action_id", "action_digest", "owner_id", "state", "owner_auth_reference",
                 "decided_at", "expires_at", "consumed_attempt_id"},
    "component_snapshot": {"component", "component_schema", "captured_at", "state", "required",
                           "artifacts", "exclusions", "incomplete_reasons", "runtime_versions"},
}


def _object(value: Any, keys: set, label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise ContractError(f"{label}: expected exactly {sorted(keys)}")
    return value


def _text(value: Any, label: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value.strip()) or "\x00" in value:
        raise ContractError(f"{label}: expected {'possibly empty ' if empty else 'nonempty '}text")
    return value


def _id(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or not _ID.fullmatch(value):
        raise ContractError(f"{label}: invalid identifier")


def _provider_id(value: Any, label: str) -> None:
    if value is not None:
        _text(value, label)
        if _CONTROL.search(value) or len(value) > 512:
            raise ContractError(f"{label}: invalid provider identifier")


def _int(value: Any, label: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ContractError(f"{label}: expected integer >= {minimum}")


def _bool(value: Any, label: str) -> None:
    if type(value) is not bool:
        raise ContractError(f"{label}: expected boolean")


def _choice(value: Any, choices: frozenset, label: str) -> None:
    if type(value) is not str or value not in choices:
        raise ContractError(f"{label}: unsupported value")


def _digest(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise ContractError(f"{label}: expected sha256 digest")


def _time(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or not value.endswith("Z"):
        raise ContractError(f"{label}: expected UTC timestamp ending Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        if "T" not in value or parsed.utcoffset().total_seconds() != 0:
            raise ValueError
    except (ValueError, AttributeError):
        raise ContractError(f"{label}: invalid UTC timestamp") from None


def _list(value: Any, label: str, *, nonempty: bool = False, identifiers: bool = False) -> None:
    if type(value) is not list or (nonempty and not value):
        raise ContractError(f"{label}: expected {'nonempty ' if nonempty else ''}list")
    for entry in value:
        (_id if identifiers else _text)(entry, label)
    if len(set(value)) != len(value):
        raise ContractError(f"{label}: duplicate entries")


def _path(value: Any, label: str, *, absolute: bool) -> None:
    _text(value, label)
    p = PurePosixPath(value)
    if _CONTROL.search(value) or "\\" in value or ":" in value or ".." in p.parts:
        raise ContractError(f"{label}: unsafe path")
    if p.is_absolute() != absolute or str(p) != value or value in {".", "/"}:
        raise ContractError(f"{label}: expected normalized {'absolute' if absolute else 'relative'} path")


def _json(value: Any, depth: int = 0) -> None:
    if depth > 64:
        raise ContractError("JSON nesting exceeds contract limit")
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is list:
        for entry in value:
            _json(entry, depth + 1)
        return
    if type(value) is dict and all(type(k) is str for k in value):
        for entry in value.values():
            _json(entry, depth + 1)
        return
    # No float coercion: action amounts use integer minor units, and NaN/Inf
    # must not have ambiguous fingerprints across consumers.
    raise ContractError("parameters: expected JSON values without floating-point amounts")


def canonical_bytes(value: Any) -> bytes:
    _json(value)
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
    except (UnicodeEncodeError, RecursionError):
        raise ContractError("state is not bounded valid Unicode JSON") from None
    if len(encoded) > MAX_RECORD_BYTES:
        raise ContractError("state exceeds contract byte limit")
    return encoded


def fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def intent_payload(kind: str, fields: Mapping) -> dict:
    keys = ({"id", "root_task_id", "from_session_id", "to_session_id", "body", "mode", "expected_turn_id"}
            if kind == "message" else
            {"id", "root_task_id", "requested_by_session_id", "action_kind", "parameters"})
    if kind not in {"message", "external_action"}:
        raise ContractError("intent digest applies only to messages and external actions")
    return {k: fields[k] for k in sorted(keys)}


def _delivery(data: dict, kind: str) -> None:
    _choice(data["state"], DELIVERY_STATES, "state")
    for field in ("attempt_id", "receipt_id", "outcome_evidence_id"):
        _id(data[field], field, nullable=True)
    _digest(data["intent_digest"], "intent_digest")
    if fingerprint(intent_payload(kind, data)) != data["intent_digest"]:
        raise ContractError("intent_digest: parameters changed")
    if data["state"] in {"delivering", "submitted", "unknown", "confirmed"} and data["attempt_id"] is None:
        raise ContractError("delivery state requires attempt_id")
    if data["state"] == "confirmed" and data["receipt_id"] is None:
        raise ContractError("confirmation requires receipt_id")
    if data["state"] != "confirmed" and data["receipt_id"] is not None:
        raise ContractError("receipt_id belongs only to confirmed state")
    if data["state"] == "failed" and data["outcome_evidence_id"] is None:
        raise ContractError("definite failure requires negative outcome evidence")
    if data["state"] == "stored" and data["attempt_id"] is not None:
        raise ContractError("stored intent has no active attempt")


def _validate(kind: str, data: dict) -> None:
    _object(data, FIELDS[kind] | {"schema", "id", "revision"}, kind)
    _id(data["id"], "id")
    _int(data["revision"], "revision")
    for field in ("root_task_id", "role_id", "owner_role_id", "session_id", "work_item_id",
                  "from_session_id", "to_session_id", "requested_by_session_id", "action_id"):
        if field in data:
            _id(data[field], field)
    if "state" in data:
        _choice(data["state"], STATES[kind], "state")
    if kind == "role":
        _int(data["uid"], "uid", 1)
        _bool(data["enabled"], "enabled")
        _list(data["capabilities"], "capabilities")
        if not set(data["capabilities"]) <= CAPABILITIES:
            raise ContractError("capabilities: unknown privilege")
        _digest(data["policy_digest"], "policy_digest")
    elif kind == "session":
        _choice(data["provider"], frozenset({"claude", "codex"}), "provider")
        _provider_id(data["provider_session_id"], "provider_session_id")
        _provider_id(data["active_turn_id"], "active_turn_id")
        _path(data["worktree"], "worktree", absolute=True)
        _choice(data["desired_state"], DESIRED_STATES, "desired_state")
        _choice(data["observed_state"], OBSERVED_STATES, "observed_state")
        _id(data["observation_id"], "observation_id", nullable=True)
        _bool(data["ready"], "ready")
        for field in ("runtime_digest", "tool_contract_digest", "permission_digest"):
            _digest(data[field], field, nullable=True)
        if data["observed_state"] != "unknown" and data["observation_id"] is None:
            raise ContractError("observed state requires observation_id")
        if data["ready"] and (data["observed_state"] != "running" or
                              any(data[f] is None for f in ("provider_session_id", "runtime_digest",
                                                           "tool_contract_digest", "permission_digest"))):
            raise ContractError("ready session requires observed running and verified contract bindings")
        # Retain the last recorded active turn during unknown recovery so the
        # adapter can reconcile it. This is not permission to steer that turn.
        if data["active_turn_id"] is not None and data["provider_session_id"] is None:
            raise ContractError("recorded active turn requires exact provider session binding")
    elif kind == "root_task":
        _list(data["acceptance_criteria"], "acceptance_criteria", nonempty=True)
        _digest(data["policy_digest"], "policy_digest")
        limits = _object(data["limits"], {"turns", "delegations", "diagnoses", "checkpoint_deadline"}, "limits")
        usage = _object(data["usage"], {"turns", "delegations", "diagnoses", "no_progress_handoffs"}, "usage")
        for field in ("turns", "delegations", "diagnoses"):
            _int(limits[field], "limits." + field, 1)
        if limits["diagnoses"] > limits["turns"]:
            raise ContractError("diagnostic allocation exceeds turn budget")
        _time(limits["checkpoint_deadline"], "checkpoint_deadline")
        for field in usage:
            _int(usage[field], "usage." + field)
        _list(data["verified_evidence_ids"], "verified_evidence_ids", identifiers=True)
        if data["state"] == "completed" and not data["verified_evidence_ids"]:
            raise ContractError("completion requires accepted evidence references")
    elif kind == "execution":
        _int(data["fencing_token"], "fencing_token", 1)
        _id(data["observation_id"], "observation_id", nullable=True)
        if data["process"] is not None:
            p = _object(data["process"], {"pid", "start_identity", "unit"}, "process")
            _int(p["pid"], "pid", 1)
            _text(p["start_identity"], "start_identity")
            _text(p["unit"], "unit")
        if data["state"] in {"running", "quiescing", "stopped"} and data["observation_id"] is None:
            raise ContractError("observed execution state requires evidence")
        if data["state"] in {"running", "quiescing"} and data["process"] is None:
            raise ContractError("live execution requires process start identity and supervision unit")
    elif kind == "message":
        _text(data["body"], "body")
        _choice(data["mode"], frozenset({"steer", "start", "follow_up"}), "mode")
        _provider_id(data["expected_turn_id"], "expected_turn_id")
        if (data["mode"] == "steer") != (data["expected_turn_id"] is not None):
            raise ContractError("expected_turn_id is required only for steer")
        _delivery(data, kind)
    elif kind == "external_action":
        _id(data["action_kind"], "action_kind")
        if type(data["parameters"]) is not dict:
            raise ContractError("parameters: expected object")
        _json(data["parameters"])
        _id(data["authorization_id"], "authorization_id", nullable=True)
        _delivery(data, kind)
        if data["state"] in {"delivering", "submitted", "unknown", "confirmed"} and data["authorization_id"] is None:
            raise ContractError("external attempt requires broker authorization reference")
    elif kind == "approval":
        _digest(data["action_digest"], "action_digest")
        _text(data["owner_id"], "owner_id")
        _id(data["owner_auth_reference"], "owner_auth_reference", nullable=True)
        _id(data["consumed_attempt_id"], "consumed_attempt_id", nullable=True)
        _time(data["expires_at"], "expires_at")
        _time(data["decided_at"], "decided_at", nullable=True)
        if data["state"] in {"granted", "denied", "consumed", "revoked"} and (
                data["owner_auth_reference"] is None or data["decided_at"] is None):
            raise ContractError("approval decision requires authenticated owner reference and time")
        if data["state"] in {"granted", "consumed"}:
            decision = datetime.fromisoformat(data["decided_at"][:-1] + "+00:00")
            expiry = datetime.fromisoformat(data["expires_at"][:-1] + "+00:00")
            if decision >= expiry:
                raise ContractError("approval was not granted before its expiry")
        if (data["state"] == "consumed") != (data["consumed_attempt_id"] is not None):
            raise ContractError("consumed approval requires its exact attempt binding")
        if data["state"] == "pending" and (data["decided_at"] is not None or data["owner_auth_reference"] is not None):
            raise ContractError("pending approval cannot claim an owner decision")
    elif kind == "component_snapshot":
        _id(data["component"], "component")
        _text(data["component_schema"], "component_schema")
        _time(data["captured_at"], "captured_at")
        _bool(data["required"], "required")
        _list(data["exclusions"], "exclusions")
        _list(data["incomplete_reasons"], "incomplete_reasons")
        if type(data["runtime_versions"]) is not dict:
            raise ContractError("runtime_versions: expected object")
        for key, value in data["runtime_versions"].items():
            _id(key, "runtime name")
            _text(value, "runtime version")
        if type(data["artifacts"]) is not list:
            raise ContractError("artifacts: expected list")
        paths = []
        for artifact in data["artifacts"]:
            _object(artifact, {"path", "digest", "size_bytes"}, "artifact")
            _path(artifact["path"], "artifact.path", absolute=False)
            _digest(artifact["digest"], "artifact.digest")
            _int(artifact["size_bytes"], "size_bytes")
            paths.append(artifact["path"])
        for path in data["exclusions"]:
            _path(path, "exclusion", absolute=False)
        if len(set(paths)) != len(paths) or set(paths) & set(data["exclusions"]):
            raise ContractError("artifacts: duplicate or excluded capture path")
        if data["state"] == "complete" and (not paths or data["incomplete_reasons"]):
            raise ContractError("complete snapshot requires artifacts and no incomplete reasons")
        if data["state"] == "incomplete" and not data["incomplete_reasons"]:
            raise ContractError("incomplete snapshot requires reasons")
        if data["state"] == "absent" and (data["required"] or paths):
            raise ContractError("required or captured component cannot be absent")


def _freeze(value: Any, depth: int = 0) -> Any:
    if depth > 64:
        raise ContractError("state nesting exceeds contract limit")
    if type(value) is dict:
        return MappingProxyType({k: _freeze(v, depth + 1) for k, v in value.items()})
    if type(value) is list:
        return tuple(_freeze(v, depth + 1) for v in value)
    return value


def _thaw(value: Any, depth: int = 0) -> Any:
    if depth > 64:
        raise ContractError("state nesting exceeds contract limit")
    if isinstance(value, Mapping):
        return {k: _thaw(v, depth + 1) for k, v in value.items()}
    if type(value) is tuple:
        return [_thaw(v, depth + 1) for v in value]
    if type(value) is list:
        return [_thaw(v, depth + 1) for v in value]
    return value


@dataclass(frozen=True)
class Record:
    kind: str
    fields: Mapping

    def __post_init__(self) -> None:
        # Constructor has the same validation boundary as persisted decoding.
        raw = _thaw(self.fields)
        if type(raw) is not dict:
            raise ContractError("record fields must be an object")
        if type(self.kind) is not str or self.kind not in FIELDS or raw.get("schema") != f"ccrelay.{self.kind}.v{VERSION}":
            raise UnsupportedSchema("unsupported record kind/version")
        canonical_bytes(raw)
        _validate(self.kind, raw)
        object.__setattr__(self, "fields", _freeze(raw))

    @property
    def id(self) -> str:
        return self.fields["id"]

    @property
    def revision(self) -> int:
        return self.fields["revision"]

    def to_dict(self) -> dict:
        return _thaw(self.fields)

    def encode(self) -> bytes:
        return canonical_bytes(self.to_dict())


def _unique_pairs(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate JSON key")
        result[key] = value
    return result


def decode(raw: Any) -> Record:
    if isinstance(raw, (bytes, str)):
        if len(raw) > MAX_RECORD_BYTES:
            raise ContractError("state exceeds contract byte limit")
        try:
            raw = json.loads(raw, object_pairs_hook=_unique_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ContractError("nonfinite JSON number")))
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            raise ContractError("invalid JSON state") from None
    if type(raw) is not dict:
        raise ContractError("state: expected object")
    schema = raw.get("schema")
    match = _SCHEMA.fullmatch(schema) if type(schema) is str else None
    if not match or match[1] not in FIELDS or match[2] != str(VERSION):
        raise UnsupportedSchema("unknown/legacy schema; preserve bytes for explicit migration")
    return Record(match[1], raw)


def create(kind: str, *, id: str, revision: int = 0, **fields: Any) -> Record:
    if "schema" in fields:
        raise ContractError("create cannot silently replace a caller-supplied schema")
    raw = dict(fields, schema=f"ccrelay.{kind}.v{VERSION}", id=id, revision=revision)
    return decode(raw)


_DELIVERY_EDGES = {
    "stored": {"delivering", "failed"}, "delivering": {"submitted", "confirmed", "unknown", "failed"},
    "submitted": {"confirmed", "unknown"}, "unknown": {"confirmed", "failed"},
    "confirmed": set(), "failed": set(),
}
_EDGES = {
    "root_task": {"open": {"active", "held", "cancelled"}, "active": {"held", "completed", "cancelled"},
                  "held": {"active", "cancelled"}, "completed": set(), "cancelled": set()},
    "execution": {"queued": {"starting", "failed", "unknown"}, "starting": {"running", "failed", "unknown"},
                  "running": {"waiting", "quiescing", "failed", "unknown"},
                  "waiting": {"running", "quiescing", "failed", "unknown"},
                  "quiescing": {"stopped", "failed", "unknown"}, "unknown": {"running", "stopped", "failed"},
                  "stopped": set(), "failed": set()},
    "message": _DELIVERY_EDGES, "external_action": _DELIVERY_EDGES,
    "approval": {"pending": {"granted", "denied", "expired"}, "granted": {"consumed", "revoked", "expired"},
                 "denied": set(), "consumed": set(), "revoked": set(), "expired": set()},
}


def transition(record: Record, target: str, *, expected_revision: int, **changes: Any) -> Record:
    """Pure transition only. Persist with atomic CAS; never use as authentication.

    Failed intents are terminal: a policy-authorized retry needs a new intent
    linked to retained negative evidence, not resetting the old action's state.
    Observed session changes belong to launcher observations, not this API.
    """
    _int(expected_revision, "expected_revision")
    if expected_revision != record.revision:
        raise StaleRevision("snapshot revision changed")
    if record.kind not in _EDGES:
        raise ContractError("this record requires an explicit broker/observation mutation")
    raw = record.to_dict()
    current = raw["state"]
    _choice(target, STATES[record.kind], "target state")
    protected = {"schema", "id", "revision", "state", "root_task_id", "session_id", "work_item_id",
                 "owner_role_id", "policy_digest", "limits", "acceptance_criteria", "fencing_token", "owner_id", "action_id",
                 "action_digest", "requested_by_session_id", "action_kind", "parameters", "intent_digest",
                 "from_session_id", "to_session_id", "body", "mode", "expected_turn_id", "expires_at"}
    if protected & set(changes):
        raise ContractError("transition cannot rewrite immutable identity/authority/intent")
    for field in ("authorization_id", "owner_auth_reference", "decided_at", "process"):
        if field in changes and raw.get(field) is not None and raw[field] != changes[field]:
            raise ContractError(f"transition cannot rewrite established {field}")
    if record.kind == "root_task":
        evidence = changes.get("verified_evidence_ids", raw["verified_evidence_ids"])
        _list(evidence, "verified_evidence_ids", identifiers=True)
        if not set(raw["verified_evidence_ids"]) <= set(evidence):
            raise ContractError("verified evidence history cannot be removed")
        if "usage" in changes:
            usage = _object(changes["usage"], set(raw["usage"]), "usage")
            for field in ("turns", "delegations", "diagnoses"):
                _int(usage[field], "usage." + field)
                if usage[field] < raw["usage"][field]:
                    raise ContractError("task counters cannot reset")
            _int(usage["no_progress_handoffs"], "usage.no_progress_handoffs")
            if usage["no_progress_handoffs"] < raw["usage"]["no_progress_handoffs"] and not (
                    set(evidence) - set(raw["verified_evidence_ids"])):
                raise ContractError("progress window reset requires new verified evidence")
    candidate = dict(raw, **changes)
    if target == current and candidate == raw:
        return record
    if target not in _EDGES[record.kind][current] and not (target == current and record.kind == "root_task"
                                                        and current in {"open", "active", "held"}):
        raise ContractError(f"illegal {record.kind} transition {current} -> {target}")
    if current == "unknown" and record.kind in {"message", "external_action", "execution"}:
        evidence_field = "observation_id" if record.kind == "execution" else "outcome_evidence_id"
        if not changes.get(evidence_field):
            raise ContractError("unknown outcome requires new reconciliation evidence")
    if record.kind in {"message", "external_action"} and raw["attempt_id"] is not None:
        if changes.get("attempt_id", raw["attempt_id"]) != raw["attempt_id"]:
            raise ContractError("attempt identity cannot change after submission starts")
    candidate.update(state=target, revision=record.revision + 1)
    return decode(candidate)


RECOVERY_RULES = {
    "role": "Revalidate against protected UID/policy registry; decoded claims grant no privilege.",
    "session": "Keep desired state; observed state becomes unknown until exact-ID runtime observation.",
    "root_task": "Preserve root, budgets, deadline, counters and evidence; no automatic budget reset.",
    "execution": "In-flight becomes unknown; broker fences and verifies all writers before transfer.",
    "message": "Delivering/submitted becomes unknown; reconcile before any further submission.",
    "external_action": "Delivering/submitted becomes unknown; verify external evidence, never blind retry.",
    "approval": "Retain single-use bindings; independently revalidate owner provenance and expiry.",
    "component_snapshot": "Verify captured artifacts/versions; incomplete required state prevents complete restore.",
}
UPGRADE_RULE = "Read v1 strictly; retain legacy/future bytes and require an explicit reviewed migration."


def recovered(record: Record) -> Record:
    """Invalidate observations after restart without minting new roots or actions."""
    raw = record.to_dict()
    if record.kind == "session":
        raw.update(observed_state="unknown", observation_id=None, ready=False)
    elif record.kind == "execution" and raw["state"] not in {"stopped", "failed", "queued", "unknown"}:
        raw.update(state="unknown", observation_id=None)
    elif record.kind in {"message", "external_action"} and raw["state"] in {"delivering", "submitted"}:
        raw.update(state="unknown")
    if raw == record.to_dict():
        return record
    raw["revision"] += 1
    return decode(raw)
