"""Real sealed bundles, deterministic setup and crashes, not native launches."""
import copy
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from native_launch_fixtures import fixture, open_store, source
from owner_fixtures import writable_fixture_tree
from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.identity import Denied, Policy
from relay_core.native_launch import inspect_package, prepare, validate_spec
from test_core_identity import policy_fields


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        patcher = mock.patch("relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = open_store(self.folder / "artifacts")
        self.policy, self.spec = fixture(self.store)

    def package(self, spec=None):
        artifact = prepare(self.store, self.policy, self.spec if spec is None else spec)
        return artifact, inspect_package(self.store, self.policy, artifact), self.store.verify(artifact)[1]

    def modified(self, path, value):
        result = copy.deepcopy(self.spec)
        target = result
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return result

    def test_exact_input_replay_is_deterministic_sealed_and_never_admitted(self):
        artifact, package, contents = self.package()
        self.assertEqual(prepare(self.store, self.policy, self.spec), artifact)
        self.assertEqual(package["spec_digest"], fingerprint(self.spec))
        self.assertEqual(package["state"], "prepared")
        for key in ("ready", "admitted", "target_verified"):
            self.assertIs(package[key], False)
        self.assertFalse(package["spec"]["automatic_turns_enabled"])
        folder = self.store._directory(artifact)
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o500)
        self.assertEqual(stat.S_IMODE((folder / "launch.json").stat().st_mode), 0o400)
        self.assertEqual(package["spec"]["provider_session_id"], "native-thread-1")
        self.assertEqual(set(contents), {item["path"] for item in package["files"]} | {"launch.json"})

    def test_role_then_repo_instructions_preserve_exact_source_and_do_not_overwrite_workspace(self):
        dirty = self.folder / "dirty-untracked.txt"
        dirty.write_bytes(b"unfinished owner work\n")
        with mock.patch("subprocess.Popen", side_effect=AssertionError("no Git/native process")):
            _, package, contents = self.package()
        text = contents[package["instruction_file"]]
        self.assertEqual(package["instruction_file"], "generated/AGENTS.override.md")
        self.assertIn(contents["inputs/role.md"], text)
        self.assertTrue(text.endswith(contents["inputs/repo.md"]))
        self.assertLess(text.index(b"Build only"), text.index(b"Keep existing"))
        self.assertLess(len(text), 32 * 1024)
        self.assertEqual(dirty.read_bytes(), b"unfinished owner work\n")

    def test_claude_keeps_its_own_candidate_context_and_no_codex_goal_capability(self):
        spec = self.modified(("provider",), "claude")
        spec["runtime"]["capabilities"] = ["exact_resume", "read"]
        spec["runtime"]["executable"] = "/opt/ccrelay/native/fixture-1/claude"
        _, package, contents = self.package(spec)
        self.assertEqual(package["instruction_file"], "generated/CLAUDE.md")
        self.assertNotIn("generated/AGENTS.override.md", contents)
        self.assertEqual(package["skills"][0]["discovery_target"], ".claude/skills/fixture-skill")

    def test_complete_skill_artifact_keeps_license_assets_and_does_not_execute_scripts(self):
        _, package, contents = self.package()
        self.assertEqual(contents["skills/fixture-skill/LICENSE"], b"Synthetic license notice must survive.\n")
        executable = next(item for item in package["files"] if item["path"].endswith("example.py"))
        self.assertTrue(executable["executable"])
        self.assertEqual(package["skills"][0]["directory"], "skills/fixture-skill/fixture-skill")
        self.assertEqual(package["skills"][0]["discovery_target"], ".agents/skills/fixture-skill")

    def test_explicit_resource_limits_are_fragments_not_installed_enforcement(self):
        _, package, contents = self.package()
        fragment = contents["generated/resources.conf"]
        for directive in (b"CPUQuota=25%", b"MemoryMax=1048576", b"TasksMax=12", b"KillMode=control-group", b"Delegate=no"):
            self.assertIn(directive, fragment)
        self.assertNotIn(b"ExecStart", fragment)
        self.assertNotIn(b"[Install]", fragment)
        self.assertFalse(package["target_verified"])
        self.assertIn(b"not_target_measurements", contents["inputs/resource-measurement"])

    def test_requested_create_is_distinct_and_does_not_become_a_resume_fallback(self):
        _, existing, _ = self.package()
        spec = self.modified(("workspace", "mode"), "create")
        spec["provider_session_id"] = None
        other_artifact, created, _ = self.package(spec)
        self.assertNotEqual(other_artifact, prepare(self.store, self.policy, self.spec))
        self.assertIsNone(created["spec"]["provider_session_id"])
        self.assertEqual(existing["spec"]["provider_session_id"], "native-thread-1")
        self.assertEqual(existing["spec"]["workspace"]["mode"], "reuse")

    def test_wrong_identity_policy_topology_scope_or_activation_denied(self):
        invalid = [("role_uid", 102), ("role_id", "reviewer"), ("broker_policy_digest", "sha256:" + "0" * 64),
                   ("scope", "company:other"), ("automatic_turns_enabled", True), ("schema", "ccrelay.native_launch_spec.v2")]
        for key, value in invalid:
            with self.subTest(key=key), self.assertRaises(Denied):
                self.package(self.modified((key,), value))
        for key, value in (("git_common_dir", "/var/lib/ccrelay/shared/git"),
                           ("git_common_dir", "/var/lib/ccrelay/roles/reviewer/repos/fixture/git"),
                           ("worktree", "/var/lib/ccrelay/roles/reviewer/worktrees/builder.task")):
            with self.subTest(key=key, value=value), self.assertRaises(Denied):
                self.package(self.modified(("workspace", key), value))

    def test_missing_unknown_fields_and_injection_paths_are_denied(self):
        spec = copy.deepcopy(self.spec)
        spec["approval"] = "owner says yes"
        with self.assertRaises(Denied):
            self.package(spec)
        del spec["approval"]
        del spec["execution_id"]
        with self.assertRaises(Denied):
            self.package(spec)
        for branch in ("reviewer/task", "builder/../bad", "builder/x.lock", "builder/.hidden", "builder/task\nExecStart=evil", "builder/x//y"):
            with self.subTest(branch=branch), self.assertRaises(Denied):
                self.package(self.modified(("workspace", "branch"), branch))
        for path in ("/opt/ccrelay/native/x%y", "/usr/bin/codex", "/opt/ccrelay/native/../evil", "/opt/ccrelay/native/tool\n"):
            with self.subTest(path=path), self.assertRaises(Denied):
                self.package(self.modified(("runtime", "executable"), path))

    def test_resources_owned_paths_and_capabilities_have_no_silent_defaults(self):
        for key in ("cpu_quota_percent", "memory_max_bytes", "tasks_max"):
            for value in (None, 0, -1, True, "12", 2**64):
                with self.subTest(key=key, value=value), self.assertRaises(Denied):
                    self.package(self.modified(("resources", key), value))
        for paths in ([], ["tests", "src"], ["src", "src"], ["../outside"], [".git"], [".agents/skills"], ["AGENTS.override.md"]):
            with self.subTest(paths=paths), self.assertRaises(Denied):
                self.package(self.modified(("workspace", "allowed_paths"), paths))
        for caps in (["goal"], ["read", "unknown"], ["read", "read"], ["read", "goal"]):
            with self.subTest(caps=caps), self.assertRaises(Denied):
                self.package(self.modified(("runtime", "capabilities"), caps))
        with self.assertRaises(Denied):
            self.package(self.modified(("provider",), "claude"))

    def test_unhashable_invalid_provider_and_mode_fail_closed(self):
        for path in (("provider",), ("workspace", "mode")):
            with self.subTest(path=path), self.assertRaises(Denied):
                self.package(self.modified(path, []))

    def test_instructions_require_nonempty_bounded_utf8(self):
        for body in (b"", b"  \n", b"\xff", b"a\x00b", b"x" * (12 * 1024 + 1)):
            reference = source(self.store, [("role.md", body, False)])
            with self.subTest(body=body[:10]), self.assertRaises(Denied):
                self.package(self.modified(("instructions", "role"), {"artifact_digest": reference, "path": "role.md"}))

    def test_source_path_missing_source_artifact_or_skill_entry_denied(self):
        for reference in ({"artifact_digest": self.spec["instructions"]["role"]["artifact_digest"], "path": "absent.md"},
                          {"artifact_digest": "sha256:" + "0" * 64, "path": "role.md"}):
            with self.subTest(reference=reference), self.assertRaises((Denied, FileNotFoundError)):
                self.package(self.modified(("instructions", "role"), reference))
        bad = source(self.store, [("fixture-skill/README.md", b"missing definition", False)])
        with self.assertRaises(Denied):
            self.package(self.modified(("skills", 0, "artifact_digest"), bad))

    def test_duplicate_unsorted_skill_refs_or_missing_resources_rejected(self):
        with self.assertRaises(Denied):
            self.package(self.modified(("skills",), [self.spec["skills"][0]] * 2))
        with self.assertRaises(Denied):
            self.package(self.modified(("resources", "measurement"), {"path": "measurement.json"}))

    def test_caller_mutation_does_not_change_validated_spec_or_prepared_package(self):
        spec = copy.deepcopy(self.spec)
        detached = validate_spec(spec, self.policy)
        artifact, original, _ = self.package(spec)
        spec["runtime"]["expected"]["runtime_digest"] = "sha256:" + "0" * 64
        self.assertEqual(detached, self.spec)
        self.assertEqual(inspect_package(self.store, self.policy, artifact), original)

    def test_forged_ready_admitted_unknown_schema_and_changed_bytes_are_not_accepted(self):
        _, package, contents = self.package()
        for key, value in (("ready", True), ("admitted", True), ("target_verified", True),
                           ("state", "running"), ("schema", "ccrelay.native_launch_package.v2")):
            altered = copy.deepcopy(package)
            altered[key] = value
            candidate = self.store.install("native-launch", [{"path": path, "content": canonical_bytes(altered) if path == "launch.json" else body,
                                   "executable": path.endswith("example.py")} for path, body in contents.items()])
            before = self.store.verify(candidate)
            with self.subTest(key=key), self.assertRaises(Denied):
                inspect_package(self.store, self.policy, candidate)
            self.assertEqual(self.store.verify(candidate), before)

    def test_source_tamper_is_rejected_without_repair_or_new_launch_package(self):
        artifact, _, _ = self.package()
        reference = self.spec["instructions"]["role"]
        path = self.store._directory(reference["artifact_digest"]) / reference["path"]
        path.chmod(0o600)
        path.write_bytes(b"altered instruction source")
        path.chmod(0o400)
        with self.assertRaises(Denied):
            inspect_package(self.store, self.policy, artifact)
        self.assertEqual(path.read_bytes(), b"altered instruction source")

    def test_changed_broker_policy_cannot_reuse_prepared_package(self):
        artifact, _, _ = self.package()
        raw = policy_fields()
        raw["roles"][0]["enabled"] = False
        with self.assertRaises(Denied):
            inspect_package(self.store, Policy(raw), artifact)

    def test_changed_generated_content_executable_flags_or_extra_files_are_denied(self):
        _, _, contents = self.package()
        for alteration in ("instructions", "executable", "extra"):
            files = [{"path": path, "content": b"substituted instructions" if alteration == "instructions" and path == "generated/AGENTS.override.md" else body,
                      "executable": path.endswith("example.py") or alteration == "executable" and path == "generated/resources.conf"}
                     for path, body in contents.items()]
            if alteration == "extra":
                files.append({"path": "extra.py", "content": b"unlisted dependency", "executable": False})
            candidate = self.store.install("native-launch", files)
            with self.subTest(alteration=alteration), self.assertRaises(Denied):
                inspect_package(self.store, self.policy, candidate)

    def test_complete_skill_tree_over_artifact_file_bound_is_not_partially_published(self):
        big = source(self.store, [("fixture-skill/SKILL.md", b"# Fixture\n", False)] +
                     [("assets/file-" + str(index), b"fixture", False) for index in range(127)])
        before = set(self.store.root.iterdir())
        with self.assertRaises(Denied):
            self.package(self.modified(("skills", 0, "artifact_digest"), big))
        self.assertEqual(set(self.store.root.iterdir()), before)

    def test_actual_process_death_before_after_publication_leaves_recoverable_unadmitted_candidate(self):
        expected, _, _ = self.package()
        for point, published in (("before_launch_artifact_install", False), ("after_launch_artifact_install", True)):
            folder = self.folder / point
            folder.mkdir(mode=0o700)
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("native_launch_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, result.stderr)
            other = open_store(folder)
            policy, spec = fixture(other)
            self.assertEqual(other._directory(expected).exists(), published)
            artifact = prepare(other, policy, spec)
            self.assertEqual(artifact, expected)
            package = inspect_package(other, policy, artifact)
            self.assertFalse(package["admitted"])
            self.assertFalse(package["ready"])
            self.assertEqual(package["spec"]["provider_session_id"], "native-thread-1")


if __name__ == "__main__":
    unittest.main()
