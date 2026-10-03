"""Stream a sealed cohort through age; verify into new, paused private storage.

No generic archive extraction, credentials, network, scheduling or activation.
The expected ciphertext digest must come from an independently trusted catalog:
age authenticates encrypted bytes, not the producer of a public-key envelope.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import struct
import subprocess
import threading

from .artifacts import digest, fsync_dir, write_new
from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, integer, strict_json
from .system_snapshot import (
    CHUNK, MANIFEST_LIMIT, ROW_LIMIT, SnapshotPolicy, _hash, _private,
    _sealed_read, _manifest, _inspect_components, _identity, inspect_snapshot,
)


MAGIC = b"CCRELAY-PACKAGE\x00\x01"
SCHEMA = "ccrelay.encrypted_backup.v1"
FRAME_LIMIT = 65536


@dataclass(frozen=True)
class AgeTool:
    """Binary digest comes from reviewed protected config, never the package."""
    path: Path
    expected_digest: str
    owner_uid: int

def _tool(tool):
    if type(tool) is not AgeTool or os.geteuid() != tool.owner_uid:
        raise Denied("protected age tool owner required")
    _hash(tool.expected_digest)
    # _sealed_read checks sealed data modes; the executable is separately pinned.
    from .identity import protected_path
    import stat
    path = protected_path(tool.path, owners={0, tool.owner_uid}, private=True)
    before = path.lstat()
    if not path.is_absolute() or before.st_uid != tool.owner_uid or before.st_nlink != 1 or \
            not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o500:
        raise Denied("sealed owned age executable required")
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        if _identity(os.fstat(handle.fileno())) != _identity(before):
            raise Denied("age executable replaced")
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            hasher.update(chunk)
        if _identity(os.fstat(handle.fileno())) != _identity(before) or _identity(path.lstat()) != _identity(before):
            raise Denied("age executable changed")
    if "sha256:" + hasher.hexdigest() != tool.expected_digest:
        raise Denied("age executable does not match independently pinned artifact")
    return path


@contextmanager
def _process(tool, arguments, *, directory, timeout, output=subprocess.PIPE, pass_fds=()):
    integer(timeout)
    if timeout > 300:
        raise Denied("explicit bounded encryption operation deadline required")
    path = _tool(tool)
    # No inherited credentials, home, updater or plugin settings; native keys only.
    process = subprocess.Popen([str(path), *arguments], stdin=subprocess.PIPE,
        stdout=output, stderr=subprocess.PIPE, cwd=directory, pass_fds=pass_fds,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TMPDIR": str(directory)})
    errors = bytearray()
    def drain_errors():
        while True:
            chunk = process.stderr.read(CHUNK)
            if not chunk:
                break
            if len(errors) < FRAME_LIMIT:
                errors.extend(chunk[:FRAME_LIMIT - len(errors)])
    reader = threading.Thread(target=drain_errors, daemon=True)
    reader.start()
    expired = threading.Event()
    def expire():
        expired.set()
        if process.poll() is None:
            process.kill()  # Only the child owned by this exact invocation.
    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    timer.start()
    def failed(code):
        detail = bytes(errors).decode("utf-8", errors="replace")
        detail = re.sub(r"AGE-SECRET-KEY-1[0-9A-Z]+", "[recovery identity redacted]", detail).strip()
        return Denied(f"age operation failed (exit {code}); no complete package: {detail}")
    try:
        yield process
        if not process.stdin.closed:
            process.stdin.close()
        code = process.wait()
        reader.join()
        if expired.is_set():
            raise Denied("age operation exceeded its explicit deadline; partial data retained")
        if code:
            raise failed(code)
        _tool(tool)
    except Denied as error:
        code = process.poll()
        if code is not None and code != 0 and not expired.is_set():
            reader.join()
            raise failed(code) from error
        raise
    except (BrokenPipeError, OSError) as error:
        raise Denied("age stream failed; incomplete private data retained") from error
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass  # Preserve the original failure, not a second cleanup error.
        if process.stdout is not None and hasattr(process.stdout, "close"):
            process.stdout.close()
        reader.join(timeout=1)
        process.stderr.close()


def _frame(output, body):
    raw = canonical_bytes(body)
    if len(raw) > FRAME_LIMIT:
        raise Denied("backup metadata frame exceeds bound")
    output.write(struct.pack(">I", len(raw)))
    output.write(raw)


def _read_exact(stream, size):
    parts, remaining = [], size
    while remaining:
        value = stream.read(min(CHUNK, remaining))
        if not value:
            raise Denied("incomplete decrypted backup frame")
        parts.append(value)
        remaining -= len(value)
    return b"".join(parts)


def _read_frame(stream):
    size = struct.unpack(">I", _read_exact(stream, 4))[0]
    if not 1 <= size <= FRAME_LIMIT:
        raise Denied("unbounded decrypted backup frame")
    return strict_json(_read_exact(stream, size))


def _members(folder, policy, uid):
    """Only generated cohort names, never source paths or archive link records."""
    yield "manifest.json", folder / "manifest.json", MANIFEST_LIMIT
    for key in sorted(policy.body["components"]):
        root = _private(folder / key, uid, directory=True)
        yield key + "/entries.jsonl", root / "entries.jsonl", policy.max_entries * ROW_LIMIT
        for path in sorted(root.iterdir()):
            if path.name != "entries.jsonl":
                if not re.fullmatch(r"[0-9]{8}\.blob", path.name):
                    raise Denied("unexpected generated capture payload")
                yield key + "/" + path.name, path, policy.max_bytes


def _bytes_info(handle, limit):
    size, hasher = 0, hashlib.sha256()
    for chunk in iter(lambda: handle.read(CHUNK), b""):
        size += len(chunk)
        if size > limit:
            raise Denied("backup member exceeds expected policy bound")
        hasher.update(chunk)
    return size, "sha256:" + hasher.hexdigest()


def _new_destination(destination, *, uid, sources):
    if os.geteuid() != integer(uid, 0):
        raise Denied("protected backup owner required")
    destination = Path(destination)
    _private(destination.parent, uid, directory=True)
    if not destination.is_absolute() or ".." in destination.parts or any(
            destination == source or destination.is_relative_to(source) or source.is_relative_to(destination)
            for source in sources):
        raise Denied("new backup storage must not overlap any source")
    destination.mkdir(mode=0o700)
    fsync_dir(destination.parent)
    return destination


def encrypt_snapshot(folder, policy, destination, *, tool, recipients, owner_uid, timeout,
                     checkpoint=lambda _: None):
    """No private key is required to produce an encrypted recovery package."""
    if type(recipients) is not tuple or not 1 <= len(recipients) <= 16 or \
            len(set(recipients)) != len(recipients) or any(type(key) is not str or not re.fullmatch(
                r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}", key) for key in recipients):
        raise Denied("explicit unique native age public recipients required; no plugins/passphrases")
    _tool(tool)
    folder = Path(folder)
    manifest = inspect_snapshot(folder, policy, owner_uid=owner_uid)
    with _sealed_read(folder / "manifest.json", owner_uid) as handle:
        manifest_raw = handle.read(MANIFEST_LIMIT + 1)
    if _manifest(manifest_raw, policy, owner_uid) != manifest:
        raise Denied("capture manifest changed before packaging")
    manifest_digest = digest(manifest_raw)
    destination = _new_destination(destination, uid=owner_uid, sources=(folder,))
    header = {"schema": "ccrelay.backup_stream.v1", "policy": policy.body,
              "manifest_digest": manifest_digest, "owner_uid": owner_uid}
    encrypted = destination / "cohort.age"
    fd = os.open(encrypted, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        arguments = ["--encrypt"]
        for recipient in recipients:
            arguments += ["--recipient", recipient]
        with _process(tool, arguments, directory=destination, timeout=timeout, output=fd) as process:
            process.stdin.write(MAGIC)
            _frame(process.stdin, header)
            count = 0
            for name, source, limit in _members(folder, policy, owner_uid):
                with _sealed_read(source, owner_uid) as handle:
                    size, hashed = _bytes_info(handle, limit)
                    handle.seek(0)
                    _frame(process.stdin, {"path": name, "size": size, "digest": hashed})
                    streamed, streamed_hash = 0, hashlib.sha256()
                    for chunk in iter(lambda: handle.read(CHUNK), b""):
                        process.stdin.write(chunk)
                        streamed += len(chunk)
                        streamed_hash.update(chunk)
                    if (streamed, "sha256:" + streamed_hash.hexdigest()) != (size, hashed):
                        raise Denied("capture bytes changed while streaming encryption")
                count += 1
                checkpoint("after_backup_member")
            _frame(process.stdin, {"end": count})
            process.stdin.close()
        if inspect_snapshot(folder, policy, owner_uid=owner_uid) != manifest:
            raise Denied("capture changed during encryption")
        os.fchmod(fd, 0o400)
        os.fsync(fd)
    finally:
        os.close(fd)
    with _sealed_read(encrypted, owner_uid) as handle:
        size, hashed = _bytes_info(handle, _stream_bound(policy) + 2 * 1024 * 1024)
    record = {"schema": SCHEMA, "cohort_id": manifest["cohort_id"], "policy_digest": policy.digest,
        "manifest_digest": manifest_digest, "captured_at_ms": manifest["captured_at_ms"],
        "cipher_digest": hashed, "cipher_size": size, "tool_digest": tool.expected_digest,
        "recipients_digest": fingerprint(list(recipients)), "encrypted": True,
        "full_system_backup": False, "scope": "configured-cohort", "restore_mode": "paused"}
    checkpoint("before_backup_record")
    write_new(destination / "record.json", canonical_bytes(record))
    fsync_dir(destination)
    checkpoint("after_backup_record")
    return record


def _stream_bound(policy):
    # Framing, inventory and encrypted chunk overhead have explicit upper bounds.
    return policy.max_bytes + policy.max_entries * (ROW_LIMIT + 1024) + \
        len(policy.body["components"]) * FRAME_LIMIT + 3 * FRAME_LIMIT


def inspect_encrypted(directory, *, owner_uid, expected_digest, max_bytes):
    """Ciphertext pin must be obtained outside this directory/package."""
    _hash(expected_digest)
    integer(max_bytes)
    root = _private(directory, owner_uid, directory=True)
    if {path.name for path in root.iterdir()} != {"cohort.age", "record.json"}:
        raise Denied("encrypted package is incomplete or contains unknown files")
    with _sealed_read(root / "record.json", owner_uid) as handle:
        record = strict_json(handle.read(FRAME_LIMIT + 1))
    exact(record, {"schema", "cohort_id", "policy_digest", "manifest_digest", "captured_at_ms",
        "cipher_digest", "cipher_size", "tool_digest", "recipients_digest", "encrypted",
        "full_system_backup", "scope", "restore_mode"})
    if record["schema"] != SCHEMA or record["encrypted"] is not True or \
            record["full_system_backup"] is not False or record["scope"] != "configured-cohort" or \
            record["restore_mode"] != "paused" or record["cipher_digest"] != expected_digest:
        raise Denied("encrypted package has unsupported scope or differs from trusted ciphertext pin")
    for key in ("policy_digest", "manifest_digest", "tool_digest", "recipients_digest"):
        _hash(record[key])
    integer(record["captured_at_ms"], 0)
    with _sealed_read(root / "cohort.age", owner_uid) as handle:
        if _bytes_info(handle, max_bytes) != (integer(record["cipher_size"]), expected_digest):
            raise Denied("encrypted bytes differ from independently expected package")
    return record


def verify_encrypted(directory, destination, *, tool, identity, owner_uid, expected_digest,
                     expected_policy_digest, max_bytes, timeout, checkpoint=lambda _: None):
    """Validate into new paused storage; never overwrite/activate original components."""
    _hash(expected_policy_digest)
    if type(identity) is not bytes or not re.fullmatch(rb"AGE-SECRET-KEY-1[023456789ACDEFGHJKLMNPQRSTUVWXYZ]{58}\n?", identity):
        raise Denied("one native recovery identity required through stdin, never argv/environment")
    record = inspect_encrypted(directory, owner_uid=owner_uid, expected_digest=expected_digest, max_bytes=max_bytes)
    if record["policy_digest"] != expected_policy_digest:
        raise Denied("backup differs from independently expected recovery policy")
    _tool(tool)
    root = Path(directory)
    destination = _new_destination(destination, uid=owner_uid, sources=(root,))
    cohort = destination / "cohort"
    cohort.mkdir(mode=0o700)
    pending_manifest = None
    # Inherited, no-follow ciphertext FD pins the exact verified generation.
    with _sealed_read(root / "cohort.age", owner_uid) as cipher:
        if _bytes_info(cipher, max_bytes) != (record["cipher_size"], expected_digest):
            raise Denied("ciphertext changed before decryption")
        cipher.seek(0)
        with _process(tool, ["--decrypt", "--identity", "-", f"/dev/fd/{cipher.fileno()}"],
                      directory=destination, timeout=timeout, pass_fds=(cipher.fileno(),)) as process:
            process.stdin.write(identity + (b"" if identity.endswith(b"\n") else b"\n"))
            process.stdin.close()
            stream = process.stdout
            if _read_exact(stream, len(MAGIC)) != MAGIC:
                raise Denied("unsupported decrypted stream; preserve package for reviewed migration")
            header = _read_frame(stream)
            exact(header, {"schema", "policy", "manifest_digest", "owner_uid"})
            policy = SnapshotPolicy(header["policy"])
            if header["schema"] != "ccrelay.backup_stream.v1" or type(header["owner_uid"]) is not int or \
                    header["owner_uid"] != owner_uid or policy.digest != expected_policy_digest or \
                    header["manifest_digest"] != record["manifest_digest"]:
                raise Denied("decrypted policy/owner/manifest differs from trusted package")
            seen, count, total = set(), 0, 0
            for key in policy.body["components"]:
                (cohort / key).mkdir(mode=0o700)
            while True:
                member = _read_frame(stream)
                if type(member) is not dict:
                    raise Denied("backup member must be an exact object")
                if set(member) == {"end"}:
                    if integer(member["end"]) != count:
                        raise Denied("backup member count changed")
                    break
                exact(member, {"path", "size", "digest"})
                name, size = member["path"], integer(member["size"], 0)
                _hash(member["digest"])
                if type(name) is not str or name in seen:
                    raise Denied("invalid or duplicate backup member")
                if name == "manifest.json":
                    limit = MANIFEST_LIMIT
                else:
                    parts = name.split("/")
                    if len(parts) != 2 or parts[0] not in policy.body["components"] or \
                            not re.fullmatch(r"entries\.jsonl|[0-9]{8}\.blob", parts[1]):
                        raise Denied("unsafe or unknown generated backup member")
                    limit = policy.max_entries * ROW_LIMIT if parts[1] == "entries.jsonl" else policy.max_bytes
                total += size
                if size > limit or total > _stream_bound(policy) or count >= policy.max_entries + len(policy.body["components"]) + 1:
                    raise Denied("decrypted package exceeds independently pinned inventory bounds")
                seen.add(name)
                hasher = hashlib.sha256()
                if name == "manifest.json":
                    pending_manifest = _read_exact(stream, size)
                    hasher.update(pending_manifest)
                else:
                    fd = os.open(cohort / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    try:
                        with os.fdopen(fd, "wb", closefd=False) as output:
                            remaining = size
                            while remaining:
                                value = _read_exact(stream, min(CHUNK, remaining))
                                output.write(value)
                                hasher.update(value)
                                remaining -= len(value)
                            output.flush()
                        os.fchmod(fd, 0o400)
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                if "sha256:" + hasher.hexdigest() != member["digest"]:
                    raise Denied("decrypted member bytes differ from stream inventory")
                count += 1
                checkpoint("after_decrypted_member")
            # This read requires final age authentication/EOF, not just a container footer.
            if stream.read(1):
                raise Denied("unexpected bytes after complete backup stream")
        if pending_manifest is None or digest(pending_manifest) != record["manifest_digest"]:
            raise Denied("decrypted cohort manifest missing or changed")
    if inspect_encrypted(root, owner_uid=owner_uid, expected_digest=expected_digest, max_bytes=max_bytes) != record:
        raise Denied("encrypted record changed during recovery verification")
    manifest = _manifest(pending_manifest, policy, owner_uid)
    _inspect_components(cohort, manifest, policy, owner_uid)
    if (manifest["cohort_id"], manifest["captured_at_ms"]) != (record["cohort_id"], record["captured_at_ms"]):
        raise Denied("untrusted outer backup record changed capture identity/age")
    for key in policy.body["components"]:
        fsync_dir(cohort / key)
    # No complete cohort marker until EOF/authentication, exit zero and inventory validation.
    checkpoint("before_decrypted_manifest")
    write_new(cohort / "manifest.json", pending_manifest)
    fsync_dir(cohort)
    write_new(destination / "verified.json", canonical_bytes({"schema": "ccrelay.verified_backup.v1",
        "cipher_digest": expected_digest, "policy_digest": expected_policy_digest,
        "manifest_digest": record["manifest_digest"], "restore_mode": "paused",
        "full_system_backup": False, "scope": "configured-cohort"}))
    fsync_dir(destination)
    checkpoint("after_decrypted_manifest")
    return manifest
