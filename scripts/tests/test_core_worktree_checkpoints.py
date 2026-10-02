"""Real dirty Git/file/SQLite snapshots; writer/OS guards explicitly synthetic."""
from contextlib import contextmanager
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from native_workspace_fixtures import fixture_fields, git, open_workspace
from owner_fixtures import writable_fixture_tree
from relay_core.identity import Denied
from relay_core.worktree_checkpoints import CHUNK_BYTES, CheckpointPolicy, WorktreeCheckpoints


class WorktreeCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.policy, self.spec, self.home, self.common, self.contract = fixture_fields(self.folder)
        self.target = self.home / "worktrees/builder.task"
        self.fixture_policy = CheckpointPolicy(128, 8 * 1024 * 1024)  # Not runtime defaults.
        with open_workspace(self.policy, self.home, self.contract) as workspace:
            workspace.prepare(self.spec)

    @contextmanager
    def snapshots(self, *, checkpoint=lambda _: None, guard=None, policy=None):
        kwargs = {} if guard is None else {"guard": guard}
        with open_workspace(self.policy, self.home, self.contract, **kwargs) as workspace, \
                mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)), \
                WorktreeCheckpoints(workspace, policy or self.fixture_policy, checkpoint=checkpoint) as snapshots:
            yield snapshots

    def dirty(self):
        (self.target / "src/main.py").write_bytes(b"staged bytes\n")
        git(["-C", str(self.target), "add", "src/main.py"])
        (self.target / "src/main.py").write_bytes(b"unstaged later bytes\n")
        (self.target / "untracked\nname").write_bytes(b"untracked binary\x00bytes")
        (self.target / "cache").mkdir(mode=0o700)
        (self.target / "cache/output").write_bytes(b"ignored build output")
        metadata = Path((self.target / ".git").read_text().strip()[8:])
        (metadata / "MERGE_HEAD").write_bytes(self.spec["workspace"]["base_commit"].encode() + b"\n")
        (metadata / "rebase-merge").mkdir(mode=0o700)
        (metadata / "rebase-merge/done").write_bytes(b"unfinished rebase state\n")
        return metadata

    def test_captures_staged_unstaged_untracked_ignored_and_unfinished_operation_bytes(self):
        metadata = self.dirty()
        index = (metadata / "index").read_bytes()
        with self.snapshots() as snapshots:
            result = snapshots.capture("checkpoint-1", self.spec)
            self.assertTrue(result["created_now"])
            self.assertTrue(result["checkpoint"]["workspace"]["dirty"])
            self.assertFalse(result["checkpoint"]["admitted"])
            self.assertEqual(snapshots.read_file("checkpoint-1", "git", "index"), index)
            self.assertEqual(snapshots.read_file("checkpoint-1", "worktree", "src/main.py"), b"unstaged later bytes\n")
            self.assertEqual(snapshots.read_file("checkpoint-1", "worktree", "untracked\nname"), b"untracked binary\x00bytes")
            self.assertEqual(snapshots.read_file("checkpoint-1", "worktree", "cache/output"), b"ignored build output")
            self.assertEqual(snapshots.read_file("checkpoint-1", "git", "rebase-merge/done"), b"unfinished rebase state\n")
            self.assertTrue(snapshots.current("checkpoint-1"))
        self.assertEqual((metadata / "index").read_bytes(), index)
        self.assertEqual(git(["-C", str(self.target), "show", ":src/main.py"]), b"staged bytes\n")

    def test_duplicate_coalesces_and_later_dirty_change_cannot_replace_original_checkpoint(self):
        with self.snapshots() as snapshots:
            first = snapshots.capture("checkpoint-1", self.spec)["checkpoint"]
            self.assertFalse(snapshots.capture("checkpoint-1", self.spec)["created_now"])
            (self.target / "src/main.py").write_bytes(b"new uncommitted work")
            self.assertFalse(snapshots.current("checkpoint-1"))
            with self.assertRaises(Denied):
                snapshots.capture("checkpoint-1", self.spec)
            self.assertEqual(snapshots.inspect("checkpoint-1"), first)
            self.assertTrue(snapshots.capture("checkpoint-2", self.spec)["created_now"])

    def test_untracked_content_change_is_stale_even_when_head_and_status_are_unchanged(self):
        marker = self.target / "notes.txt"
        marker.write_bytes(b"original unfinished notes")
        with self.snapshots() as snapshots:
            sealed = snapshots.capture("checkpoint-1", self.spec)["checkpoint"]
            marker.write_bytes(b"different unfinished notes")
            observed = snapshots.workspace._observe(self.spec, self.common, self.target)
            self.assertEqual(observed["head"], sealed["workspace"]["head"])
            self.assertEqual(observed["status_digest"], sealed["workspace"]["status_digest"])
            self.assertFalse(snapshots.current("checkpoint-1"))
            self.assertEqual(snapshots.read_file("checkpoint-1", "worktree", "notes.txt"), b"original unfinished notes")

    def test_untracked_executable_mode_change_also_invalidates_freshness(self):
        marker = self.target / "unfinished-script"
        marker.write_bytes(b"script data, never executed")
        marker.chmod(0o600)
        with self.snapshots() as snapshots:
            snapshots.capture("checkpoint-1", self.spec)
            marker.chmod(0o700)
            self.assertFalse(snapshots.current("checkpoint-1"))

    def test_chunked_binary_larger_than_json_frame_is_preserved_without_flat_manifest_limit(self):
        body = bytes(range(256)) * (CHUNK_BYTES // 256 * 5 + 1)
        (self.target / "large.bin").write_bytes(body)
        with self.snapshots() as snapshots:
            snapshots.capture("checkpoint-1", self.spec)
            self.assertEqual(snapshots.read_file("checkpoint-1", "worktree", "large.bin"), body)
            self.assertEqual(snapshots.connection.execute("SELECT COUNT(*) FROM checkpoint_chunks WHERE area='worktree' AND path=?", (b"large.bin",)).fetchone()[0], 6)

    def test_symlink_targets_are_preserved_but_never_followed(self):
        denied = Path(os.environ["CCRELAY_DENIED_SENTINEL"])
        os.symlink(str(denied), self.target / "outside-link")
        os.symlink("missing-local-file", self.target / "dangling-link")
        with self.snapshots() as snapshots:
            snapshots.capture("checkpoint-1", self.spec)
            with self.assertRaises(Denied):
                snapshots.read_file("checkpoint-1", "worktree", "outside-link")
            self.assertTrue(snapshots.current("checkpoint-1"))
            self.assertFalse(snapshots.connection.execute("SELECT 1 FROM checkpoint_chunks WHERE path=?", (b"outside-link",)).fetchone())

    def test_directory_prefix_order_is_stable_and_empty_files_and_directories_survive(self):
        (self.target / "a").mkdir(mode=0o700)
        (self.target / "a/file").write_bytes(b"inside directory")
        (self.target / "a-file").write_bytes(b"neighbor prefix")
        (self.target / "empty").write_bytes(b"")
        (self.target / "empty-dir").mkdir(mode=0o700)
        with self.snapshots() as snapshots:
            snapshots.capture("checkpoint-1", self.spec)
            self.assertEqual(snapshots.read_file("checkpoint-1", "worktree", "empty"), b"")
            self.assertTrue(snapshots.current("checkpoint-1"))

    def test_file_change_at_preseal_boundary_rolls_back_all_content_but_preserves_request(self):
        def mutate(point):
            if point == "before_checkpoint_seal_commit":
                (self.target / "src/main.py").write_bytes(b"changed before sealing")
        with self.snapshots(checkpoint=mutate) as snapshots:
            with self.assertRaises(Denied):
                snapshots.capture("checkpoint-1", self.spec)
            self.assertEqual(snapshots._row("checkpoint-1")["state"], "planned")
            self.assertFalse(snapshots.connection.execute("SELECT 1 FROM checkpoint_entries").fetchone())
            self.assertFalse(snapshots.connection.execute("SELECT 1 FROM checkpoint_chunks").fetchone())

    def test_oversize_holds_without_accepting_partial_or_deleting_work(self):
        marker = self.target / "must-preserve"
        marker.write_bytes(b"original bytes")
        with self.snapshots(policy=CheckpointPolicy(128, 1)) as snapshots:
            with self.assertRaises(Denied):
                snapshots.capture("checkpoint-1", self.spec)
            with self.assertRaises(Denied):
                snapshots.inspect("checkpoint-1")
        self.assertEqual(marker.read_bytes(), b"original bytes")

    def test_special_fifo_is_not_read_blocked_on_or_silently_skipped(self):
        fifo = self.target / "unfinished-operation-pipe"
        os.mkfifo(fifo, mode=0o600)
        with self.snapshots() as snapshots:
            with self.assertRaises(Denied):
                snapshots.capture("checkpoint-1", self.spec)
            self.assertEqual(snapshots._row("checkpoint-1")["state"], "planned")
        self.assertTrue(fifo.exists())

    def test_linked_files_are_not_accepted_as_complete_private_checkpoint_content(self):
        os.link(self.target / "src/main.py", self.target / "other-link")
        with self.snapshots() as snapshots, self.assertRaises(Denied):
            snapshots.capture("checkpoint-1", self.spec)
        self.assertEqual((self.target / "other-link").read_bytes(), b"original tracked bytes\n")

    def test_modified_chunk_bytes_and_unlisted_chunks_are_detected(self):
        with self.snapshots() as snapshots:
            snapshots.capture("checkpoint-1", self.spec)
            saved = snapshots.connection.execute("SELECT body FROM checkpoint_chunks WHERE area='worktree' AND path=?", (b"src/main.py",)).fetchone()[0]
            snapshots.connection.execute("UPDATE checkpoint_chunks SET body=? WHERE area='worktree' AND path=?", (b"modified", b"src/main.py"))
            with self.assertRaises(Denied):
                snapshots.inspect("checkpoint-1")
            snapshots.connection.execute("UPDATE checkpoint_chunks SET body=? WHERE area='worktree' AND path=?", (saved, b"src/main.py"))
            from relay_core.artifacts import digest
            snapshots.connection.execute("INSERT INTO checkpoint_chunks VALUES (?,?,?,?,?,?)", ("checkpoint-1", "worktree", b"unlisted-file", 0, b"extra", digest(b"extra")))
            with self.assertRaises(Denied):
                snapshots.inspect("checkpoint-1")

    def test_corrupted_or_missing_chunk_and_incomplete_manifest_are_detected(self):
        with self.snapshots() as snapshots:
            snapshots.capture("checkpoint-1", self.spec)
            snapshots.connection.execute("DELETE FROM checkpoint_chunks WHERE snapshot_id=? AND area=? AND path=?", ("checkpoint-1", "worktree", b"src/main.py"))
            with self.assertRaises(Denied):
                snapshots.inspect("checkpoint-1")

    def test_policy_and_mapping_changes_cannot_reinterpret_existing_checkpoint(self):
        with self.snapshots() as snapshots:
            snapshots.capture("checkpoint-1", self.spec)
            changed = copy.deepcopy(self.spec)
            changed["execution_id"] = "other-execution"
            with self.assertRaises(Denied):
                snapshots.capture("checkpoint-1", changed)
        with self.assertRaises(Denied), self.snapshots(policy=CheckpointPolicy(256, 8 * 1024 * 1024)):
            pass

    def test_fence_is_required_and_fence_failure_cannot_create_a_checkpoint_request(self):
        @contextmanager
        def no_fence(_):
            raise Denied("synthetic writer fence unavailable")
            yield
        with self.snapshots(guard=no_fence) as snapshots, self.assertRaises(Denied):
            snapshots.capture("checkpoint-1", self.spec)

    def test_actual_request_capture_and_seal_deaths_never_select_partial_content(self):
        points = ("before_checkpoint_request_commit", "after_checkpoint_request_commit", "after_checkpoint_entry", "before_checkpoint_seal_commit", "after_checkpoint_seal_commit")
        for point in points:
            folder = self.folder / point
            policy, spec, home, common, contract = fixture_fields(folder)
            with open_workspace(policy, home, contract) as workspace:
                workspace.prepare(spec)
            marker = home / "worktrees/builder.task/src/main.py"
            marker.write_bytes(b"unfinished work survives process death\n")
            died = subprocess.run([sys.executable, str(Path(__file__).with_name("worktree_checkpoint_fault_fixture.py")), str(folder), point], capture_output=True, timeout=15)
            self.assertEqual(died.returncode, 73, died.stderr.decode())
            with open_workspace(policy, home, contract) as workspace, \
                    mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)), \
                    WorktreeCheckpoints(workspace, self.fixture_policy) as snapshots:
                row = snapshots._row("checkpoint-1")
                self.assertEqual(None if row is None else row["state"], None if point == "before_checkpoint_request_commit" else "sealed" if point == "after_checkpoint_seal_commit" else "planned")
                if point != "after_checkpoint_seal_commit":
                    with self.assertRaises(Denied):
                        snapshots.inspect("checkpoint-1")
                result = snapshots.capture("checkpoint-1", spec)
                self.assertEqual(result["created_now"], point != "after_checkpoint_seal_commit")
                self.assertEqual(snapshots.read_file("checkpoint-1", "worktree", "src/main.py"), marker.read_bytes())
                self.assertFalse(result["checkpoint"]["admitted"])
