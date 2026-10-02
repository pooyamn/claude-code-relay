"""Real worker-owned setup files/links and deaths, no native loading or models."""
import copy
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from native_launch_fixtures import open_store
from native_workspace_fixtures import fixture_fields, git, open_workspace
from owner_fixtures import writable_fixture_tree
from relay_core.identity import Denied
from relay_core.native_launch import prepare
from relay_core.native_setup import WorktreeSetup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        patcher = mock.patch("relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.policy, self.spec, self.home, self.common, self.contract = fixture_fields(self.folder)
        self.store = open_store(self.folder / "inputs")
        self.bundle = prepare(self.store, self.policy, self.spec)
        self.target = self.home / "worktrees/builder.task"

    def apply(self, workspace, bundle=None):
        with WorktreeSetup(workspace) as setup:
            return setup.apply(self.store, self.bundle if bundle is None else bundle)

    def test_actual_codex_files_and_complete_skill_assets_are_installed_without_execution(self):
        with open_workspace(self.policy, self.home, self.contract) as workspace:
            workspace.prepare(self.spec)
            result = self.apply(workspace)
            self.assertEqual(self.apply(workspace), result)
        self.assertTrue(result["files_installed"])
        for key in ("native_loaded", "runtime_ready", "admitted"):
            self.assertFalse(result[key])
        instructions = self.target / "AGENTS.override.md"
        self.assertTrue(instructions.is_symlink())
        self.assertIn(b"Build only the assigned change", instructions.read_bytes())
        skill = self.target / ".agents/skills/fixture-skill"
        self.assertTrue(skill.is_symlink())
        self.assertTrue((skill / "SKILL.md").is_file())
        self.assertEqual((skill / "../LICENSE").read_bytes(), b"Synthetic license notice must survive.\n")
        self.assertEqual(stat.S_IMODE((skill / "scripts/example.py").stat().st_mode), 0o500)
        self.assertFalse((self.target / "CLAUDE.md").exists())

    def test_claude_uses_its_own_context_and_skill_discovery_paths(self):
        spec = copy.deepcopy(self.spec)
        spec["provider"] = "claude"
        spec["runtime"]["capabilities"] = ["exact_resume", "read"]
        spec["runtime"]["executable"] = "/opt/ccrelay/native/fixture-1/claude"
        bundle = prepare(self.store, self.policy, spec)
        with open_workspace(self.policy, self.home, self.contract) as workspace:
            workspace.prepare(spec)
            result = self.apply(workspace, bundle)
        self.assertEqual(result["links"], ["CLAUDE.md", ".claude/skills/fixture-skill"])
        self.assertTrue((self.target / "CLAUDE.md").is_symlink())
        self.assertTrue((self.target / ".claude/skills/fixture-skill/SKILL.md").is_file())
        self.assertFalse((self.target / "AGENTS.override.md").exists())

    def test_existing_instruction_collision_preserves_bytes_and_does_not_register_setup(self):
        with open_workspace(self.policy, self.home, self.contract) as workspace:
            workspace.prepare(self.spec)
            instructions = self.target / "AGENTS.override.md"
            instructions.write_bytes(b"existing project instructions\n")
            with WorktreeSetup(workspace) as setup:
                with self.assertRaises(Denied):
                    setup.apply(self.store, self.bundle)
                self.assertIsNone(setup._row("builder.task"))
            self.assertEqual(instructions.read_bytes(), b"existing project instructions\n")
            self.assertFalse((self.target / ".agents").exists())

    def test_symlinked_parent_cannot_redirect_setup_outside_worktree(self):
        with open_workspace(self.policy, self.home, self.contract) as workspace:
            workspace.prepare(self.spec)
            outside = self.home / "outside"
            outside.mkdir(mode=0o700)
            (self.target / ".agents").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(Denied):
                self.apply(workspace)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse((self.target / "AGENTS.override.md").exists())

    def test_dirty_files_index_and_merge_marker_are_unchanged_by_install_and_replay(self):
        with open_workspace(self.policy, self.home, self.contract) as workspace:
            workspace.prepare(self.spec)
            tracked = self.target / "src/main.py"
            tracked.write_bytes(b"staged work\n")
            git(["-C", str(self.target), "add", "src/main.py"])
            tracked.write_bytes(b"unstaged work\n")
            metadata = Path((self.target / ".git").read_text().strip()[8:])
            (metadata / "MERGE_HEAD").write_bytes(self.spec["workspace"]["base_commit"].encode() + b"\n")
            paths = [tracked, metadata / "index", metadata / "MERGE_HEAD"]
            before = {path: path.read_bytes() for path in paths}
            self.apply(workspace)
            self.apply(workspace)
            self.assertEqual({path: path.read_bytes() for path in paths}, before)

    def test_no_setup_without_exact_prepared_workspace_or_with_changed_spec(self):
        with open_workspace(self.policy, self.home, self.contract) as workspace:
            with self.assertRaises(Denied):
                self.apply(workspace)
            workspace.prepare(self.spec)
            spec = copy.deepcopy(self.spec)
            spec["execution_id"] = "other-execution"
            other = prepare(self.store, self.policy, spec)
            with self.assertRaises(Denied):
                self.apply(workspace, other)
            self.assertFalse((self.target / "AGENTS.override.md").exists())

    def test_changed_link_or_missing_recorded_link_is_not_repaired_silently(self):
        with open_workspace(self.policy, self.home, self.contract) as workspace:
            workspace.prepare(self.spec)
            self.apply(workspace)
            link = self.target / "AGENTS.override.md"
            link.unlink()
            link.symlink_to(self.home / "unexpected")
            with self.assertRaises(Denied):
                self.apply(workspace)
            self.assertEqual(os.readlink(link), str(self.home / "unexpected"))
            link.unlink()
            with self.assertRaises(Denied):
                self.apply(workspace)
            self.assertFalse(link.exists())

    def test_future_setup_schema_preserves_database_bytes(self):
        with open_workspace(self.policy, self.home, self.contract) as workspace:
            workspace.prepare(self.spec)
            with WorktreeSetup(workspace) as setup:
                setup.connection.execute("UPDATE setup_metadata SET schema='future.setup.v9'")
            database = self.home / "native-setup/outbox.sqlite"
            before = database.read_bytes()
            with self.assertRaises(Denied):
                WorktreeSetup(workspace)
            self.assertEqual(database.read_bytes(), before)

    def test_actual_deaths_reconcile_same_bundle_and_links_without_resetting_work(self):
        points = ("after_setup_register_commit", "after_setup_bundle_copy", "after_setup_copied_commit",
                  "after_setup_link_0", "after_setup_link_1", "after_setup_linked_commit")
        for point in points:
            folder = self.folder / point
            policy, spec, home, common, contract = fixture_fields(folder)
            store = open_store(folder / "inputs")
            bundle = prepare(store, policy, spec)
            with open_workspace(policy, home, contract) as workspace:
                workspace.prepare(spec)
            target = home / "worktrees/builder.task"
            (target / "src/main.py").write_bytes(b"unfinished work survives\n")
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("native_setup_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, result.stderr)
            with open_workspace(policy, home, contract) as workspace, WorktreeSetup(workspace) as setup:
                observation = setup.apply(store, bundle)
                self.assertEqual(setup._row("builder.task")["phase"], "linked")
                self.assertEqual(observation["bundle_digest"], bundle)
                self.assertFalse(observation["native_loaded"])
            self.assertEqual((target / "src/main.py").read_bytes(), b"unfinished work survives\n")
            self.assertTrue((target / "AGENTS.override.md").is_symlink())
            self.assertTrue((target / ".agents/skills/fixture-skill/SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
