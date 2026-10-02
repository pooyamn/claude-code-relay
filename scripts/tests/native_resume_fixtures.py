"""Non-idempotent fake resume provider; not a native/OS authorization proof."""
import sqlite3

from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.native_settings import permission_contract


def resume_settings(cwd="/fixture/worktree"):
    return {"cwd": cwd, "approvalPolicy": "never", "approvalsReviewer": "user",
            "sandbox": {"type": "readOnly", "networkAccess": False}}


SETTINGS_DIGEST = fingerprint(permission_contract(cwd="/fixture/worktree", approval_policy="never",
                                                approvals_reviewer="user", sandbox={"type": "readOnly"}))


class FakeResume:
    def __init__(self, path):
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS resumes (request_id TEXT,parameters BLOB)")

    def close(self):
        self.connection.close()

    def rpc(self, method, parameters, *, request_id):
        if method != "thread/resume":
            raise AssertionError("no start/fork/turn/queue/profile fallback permitted")
        self.connection.execute("INSERT INTO resumes VALUES (?,?)", (request_id, canonical_bytes(parameters)))
        return {"id": request_id, "result": {**resume_settings(parameters["cwd"]),
                "thread": {"id": parameters["threadId"], "sessionId": "different-tree-root"}}}

    def count(self):
        return self.connection.execute("SELECT COUNT(*) FROM resumes").fetchone()[0]
