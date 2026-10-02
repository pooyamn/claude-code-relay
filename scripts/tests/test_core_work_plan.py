"""Root/work plan stays inert with no accidental runtime command or defaults."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from ccrelay_work import configuration
from relay_core.identity import Denied


class WorkPlanTests(unittest.TestCase):
    def test_read_only_plan_reports_unavailable_runtime_proof_and_refuses_effects(self):
        script = Path(__file__).resolve().parents[1] / "ccrelay_work.py"
        result = subprocess.run([sys.executable, "-I", str(script), "--plan"], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["component_schema"], "ccrelay.work_ownership.v1")
        self.assertEqual(plan["initial_watchdog_completed_handoffs"], 3)
        self.assertEqual(plan["state_dir"], "/var/lib/ccrelay-broker/work")
        for key in ("enabled", "automatic_turns_enabled", "state_changes", "native_calls", "task_limits_configured",
                    "evidence_verifier_available", "all_writer_verifier_available", "admission_available"):
            self.assertIs(plan[key], False)
        for args in (["--run"], ["--claim", "work-1"], ["--release", "work-1"], ["--plan", "--run"]):
            rejected = subprocess.run([sys.executable, "-I", str(script), *args], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(rejected.returncode, 0)

    def test_unsafe_paths_enabled_flags_and_other_scopes_are_not_defaulted(self):
        raw = {"schema": "ccrelay.work_config.v1", "enabled": False, "automatic_turns_enabled": False,
               "scope": "platform-owner-only", "broker_policy_path": "/etc/ccrelay/broker-policy.json", "state_dir": "/var/lib/ccrelay-broker/work"}
        self.assertEqual(configuration(raw), raw)
        for patch in ({"schema": "future"}, {"enabled": True}, {"automatic_turns_enabled": True}, {"scope": "all-companies"},
                      {"state_dir": "/"}, {"state_dir": "/tmp/../work"}, {"state_dir": "relative"}, {"state_dir": "/tmp/work//"}, {"token": "invented"}):
            with self.assertRaises(Denied):
                configuration({**raw, **patch})
