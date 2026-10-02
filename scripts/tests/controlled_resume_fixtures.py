"""Joined real storage/framing with synthetic source and loaded-context facts."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from native_epoch_fixtures import enroll_epochs, open_epochs
from native_resume_fixtures import FakeResume, SETTINGS_DIGEST
from native_rpc_fixtures import RPCFixture
from native_session_fixtures import CONTROLLER, enrollment, native_fixture
from outbox_fixtures import CONTEXT, open_outbox
from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.native_controlled_resume import CodexControlledResume
from relay_core.native_observe import CONTEXT_SCHEMA, CodexNativeObserver, NativeContextReceipt
from relay_core.native_resume import resume_action


@contextmanager
def controlled_fixture(folder, *, wire_type=RPCFixture, checkpoint=lambda _: None):
    folder = Path(folder)
    with ExitStack() as stack:
        registry, authority = stack.enter_context(native_fixture(folder, checkpoint=checkpoint))
        registry.enroll(CONTROLLER, enrollment())
        ledger = open_outbox(folder / "ledger", policy_digest=authority.policy.digest, checkpoint=checkpoint)
        stack.callback(ledger.close)
        controls = open_epochs(folder / "epochs", policy_digest=authority.policy.digest)
        stack.callback(controls.close)
        wire = wire_type()
        stack.callback(wire.close)
        enroll_epochs(controls, wire, folder / "artifacts")
        wire.initialize()
        def inspect(binding, record, probe_id, ticket, read_reference):
            # Invented fixture measurements; sealing does NOT make them native proof.
            context = {"schema": CONTEXT_SCHEMA, "probe_id": probe_id, "binding_digest": fingerprint(binding),
                       "source_digest": ticket.source_digest, "connection_id": ticket.connection_id,
                       "control_epoch": ticket.epoch, "read_artifact_digest": read_reference["artifact_digest"],
                       "provider": "codex", "provider_session_id": "native-thread-1", "worktree": "/fixture/worktree",
                       "runtime_digest": "sha256:" + "a" * 64, "tool_contract_digest": "sha256:" + "b" * 64,
                       "permission_digest": "sha256:" + "c" * 64, "capabilities": ["read", "exact_resume"]}
            digest = wire.rpc.capture.store.install("native-context", [
                {"path": "context.json", "content": canonical_bytes(context), "executable": False}])
            return NativeContextReceipt(digest)
        observer = CodexNativeObserver(wire.rpc, controls, inspect_loaded_context=inspect)
        registry.observe_runtime = observer
        adapter = CodexControlledResume(wire.rpc, controls, observer, authorize=lambda *_: "fixture-admission", resume_supported=True)
        yield SimpleNamespace(folder=folder, registry=registry, ledger=ledger, controls=controls, wire=wire,
                              observer=observer, adapter=adapter)


def store_resume(fixture, action_id="resume-1", *, settings_digest=SETTINGS_DIGEST):
    action = resume_action(fixture.registry._row("builder.task"), action_id, settings_digest=settings_digest)
    fixture.ledger.store(action, CONTEXT)
    return action


def resume_count(folder):
    path = Path(folder) / "provider.sqlite"
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT COUNT(*) FROM resumes").fetchone()[0]


def run_resume(fixture, *, event=None, read_event=None, expect_read=True, change_response=lambda response: response):
    # Provider SQLite belongs to this peer thread, never to its caller's thread.
    def provider(peer):
        request = peer.receive()
        assert request["method"] == "thread/resume"
        assert request["params"] == {"threadId": "native-thread-1", "cwd": "/fixture/worktree"}
        native = FakeResume(fixture.folder / "provider.sqlite")
        try:
            response = native.rpc(request["method"], request["params"], request_id=request["id"])
        finally:
            native.close()
        if event:
            peer.write(event)
        peer.write(change_response(response))
        if expect_read:
            read = peer.receive()
            assert read["method"] == "thread/read" and read["params"] == {"threadId": "native-thread-1", "includeTurns": True}
            if read_event:
                peer.write(read_event)
            peer.write({"id": read["id"], "result": {"thread": {"id": "native-thread-1", "sessionId": "different-tree-root",
                       "cwd": "/fixture/worktree", "status": {"type": "idle"}, "turns": []}}})
    fixture.wire.peer.start(provider)
    try:
        return fixture.adapter.deliver(fixture.ledger, "resume-1", "resume-attempt", fixture.registry, CONTROLLER)
    finally:
        fixture.wire.peer.finish()
