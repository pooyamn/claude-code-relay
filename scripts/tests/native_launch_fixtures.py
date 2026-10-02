"""Invented owner-only launch inputs; real sealed local ArtifactStore bytes."""
import os
from pathlib import Path
from unittest import mock

from relay_core.artifacts import ArtifactStore
from relay_core.contracts import fingerprint
from relay_core.identity import Policy
from test_core_identity import policy_fields


def open_store(folder):
    Path(folder).mkdir(mode=0o700, exist_ok=True)
    with mock.patch("relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path)):
        return ArtifactStore(folder, owner_uid=os.geteuid())


def source(store, files):
    return store.install("launch-inputs", [{"path": path, "content": body, "executable": executable}
                                          for path, body, executable in files])


def fixture(store):
    policy = Policy(policy_fields())
    inputs = source(store, [("instructions/role.md", b"Build only the assigned change.\n", False),
                            ("instructions/repo.md", b"Keep existing project guidance.\n", False),
                            ("native.json", b'{"fixture":true,"permissions":"synthetic"}', False),
                            ("mcp.json", b'{"fixture":true,"tools":[]}', False),
                            ("measurement.json", b'{"fixture":true,"not_target_measurements":true}', False)])
    skill = source(store, [("fixture-skill/SKILL.md", b"# Fixture skill\nUse scratch files only.\n", False),
                           ("fixture-skill/scripts/example.py", b'raise RuntimeError("never execute fixture")\n', True),
                           ("LICENSE", b"Synthetic license notice must survive.\n", False)])
    reference = lambda path: {"artifact_digest": inputs, "path": path}
    spec = {"schema": "ccrelay.native_launch_spec.v1", "scope": "platform-owner-only", "automatic_turns_enabled": False,
            "session_id": "builder.task", "root_task_id": "root-builder", "execution_id": "exec-builder",
            "role_id": "builder", "role_uid": 101, "broker_policy_digest": policy.digest,
            "provider": "codex", "provider_session_id": "native-thread-1",
            "workspace": {"repo_id": "fixture", "base_commit": "a" * 40, "branch": "builder/task",
                          "worktree": "/var/lib/ccrelay/roles/builder/worktrees/builder.task",
                          "git_common_dir": "/var/lib/ccrelay/roles/builder/repos/fixture/git",
                          "mode": "reuse", "allowed_paths": ["src", "tests"]},
            "runtime": {"executable": "/opt/ccrelay/native/fixture-1/codex", "version": "fixture-1",
                        "adapter_digest": fingerprint({"fixture": "adapter"}),
                        "expected": {"runtime_digest": fingerprint({"fixture": "runtime"}),
                                     "tool_contract_digest": fingerprint({"fixture": "tool"}),
                                     "permission_digest": fingerprint({"fixture": "permissions"})},
                        "capabilities": ["exact_resume", "goal", "read"]},
            "permissions": {"native_config": reference("native.json"), "mcp_config": reference("mcp.json")},
            "resources": {"cpu_quota_percent": 25, "memory_max_bytes": 1048576, "tasks_max": 12,
                          "measurement": reference("measurement.json")},
            "instructions": {"role": reference("instructions/role.md"), "repo": reference("instructions/repo.md")},
            "skills": [{"id": "fixture-skill", "artifact_digest": skill, "directory": "fixture-skill"}]}
    return policy, spec
