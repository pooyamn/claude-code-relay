"""Target native preparation cannot start/control an existing session."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from ccrelay_native import configuration
from relay_core.identity import Denied


class NativePlanTests(unittest.TestCase):
    def test_read_only_plan_has_no_native_calls_or_admission_and_refuses_runtime_cli(self):
        source = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, "-I", str(source / "ccrelay_native.py"), "--plan"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        for key in ("enabled", "automatic_turns_enabled", "native_calls", "state_changes", "admission_available",
                    "launch_package_activated", "resource_limits_enforced", "workspace_helper_activated", "setup_helper_activated"):
            self.assertIs(plan[key], False)
        self.assertEqual(plan["launch_package_schema"], "ccrelay.native_launch_package.v1")
        self.assertEqual(plan["workspace_journal_schema"], "ccrelay.native_workspace_journal.v1")
        self.assertEqual(plan["setup_journal_schema"], "ccrelay.native_setup_journal.v1")
        self.assertIn("builder", plan["role_profiles_not_active_sessions"])
        self.assertEqual(plan["state_dir"], "/var/lib/ccrelay-broker/native")
        for args in (["--run"], ["--resume", "native-thread-1"], ["--goal", "invented goal"]):
            result = subprocess.run([sys.executable, "-I", str(source / "ccrelay_native.py"), *args],
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)

    def test_enabled_automation_company_scope_and_unsafe_paths_are_not_silently_defaulted(self):
        raw = {"schema": "ccrelay.native_registry_config.v1", "enabled": False, "automatic_turns_enabled": False,
               "scope": "platform-owner-only", "broker_policy_path": "/etc/ccrelay/broker-policy.json",
               "state_dir": "/var/lib/ccrelay-broker/native"}
        self.assertEqual(configuration(raw), raw)
        for changes in ({"enabled": True}, {"automatic_turns_enabled": True}, {"scope": "all-companies"},
                        {"state_dir": "/"}, {"state_dir": "relative"}, {"state_dir": "/tmp/../native"},
                        {"state_dir": "/tmp/native//"}, {"credential": "invented"}, {"schema": "future"}):
            with self.subTest(changes=changes), self.assertRaises(Denied):
                configuration({**raw, **changes})
