"""Release-local legacy launcher checks; no live bot, session or native CLI."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class LegacyReleaseTests(unittest.TestCase):
    def run_launcher(self, *, pinned):
        with tempfile.TemporaryDirectory(prefix="release with spaces-") as temporary:
            root = Path(temporary).resolve()
            scripts, project, binaries = root / "scripts", root / "project", root / "bin"
            for folder in (scripts, project, binaries, scripts / "relay-work"):
                folder.mkdir()
            shutil.copy2(Path(__file__).parents[1] / "claude-relay-group", scripts / "claude-relay-group")
            key = "cr-" + hashlib.md5(str(project).encode()).hexdigest()[:10]
            state = scripts / "relay-work"
            if pinned:
                (state / f"default-model-{key}.txt").write_text("cx\n")
            else:
                (state / f"backend-{key}.json").write_text('{"backend":"codex"}')
            (scripts / "relay-claude-settings-cx.json").write_text('{"model":"fixture-model"}')
            (scripts / "claude-relay-send.py").write_text(
                "import json, os, sys\n"
                "print(json.dumps({'script':__file__, 'args':sys.argv[1:], 'session':os.environ['CLAUDE_RELAY_SESSION']}))\n")
            # Existing watcher: no launch, no native process and no tmux server.
            (binaries / "tmux").write_text("#!/bin/sh\n[ \"$1\" = has-session ]\n")
            (binaries / "tmux").chmod(0o700)
            (binaries / "python3").symlink_to(sys.executable)
            environment = {**os.environ, "PATH": str(binaries) + ":/usr/bin:/bin:/usr/sbin:/sbin"}
            result = subprocess.run(["/bin/bash", str(scripts / "claude-relay-group"), str(project), "/goal status"],
                                    capture_output=True, text=True, env=environment, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = json.loads(result.stdout)
            self.assertEqual(actual, {"script":str(scripts / "claude-relay-send.py"),
                                      "args":["/goal status"], "session":key})
            self.assertEqual(json.loads((state / f"backend-{key}.json").read_text()),
                             {"backend":"codex", "model":"fixture-model"})

    def test_codex_backend_uses_the_invoked_release_with_spaces(self):
        self.run_launcher(pinned=False)

    def test_codex_pin_uses_the_invoked_release_with_spaces(self):
        self.run_launcher(pinned=True)

    def test_no_launcher_path_can_escape_to_the_shared_mac_installation(self):
        source = (Path(__file__).parents[1] / "claude-relay-group").read_text()
        self.assertNotIn("/Users/pouya", source)
        self.assertIn('DIR0="$DIR"', source)
        self.assertIn('RW="$RW0"', source)
        self.assertIn('SETTINGS="$DIR/relay-claude-settings.json"', source)
        self.assertIn('python3 "$DIR/relay-alt-launch"', source)
