import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

from relay_core.identity import Denied


DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "wsl"
spec = importlib.util.spec_from_file_location("identity_plan", DEPLOY / "identity-plan.py")
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


class PlanTests(unittest.TestCase):
    def test_empty_target_plan_is_read_only_and_has_distinct_private_identities(self):
        result = planner.plan(DEPLOY, users=[], groups=[])
        self.assertFalse(result["changes_applied"])
        self.assertFalse(result["services_enabled"])
        self.assertFalse(result["owner_ingress_enabled"])
        self.assertFalse(result["bootstrap_deployment_enabled"])
        self.assertEqual(len(result["accounts"]), 11)
        self.assertEqual(len({row["uid"] for row in result["accounts"].values()}), 11)
        self.assertNotIn("/Users/pouya", {row["home"] for row in result["accounts"].values()})
        self.assertTrue(all(row["shell"] == "/usr/sbin/nologin" for row in result["accounts"].values()))

    def test_existing_uid_alias_wrong_home_or_privileged_membership_is_rejected(self):
        for name, home in (("unrelated", "/var/lib/ccrelay/roles/builder"), ("ccrelay-builder", "/Users/pouya")):
            user = SimpleNamespace(pw_name=name, pw_uid=23100, pw_gid=23100, pw_dir=home, pw_shell="/usr/sbin/nologin")
            with self.assertRaises(Denied):
                planner.plan(DEPLOY, users=[user], groups=[])
        for group in (SimpleNamespace(gr_name="sudo", gr_gid=27, gr_mem=["ccrelay-builder"]),
                      SimpleNamespace(gr_name="ccrelay-reviewer", gr_gid=23101, gr_mem=["ccrelay-builder"]),
                      SimpleNamespace(gr_name="ccrelay-clients", gr_gid=23200, gr_mem=["unregistered"])):
            with self.assertRaises(Denied):
                planner.plan(DEPLOY, users=[], groups=[group])

    def test_legacy_apply_and_bulk_copy_exit_before_any_external_operation(self):
        for name, args in (("setup-wsl.sh", ["root"]), ("setup-wsl.sh", ["user"]), ("setup-wsl.sh", ["enable"]),
                           ("pull-from-mac.sh", ["SYNTHETIC-NOT-A-HOST", "--final"])):
            result = subprocess.run(["/bin/bash", str(DEPLOY / name), *args], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 64, result.stderr)
            self.assertIn("Blocked:", result.stderr)

    def test_templates_do_not_enable_units_or_delegate_worker_cgroups(self):
        service = (DEPLOY / "systemd/ccrelay-broker.service").read_text()
        worker = (DEPLOY / "identities/session.service.in").read_text()
        self.assertNotIn("[Install]", service)
        self.assertIn("Delegate=no", worker)
        self.assertIn("ProtectControlGroups=yes", worker)
        self.assertIn("NoNewPrivileges=yes", worker)
        self.assertIn("User=ccrelay-@ROLE@", worker)
        self.assertIn("KillMode=control-group", worker)
        self.assertIn("RestrictNamespaces=yes", worker)
        owner = (DEPLOY / "systemd/ccrelay-owner-gate.service").read_text()
        self.assertNotIn("\n[Install]", owner)
        self.assertIn("User=ccrelay-deployer", owner)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", owner)

    def test_read_only_planner_cli_works_with_isolated_python(self):
        result = subprocess.run([sys.executable, "-I", str(DEPLOY / "identity-plan.py"), "--dry-run"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["mode"], "dry-run-only")
        self.assertFalse(plan["changes_applied"])

    def test_broker_entry_points_import_without_cwd_or_user_python_paths(self):
        source = Path(__file__).resolve().parent.parent
        for name in ("ccrelay_broker.py", "ccrelay_broker_mcp.py", "ccrelay_owner_gate.py"):
            result = subprocess.run([sys.executable, "-I", str(source / name), "--help"],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
