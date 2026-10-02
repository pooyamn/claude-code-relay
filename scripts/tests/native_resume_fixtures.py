"""Non-idempotent fake resume provider; not a native/OS authorization proof."""
import sqlite3
import os
from pathlib import Path
import uuid

from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.native_settings import permission_contract
from relay_core.artifacts import ArtifactStore
from relay_core.native_capture import NativeCapture
from relay_core.native_rpc import _encode


def resume_settings(cwd="/fixture/worktree"):
    return {"cwd": cwd, "approvalPolicy": "never", "approvalsReviewer": "user",
            "sandbox": {"type": "readOnly", "networkAccess": False}}


SETTINGS_DIGEST = fingerprint(permission_contract(cwd="/fixture/worktree", approval_policy="never",
                                                approvals_reviewer="user", sandbox={"type": "readOnly"}))


def fixture_capture(folder, connection_id, *, notify=None, checkpoint=lambda _: None):
    """Real sealed scratch bytes; source identity remains explicitly synthetic."""
    Path(folder).mkdir(mode=0o700, parents=True, exist_ok=True)
    source = fingerprint({"synthetic_capture_source": "NOT-KERNEL-PROOF"})
    return NativeCapture(ArtifactStore(folder, owner_uid=os.geteuid()), source_digest=source,
                         connection_id=connection_id, current_source=lambda: source, notify=notify, checkpoint=checkpoint)


def attach_capture(wire, folder):
    wire.rpc.capture = fixture_capture(folder, wire.rpc.connection_id, notify=wire.capture)


class FakeResume:
    def __init__(self, path, *, checkpoint=lambda _: None):
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS resumes (request_id TEXT,parameters BLOB)")
        self.capture = fixture_capture(Path(path).parent / "provider-artifacts", "fixture-connection-" + uuid.uuid4().hex,
                                       checkpoint=checkpoint)
        self.last_response = None

    def close(self):
        self.connection.close()

    def rpc(self, method, parameters, *, request_id):
        if method != "thread/resume":
            raise AssertionError("no start/fork/turn/queue/profile fallback permitted")
        self.connection.execute("INSERT INTO resumes VALUES (?,?)", (request_id, canonical_bytes(parameters)))
        response = {"id": request_id, "result": {**resume_settings(parameters["cwd"]),
                "thread": {"id": parameters["threadId"], "sessionId": "different-tree-root"}}}
        receipt = self.capture(response, raw=_encode(response), kind="response", connection_id=self.capture.connection_id)
        self.last_response = (method, _encode(parameters), receipt)
        return response

    def response_evidence(self, method, parameters, *, request_id, response):
        if self.last_response is None or self.last_response[:2] != (method, _encode(parameters)):
            raise AssertionError("fixture response was not captured for this request")
        return self.capture.response_evidence(self.last_response[2], response=response, request_id=request_id)

    def count(self):
        return self.connection.execute("SELECT COUNT(*) FROM resumes").fetchone()[0]
