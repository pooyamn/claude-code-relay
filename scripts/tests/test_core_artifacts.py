"""Real sealed scratch artifacts/crashes; fake owner and screening provenance."""
import base64
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from relay_core.artifacts import BootstrapDeployer, DeploymentPolicy
from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.identity import Denied
from relay_core import screening
from owner_fixtures import (GATE, ROOT, action, approved, deployment_fields, open_ledger, open_store,
                            screen_report, source, writable_fixture_tree)


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        (self.folder / "ledger").mkdir(mode=0o700)
        (self.folder / "artifacts").mkdir(mode=0o700)
        # Only protected ancestor observations are mocked in Mac scratch. Actual
        # file modes, bytes, SQLite, locks, rename and process death are exercised.
        self.patcher = mock.patch("relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.store = open_store(self.folder / "artifacts")
        self.ledger = open_ledger(self.folder / "ledger")
        self.addCleanup(self.ledger.close)
        self.policy = DeploymentPolicy(deployment_fields())
        self.deployer = BootstrapDeployer(self.policy, self.store, self.ledger)

    def candidate(self, body=b"fixture code", component="router", path="render/main.py"):
        return self.store.install(component, source(body, path))

    def intent(self, artifact_digest=None, *, verdict="clear", exception=None):
        artifact_digest = artifact_digest or self.candidate()
        report = screen_report(self.store, artifact_digest, verdict)
        parameters = self.deployer.plan(artifact_digest, report, screening_exception=exception)
        return action(parameters, kind="deploy_artifact")

    def activate(self, intent):
        approved(self.ledger, intent)
        return self.deployer.activate(GATE, intent.id, "attempt-1")

    def test_complete_content_addressed_tree_is_sealed_and_install_replay_verified(self):
        files = [*source(), {"path": "bin/run", "content": b"fixture executable", "executable": True}]
        artifact_digest = self.store.install("router", files)
        manifest, contents = self.store.verify(artifact_digest)
        self.assertEqual(fingerprint(manifest), artifact_digest)
        self.assertEqual(contents["bin/run"], b"fixture executable")
        root = self.store._directory(artifact_digest)
        self.assertEqual(stat.S_IMODE((root / "bin/run").stat().st_mode), 0o500)
        self.assertEqual(stat.S_IMODE((root / "render/main.py").stat().st_mode), 0o400)
        self.assertEqual(self.store.install("router", list(reversed(files))), artifact_digest)

    def test_path_traversal_duplicate_collisions_links_and_size_not_extracted(self):
        for name in (".", "..", "../outside", "/absolute", "a//b", "./a", "a/./b", "a/../b", "a\\b", "a\nb", "manifest.json", "manifest.json/evil"):
            with self.subTest(path=name), self.assertRaises(Denied):
                self.store.install("router", source(path=name))
        for files in ([*source(), *source()], [*source(path="a"), *source(path="a/b")],
                      source(body=b"x" * (1024 * 1024 + 1)), []):
            with self.assertRaises(Denied):
                self.store.install("router", files)

    def test_modified_bytes_manifest_extra_entries_symlink_hardlink_and_modes_denied(self):
        for corruption in ("bytes", "manifest", "extra", "symlink", "hardlink", "mode", "directory"):
            with self.subTest(corruption=corruption):
                artifact_digest = self.candidate(corruption.encode())
                root = self.store._directory(artifact_digest)
                file = root / "render/main.py"
                os.chmod(root, 0o700)
                os.chmod(file.parent, 0o700)
                if corruption == "bytes":
                    os.chmod(file, 0o600)
                    file.write_bytes(b"malicious replacement")
                    os.chmod(file, 0o400)
                elif corruption == "manifest":
                    manifest = root / "manifest.json"
                    os.chmod(manifest, 0o600)
                    manifest.write_bytes(b'{"schema":"ccrelay.artifact.v999"}')
                    os.chmod(manifest, 0o400)
                elif corruption == "extra":
                    (root / "unreviewed.py").write_bytes(b"extra import")
                elif corruption == "symlink":
                    file.unlink()
                    file.symlink_to(root / "manifest.json")
                elif corruption == "hardlink":
                    os.link(file, root / "extra-link")
                elif corruption == "mode":
                    os.chmod(file, 0o600)
                elif corruption == "directory":
                    os.chmod(file.parent, 0o700)
                os.chmod(root, 0o500)
                if corruption != "directory":
                    os.chmod(file.parent, 0o500)
                with self.assertRaises((Denied, OSError)):
                    self.store.verify(artifact_digest)

    def test_classifier_uses_installed_policy_and_full_added_deleted_tree(self):
        base_id = self.candidate(component="presentation")
        candidate_id = self.candidate(b"next", component="presentation")
        base = self.store.verify(base_id)[0]
        candidate = self.store.verify(candidate_id)[0]
        classification = self.policy.classify(candidate, base)
        self.assertEqual(classification["class"], "routine")
        self.assertEqual(self.policy.classify(candidate, None)["class"], "protected")
        router1 = self.candidate(b"one")
        router2 = self.candidate(b"two")
        self.assertIn("credential_boundary", self.policy.classify(self.store.verify(router2)[0], self.store.verify(router1)[0])["reasons"])
        protected = self.store.install("presentation", [*source(), *source(b"policy", "authorization/policy.json")])
        self.assertEqual(self.policy.classify(candidate, self.store.verify(protected)[0])["class"], "protected")
        injected = self.store.install("presentation", source(b'{"routine_enabled":true}', "deployment-policy.json"))
        self.assertEqual(self.policy.classify(self.store.verify(injected)[0], base)["class"], "protected")

    def test_routine_gate_cannot_be_enabled_by_candidate_or_policy_v1(self):
        with self.assertRaises(Denied):
            DeploymentPolicy({**deployment_fields(), "routine_enabled": True})
        unknown = self.candidate(component="not-installed-component")
        with self.assertRaises(Denied):
            self.deployer.plan(unknown, screen_report(self.store, unknown))

    def test_artifact_install_and_activation_are_serialized_by_protected_lifetime_lock(self):
        with self.store.locked(), self.assertRaises(BlockingIOError):
            with self.store.locked():
                self.fail("second installer obtained the lock")

    def test_explicit_known_secret_masking_binds_the_same_candidate_payload_at_activation(self):
        known = "SYNTHETIC-literal-private-value"
        artifact_digest = self.candidate(known.encode())
        deployer = BootstrapDeployer(self.policy, self.store, self.ledger, known_secrets=[known])
        report = screen_report(self.store, artifact_digest, known_secrets=[known])
        parameters = deployer.plan(artifact_digest, report)
        intent = action(parameters, kind="deploy_artifact")
        approved(self.ledger, intent)
        self.assertEqual(deployer.activate(GATE, intent.id, "attempt-1").fields["state"], "confirmed")

    def test_changed_screening_artifact_or_payload_and_invented_exception_fail_closed(self):
        artifact_digest = self.candidate()
        report = screen_report(self.store, artifact_digest)
        for key in ("artifact_digest", "payload_digest"):
            with self.assertRaises(Denied):
                self.deployer.plan(artifact_digest, {**report, key: "changed"})
        with self.assertRaises(Denied):
            self.deployer.plan(artifact_digest, report, screening_exception="unnecessary waiver")

    def test_disabled_bootstrap_policy_cannot_install_a_pointer_despite_owner_approval(self):
        intent = self.intent()
        approved(self.ledger, intent)
        disabled = BootstrapDeployer(DeploymentPolicy({**deployment_fields(), "bootstrap_enabled": False}), self.store, self.ledger)
        with self.assertRaises(Denied):
            disabled.activate(GATE, intent.id, "attempt-1")
        self.assertIsNone(self.store.active("router"))

    def test_clear_screening_never_replaces_owner_approval_even_for_cosmetic_router_code(self):
        intent = self.intent()
        self.ledger.enroll(ROOT, intent.to_dict(), "approval-1", "2026-10-02T05:00:00Z")
        with self.assertRaises(Denied):
            self.deployer.activate(GATE, intent.id, "attempt-1")
        self.assertIsNone(self.store.active("router"))

    def test_flagged_unavailable_uncertain_incomplete_require_explicit_owner_exception(self):
        artifact_digest = self.candidate()
        for verdict in ("flagged", "unavailable", "uncertain", "incomplete"):
            report = screen_report(self.store, artifact_digest, verdict)
            with self.assertRaises(Denied):
                self.deployer.plan(artifact_digest, report)
            planned = self.deployer.plan(artifact_digest, report, screening_exception="Owner must review exact fixture risk")
            self.assertEqual(planned["screening"]["verdict"], verdict)
        intent = self.intent(artifact_digest, verdict="unavailable", exception="Explicit bootstrap exception; no Jev claim")
        self.assertEqual(self.activate(intent).fields["state"], "confirmed")

    def test_owner_bootstrap_pointer_install_does_not_execute_candidate_or_restart_service(self):
        artifact_digest = self.candidate(b"raise RuntimeError('candidate must never run in deployer')")
        intent = self.intent(artifact_digest)
        result = self.activate(intent)
        self.assertEqual(result.fields["state"], "confirmed")
        active = self.store.active("router")
        self.assertEqual(active["artifact_digest"], artifact_digest)
        self.assertEqual(active["action_id"], intent.id)
        with self.assertRaises(Denied):
            self.deployer.activate(GATE, intent.id, "attempt-1")

    def test_altered_candidate_policy_screening_parameters_do_not_reuse_approval(self):
        intent = self.intent()
        approved(self.ledger, intent)
        changed_policy = deployment_fields()
        changed_policy["components"][0]["credentialed"] = False
        other = BootstrapDeployer(DeploymentPolicy(changed_policy), self.store, self.ledger)
        with self.assertRaises(Denied):
            other.activate(GATE, intent.id, "attempt-1")
        # Physical mutation cannot pass the immutable store verification either.
        root = self.store._directory(intent.fields["parameters"]["artifact_digest"])
        file = root / "render/main.py"
        os.chmod(file, 0o600)
        file.write_bytes(b"changed bytes")
        os.chmod(file, 0o400)
        with self.assertRaises(Denied):
            self.deployer.activate(GATE, intent.id, "attempt-1")
        self.assertEqual(self.ledger.load(intent.id)[1].fields["state"], "granted")

    def test_changed_current_base_invalidates_prepared_owner_decision(self):
        first_id = self.candidate(b"first")
        second_id = self.candidate(b"second")
        stale = self.intent(second_id)
        approved(self.ledger, stale)
        first = action(self.deployer.plan(first_id, screen_report(self.store, first_id)), id="action-2", kind="deploy_artifact")
        approved(self.ledger, first, "approval-2", update_id=20, message_id=21)
        self.deployer.activate(GATE, first.id, "attempt-2")
        with self.assertRaises(Denied):
            self.deployer.activate(GATE, stale.id, "attempt-1")

    def test_candidate_test_runs_only_in_existing_os_sandbox_without_network_or_host_credentials(self):
        # The runner's separate isolation-probe tests establish those OS denials.
        # Execute an explicitly synthetic candidate, never arbitrary host code.
        artifact_digest = self.candidate(b"print('isolated synthetic candidate')")
        script = self.store._directory(artifact_digest) / "render/main.py"
        result = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "isolated synthetic candidate")

    def test_actual_process_crash_before_after_claim_pointer_and_confirmation_reconciles_without_replay(self):
        for boundary in ("before_claim", "after_claim", "after_pointer", "after_confirm"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory(dir=self.folder) as scratch:
                location = Path(scratch)
                (location / "ledger").mkdir(mode=0o700)
                (location / "artifacts").mkdir(mode=0o700)
                ledger = open_ledger(location / "ledger")
                try:
                    store = open_store(location / "artifacts")
                    deployer = BootstrapDeployer(self.policy, store, ledger)
                    artifact_digest = store.install("router", source())
                    intent = action(deployer.plan(artifact_digest, screen_report(store, artifact_digest)), kind="deploy_artifact")
                    approved(ledger, intent)
                    result = subprocess.run([sys.executable, str(Path(__file__).with_name("owner_fault_fixture.py")), str(location), boundary],
                                            capture_output=True, text=True, timeout=8)
                    self.assertEqual(result.returncode, 73, result.stderr)
                    record = deployer.reconcile(GATE, intent.id)
                    if boundary == "before_claim":
                        self.assertEqual(record.fields["state"], "stored")
                        self.assertEqual(ledger.load(intent.id)[1].fields["state"], "granted")
                        deployer.activate(GATE, intent.id, "attempt-1")
                    elif boundary == "after_claim":
                        self.assertEqual(record.fields["state"], "unknown")
                        self.assertIsNone(store.active("router"))
                        with self.assertRaises(Denied):
                            deployer.activate(GATE, intent.id, "attempt-1")
                    else:
                        self.assertEqual(record.fields["state"], "confirmed")
                        with self.assertRaises(Denied):
                            deployer.activate(GATE, intent.id, "attempt-1")
                    self.assertLessEqual(ledger.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)
                finally:
                    ledger.close()
                    writable_fixture_tree(location)


class ScreeningTests(unittest.TestCase):
    def test_masking_is_pure_explicit_and_handles_common_literal_encoded_patterns(self):
        value = "SYNTHETIC/value-to-mask"
        encoded = base64.b64encode(value.encode()).decode()
        text = " ".join((value, encoded, value.encode().hex(), "SYNTHETIC%2Fvalue-to-mask", "123456789:AA" + "x" * 35,
                         "ghp_" + "y" * 36, "password=fixture-password"))
        with mock.patch("os.environ", {}), mock.patch("pathlib.Path.read_text", side_effect=AssertionError("home discovery forbidden")):
            masked = screening.mask(text, [value])
        for secret in (value, encoded, value.encode().hex(), "SYNTHETIC%2Fvalue-to-mask", "fixture-password", "ghp_"):
            self.assertNotIn(secret, masked)
        self.assertIn("[MASKED]", masked)

    def test_full_tree_coverage_binary_and_report_mismatch_fail_closed(self):
        files = [{"path": "config.env", "size": 14, "digest": "sha256:unused", "executable": False}]
        with self.assertRaises(Denied):
            screening.payload({"files": files}, {})
        with self.assertRaises(Denied):
            screening.payload({"files": files}, {"config.env": b"token=fixture!"})
        body = b"\x00binary"
        import hashlib
        manifest = {"schema": "ccrelay.artifact.v1", "component": "router",
                    "files": [{"path": "binary", "size": len(body), "digest": "sha256:" + hashlib.sha256(body).hexdigest(), "executable": False}]}
        masked = screening.payload(manifest, {"binary": body})
        report = {"schema": "ccrelay.screening_report.v1", "artifact_digest": fingerprint(manifest),
                  "payload_digest": fingerprint(masked), "verdict": "clear", "evidence_id": "fixture", "model": "fixture", "coverage_complete": False}
        with self.assertRaises(Denied):
            screening.report(report, manifest, masked)
        report["verdict"] = "incomplete"
        self.assertEqual(screening.report(report, manifest, masked)["verdict"], "incomplete")
        for key, value in (("artifact_digest", "wrong"), ("payload_digest", "wrong"), ("verdict", []), ("coverage_complete", True)):
            with self.assertRaises(Denied):
                screening.report({**report, key: value}, manifest, masked)


if __name__ == "__main__":
    unittest.main()
