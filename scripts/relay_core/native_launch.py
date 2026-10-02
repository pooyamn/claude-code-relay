"""Deterministic native launch bundles, without launch or execution permission.

Only a protected component may call this with its ArtifactStore and installed
broker policy. Sealing inputs is not review approval; a later launcher must bind
the package digest to authorization, current kernel identity, native contracts,
workspace/writer evidence and all-source admission. No worker RPC is provided.
"""
from pathlib import PurePosixPath
import re

from .artifacts import digest, relative_path
from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, integer, strict_json
from .native_sessions import _capabilities, _digests


SPEC_SCHEMA = "ccrelay.native_launch_spec.v1"
PACKAGE_SCHEMA = "ccrelay.native_launch_package.v1"
COMPONENT = "native-launch"


def _hash(value):
    if type(value) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise Denied("explicit pinned launch digest required")
    return value


def _path(value):
    if type(value) is not str or not value.startswith("/") or value == "/" or \
            "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value) or \
            ".." in value.split("/") or str(PurePosixPath(value)) != value:
        raise Denied("canonical absolute native launch path required")
    return value


def _reference(value):
    exact(value, {"artifact_digest", "path"})
    _hash(value["artifact_digest"])
    relative_path(value["path"])
    return value


def validate_spec(raw, policy):
    exact(raw, {"schema", "scope", "automatic_turns_enabled", "session_id", "root_task_id", "execution_id",
                "role_id", "role_uid", "broker_policy_digest", "provider", "provider_session_id",
                "workspace", "runtime", "permissions", "resources", "instructions", "skills"})
    if raw["schema"] != SPEC_SCHEMA or raw["scope"] != "platform-owner-only" or raw["automatic_turns_enabled"] is not False:
        raise Denied("only disabled owner-scoped launch preparation is supported")
    for key in ("session_id", "root_task_id", "execution_id", "role_id"):
        identifier(raw[key])
    role = policy.roles.get(raw["role_id"])
    if role is None or not role.fields["enabled"] or integer(raw["role_uid"]) != role.fields["uid"] or \
            raw["broker_policy_digest"] != policy.digest:
        raise Denied("launch role/UID/current broker policy mismatch")
    if type(raw["provider"]) is not str or raw["provider"] not in {"claude", "codex"} or \
            raw["provider_session_id"] is not None and (type(raw["provider_session_id"]) is not str or
            not raw["provider_session_id"] or len(raw["provider_session_id"]) > 4096 or
            any(ord(char) < 32 or ord(char) == 127 for char in raw["provider_session_id"])):
        raise Denied("explicit provider and exact existing conversation ID or new-session null required")
    workspace = raw["workspace"]
    exact(workspace, {"repo_id", "base_commit", "branch", "worktree", "git_common_dir", "mode", "allowed_paths"})
    identifier(workspace["repo_id"])
    if type(workspace["base_commit"]) is not str or not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", workspace["base_commit"]) or \
            type(workspace["mode"]) is not str or workspace["mode"] not in {"create", "reuse"}:
        raise Denied("exact full baseline commit and explicit workspace operation required")
    role_root = "/var/lib/ccrelay/roles/" + role.id
    if _path(workspace["worktree"]) != role_root + "/worktrees/" + raw["session_id"] or \
            _path(workspace["git_common_dir"]) != role_root + "/repos/" + workspace["repo_id"] + "/git":
        raise Denied("role-private worktree and Git metadata topology required")
    branch = workspace["branch"]
    if type(branch) is not str or not branch.startswith(role.id + "/") or len(branch) > 200 or \
            not re.fullmatch(r"[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)+", branch) or \
            ".." in branch or any(part.startswith(".") or part.endswith((".", ".lock")) for part in branch.split("/")):
        raise Denied("explicit role-scoped safe branch required")
    paths = workspace["allowed_paths"]
    if type(paths) is not list or not 1 <= len(paths) <= 64 or any(type(path) is not str for path in paths) or \
            len(set(paths)) != len(paths) or paths != sorted(paths):
        raise Denied("explicit canonical owned path list required")
    for path in paths:
        relative_path(path)
        if path.split("/")[0] in {".git", ".claude", ".agents", ".codex", "AGENTS.override.md"}:
            raise Denied("generated setup and Git metadata are not ordinary owned paths")
    runtime = raw["runtime"]
    exact(runtime, {"executable", "version", "adapter_digest", "expected", "capabilities"})
    _path(runtime["executable"])
    if not re.fullmatch(r"/opt/ccrelay/native/[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*", runtime["executable"]) or \
            type(runtime["version"]) is not str or \
            not re.fullmatch(r"[A-Za-z0-9_.+-]{1,100}", runtime["version"]):
        raise Denied("explicit installed native executable/version pin required")
    _hash(runtime["adapter_digest"])
    _digests(runtime["expected"])
    capabilities = _capabilities(runtime["capabilities"])
    if list(runtime["capabilities"]) != capabilities or raw["provider"] != "codex" and "goal" in capabilities:
        raise Denied("canonical backend-specific capability list required")
    permissions = raw["permissions"]
    exact(permissions, {"native_config", "mcp_config"})
    for reference in permissions.values():
        _reference(reference)
    resources = raw["resources"]
    exact(resources, {"cpu_quota_percent", "memory_max_bytes", "tasks_max", "measurement"})
    for key in ("cpu_quota_percent", "memory_max_bytes", "tasks_max"):
        if integer(resources[key], 1) > 2**63 - 1:
            raise Denied("resource setting exceeds signed platform integer range")
    _reference(resources["measurement"])
    instructions = raw["instructions"]
    exact(instructions, {"role", "repo"})
    for reference in instructions.values():
        _reference(reference)
    if type(raw["skills"]) is not list or len(raw["skills"]) > 16:
        raise Denied("explicit bounded skill references required")
    names = []
    for skill in raw["skills"]:
        exact(skill, {"id", "artifact_digest", "directory"})
        names.append(identifier(skill["id"]))
        _hash(skill["artifact_digest"])
        relative_path(skill["directory"])
    if names != sorted(set(names)):
        raise Denied("canonical unique skill IDs required")
    # Detach from caller-owned dicts/lists before packaging or returning a plan.
    return strict_json(canonical_bytes(raw))


def _input(store, reference):
    _, contents = store.verify(reference["artifact_digest"])
    body = contents.get(reference["path"])
    if body is None:
        raise Denied("pinned launch input missing from sealed artifact")
    return body


def _text(body):
    try:
        value = body.decode("utf-8")
    except UnicodeError:
        raise Denied("UTF-8 native instructions required") from None
    if not value.strip() or len(body) > 12 * 1024 or "\x00" in value:
        raise Denied("bounded nonempty native instructions required")
    return value


def _compile(store, policy, raw):
    spec = validate_spec(raw, policy)
    files = {}
    role = _input(store, spec["instructions"]["role"])
    repo = _input(store, spec["instructions"]["repo"])
    role_text, repo_text = _text(role), _text(repo)
    combined = ("# Prepared session instructions\n\n"
                "Role: " + spec["role_id"] + ". Session: " + spec["session_id"] + ". Root: " + spec["root_task_id"] + ".\n"
                "This text grants no broker authority, approval or execution permission.\n"
                "Owned repository paths: " + ", ".join(spec["workspace"]["allowed_paths"]) + ".\n\n"
                "## Role guidance\n\n" + role_text + "\n\n## Repository guidance\n\n" + repo_text).encode("utf-8")
    if len(combined) > 30 * 1024:
        raise Denied("generated instructions exceed conservative discovery byte bound")
    instruction_name = "AGENTS.override.md" if spec["provider"] == "codex" else "CLAUDE.md"
    for path, body in (("inputs/role.md", role), ("inputs/repo.md", repo), ("generated/" + instruction_name, combined)):
        files[path] = {"path": path, "content": body, "executable": False}
    # These are sealed references/bytes, not validated provider permissions or
    # measured target limits. Their semantics require the pinned target adapters.
    for name, reference in (("native-config", spec["permissions"]["native_config"]),
                            ("mcp-config", spec["permissions"]["mcp_config"]),
                            ("resource-measurement", spec["resources"]["measurement"])):
        path = "inputs/" + name
        files[path] = {"path": path, "content": _input(store, reference), "executable": False}
    resources = spec["resources"]
    fragment = ("# Prepared limits only; not an installed or enforced unit.\n[Service]\n"
                "CPUQuota=" + str(resources["cpu_quota_percent"]) + "%\n"
                "MemoryMax=" + str(resources["memory_max_bytes"]) + "\n"
                "TasksMax=" + str(resources["tasks_max"]) + "\nKillMode=control-group\nDelegate=no\n").encode("ascii")
    files["generated/resources.conf"] = {"path": "generated/resources.conf", "content": fragment, "executable": False}
    skills = []
    for skill in spec["skills"]:
        manifest, contents = store.verify(skill["artifact_digest"])
        entry = next((entry for entry in manifest["files"] if entry["path"] == skill["directory"] + "/SKILL.md"), None)
        if entry is None or entry["executable"]:
            raise Denied("pinned skill directory lacks non-executable SKILL.md")
        _text(contents[entry["path"]])
        # Preserve the complete selected artifact, including license notices and
        # ancillary assets outside the skill directory. Never execute its scripts.
        for source in manifest["files"]:
            path = "skills/" + skill["id"] + "/" + source["path"]
            files[path] = {"path": path, "content": contents[source["path"]], "executable": source["executable"]}
        skills.append({"id": skill["id"], "directory": "skills/" + skill["id"] + "/" + skill["directory"],
                       "discovery_target": (".agents/skills/" if spec["provider"] == "codex" else ".claude/skills/") + skill["id"]})
    package = {"schema": PACKAGE_SCHEMA, "spec": spec, "spec_digest": fingerprint(spec),
               "state": "prepared", "ready": False, "admitted": False, "target_verified": False,
               "instruction_file": "generated/" + instruction_name, "skills": skills,
               "files": [{"path": path, "digest": digest(item["content"]), "executable": item["executable"]}
                         for path, item in sorted(files.items())]}
    files["launch.json"] = {"path": "launch.json", "content": canonical_bytes(package), "executable": False}
    strict_json(files["launch.json"]["content"])  # Same bounded decoder used on recovery.
    if len(files) > 128 or sum(len(item["content"]) for item in files.values()) > 8 * 1024 * 1024:
        raise Denied("complete native launch package exceeds artifact bounds")
    return package, list(files.values())


def prepare(store, policy, spec, *, checkpoint=lambda _: None):
    """Seal a candidate, not activate it. Same exact inputs produce the same ID."""
    _, files = _compile(store, policy, spec)
    checkpoint("before_launch_artifact_install")
    artifact_digest = store.install(COMPONENT, files)
    checkpoint("after_launch_artifact_install")
    inspect_package(store, policy, artifact_digest)
    return artifact_digest


def inspect_package(store, policy, artifact_digest):
    """Verify candidate and exact pinned inputs; never bless launch or readiness."""
    manifest, contents = store.verify(artifact_digest)
    if manifest["component"] != COMPONENT or "launch.json" not in contents:
        raise Denied("native launch package required")
    package = strict_json(contents["launch.json"])
    exact(package, {"schema", "spec", "spec_digest", "state", "ready", "admitted", "target_verified",
                    "instruction_file", "skills", "files"})
    if package["schema"] != PACKAGE_SCHEMA:
        raise Denied("unknown launch package schema; preserve for reviewed migration")
    expected, files = _compile(store, policy, package["spec"])
    if package != expected or {item["path"]: item["content"] for item in files} != contents or \
            {item["path"]: item["executable"] for item in files} != {item["path"]: item["executable"] for item in manifest["files"]}:
        raise Denied("native launch package differs from exact sealed inputs/specification")
    return package
