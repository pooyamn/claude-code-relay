"""Read-only/fail-closed contracts; actual root fixture runs separately on WSL."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


class DrillPreparationTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(__file__).resolve().parents[2] / "deploy" / "wsl"
        self.environment = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}

    def test_default_python_and_shell_paths_only_print_no_change_plan(self):
        for command in ([sys.executable, "-I", str(self.folder / "identity-drill.py")],
                        ["/bin/sh", str(self.folder / "run-identity-drill.sh")]):
            result = subprocess.run(command, env=self.environment, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            plan = json.loads(result.stdout)
            self.assertEqual(plan["mode"], "plan-only")
            self.assertIs(plan["changes_applied"], False)
            self.assertEqual(plan["uids"], {"builder": 23100, "reviewer": 23101, "cto": 23102})

    def test_run_outside_restricted_root_service_fails_before_fixture_changes(self):
        result = subprocess.run([sys.executable, "-I", str(self.folder / "identity-drill.py"),
                                 "--run", "--fixture-root", "/run/ccrelay-identity-proof-000000000000"],
                                env=self.environment, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"restricted root transient service required", result.stderr)

    def test_transient_manager_never_installs_accounts_models_or_persistent_units(self):
        script = (self.folder / "run-identity-drill.sh").read_text()
        for required in ("--wait --pipe --collect", "RuntimeMaxSec=30s", "MemoryMax=128M",
                         "TasksMax=24", "NoNewPrivileges=yes", "PrivateNetwork=yes",
                         "ProtectControlGroups=yes", "RestrictNamespaces=yes", "Delegate=no",
                         "KillMode=control-group", "-/mnt -/init -/run/WSL", "python3 -I"):
            self.assertIn(required, script)
        for forbidden in ("useradd", "groupadd", "systemctl enable", "codex", "claude", "curl"):
            self.assertNotIn(forbidden, script)


if __name__ == "__main__":
    unittest.main()
