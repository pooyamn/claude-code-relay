"""Synthetic normalized runtime/kernel facts; real private SQLite and locks."""
from contextlib import contextmanager
import os
from pathlib import Path
from unittest import mock

from relay_core.bindings import BindingRegistry
from relay_core.identity import Authority, Peer, Policy, Process, expected_cgroup
from relay_core.native_sessions import NativeObservation, NativeSessionRegistry
from relay_core.contracts import fingerprint
from test_core_identity import BOOT, policy_fields


CONTROLLER = Peer(1, 0, 0)  # Substituted kernel identity, never a user header.


def enrollment(session_id="builder.task", *, provider="codex", native_id="native-thread-1"):
    return {"session_id": session_id, "provider": provider, "provider_session_id": native_id,
            "worktree": "/fixture/worktree", "desired_state": "running",
            "expected": {"runtime_digest": "sha256:" + "a" * 64, "tool_contract_digest": "sha256:" + "b" * 64,
                         "permission_digest": "sha256:" + "c" * 64}, "capabilities": ["read", "exact_resume"]}


def observation(binding, record, probe_id):
    return NativeObservation(probe_id, "observation-" + probe_id, fingerprint(binding),
                             record.fields["provider"], record.fields["provider_session_id"], record.fields["worktree"],
                             "running", "native-turn-1", "sha256:" + "a" * 64, "sha256:" + "b" * 64,
                             "sha256:" + "c" * 64, ("read", "exact_resume", "interrupt"))


def open_registry(folder, authority, *, observer=observation, checkpoint=lambda _: None):
    Path(folder).mkdir(mode=0o700, parents=True, exist_ok=True)
    with mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)):
        return NativeSessionRegistry(folder, owner_uid=os.geteuid(), authority=authority,
                                     observe_runtime=observer, checkpoint=checkpoint)


@contextmanager
def native_fixture(folder, *, observer=observation, checkpoint=lambda _: None):
    folder = Path(folder)
    (folder / "bindings").mkdir(mode=0o700, parents=True, exist_ok=True)
    with mock.patch("relay_core.bindings.protected_path", side_effect=lambda path, **_: Path(path)):
        bindings = BindingRegistry(folder / "bindings", owner_uid=os.geteuid())
    policy = Policy(policy_fields())
    authority = Authority(policy, bindings, observer=lambda pid: Process(
        pid, 101 if pid in {11, 12} else 102, BOOT + ":100", expected_cgroup(
            "exec-builder" if pid == 11 else "exec-builder-other" if pid == 12 else "exec-reviewer")))
    for session_id, role_id, execution_id, leader_pid in (("builder.task", "builder", "exec-builder", 11),
            ("builder.other", "builder", "exec-builder-other", 12), ("reviewer.task", "reviewer", "exec-reviewer", 21)):
        authority.register(CONTROLLER, {"session_id": session_id, "role_id": role_id, "root_task_id": "root-" + role_id,
                                      "execution_id": execution_id, "leader_pid": leader_pid})
    registry = None
    try:
        registry = open_registry(folder / "native", authority, observer=observer, checkpoint=checkpoint)
        # Mac scratch has shared writable ancestors. Real artifact bytes,
        # owners/modes/links, locks and fsync remain checked; ancestor isolation
        # and native source/kernel observations are NOT target-OS evidence.
        with mock.patch("relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path)):
            yield registry, authority
    finally:
        if registry is not None:
            registry.close()
        bindings.close()
