"""Actual staged/dirty Git replays and crash retention, not live PC acceptance."""
from contextlib import contextmanager
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from native_workspace_fixtures import git
from owner_fixtures import writable_fixture_tree
from post_merge_fixtures import commit, fields, loaded_fields, replay_fixture, request
from relay_core.contracts import canonical_bytes
from relay_core.identity import Denied


class PostMergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.data = fields(self.folder)
        self.source = self.data[2] / "worktrees/builder.task"

    def test_real_squash_replays_later_commit_and_preserves_index_dirty_untracked_ignored(self):
        original_head = git(["-C", str(self.source), "rev-parse", "HEAD"])
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "ready")
            stage = replay._paths(body)[2]
            self.assertEqual((stage / "later.txt").read_bytes(), b"later committed work\n")
            self.assertEqual((stage / "published.txt").read_bytes(), b"published candidate\n")
            self.assertEqual(git(["-C", str(stage), "show", ":src/main.py"]), b"staged future bytes\n")
            self.assertEqual((stage / "src/main.py").read_bytes(), b"unstaged future bytes\n")
            self.assertEqual((stage / "unfinished\nnotes").read_bytes(), b"untracked\x00binary")
            self.assertEqual((stage / "cache/output").read_bytes(), b"ignored output")
            self.assertTrue((stage / "empty-dir").is_dir())
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))
            self.assertTrue(replay.snapshots.current(body["stage_checkpoint"]))
            self.assertEqual(git(["-C", str(self.source), "rev-parse", "HEAD"]), original_head)
            self.assertFalse(body["admitted"])
            self.assertEqual(replay.run("replay-1"), body)

    def test_committed_rebase_conflict_retains_original_and_git_operation(self):
        data = fields(self.folder / "commit-conflict", dirty=False, conflict="committed")
        with replay_fixture(data) as replay:
            request(replay, data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "conflicted")
            stage = replay._paths(body)[2]
            pointer = Path((stage / ".git").read_bytes()[8:-1].decode())
            self.assertTrue((pointer / "rebase-merge").is_dir())
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))
            self.assertEqual((data[2] / "worktrees/builder.task/src/main.py").read_bytes(), b"local committed replacement\n")
            self.assertEqual(replay.run("replay-1"), body)

    def test_dirty_replay_conflict_keeps_original_staging_and_candidate(self):
        data = fields(self.folder / "dirty-conflict", conflict="dirty")
        with replay_fixture(data) as replay:
            request(replay, data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "conflicted")
            self.assertEqual(body["finding"]["reason"], "staged_or_unstaged_replay_conflict_retained")
            source = replay._paths(body)[1]
            self.assertEqual(git(["-C", str(source), "show", ":src/main.py"]), b"staged future bytes\n")
            self.assertEqual((source / "src/main.py").read_bytes(), b"unstaged future bytes\n")
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))

    def test_untracked_and_ignored_collisions_never_overwrite_either_version(self):
        for kind, path, local, upstream in (("untracked", "unfinished\nnotes", b"untracked\x00binary", b"upstream owns this path\n"),
                                            ("ignored", "cache/output", b"ignored output", b"upstream now tracks ignored path\n")):
            data = fields(self.folder / kind, conflict=kind)
            with replay_fixture(data) as replay:
                request(replay, data)
                body = replay.run("replay-1")
                self.assertEqual(body["phase"], "conflicted")
                _, source, stage = replay._paths(body)
                self.assertEqual((source / path).read_bytes(), local)
                self.assertEqual((stage / path).read_bytes(), upstream)
                self.assertEqual(replay.snapshots.read_file(body["source_checkpoint"], "worktree", path), local)

    def test_symlink_overlay_does_not_read_external_target_and_modes_survive(self):
        os.symlink(os.environ["CCRELAY_DENIED_SENTINEL"], self.source / "outside-link")
        (self.source / "unfinished\nnotes").chmod(0o700)
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "ready")
            stage = replay._paths(body)[2]
            self.assertEqual(os.readlink(stage / "outside-link"), os.environ["CCRELAY_DENIED_SENTINEL"])
            self.assertEqual((stage / "unfinished\nnotes").stat().st_mode & 0o777, 0o700)

    def test_later_empty_commit_is_not_silently_dropped(self):
        git(["-C", str(self.source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "meaningful empty checkpoint"])
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            stage = replay._paths(body)[2]
            count = git(["-C", str(stage), "rev-list", "--count", self.data[6] + "..HEAD"])
            self.assertEqual(count.strip(), b"2")

    def test_changed_ready_candidate_cannot_be_selected_as_current_replay(self):
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            stage = replay._paths(body)[2]
            (stage / "unfinished\nnotes").write_bytes(b"changed candidate bytes")
            with self.assertRaises(Denied):
                replay.run("replay-1")
            self.assertEqual(replay.load_replay("replay-1"), body)
            self.assertEqual(replay.snapshots.read_file(body["stage_checkpoint"], "worktree", "unfinished\nnotes"), b"untracked\x00binary")

    def test_staged_rename_deletion_and_binary_addition_keep_later_unstaged_bytes(self):
        git(["-C", str(self.source), "mv", "later.txt", "renamed.txt"])
        git(["-C", str(self.source), "rm", "published.txt"])
        (self.source / "new.bin").write_bytes(b"staged\x00binary")
        git(["-C", str(self.source), "add", "new.bin"])
        (self.source / "new.bin").write_bytes(b"unstaged\x00binary")
        (self.source / "renamed.txt").write_bytes(b"unstaged rename edit\n")
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "ready")
            stage = replay._paths(body)[2]
            self.assertFalse((stage / "published.txt").exists())
            self.assertFalse((stage / "later.txt").exists())
            self.assertEqual(git(["-C", str(stage), "show", ":renamed.txt"]), b"later committed work\n")
            self.assertEqual((stage / "renamed.txt").read_bytes(), b"unstaged rename edit\n")
            self.assertEqual(git(["-C", str(stage), "show", ":new.bin"]), b"staged\x00binary")
            self.assertEqual((stage / "new.bin").read_bytes(), b"unstaged\x00binary")
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))

    def test_later_merge_topology_is_retained_for_nonconflicting_branch(self):
        data = fields(self.folder / "merge-topology", dirty=False)
        source = data[2] / "worktrees/builder.task"
        side = data[2] / "side-fixture"
        git(["--git-dir=" + str(data[3]), "worktree", "add", "-b", "builder/side", str(side), data[5]])
        (side / "side.txt").write_bytes(b"later side branch work\n")
        git(["-C", str(side), "add", "side.txt"])
        commit(side, "side branch")
        git(["-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "merge", "--no-ff", "-m", "later merge", "builder/side"])
        with replay_fixture(data) as replay:
            request(replay, data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "ready")
            stage = replay._paths(body)[2]
            self.assertEqual((stage / "side.txt").read_bytes(), b"later side branch work\n")
            self.assertEqual((stage / "later.txt").read_bytes(), b"later committed work\n")
            self.assertEqual(git(["-C", str(stage), "rev-list", "--count", "--min-parents=2", data[6] + "..HEAD"]).strip(), b"1")

    def test_unfinished_original_operation_is_preserved_and_not_aborted(self):
        pointer = Path((self.source / ".git").read_bytes()[8:-1].decode())
        (pointer / "MERGE_HEAD").write_bytes(self.data[5].encode() + b"\n")
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            with self.assertRaises(Denied):
                replay.run("replay-1")
            self.assertTrue((pointer / "MERGE_HEAD").exists())

    def test_changed_untracked_source_after_request_cannot_be_replayed_as_same_input(self):
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            (self.source / "unfinished\nnotes").write_bytes(b"newer unfinished data")
            with self.assertRaises(Denied):
                replay.run("replay-1")
            self.assertEqual((self.source / "unfinished\nnotes").read_bytes(), b"newer unfinished data")

    def test_exact_merge_reader_and_current_authority_are_mandatory(self):
        with replay_fixture(self.data) as replay:
            verify = replay.verify_merge
            for change in ({"verified_merged": False}, {"currently_authorized": False}, {"merged_sha": "f" * 40}, {"root_task_id": "other-root"}, {"scope_digest": "sha256:" + "f" * 64}):
                replay.verify_merge = lambda scope, change=change: replace(verify(scope), **change)
                with self.assertRaises(Denied):
                    request(replay, self.data)
            replay.verify_merge = verify
            request(replay, self.data)
            replay.verify_merge = lambda scope: replace(verify(scope), currently_authorized=False)
            with self.assertRaises(Denied):
                replay.run("replay-1")

    def test_stable_request_and_one_pending_per_session_cannot_retarget_merge(self):
        with replay_fixture(self.data) as replay:
            first = request(replay, self.data)
            self.assertEqual(request(replay, self.data), first)
            with self.assertRaises(Denied):
                replay.request("replay-1", self.data[1], "publication-1", published_sha=self.data[5], merged_sha=self.data[5])
            with self.assertRaises(Denied):
                request(replay, self.data, "replay-2")

    def test_writer_fence_failure_cannot_create_request_or_stage(self):
        @contextmanager
        def missing(_):
            raise Denied("synthetic stopped-writer proof unavailable")
            yield
        with replay_fixture(self.data, guard=missing) as replay:
            with self.assertRaises(Denied):
                request(replay, self.data)
            self.assertIsNone(replay.load_replay("replay-1"))

    def test_alternate_index_cannot_select_original_outside_or_linked_files(self):
        pointer = Path((self.source / ".git").read_bytes()[8:-1].decode())
        with replay_fixture(self.data) as replay:
            outside = self.folder / "outside-index"
            outside.write_bytes((pointer / "index").read_bytes())
            linked = replay.workspace.folder / "replay-index.linked"
            os.symlink(str(pointer / "index"), linked)
            for path in (pointer / "index", outside, linked):
                with self.assertRaises(Denied):
                    replay.workspace._git(self.data[3], ["status", "--porcelain"], worktree=self.source, index_file=path)

    def _death(self, point):
        folder = self.folder / point
        data = fields(folder)
        (folder / "fixture-inputs.json").write_bytes(canonical_bytes({"published": data[5], "merged": data[6]}))
        if point in {"after_replay_overlay_file", "after_replay_ready_commit"}:
            class PreparedBoundary(Exception):
                pass
            def pause(name):
                if name == "after_replay_applied_commit":
                    raise PreparedBoundary()
            with replay_fixture(data, checkpoint=pause) as replay:
                request(replay, data)
                with self.assertRaises(PreparedBoundary):
                    replay.run("replay-1")
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("post_merge_fault_fixture.py")), str(folder), point], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 73, result.stderr.decode())
        data = loaded_fields(folder)
        home = data[2]
        with replay_fixture(data) as replay:
            source = home / "worktrees/builder.task"
            self.assertEqual((source / "src/main.py").read_bytes(), b"unstaged future bytes\n")
            self.assertEqual(git(["-C", str(source), "show", ":src/main.py"]), b"staged future bytes\n")
            if point == "before_replay_request_commit":
                self.assertIsNone(replay.load_replay("replay-1"))
                return
            body = replay.run("replay-1")
            if point == "after_replay_dirty_apply_effect":
                self.assertEqual(body["phase"], "recovery_required")
                self.assertEqual(body["finding"]["reason"], "unconfirmed_dirty_apply_not_repeated")
            else:
                self.assertEqual(body["phase"], "ready")
            self.assertEqual(replay.run("replay-1"), body)

    def test_death_before_replay_request_commit(self):
        self._death("before_replay_request_commit")

    def test_death_after_replay_request_commit(self):
        self._death("after_replay_request_commit")

    def test_death_after_replay_stage_create_effect(self):
        self._death("after_replay_stage_create_effect")

    def test_death_after_replay_source_load_effect(self):
        self._death("after_replay_source_load_effect")

    def test_death_after_replay_rebase_effect(self):
        self._death("after_replay_rebase_effect")

    def test_death_after_replay_dirty_apply_effect(self):
        self._death("after_replay_dirty_apply_effect")

    def test_death_after_replay_overlay_file(self):
        self._death("after_replay_overlay_file")

    def test_death_after_replay_ready_commit(self):
        self._death("after_replay_ready_commit")
