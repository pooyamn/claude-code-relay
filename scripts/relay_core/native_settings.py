"""Pinned Codex 0.160 legacy sandbox/approval response checks, not readiness.

The settings digest is separately reviewed and bound to the resume action. It
does not redefine the registry's broader permission/context digest. Named
profiles require their own effective-policy evidence, never a legacy fallback.
"""
from pathlib import PurePosixPath
import re

from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, strict_json


SCHEMA = "ccrelay.codex_resume_permissions.v1"


def _path(value):
    if type(value) is not str or not 1 <= len(value) <= 4096 or not value.startswith("/") or \
            str(PurePosixPath(value)) != value or ".." in value.split("/") or "\\" in value or \
            any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise Denied("canonical environment-native absolute path required")
    return value


def _approval(value):
    if type(value) is str and value in {"never", "on-request", "untrusted"}:
        return value
    exact(value, {"granular"})
    granular = value["granular"]
    required = {"sandbox_approval", "rules", "mcp_elicitations"}
    optional = {"skill_approval", "request_permissions"}
    if type(granular) is not dict or not required <= set(granular) or set(granular) - required - optional or \
            any(type(item) is not bool for item in granular.values()):
        raise Denied("unsupported native granular approval policy")
    return {"granular": {key: granular.get(key, False) for key in sorted(required | optional)}}


def _sandbox(value):
    if type(value) is not dict or type(value.get("type")) is not str:
        raise Denied("native sandbox policy required")
    kind = value["type"]
    if kind == "dangerFullAccess":
        exact(value, {"type"})
        return {"type": kind}
    if kind == "externalSandbox":
        network = value.get("networkAccess", "restricted")
        if set(value) - {"type", "networkAccess"} or type(network) is not str or network not in {"restricted", "enabled"}:
            raise Denied("unsupported external native sandbox policy")
        return {"type": kind, "networkAccess": network}
    if kind not in {"readOnly", "workspaceWrite"}:
        raise Denied("unsupported native sandbox variant")
    optional = {"networkAccess"} | ({"writableRoots", "excludeTmpdirEnvVar", "excludeSlashTmp"} if kind == "workspaceWrite" else set())
    if set(value) - {"type"} - optional:
        raise Denied("unsupported native sandbox fields; no permission fallback")
    normalized = {"type": kind}
    for key in optional - {"writableRoots"}:
        if type(value.get(key, False)) is not bool:
            raise Denied("native sandbox flag must be boolean")
        normalized[key] = value.get(key, False)
    if kind == "workspaceWrite":
        roots = value.get("writableRoots", [])
        if type(roots) is not list or len(roots) > 64:
            raise Denied("bounded native writable root list required")
        checked = [_path(root) for root in roots]
        if len(set(checked)) != len(checked):
            raise Denied("duplicate native writable roots")
        normalized["writableRoots"] = sorted(checked)
    return normalized


def permission_contract(*, cwd, approval_policy, approvals_reviewer, sandbox):
    """Canonical reviewed expectation or observed native response; no authority."""
    if type(approvals_reviewer) is not str or approvals_reviewer not in {"user", "auto_review", "guardian_subagent"}:
        raise Denied("supported explicit native approvals reviewer required")
    return {"schema": SCHEMA, "cwd": _path(cwd), "approval_policy": _approval(approval_policy),
            "approvals_reviewer": approvals_reviewer, "sandbox": _sandbox(sandbox)}


def verify_resume_permissions(result, *, thread_id, worktree, expected_digest):
    if type(expected_digest) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", expected_digest) or \
            type(result) is not dict or type(result.get("thread")) is not dict or \
            result["thread"].get("id") != thread_id or result.get("cwd") != worktree:
        raise Denied("exact native thread/worktree and reviewed settings digest required")
    if result.get("activePermissionProfile") is not None:
        raise Denied("named native profiles need effective policy evidence; no legacy sandbox fallback")
    allowed = {"thread", "cwd", "approvalPolicy", "approvalsReviewer", "sandbox", "model", "modelProvider",
               "collaborationMode", "reasoningEffort", "serviceTier", "instructionSources", "disabledPluginIds",
               "itemsBackwardsCursor", "turnsBackwardsCursor", "activePermissionProfile", "initialTurnsPage", "multiAgentMode"}
    if set(result) - allowed:
        raise Denied("unsupported native resume fields; review the pinned permission contract")
    required = {"cwd", "approvalPolicy", "approvalsReviewer", "sandbox"}
    if not required <= set(result):
        raise Denied("native resume did not report complete sandbox/approval settings")
    contract = permission_contract(cwd=result["cwd"], approval_policy=result["approvalPolicy"],
                                   approvals_reviewer=result["approvalsReviewer"], sandbox=result["sandbox"])
    if fingerprint(contract) != expected_digest:
        raise Denied("native resumed permissions differ from the exact reviewed action")
    return strict_json(canonical_bytes(contract))
