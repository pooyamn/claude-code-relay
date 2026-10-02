"""Actual role-owned Git worktrees/SQLite/crashes, fake path/descendant guards."""
import copy
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib

from native_workspace_fixtures import fixture_fields, git, open_workspace
from relay_core.contracts import fingerprint
from relay_core.identity import Denied
from relay_core.native_workspace import WorkspacePreparation


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.policy, self.spec, self.home, self.common, self.contract = fixture_fields(self.folder)
        self.target = self.home / "worktrees/builder.task"

    def test_actual_create_promotion_and_replay_keep_exact_branch_and_unadmitted_identity(self):
        with open_workspace(self.policy, self.home, self.contract) as journal:
            result = journal.prepare(self.spec)
            self.assertFalse(result["dirty"])
            self.assertFalse(result["runtime_ready"])
            self.assertFalse(result["admitted"])
            self.assertEqual(result["head"], self.spec["workspace"]["base_commit"])
            self.assertEqual((self.target / "src/main.py").read_bytes(), b"original tracked bytes\n")
            self.assertEqual(journal.prepare(self.spec), result)
            self.assertEqual(journal._row("builder.task")["phase"], "prepared")
        self.assertEqual(git(["-C", str(self.target), "symbolic-ref", "--short", "HEAD"]).strip(), b"builder/task")

    def test_actual_dirty_index_untracked_ignored_and_unfinished_operation_are_preserved(self):
        with open_workspace(self.policy, self.home, self.contract) as journal:
            journal.prepare(self.spec)
        (self.target / "src/main.py").write_bytes(b"staged change\n")
        git(["-C", str(self.target), "add", "src/main.py"])
        (self.target / "src/main.py").write_bytes(b"later unstaged change\n")
        (self.target / "untracked\nname").write_bytes(b"untracked bytes\n")
        (self.target / "cache").mkdir(mode=0o700)
        (self.target / "cache/output").write_bytes(b"ignored bytes\n")
        metadata = Path((self.target / ".git").read_text().strip()[8:])
        (metadata / "MERGE_HEAD").write_bytes(self.spec["workspace"]["base_commit"].encode() + b"\n")
        before = {path: path.read_bytes() for path in (self.target / "src/main.py", self.target / "untracked\nname",
                                                      self.target / "cache/output", metadata / "index", metadata / "MERGE_HEAD")}
        with open_workspace(self.policy, self.home, self.contract) as journal:
            result = journal.prepare(self.spec)
        self.assertTrue(result["dirty"])
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_explicit_reuse_reads_existing_dirty_worktree_without_initial_checkout(self):
        git(["--git-dir=" + str(self.common), "worktree", "add", "-b", "builder/task", str(self.target), self.spec["workspace"]["base_commit"]])
        (self.target / "src/main.py").write_bytes(b"existing unfinished work\n")
        spec = copy.deepcopy(self.spec)
        spec["workspace"]["mode"] = "reuse"
        spec["provider_session_id"] = "native-thread-existing"
        with open_workspace(self.policy, self.home, self.contract) as journal:
            result = journal.prepare(spec)
            self.assertEqual(journal._row("builder.task")["spec"]["provider_session_id"], "native-thread-existing")
        self.assertTrue(result["dirty"])
        self.assertEqual((self.target / "src/main.py").read_bytes(), b"existing unfinished work\n")

    def test_existing_target_or_branch_is_not_adopted_by_create(self):
        self.target.mkdir(mode=0o700)
        marker = self.target / "owner-file"
        marker.write_bytes(b"must not overwrite")
        with open_workspace(self.policy, self.home, self.contract) as journal, self.assertRaises(Denied):
            journal.prepare(self.spec)
        self.assertEqual(marker.read_bytes(), b"must not overwrite")
        spec = copy.deepcopy(self.spec)
        spec["session_id"] = "builder.other"
        spec["workspace"]["worktree"] = "/var/lib/ccrelay/roles/builder/worktrees/builder.other"
        git(["--git-dir=" + str(self.common), "branch", "builder/task", self.spec["workspace"]["base_commit"]])
        with open_workspace(self.policy, self.home, self.contract) as journal, self.assertRaises(Denied):
            journal.prepare(spec)

    def test_repository_includes_filters_fsmonitor_remotes_and_external_objects_denied(self):
        config = self.common / "config"
        original = config.read_bytes()
        for suffix in (b"\n[include]\npath=/outside\n", b"\n[filter \"bad\"]\nsmudge=evil\n",
                       b"\n[core]\nfsmonitor=evil\n", b"\n[remote \"origin\"]\nurl=evil\n"):
            config.write_bytes(original + suffix)
            with self.subTest(suffix=suffix), open_workspace(self.policy, self.home, self.contract) as journal, self.assertRaises(Denied):
                journal.prepare(self.spec)
        config.write_bytes(original)
        alternates = self.common / "objects/info/alternates"
        alternates.write_bytes(b"/outside/objects\n")
        with open_workspace(self.policy, self.home, self.contract) as journal, self.assertRaises(Denied):
            journal.prepare(self.spec)
        self.assertFalse(self.target.exists())

    def test_hook_is_not_executed_and_ambient_git_configuration_is_not_inherited(self):
        hooks = self.common / "hooks"
        hooks.mkdir(mode=0o700)
        marker = self.home / "hook-executed"
        hook = hooks / "post-checkout"
        hook.write_text("#!/bin/sh\ntouch '" + str(marker) + "'\n")
        hook.chmod(0o700)
        with mock.patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor",
                                         "GIT_CONFIG_VALUE_0": "evil", "GIT_DIR": "/outside"}):
            with open_workspace(self.policy, self.home, self.contract) as journal:
                journal.prepare(self.spec)
        self.assertFalse(marker.exists())

    def test_wrong_uid_role_missing_guard_and_changed_git_pins_cannot_mutate_workspace(self):
        with self.assertRaises(Denied):
            WorkspacePreparation(policy=self.policy, role_id="reviewer", git_contract=self.contract, writer_guard=lambda _: None)
        with open_workspace(self.policy, self.home, self.contract) as journal:
            old = journal.git_contract
            journal.git_contract = {**old, "digest": "sha256:" + "0" * 64}
            with self.assertRaises(Denied):
                journal.prepare(self.spec)
            journal.git_contract = {**old, "version_line": "git version wrong"}
            with self.assertRaises(Denied):
                journal.prepare(self.spec)
        with self.assertRaises(Denied), open_workspace(self.policy, self.home, self.contract, guard=None):
            pass
        self.assertFalse(self.target.exists())

    def test_live_writer_guard_refusal_happens_before_git_effects(self):
        @contextmanager
        def denied(spec):
            raise Denied("writer still alive")
            yield
        with open_workspace(self.policy, self.home, self.contract, guard=denied) as journal, self.assertRaises(Denied):
            journal.prepare(self.spec)
        self.assertFalse(self.target.exists())
        self.assertEqual(git(["--git-dir=" + str(self.common), "for-each-ref", "--format=%(refname)"]).strip(), b"refs/heads/main")

    def test_changed_execution_or_manifest_cannot_reset_existing_worktree_mapping(self):
        with open_workspace(self.policy, self.home, self.contract) as journal:
            journal.prepare(self.spec)
            changed = copy.deepcopy(self.spec)
            changed["execution_id"] = "replacement-execution"
            with self.assertRaises(Denied):
                journal.prepare(changed)
            self.assertEqual(journal._row("builder.task")["spec"], self.spec)

    def test_symlink_linked_metadata_and_wrong_common_directory_fail_closed(self):
        with open_workspace(self.policy, self.home, self.contract) as journal:
            journal.prepare(self.spec)
        pointer = self.target / ".git"
        original = pointer.read_bytes()
        pointer.write_bytes(b"gitdir: /outside/worktrees/evil\n")
        with open_workspace(self.policy, self.home, self.contract) as journal, self.assertRaises(Denied):
            journal.prepare(self.spec)
        pointer.write_bytes(original)
        os.link(pointer, self.home / "linked-pointer")
        with open_workspace(self.policy, self.home, self.contract) as journal, self.assertRaises(Denied):
            journal.prepare(self.spec)

    def test_unknown_journal_schema_is_preserved_without_git_recovery_writes(self):
        with open_workspace(self.policy, self.home, self.contract) as journal:
            journal.prepare(self.spec)
            journal.connection.execute("UPDATE workspace_metadata SET schema='future.workspace.v9'")
        path = self.home / "workspace-preparation/outbox.sqlite"
        before = path.read_bytes()
        with self.assertRaises(Denied), open_workspace(self.policy, self.home, self.contract):
            pass
        self.assertEqual(path.read_bytes(), before)

    def test_actual_lifetime_lock_prevents_a_second_preparer(self):
        with open_workspace(self.policy, self.home, self.contract), self.assertRaises(BlockingIOError):
            with open_workspace(self.policy, self.home, self.contract):
                pass

    def test_replacement_objects_and_legacy_grafts_cannot_reframe_pinned_baseline(self):
        replacement = b"replacement tracked bytes\n"
        stream = (b"blob\nmark :1\ndata " + str(len(replacement)).encode() + b"\n" + replacement +
                  b"commit refs/heads/alternative\nauthor Fixture <fixture@example.invalid> 1700000001 +0000\n"
                  b"committer Fixture <fixture@example.invalid> 1700000001 +0000\ndata 4\nfake\n"
                  b"M 100644 :1 src/main.py\n\ndone\n")
        git(["--git-dir=" + str(self.common), "fast-import", "--quiet"], data=stream)
        other = git(["--git-dir=" + str(self.common), "rev-parse", "refs/heads/alternative"]).strip().decode()
        git(["--git-dir=" + str(self.common), "replace", self.spec["workspace"]["base_commit"], other])
        with open_workspace(self.policy, self.home, self.contract) as journal:
            observed = journal.prepare(self.spec)
        self.assertEqual(observed["head"], self.spec["workspace"]["base_commit"])
        self.assertEqual((self.target / "src/main.py").read_bytes(), b"original tracked bytes\n")
        (self.common / "info").mkdir(mode=0o700, exist_ok=True)
        (self.common / "info/grafts").write_bytes(self.spec["workspace"]["base_commit"].encode() + b"\n")
        with open_workspace(self.policy, self.home, self.contract) as journal, self.assertRaises(Denied):
            journal.prepare(self.spec)

    def test_changed_git_contract_cannot_reopen_existing_journal_or_rewrite_its_bytes(self):
        with open_workspace(self.policy, self.home, self.contract) as journal:
            journal.prepare(self.spec)
        path = self.home / "workspace-preparation/outbox.sqlite"
        before = path.read_bytes()
        changed = {**self.contract, "version_line": "git version changed"}
        with self.assertRaises(Denied), open_workspace(self.policy, self.home, changed):
            pass
        self.assertEqual(path.read_bytes(), before)

    def test_corrupt_object_named_by_expected_hash_is_rejected_before_workspace_effects(self):
        object_id = git(["--git-dir=" + str(self.common), "rev-parse",
                         self.spec["workspace"]["base_commit"] + ":src/main.py"]).strip().decode()
        loose = self.common / "objects" / object_id[:2] / object_id[2:]
        loose.parent.mkdir(mode=0o700, exist_ok=True)
        if loose.exists():
            loose.chmod(0o600)  # An owning worker can change its own object mode.
        other = b"corrupt tracked bytes\n"
        loose.write_bytes(zlib.compress(b"blob " + str(len(other)).encode() + b"\0" + other))
        with open_workspace(self.policy, self.home, self.contract) as journal:
            with self.assertRaises(Denied):
                journal.prepare(self.spec)
            self.assertIsNone(journal._row("builder.task"))
        self.assertFalse(self.target.exists())
        self.assertEqual(list((self.home / "worktrees").iterdir()), [])
        self.assertEqual(git(["--git-dir=" + str(self.common), "for-each-ref", "--format=%(refname)"]).splitlines(),
                         [b"refs/heads/main"])

    def test_partial_staging_work_and_destination_collision_are_preserved(self):
        for point in ("after_git_worktree_add", "after_git_checkout", "before_git_worktree_move"):
            folder = self.folder / point
            policy, spec, home, common, contract = fixture_fields(folder)
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("native_workspace_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, result.stderr)
            stage = home / "worktrees" / (".ccrelay-" + fingerprint(spec)[7:])
            marker = stage / "owner-change"
            marker.write_bytes(b"unfinished staging work")
            if point == "before_git_worktree_move":
                target = home / "worktrees/builder.task"
                target.mkdir(mode=0o700)
                (target / "owner-file").write_bytes(b"destination collision")
            with open_workspace(policy, home, contract) as journal, self.assertRaises(Denied):
                journal.prepare(spec)
            self.assertEqual(marker.read_bytes(), b"unfinished staging work")
            self.assertTrue(stage.exists())

    def test_actual_worker_deaths_reconcile_git_effects_without_fresh_branch_or_dirty_reset(self):
        points = ("after_workspace_register_commit", "before_git_worktree_add", "after_git_worktree_add",
                  "before_git_checkout", "after_git_checkout", "before_git_worktree_move", "after_git_worktree_move",
                  "before_workspace_prepared_commit", "after_workspace_prepared_commit")
        for point in points:
            folder = self.folder / point
            policy, spec, home, common, contract = fixture_fields(folder)
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("native_workspace_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, result.stderr)
            target = home / "worktrees/builder.task"
            if target.exists():
                (target / "src/main.py").write_bytes(b"unfinished post-promotion work\n")
            with open_workspace(policy, home, contract) as journal:
                observed = journal.prepare(spec)
                self.assertFalse(observed["admitted"])
                self.assertEqual(journal._row("builder.task")["phase"], "prepared")
            expected = b"unfinished post-promotion work\n" if observed["dirty"] else b"original tracked bytes\n"
            self.assertEqual((target / "src/main.py").read_bytes(), expected)
            refs = git(["--git-dir=" + str(common), "for-each-ref", "--format=%(refname)"]).splitlines()
            self.assertEqual(refs, [b"refs/heads/builder/task", b"refs/heads/main"])


if __name__ == "__main__":
    unittest.main()
