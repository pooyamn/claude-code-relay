import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location("isolated_runner", Path(__file__).with_name("run_isolated.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def test_environment_never_inherits_tokens_or_session_identity(self):
        with mock.patch.dict(os.environ, {"HOME": "/host", "CODEX_HOME": "/host/codex",
                                         "OPENAI_API_KEY": "SYNTHETIC", "TMUX_PANE": "%99"}):
            env = runner.child_environment(Path("/scratch"), Path("/scratch/scripts"), Path("/denied"))
        for key in ("HOME", "CODEX_HOME", "OPENAI_API_KEY", "TMUX_PANE"):
            self.assertNotIn(key, env)
        self.assertEqual(env["PYTHONPATH"], "/scratch/scripts")

    def test_missing_sandbox_has_no_unsafe_fallback(self):
        for platform in ("darwin", "linux", "unsupported"):
            with mock.patch.object(runner.sys, "platform", platform), mock.patch.object(runner.shutil, "which", return_value=None):
                with self.assertRaises(RuntimeError):
                    runner.sandbox_command(Path("/scratch"), ["fixture-command"], {})

    def test_linux_command_explicitly_isolates_network_pids_and_environment(self):
        with mock.patch.object(runner.sys, "platform", "linux"), mock.patch.object(runner.shutil, "which", return_value="/usr/bin/bwrap"):
            command = runner.sandbox_command(Path("/scratch"), ["fixture-command"], {"CCRELAY_TEST": "1"})
        for argument in ("--unshare-all", "--die-with-parent", "--clearenv", "--new-session"):
            self.assertIn(argument, command)
        self.assertNotIn("--share-net", command)
        self.assertEqual(command[-2:], ["--", "fixture-command"])

    def test_only_code_and_synthetic_configuration_are_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            for name in runner.LEGACY_SOURCES:
                (source / name).write_text("fixture source", encoding="utf-8")
            (source / "tests").mkdir()
            (source / "relay_core").mkdir()
            (source / "tests" / "test_fixture.py").write_text("fixture", encoding="utf-8")
            (source / "tests" / "personal.json").write_text("SYNTHETIC SHOULD NOT COPY", encoding="utf-8")
            (source / "relay-work").mkdir()
            (source / "relay-work" / "token.env").write_text("SYNTHETIC SHOULD NOT COPY", encoding="utf-8")
            target = root / "copied"
            runner.copy_sources(source, target)
            self.assertFalse((target / "relay-work").exists())
            self.assertFalse((target / "tests" / "personal.json").exists())
            self.assertTrue((target / "tests" / "test_fixture.py").exists())
            self.assertIn("fixture/model", (target / "relay-claude-settings-ox.json").read_text())


if __name__ == "__main__":
    unittest.main()
