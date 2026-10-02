"""Real native framing/storage, synthetic protected source/UID observations."""
import os
from contextlib import closing
from pathlib import Path
from unittest import mock

from native_resume_fixtures import SETTINGS_DIGEST, attach_capture, resume_settings
from relay_core.contracts import fingerprint
from relay_core.native_epochs import NativeControlEpochs


POLICY_DIGEST = fingerprint({"synthetic_epoch_policy": "NOT-LINUX-ENFORCEMENT"})


def open_epochs(folder, *, checkpoint=lambda _: None):
    Path(folder).mkdir(mode=0o700, parents=True, exist_ok=True)
    source = fingerprint({"synthetic_capture_source": "NOT-KERNEL-PROOF"})
    with mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)):
        return NativeControlEpochs(folder, owner_uid=os.geteuid(), policy_digest=POLICY_DIGEST,
                                   current_source=lambda _: source, checkpoint=checkpoint)


def enroll_epochs(ledger, wire, folder):
    attach_capture(wire, folder)
    return ledger.enroll(wire.rpc, thread_id="native-thread-1", worktree="/fixture/worktree", settings_digest=SETTINGS_DIGEST)


def establish_baseline(ledger, wire, request_id="resume-1", provider=None):
    row = ledger._row(wire.rpc.connection_id)
    epoch = ledger.invalidate(wire.rpc, expected_epoch=row["epoch"], reason="resume_requested")
    def respond(peer):
        request = peer.receive()
        if provider:
            with closing(provider()) as native:
                response = native.rpc(request["method"], request["params"], request_id=request["id"])
        else:
            response = {"id": request["id"], "result": {**resume_settings(), "thread": {"id": "native-thread-1"}}}
        peer.write(response)
    wire.peer.start(respond)
    try:
        response = wire.rpc.rpc("thread/resume", {"threadId": "native-thread-1", "cwd": "/fixture/worktree"}, request_id=request_id)
    finally:
        wire.peer.finish()
    return ledger.accept_resume(wire.rpc, expected_epoch=epoch, request_id=request_id, response=response)


def settings_event(**changes):
    values = {**resume_settings(), "model": "fixture", "modelProvider": "fixture", "collaborationMode": {"mode": "default"}}
    values["sandboxPolicy"] = values.pop("sandbox")
    return {"method": "thread/settings/updated", "params": {"threadId": "native-thread-1", "threadSettings": {**values, **changes}}}
