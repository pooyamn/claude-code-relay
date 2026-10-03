"""Synthetic GitHub/CI/kernel facts; real joined journal and non-idempotent effects."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sqlite3

from model_admission_fixtures import scheduler
from native_session_fixtures import CONTROLLER, enrollment, open_registry
from work_ownership_fixtures import NOW, root_record, work_fixture
from relay_core.contracts import canonical_bytes, decode, fingerprint
from relay_core.identity import Peer, Process, expected_cgroup
from relay_core.publications import (AppScope, BuildTest, MergeResult, PublicationAuthority, PublicationCheckpoint,
                                     PublicationPolicy, PublicationRemote, Publications, QueueRules)
from relay_core.runtime_delivery import evidence_for


BUILDER, OTHER, REVIEWER, CTO = Peer(11, 101, 121), Peer(12, 101, 121), Peer(21, 102, 121), Peer(31, 103, 121)
HEAD, BASE = "a" * 40, "b" * 40


def policy():
    return PublicationPolicy({"schema": "ccrelay.publication_policy.v1", "scope": "platform-owner-only", "publisher_roles": ["builder"],
        "reviewer_role": "reviewer", "merge_role": "cto", "max_pending_per_repo": 4, "test_max_age_ms": 1000,
        "repositories": [{"id": "fixture", "owner": "synthetic-owner", "name": "synthetic-repo", "repository_id": 123,
                          "app_id": 456, "installation_id": 789, "base_branch": "main",
                          "required_checks": ["ccrelay/review", "ccrelay/authorized-pair", "ccrelay/build-test"]}]})


class FakeGitHub:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS effects(action_id TEXT,attempt_id TEXT,body BLOB)")

    def call(self, result):
        if not result["may_execute"]:
            raise AssertionError("fake provider called without a new gate grant")
        record = result["record"]
        self.db.execute("INSERT INTO effects VALUES (?,?,?)", (record.id, record.fields["attempt_id"], canonical_bytes(result["plan"])))
        return evidence_for(record, record.fields["attempt_id"], result["plan"], outcome="accepted",
                            provider_reference="synthetic-receipt-" + record.id, payload={"synthetic_effect_only": True})

    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM effects").fetchone()[0]


@contextmanager
def publication_fixture(folder):
    folder = Path(folder)
    with work_fixture(folder) as f:
        observer = f.authority.observer
        f.authority.observer = lambda pid: Process(pid, 103, "00000000-0000-0000-0000-000000000001:100", expected_cgroup("exec-cto")) if pid == 31 else observer(pid)
        f.authority.register(CONTROLLER, {"session_id": "cto.task", "role_id": "cto", "root_task_id": "root-cto", "execution_id": "exec-cto", "leader_pid": 31})
        for role in ("builder", "reviewer", "cto"):
            raw = root_record(f.authority.policy.digest, root_id="root-" + role).to_dict()
            raw["owner_role_id"] = role
            f.ledger.enroll_root(CONTROLLER, decode(raw))
        for work, peer in (("work-1", BUILDER), ("work-2", OTHER)):
            f.ledger.enroll_work(CONTROLLER, work_id=work, root_id="root-builder", criteria=["Fixture acceptance"], dependencies=[], assignee_role_id="builder", resource_id="resource-" + work)
            if f.ledger.work(work)["binding"] is None:
                f.ledger.checkout(peer, work, "claim-" + work, expected_revision=0)
        registry = open_registry(folder / "publication-native", f.authority)
        provider = FakeGitHub(folder / "fake-provider.sqlite")
        try:
            for session, tool in (("builder.task", "codex"), ("builder.other", "codex"), ("reviewer.task", "claude"), ("cto.task", "claude")):
                registry.enroll(CONTROLLER, enrollment(session, provider=tool, native_id="native-" + session))
            admission = scheduler(f)
            admission.initialize(CONTROLLER)
            state = {"base": BASE, "remote": "open", "result": "enqueued"}
            def checkpoint(scope):
                head = scope["head_sha"] if "head_sha" in scope else scope["publication"]["head_sha"]
                return PublicationCheckpoint(fingerprint(scope), fingerprint({"synthetic_commit_reader_not_git": True}), head, "c" * 40,
                                             fingerprint({"synthetic_sealed_artifact": head}), True, True)
            def authority(scope):
                return PublicationAuthority(fingerprint(scope), fingerprint({"synthetic_screening_not_jev_or_owner": True}), True)
            def app(scope):
                wanted = scope["action"]["parameters"]["app_scope"]
                return AppScope(fingerprint(scope), fingerprint({"synthetic_installation_not_credentials": True}), wanted["app_id"], wanted["installation_id"],
                                tuple(wanted["repository_ids"]), wanted["permissions"], NOW + 100000)
            def remote(scope):
                body = scope["publication"]
                return PublicationRemote(fingerprint(scope), fingerprint({"synthetic_remote_not_github": True}), body["branch"], body["head_sha"],
                                         state["base"], 1 if body["id"] == "pub-1" else 2, state["remote"], None)
            def tests(scope):
                return BuildTest(fingerprint(scope), fingerprint({"synthetic_tests_not_ci": True}), scope["publication"]["head_sha"],
                                 state["base"], "d" * 40, NOW, True, True)
            def queue(scope):
                return QueueRules(fingerprint(scope), fingerprint({"synthetic_rules_not_server_enforcement": True}),
                                  tuple(scope["repository"]["required_checks"]), True, True, True, True, True)
            def outcome(scope):
                request = scope["merge_request"]
                return MergeResult(fingerprint(scope), fingerprint({"synthetic_queue_result_not_merge": True}), request["id"], request["head_sha"],
                                   request["base_sha"], state["result"], "e" * 40 if state["result"] == "merged" else None)
            engine = Publications(admission, registry, policy(), verify_checkpoint=checkpoint, verify_authority=authority, verify_app=app,
                                  observe_remote=remote, verify_tests=tests, verify_queue=queue, verify_result=outcome)
            engine.initialize(CONTROLLER)
            yield SimpleNamespace(f=f, ledger=f.ledger, registry=registry, admission=admission, engine=engine, provider=provider, state=state)
        finally:
            provider.db.close()
            registry.close()


def publish(s, key="pub-1", peer=BUILDER, work="work-1", head=HEAD):
    return s.engine.publish(peer, key, work, "fixture", head, fencing_token=s.ledger.work(work)["fencing_token"])


def execute(s, result):
    evidence = s.provider.call(result)
    s.ledger.reconcile(evidence)
    return result


def open_publication(s, key="pub-1", peer=BUILDER, work="work-1", head=HEAD):
    publish(s, key, peer, work, head)
    for step in ("branch", "pull_request"):
        execute(s, s.engine.claim_publish(CONTROLLER, key, step, "attempt-" + key + "-" + step))
    return s.engine.sync_open(CONTROLLER, key)


def reviewed(s, key="pub-1", peer=BUILDER, work="work-1", head=HEAD):
    open_publication(s, key, peer, work, head)
    s.engine.review(REVIEWER, key, "verdict-" + key, head_sha=head, verdict="approve")
    execute(s, s.engine.claim_publish(CONTROLLER, key, "review", "attempt-" + key + "-review"))
    return s.engine.load(key)
