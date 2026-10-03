"""Real pinned age crypto; ephemeral identities only inside the OS test sandbox."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from relay_core.artifacts import digest, write_new
from relay_core.contracts import canonical_bytes
from relay_core.encrypted_backup import (
    AgeTool, MAGIC, _frame, _read_frame, _read_exact,
    _process, encrypt_snapshot, inspect_encrypted, verify_encrypted,
)
from relay_core.identity import Denied, strict_json
from relay_core.system_snapshot import SnapshotPolicy, inspect_snapshot
from system_snapshot_fixtures import fixture, capture_fixture


class EncryptedBackupTests(unittest.TestCase):
    def setUp(self):
        runtime = os.environ.get("CCRELAY_TEST_AGE_DIR")
        if not runtime:
            raise RuntimeError("real encryption tests require explicit reviewed --age-runtime; no skip/fake crypto")
        self.runtime = Path(runtime)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.folder.chmod(0o700)
        for target in ("relay_core.system_snapshot.protected_path", "relay_core.identity.protected_path"):
            patch = mock.patch(target, side_effect=lambda path, **_: Path(path))
            patch.start()
            self.addCleanup(patch.stop)
        self.tool = AgeTool(self.runtime / "age",
            "sha256:4012dfc2725883beafb710894af4f599b7a94f8c8e0f51f02cc96ab8df33915e", os.geteuid())
        self.identity, self.recipient = self.key("identity")
        self.components, self.policy = fixture(self.folder)
        for component in self.components:
            self.addCleanup(component.databases[b"state.sqlite"].close)
        write_new(self.components[0].root / "large.bin", bytes(range(256)) * 1600, mode=0o600)
        self.capture = self.folder / "capture"
        self.manifest = capture_fixture(self.components, self.policy, self.capture)
        self.encrypted = self.folder / "encrypted"
        self.recovered = self.folder / "recovered"
        self.max_bytes = 32 * 1024 * 1024

    def key(self, name):
        path = self.folder / name
        result = subprocess.run([str(self.runtime / "age-keygen"), "-o", str(path)],
            env={"PATH": "/usr/bin:/bin"}, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, "ephemeral key generation failed")
        # Secret bytes never appear in assertions, argv, environment or output.
        identity = next(line for line in path.read_bytes().splitlines() if line.startswith(b"AGE-SECRET-KEY-1"))
        recipient = next(line.split(b": ", 1)[1] for line in path.read_bytes().splitlines()
                         if line.startswith(b"# public key:" )).decode()
        return identity, recipient

    def encrypt(self, **kwargs):
        return encrypt_snapshot(self.capture, self.policy, self.encrypted,
            tool=self.tool, recipients=(self.recipient,), owner_uid=os.geteuid(), timeout=10, **kwargs)

    def verify(self, record, **kwargs):
        args = dict(tool=self.tool, identity=self.identity, owner_uid=os.geteuid(),
            expected_digest=record["cipher_digest"], expected_policy_digest=self.policy.digest,
            max_bytes=self.max_bytes, timeout=10)
        args.update(kwargs)
        return verify_encrypted(self.encrypted, self.recovered, **args)

    def inspect(self, record):
        return inspect_encrypted(self.encrypted, owner_uid=os.geteuid(),
            expected_digest=record["cipher_digest"], max_bytes=self.max_bytes)

    def update_cipher(self, record, body):
        path = self.encrypted / "cohort.age"
        path.chmod(0o600)
        path.write_bytes(body)
        path.chmod(0o400)
        changed = {**record, "cipher_digest": digest(body), "cipher_size": len(body)}
        path = self.encrypted / "record.json"
        path.chmod(0o600)
        path.write_bytes(canonical_bytes(changed))
        path.chmod(0o400)
        return changed

    def rewrite_stream(self, record, transform):
        decrypted = subprocess.run([str(self.runtime / "age"), "-d", "-i", "-", str(self.encrypted / "cohort.age")],
            input=self.identity + b"\n", capture_output=True, env={"PATH": "/usr/bin:/bin"}, timeout=5)
        self.assertEqual(decrypted.returncode, 0, "fixture decryption failed")
        result = subprocess.run([str(self.runtime / "age"), "-e", "-r", self.recipient],
            input=transform(decrypted.stdout), capture_output=True, env={"PATH": "/usr/bin:/bin"}, timeout=5)
        self.assertEqual(result.returncode, 0, "fixture re-encryption failed")
        return self.update_cipher(record, result.stdout)

    def no_complete_recovery(self):
        self.assertFalse((self.recovered / "verified.json").exists())
        self.assertFalse((self.recovered / "cohort" / "manifest.json").exists())
        self.assertEqual(inspect_snapshot(self.capture, self.policy, owner_uid=os.geteuid()), self.manifest)

    def test_real_round_trip_preserves_entire_cohort_and_pauses_unknown_actions(self):
        record = self.encrypt()
        self.assertEqual(self.inspect(record), record)
        self.assertEqual(self.verify(record), self.manifest)
        for source in self.capture.rglob("*"):
            target = self.recovered / "cohort" / source.relative_to(self.capture)
            if source.is_file():
                self.assertEqual(source.read_bytes(), target.read_bytes())
                self.assertEqual(target.stat().st_mode & 0o777, 0o400)
        verified = strict_json((self.recovered / "verified.json").read_bytes())
        self.assertEqual(verified["restore_mode"], "paused")
        self.assertFalse(verified["full_system_backup"])
        cipher = (self.encrypted / "cohort.age").read_bytes()
        self.assertNotIn(b"verified company decision", cipher)
        self.assertNotIn(self.identity, cipher)
        self.assertEqual({path.name for path in self.encrypted.iterdir()}, {"cohort.age", "record.json"})

    def test_wrong_identity_rejects_without_complete_marker_or_source_change(self):
        record = self.encrypt()
        other, _ = self.key("other")
        with self.assertRaises(Denied):
            self.verify(record, identity=other)
        self.no_complete_recovery()

    def test_private_identity_is_only_stdin_not_arguments_environment_or_package(self):
        record = self.encrypt()
        original = subprocess.Popen
        observed = []
        def spawn(arguments, **kwargs):
            observed.append((arguments, kwargs["env"]))
            self.assertNotIn(self.identity.decode(), " ".join(arguments))
            self.assertNotIn(self.identity.decode(), repr(kwargs["env"]))
            return original(arguments, **kwargs)
        with mock.patch("relay_core.encrypted_backup.subprocess.Popen", side_effect=spawn):
            self.verify(record)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0][1:4], ["--decrypt", "--identity", "-"])
        self.assertNotIn("HOME", observed[0][1])

    def test_old_trusted_cipher_pin_rejects_rehashed_corruption_before_extraction(self):
        record = self.encrypt()
        cipher = bytearray((self.encrypted / "cohort.age").read_bytes())
        cipher[-100] ^= 1
        self.update_cipher(record, bytes(cipher))
        with self.assertRaises(Denied):
            self.verify(record)
        self.assertFalse(self.recovered.exists())

    def test_truncated_ciphertext_with_new_pin_still_requires_age_authentication(self):
        record = self.encrypt()
        record = self.update_cipher(record, (self.encrypted / "cohort.age").read_bytes()[:-8])
        with self.assertRaises(Denied):
            self.verify(record)
        self.no_complete_recovery()

    def test_authenticated_but_invalid_frame_and_trailing_bytes_fail_closed(self):
        record = self.encrypt()
        for index, transform in enumerate((lambda body: body + b"unlisted trailing bytes",
                                           lambda body: MAGIC + b"\xff\xff\xff\xff")):
            self.recovered = self.folder / ("recovered-" + str(index))
            changed = self.rewrite_stream(record, transform)
            with self.assertRaises(Denied):
                self.verify(changed)
            self.no_complete_recovery()
            record = changed

    def test_path_traversal_duplicate_and_missing_inventory_never_publish_manifest(self):
        import io
        original = self.encrypt()
        saved_cipher = (self.encrypted / "cohort.age").read_bytes()
        def forge(body, path):
            source, output = io.BytesIO(body), io.BytesIO()
            self.assertEqual(_read_exact(source, len(MAGIC)), MAGIC)
            header = _read_frame(source)
            output.write(MAGIC)
            _frame(output, header)
            member = _read_frame(source)
            payload = _read_exact(source, member["size"])
            if path == "missing":
                _frame(output, {"end": 1})
            elif path == "duplicate":
                for _ in range(2):
                    _frame(output, member)
                    output.write(payload)
                output.write(source.read())
            else:
                _frame(output, {**member, "path": path})
                output.write(payload)
                output.write(source.read())
            return output.getvalue()
        for index, name in enumerate(("../outside", "broker/../../outside", "/absolute", "duplicate", "missing")):
            self.recovered = self.folder / ("unsafe-" + str(index))
            reset = self.update_cipher(original, saved_cipher)
            changed = self.rewrite_stream(reset, lambda body: forge(body, name))
            with self.assertRaises(Denied):
                self.verify(changed)
            self.no_complete_recovery()
        self.assertFalse((self.folder / "outside").exists())

    def test_independent_policy_pin_rejects_valid_cipher_before_extraction(self):
        record = self.encrypt()
        with self.assertRaises(Denied):
            self.verify(record, expected_policy_digest="sha256:" + "0" * 64)
        self.assertFalse(self.recovered.exists())

    def test_untrusted_outer_capture_age_cannot_claim_a_newer_recovery_point(self):
        record = self.encrypt()
        path = self.encrypted / "record.json"
        changed = {**record, "captured_at_ms": record["captured_at_ms"] + 1}
        path.chmod(0o600)
        path.write_bytes(canonical_bytes(changed))
        path.chmod(0o400)
        with self.assertRaises(Denied):
            self.verify(changed)
        self.no_complete_recovery()

    def test_tool_digest_plugin_recipient_and_non_native_identity_fail_before_execution(self):
        wrong = AgeTool(self.tool.path, "sha256:" + "0" * 64, os.geteuid())
        with mock.patch("relay_core.encrypted_backup.subprocess.Popen") as spawn:
            for recipients, tool in (((self.recipient,), wrong), (("age1plugin-evil",), self.tool),
                                     ((self.recipient, self.recipient), self.tool)):
                with self.assertRaises(Denied):
                    encrypt_snapshot(self.capture, self.policy, self.encrypted, tool=tool,
                        recipients=recipients, owner_uid=os.geteuid(), timeout=10)
            spawn.assert_not_called()
        record = self.encrypt()
        with self.assertRaises(Denied):
            self.verify(record, identity=b"AGE-PLUGIN-EVIL-1")
        self.assertFalse(self.recovered.exists())

    def test_existing_storage_and_source_overlap_never_overwrite_work(self):
        record = self.encrypt()
        self.recovered.mkdir(mode=0o700)
        write_new(self.recovered / "keep", b"existing work")
        with self.assertRaises(FileExistsError):
            self.verify(record)
        self.assertEqual((self.recovered / "keep").read_bytes(), b"existing work")
        with self.assertRaises(Denied):
            encrypt_snapshot(self.capture, self.policy, self.capture / "encrypted", tool=self.tool,
                recipients=(self.recipient,), owner_uid=os.geteuid(), timeout=10)

    def test_failure_before_record_retains_private_cipher_without_success(self):
        def stop(name):
            if name == "before_backup_record":
                raise RuntimeError("invented crash boundary")
        with self.assertRaises(RuntimeError):
            self.encrypt(checkpoint=stop)
        self.assertTrue((self.encrypted / "cohort.age").exists())
        self.assertFalse((self.encrypted / "record.json").exists())

    def test_failure_before_manifest_never_publishes_complete_recovered_cohort(self):
        record = self.encrypt()
        def stop(name):
            if name == "before_decrypted_manifest":
                raise RuntimeError("invented crash boundary")
        with self.assertRaises(RuntimeError):
            self.verify(record, checkpoint=stop)
        self.no_complete_recovery()

    def test_deadline_stops_only_its_owned_child_and_keeps_incomplete_storage(self):
        child = None
        with self.assertRaisesRegex(Denied, "deadline"):
            with _process(self.tool, ["--encrypt", "--recipient", self.recipient],
                          directory=self.folder, timeout=1) as process:
                child = process
                # Intentionally no input/EOF: this exact child must hit its deadline.
                # age emits its header before waiting for plaintext. Only EOF
                # proves the deliberately stalled input has actually stopped.
                process.stdout.read()
        self.assertIsNotNone(child)
        self.assertIsNotNone(child.poll())
        self.assertEqual(child.returncode, -9)
        self.assertFalse(self.encrypted.exists())

    def test_noncanonical_but_valid_manifest_binds_exact_bytes_in_encrypted_package(self):
        path = self.capture / "manifest.json"
        original = path.read_bytes()
        path.chmod(0o600)
        path.write_bytes(b"\n" + original + b"\n")
        path.chmod(0o400)
        record = self.encrypt()
        self.assertEqual(record["manifest_digest"], digest(path.read_bytes()))
        self.assertEqual(self.verify(record), self.manifest)
        self.assertEqual((self.recovered / "cohort" / "manifest.json").read_bytes(), path.read_bytes())

    def test_real_process_deaths_do_not_forge_backup_or_recovery_completion(self):
        points = ("before_backup_record", "after_backup_record", "after_decrypted_member",
                  "before_decrypted_manifest", "after_decrypted_manifest")
        for index, point in enumerate(points):
            with self.subTest(point=point):
                root = self.folder / ("death-" + str(index))
                root.mkdir(mode=0o700)
                result = subprocess.run([sys.executable, str(Path(__file__).with_name("encrypted_backup_fault_fixture.py")),
                    str(root), str(self.runtime), point], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 86, result.stderr)
                policy = SnapshotPolicy(strict_json((root / "policy.json").read_bytes()))
                self.assertEqual(inspect_snapshot(root / "capture", policy, owner_uid=os.geteuid())["cohort_id"], "fixture")
                if point == "before_backup_record":
                    self.assertFalse((root / "encrypted" / "record.json").exists())
                else:
                    record = strict_json((root / "encrypted" / "record.json").read_bytes())
                    self.assertEqual(inspect_encrypted(root / "encrypted", owner_uid=os.geteuid(),
                        expected_digest=record["cipher_digest"], max_bytes=self.max_bytes), record)
                complete = point == "after_decrypted_manifest"
                self.assertEqual((root / "recovered" / "verified.json").exists(), complete)
                self.assertEqual((root / "recovered" / "cohort" / "manifest.json").exists(), complete)
                if complete:
                    self.assertEqual(inspect_snapshot(root / "recovered" / "cohort", policy,
                                                     owner_uid=os.geteuid())["restore_mode"], "paused")


if __name__ == "__main__":
    unittest.main()
