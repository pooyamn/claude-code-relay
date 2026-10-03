"""Invented cohort/keys; abrupt process death at real encryption/seal boundaries."""
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock

from relay_core.artifacts import write_new
from relay_core.contracts import canonical_bytes
from relay_core.encrypted_backup import AgeTool, encrypt_snapshot, verify_encrypted
from system_snapshot_fixtures import capture_fixture, fixture


def main():
    root, runtime, point = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    with mock.patch("relay_core.system_snapshot.protected_path", side_effect=lambda path, **_: Path(path)), \
            mock.patch("relay_core.identity.protected_path", side_effect=lambda path, **_: Path(path)):
        components, policy = fixture(root)
        write_new(root / "policy.json", canonical_bytes(policy.body))
        capture_fixture(components, policy, root / "capture")
        result = subprocess.run([str(runtime / "age-keygen"), "-o", str(root / "identity")],
                                env={"PATH": "/usr/bin:/bin"}, capture_output=True, timeout=5)
        if result.returncode:
            raise RuntimeError("ephemeral fixture key generation failed")
        lines = (root / "identity").read_bytes().splitlines()
        identity = next(line for line in lines if line.startswith(b"AGE-SECRET-KEY-1"))
        recipient = next(line.split(b": ", 1)[1].decode() for line in lines if line.startswith(b"# public key:"))
        tool = AgeTool(runtime / "age",
            "sha256:4012dfc2725883beafb710894af4f599b7a94f8c8e0f51f02cc96ab8df33915e", os.geteuid())
        def die(name):
            if name == point:
                os._exit(86)
        record = encrypt_snapshot(root / "capture", policy, root / "encrypted", tool=tool,
            recipients=(recipient,), owner_uid=os.geteuid(), timeout=10, checkpoint=die)
        verify_encrypted(root / "encrypted", root / "recovered", tool=tool, identity=identity,
            owner_uid=os.geteuid(), expected_digest=record["cipher_digest"], expected_policy_digest=policy.digest,
            max_bytes=32 * 1024 * 1024, timeout=10, checkpoint=die)
        raise RuntimeError("requested process-death boundary was not reached")


if __name__ == "__main__":
    main()
