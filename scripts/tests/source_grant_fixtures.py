"""Synthetic protected controller/grants; no native connection or company claim."""
from contextlib import contextmanager
import os
from pathlib import Path
from unittest import mock

from relay_core.bindings import BindingRegistry
from relay_core.identity import Authority, Peer, Policy, Process, expected_cgroup
from relay_core.telegram_authority import SourceGrants
from test_core_identity import BOOT, policy_fields


CONTROLLER = Peer(1, 0, 0)  # Kernel identity is substituted, never request JSON.


@contextmanager
def sources(folder, ledger, *, current_check=lambda body, binding: True):
    folder = Path(folder)
    (folder / "bindings").mkdir(mode=0o700, parents=True, exist_ok=True)
    (folder / "grants").mkdir(mode=0o700, parents=True, exist_ok=True)
    with mock.patch("relay_core.bindings.protected_path", side_effect=lambda path, **_: Path(path)):
        registry = BindingRegistry(folder / "bindings", owner_uid=os.geteuid())
    policy = Policy(policy_fields())
    process = Process(11, 101, BOOT + ":100", expected_cgroup("exec-builder"))
    authority = Authority(policy, registry, observer=lambda pid: process)
    if registry.session("builder.fixture") is None:
        authority.register(CONTROLLER, {"session_id": "builder.fixture", "role_id": "builder", "root_task_id": "root-1",
                                       "execution_id": "exec-builder", "leader_pid": 11})
    grants = SourceGrants(folder / "grants", ledger=ledger, authority=authority, current_check=current_check)
    try:
        yield grants, authority
    finally:
        grants.close()
        registry.close()
