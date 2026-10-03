"""Real shared custody/native journals; authority/loading/fences are synthetic."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from model_admission_fixtures import scheduler
from native_session_fixtures import CONTROLLER, enrollment, open_registry
from work_ownership_fixtures import root_record, work_fixture
from relay_core.contracts import fingerprint
from relay_core.identity import Peer
from relay_core.tool_switches import SwitchAuthority, SwitchCheckpoint, SwitchFence, SwitchLoaded, ToolSwitches


BUILDER = Peer(11, 101, 121)
OTHER = Peer(12, 101, 121)


def snapshot(worktree="/fixture/worktree"):
    return {"schema": "ccrelay.worktree_checkpoint.v1", "checkpoint_id": "checkpoint-1",
            "checkpoint_digest": fingerprint({"synthetic_checkpoint": True}),
            "spec_digest": fingerprint({"synthetic_spec": True}), "worktree": worktree}


def context():
    return {"task_context": {"objective": "Preserve unfinished fixture work", "next": "Verify the pending mapping"},
            "operations": [{"id": "operation-1", "state": "unfinished"}],
            "publications": [], "approvals": [], "pending_inputs": ["Unanswered fixture question"]}


@contextmanager
def switch_fixture(folder, *, worktree="/fixture/worktree"):
    with work_fixture(folder) as f:
        f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
        f.ledger.enroll_work(CONTROLLER, work_id="work-1", root_id="root-builder", criteria=["Verified fixture result"],
                             dependencies=[], assignee_role_id="builder", resource_id="fixture-worktree")
        if f.ledger.work("work-1")["binding"] is None:
            f.ledger.checkout(BUILDER, "work-1", "original-claim", expected_revision=0)
        registry = open_registry(Path(folder) / "switch-native", f.authority)
        try:
            for session, provider, native in (("builder.task", "claude", "claude-original"),
                                               ("builder.other", "codex", "codex-destination")):
                registry.enroll(CONTROLLER, {**enrollment(session, provider=provider, native_id=native), "worktree": worktree})
            admission = scheduler(f)
            admission.initialize(CONTROLLER)
            def authority(scope):
                return SwitchAuthority(fingerprint(scope), fingerprint({"synthetic_owner_not_ingress": True}), "owner-switch-decision")
            def checkpoint(scope):
                capsule = scope["proposed_capsule"]
                return SwitchCheckpoint(fingerprint(scope), fingerprint({"synthetic_checkpoint_reader": capsule}), fingerprint(capsule), True)
            def loaded(scope):
                return SwitchLoaded(fingerprint(scope), fingerprint({"synthetic_native_context_not_loading": True}),
                                    fingerprint(scope["capsule"]), scope["switch"]["destination_native"]["provider_session_id"], None, True,
                                    **scope["switch"]["destination_native"]["expected"])
            @contextmanager
            def fence(scope):
                yield SwitchFence(fingerprint(scope), fingerprint({"synthetic_fence_not_kernel": True}), True, True)
            engine = ToolSwitches(admission, registry, authorize=authority, verify_checkpoint=checkpoint,
                                  verify_loaded=loaded, writer_guard=fence)
            engine.initialize(CONTROLLER)
            yield SimpleNamespace(f=f, ledger=f.ledger, registry=registry, admission=admission, engine=engine)
        finally:
            registry.close()
