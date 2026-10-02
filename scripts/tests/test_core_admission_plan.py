"""Admission plan remains disabled and invents no numerical pacing choices."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from ccrelay_admission import configuration
from relay_core.identity import Denied


class AdmissionPlanTests(unittest.TestCase):
    def test_plan_is_inert_without_model_quota_or_probe_calls(self):
        path = Path(__file__).resolve().parents[1] / "ccrelay_admission.py"
        result = subprocess.run([sys.executable, "-I", str(path), "--plan"], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["component_schema"], "ccrelay.model_admission.v1")
        self.assertEqual(plan["capacity_journal_schema"], "ccrelay.capacity_journal.v1")
        self.assertEqual((plan["active_cap"], plan["owner_reserve_percent"]), (3, 10))
        self.assertEqual(plan["work_state_dir"], "/var/lib/ccrelay-broker/work")
        for key in ("enabled", "automatic_turns_enabled", "state_changes", "native_calls", "quota_calls", "pacing_values_configured",
                    "all_source_fence_available", "quota_adapter_available", "source_verifier_available", "stop_verifier_available",
                    "capacity_retry_activated", "capacity_verifier_available"):
            self.assertIs(plan[key], False)
        for args in (["--run"], ["--claim", "turn-1"], ["--plan", "--run"]):
            rejected = subprocess.run([sys.executable, "-I", str(path), *args], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(rejected.returncode, 0)

    def test_unsafe_configuration_is_not_defaulted_or_activated(self):
        raw = {"schema": "ccrelay.admission_config.v1", "enabled": False, "automatic_turns_enabled": False, "scope": "platform-owner-only",
               "broker_policy_path": "/etc/ccrelay/broker-policy.json", "work_state_dir": "/var/lib/ccrelay-broker/work",
               "minimum_gap_ms": None, "quota_max_age_ms": None, "activity_max_age_ms": None}
        self.assertEqual(configuration(raw), raw)
        for patch in ({"schema": "future"}, {"enabled": True}, {"automatic_turns_enabled": True}, {"scope": "all-companies"},
                      {"work_state_dir": "/"}, {"work_state_dir": "/tmp/../admission"}, {"work_state_dir": "relative"},
                      {"minimum_gap_ms": 0}, {"quota_max_age_ms": False}, {"activity_max_age_ms": -1}, {"token": "invented"}):
            with self.assertRaises(Denied):
                configuration({**raw, **patch})
