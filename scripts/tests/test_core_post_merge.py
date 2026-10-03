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
from relay_core.contracts import canonical_bytes, fingerprint
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

    def test_special_assume_unchanged_keeps_hidden_unstaged_bytes_and_flag(self):
        git(["-C", str(self.source), "update-index", "--assume-unchanged", "src/main.py"])
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "ready")
            stage = replay._paths(body)[2]
            self.assertEqual((stage / "src/main.py").read_bytes(), b"unstaged future bytes\n")
            self.assertEqual(git(["-C", str(stage), "show", ":src/main.py"]), b"staged future bytes\n")
            self.assertEqual(git(["-C", str(stage), "ls-files", "-v", "src/main.py"])[:1], b"h")
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))

    def test_special_skip_worktree_keeps_hidden_unstaged_bytes_and_flag(self):
        git(["-C", str(self.source), "update-index", "--skip-worktree", "src/main.py"])
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "ready")
            stage = replay._paths(body)[2]
            self.assertEqual((stage / "src/main.py").read_bytes(), b"unstaged future bytes\n")
            self.assertEqual(git(["-C", str(stage), "show", ":src/main.py"]), b"staged future bytes\n")
            self.assertEqual(git(["-C", str(stage), "ls-files", "-v", "src/main.py"])[:1], b"S")
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))

    def test_special_intent_to_add_keeps_unstaged_binary_and_intent_flag(self):
        (self.source / "intent\nfile.bin").write_bytes(b"unfinished\x00binary")
        git(["-C", str(self.source), "add", "--intent-to-add", "intent\nfile.bin"])
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "ready")
            stage = replay._paths(body)[2]
            self.assertEqual((stage / "intent\nfile.bin").read_bytes(), b"unfinished\x00binary")
            self.assertIn(b"flags: 20004000", git(["-C", str(stage), "ls-files", "--debug", "intent\nfile.bin"]))
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))

    def test_special_combined_flags_and_missing_assume_file_keep_staged_state(self):
        git(["-C", str(self.source), "update-index", "--assume-unchanged", "src/main.py", "later.txt"])
        git(["-C", str(self.source), "update-index", "--skip-worktree", "src/main.py"])
        (self.source / "later.txt").unlink()
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "ready")
            stage = replay._paths(body)[2]
            self.assertEqual((stage / "src/main.py").read_bytes(), b"unstaged future bytes\n")
            self.assertEqual(git(["-C", str(stage), "ls-files", "-v", "src/main.py"])[:1], b"s")
            self.assertFalse((stage / "later.txt").exists())
            self.assertEqual(git(["-C", str(stage), "show", ":later.txt"]), b"later committed work\n")
            self.assertEqual(git(["-C", str(stage), "ls-files", "-v", "later.txt"])[:1], b"h")
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))

    def test_special_missing_skip_file_stays_index_only_not_deleted(self):
        git(["-C", str(self.source), "update-index", "--skip-worktree", "src/main.py"])
        (self.source / "src/main.py").unlink()
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "ready")
            stage = replay._paths(body)[2]
            self.assertFalse((stage / "src/main.py").exists())
            self.assertEqual(git(["-C", str(stage), "show", ":src/main.py"]), b"staged future bytes\n")
            self.assertEqual(git(["-C", str(stage), "ls-files", "-v", "src/main.py"])[:1], b"S")
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))

    def test_special_absent_empty_executable_and_literal_intent_paths_are_not_staged(self):
        paths = ["absent", "empty", "-exec[?]*\nfile"]
        for name in paths:
            (self.source / name).write_bytes(b"" if name != paths[2] else b"unfinished executable\n")
        (self.source / paths[2]).chmod(0o700)
        git(["-C", str(self.source), "--literal-pathspecs", "add", "--intent-to-add", "--", *paths])
        (self.source / "absent").unlink()
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "ready")
            stage = replay._paths(body)[2]
            self.assertFalse((stage / "absent").exists())
            self.assertEqual((stage / "empty").read_bytes(), b"")
            self.assertEqual((stage / paths[2]).read_bytes(), b"unfinished executable\n")
            for name in paths:
                raw = git(["-C", str(stage), "--literal-pathspecs", "ls-files", "--stage", "--debug", "--", name])
                self.assertIn(b"flags: 20004000", raw)
                self.assertTrue(raw.startswith(b"100755" if name == paths[2] else b"100644"))
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))

    def test_special_intent_collision_preserves_upstream_and_original_versions(self):
        data = fields(self.folder / "intent-collision", conflict="untracked")
        source = data[2] / "worktrees/builder.task"
        git(["-C", str(source), "add", "--intent-to-add", "unfinished\nnotes"])
        with replay_fixture(data) as replay:
            request(replay, data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "conflicted")
            stage = replay._paths(body)[2]
            self.assertEqual((stage / "unfinished\nnotes").read_bytes(), b"upstream owns this path\n")
            self.assertEqual((source / "unfinished\nnotes").read_bytes(), b"untracked\x00binary")
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))

    def test_special_complete_read_only_overlay_survives_restoration_revalidation(self):
        (self.source / "unfinished\nnotes").chmod(0o400)
        (self.source / "empty-dir").chmod(0o500)
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "ready")
            stage = replay._paths(body)[2]
            self.assertEqual((stage / "unfinished\nnotes").read_bytes(), b"untracked\x00binary")
            self.assertEqual((stage / "unfinished\nnotes").stat().st_mode & 0o777, 0o400)
            self.assertEqual((stage / "empty-dir").stat().st_mode & 0o777, 0o500)
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))

    def test_index_manifest_rejects_rehashed_row_and_missing_entry(self):
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            path, raw, hashed = replay.connection.execute("SELECT path,body,digest FROM replay_index_entries WHERE id=? ORDER BY path LIMIT 1", (body["id"],)).fetchone()
            from relay_core.identity import strict_json
            entry = strict_json(raw)
            entry["present"] = not entry["present"]
            replay.connection.execute("UPDATE replay_index_entries SET body=?,digest=? WHERE id=? AND path=?", (canonical_bytes(entry), fingerprint(entry), body["id"], path))
            with self.assertRaises(Denied):
                replay.run("replay-1")
            replay.connection.execute("UPDATE replay_index_entries SET body=?,digest=? WHERE id=? AND path=?", (raw, hashed, body["id"], path))
            replay.connection.execute("DELETE FROM replay_index_entries WHERE id=? AND path=?", (body["id"], path))
            with self.assertRaises(Denied):
                replay.load_replay("replay-1")
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))

    def test_changed_complete_read_only_overlay_is_retained_as_conflict(self):
        (self.source / "unfinished\nnotes").chmod(0o400)
        changed = b"changed!\x00content"
        self.assertEqual(len(changed), len((self.source / "unfinished\nnotes").read_bytes()))
        def corrupt(point):
            if point == "after_replay_restoring_index_commit":
                target = replay._paths(replay.load_replay("replay-1"))[2] / "unfinished\nnotes"
                target.chmod(0o600)
                target.write_bytes(changed)
                target.chmod(0o400)
        with replay_fixture(self.data, checkpoint=corrupt) as replay:
            request(replay, self.data)
            body = replay.run("replay-1")
            self.assertEqual(body["phase"], "conflicted")
            self.assertIn("overlay bytes disagree", body["finding"]["reason"])
            stage = replay._paths(body)[2]
            self.assertEqual((stage / "unfinished\nnotes").read_bytes(), changed)
            self.assertEqual((stage / "unfinished\nnotes").stat().st_mode & 0o777, 0o400)
            self.assertEqual((self.source / "unfinished\nnotes").read_bytes(), b"untracked\x00binary")
            self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))
            self.assertEqual(replay.run("replay-1"), body)

    def test_old_replay_schema_is_preserved_without_automatic_migration(self):
        with replay_fixture(self.data) as replay:
            request(replay, self.data)
            path = replay.path
            replay.connection.execute("UPDATE replay_metadata SET schema='ccrelay.post_merge.v1'")
        original = path.read_bytes()
        with self.assertRaises(Denied):
            with replay_fixture(self.data):
                pass
        self.assertEqual(path.read_bytes(), original)

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
        special_index = point in {"after_replay_index_flags_effect", "after_replay_intent_placeholder_effect", "after_replay_intent_index_effect", "after_replay_intent_absence_effect"}
        if special_index:
            source = data[2] / "worktrees/builder.task"
            git(["-C", str(source), "update-index", "--assume-unchanged", "src/main.py"])
            (source / "absent-intent").write_bytes(b"unfinished intent\n")
            git(["-C", str(source), "add", "--intent-to-add", "absent-intent"])
            (source / "absent-intent").unlink()
            if point == "after_replay_index_flags_effect":
                (source / "unfinished\nnotes").chmod(0o400)
                (source / "empty-dir").chmod(0o500)
        (folder / "fixture-inputs.json").write_bytes(canonical_bytes({"published": data[5], "merged": data[6]}))
        if point in {"after_replay_overlay_file", "after_replay_ready_commit"} or special_index:
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
            if special_index:
                stage = replay._paths(body)[2]
                self.assertEqual((stage / "src/main.py").read_bytes(), b"unstaged future bytes\n")
                self.assertEqual(git(["-C", str(stage), "ls-files", "-v", "src/main.py"])[:1], b"h")
                self.assertFalse((stage / "absent-intent").exists())
                self.assertIn(b"flags: 20004000", git(["-C", str(stage), "ls-files", "--debug", "absent-intent"]))
                self.assertTrue(replay.snapshots.current(body["source_checkpoint"]))
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

    def test_death_after_replay_index_flags_effect(self):
        self._death("after_replay_index_flags_effect")

    def test_death_after_replay_intent_placeholder_effect(self):
        self._death("after_replay_intent_placeholder_effect")

    def test_death_after_replay_intent_index_effect(self):
        self._death("after_replay_intent_index_effect")

    def test_death_after_replay_intent_absence_effect(self):
        self._death("after_replay_intent_absence_effect")
