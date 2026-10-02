"""Complete worker-owned worktree checkpoints, not switch authority or backup.

Capture uses the existing reviewed Git pins and mandatory writer guard. The
protected switch driver must independently establish that guard, copy/verify
the checkpoint and bind semantic/action/native state before writer transfer.
No native call, restoration, Git reset, publication or model execution exists.
"""
import base64
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import stat

from .artifacts import digest
from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, integer, strict_json
from .native_launch import validate_spec
from .native_workspace import WorkspacePreparation
from .outbox import DeliveryLedger


SCHEMA = "ccrelay.worktree_checkpoint.v1"
CHUNK_BYTES = 256 * 1024


@dataclass(frozen=True)
class CheckpointPolicy:
    max_entries: int
    max_bytes: int

    def __post_init__(self):
        integer(self.max_entries)
        integer(self.max_bytes)

    def body(self):
        return {"schema": SCHEMA, **asdict(self)}


def _identity(value):
    return (value.st_dev, value.st_ino, value.st_uid, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


class WorktreeCheckpoints(DeliveryLedger):
    def __init__(self, workspace, policy, *, checkpoint=lambda _: None):
        if type(workspace) is not WorkspacePreparation or type(policy) is not CheckpointPolicy or \
                os.geteuid() == 0 or os.geteuid() != workspace.uid:
            raise Denied("current non-root workspace worker and explicit checkpoint bounds required")
        self.workspace, self.policy = workspace, policy
        workspace._check_lock()
        folder = workspace.home / "worktree-checkpoints"
        if not folder.exists() and not folder.is_symlink():
            folder.mkdir(mode=0o700)
        workspace._private(folder, directory=True)
        super().__init__(folder, owner_uid=workspace.uid, policy_digest=workspace.policy_digest, checkpoint=checkpoint)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _initialize_component(self):
        self.connection.execute("CREATE TABLE checkpoint_metadata (schema TEXT,policy_digest TEXT,body BLOB)")
        self.connection.execute("INSERT INTO checkpoint_metadata VALUES (?,?,?)", (SCHEMA, fingerprint(self.policy.body()), canonical_bytes(self.policy.body())))
        self.connection.execute("CREATE TABLE checkpoints (id TEXT PRIMARY KEY,spec BLOB,spec_digest TEXT,state TEXT,body BLOB,digest TEXT)")
        self.connection.execute("CREATE TABLE checkpoint_entries (snapshot_id TEXT,sequence INTEGER,area TEXT,path BLOB,body BLOB,digest TEXT,PRIMARY KEY(snapshot_id,area,path),UNIQUE(snapshot_id,sequence))")
        self.connection.execute("CREATE TABLE checkpoint_chunks (snapshot_id TEXT,area TEXT,path BLOB,sequence INTEGER,body BLOB,digest TEXT,PRIMARY KEY(snapshot_id,area,path,sequence))")

    def _validate_component(self):
        if self.connection.execute("SELECT schema,policy_digest,body FROM checkpoint_metadata").fetchall() != \
                [(SCHEMA, fingerprint(self.policy.body()), canonical_bytes(self.policy.body()))]:
            raise Denied("unsupported checkpoint schema/policy; preserve state for reviewed migration")
        for (key,) in self.connection.execute("SELECT id FROM checkpoints").fetchall():
            self._row(key)

    def _row(self, key):
        self._check_lock()
        row = self.connection.execute("SELECT spec,spec_digest,state,body,digest FROM checkpoints WHERE id=?", (identifier(key),)).fetchone()
        if row is None:
            return None
        spec = validate_spec(strict_json(row[0]), self.workspace.policy)
        if fingerprint(spec) != row[1] or row[2] not in {"planned", "sealed"} or \
                (row[3] is None) != (row[2] == "planned") or (row[4] is None) != (row[2] == "planned"):
            raise Denied("checkpoint request/index changed")
        body = None if row[3] is None else strict_json(row[3])
        if body is not None:
            exact(body, {"schema", "id", "spec_digest", "policy_digest", "workspace", "manifest_digest", "entry_count", "total_bytes", "admitted"})
            if body["schema"] != SCHEMA or body["id"] != key or body["spec_digest"] != row[1] or body["policy_digest"] != fingerprint(self.policy.body()) or \
                    body["admitted"] is not False or fingerprint(body) != row[4]:
                raise Denied("sealed checkpoint header/provenance changed")
        return {"spec": spec, "state": row[2], "body": body}

    def _mapping(self, spec):
        self.workspace._check_lock()
        if os.geteuid() != self.workspace.uid or self.workspace.policy.digest != self.policy_digest:
            raise Denied("workspace UID/policy changed during checkpoint")
        prepared = self.workspace._row(spec["session_id"])
        if prepared is None or prepared["phase"] != "prepared" or prepared["spec"] != spec:
            raise Denied("exact prepared worktree required; checkpoint never creates or adopts one")
        common = self.workspace.home / "repos" / spec["workspace"]["repo_id"] / "git"
        target = self.workspace.home / "worktrees" / spec["session_id"]
        self.workspace._linked(common, target)
        pointer = (target / ".git").read_bytes()
        metadata = Path(pointer[8:-1].decode("utf-8"))
        return common, target, metadata

    def _content(self, key, area, path):
        expected = 0
        for sequence, body, stored_digest in self.connection.execute(
                "SELECT sequence,body,digest FROM checkpoint_chunks WHERE snapshot_id=? AND area=? AND path=? ORDER BY sequence", (key, area, path)):
            if sequence != expected or type(body) is not bytes or not 1 <= len(body) <= CHUNK_BYTES or digest(body) != stored_digest:
                raise Denied("checkpoint chunk missing, changed or out of order")
            expected += 1
            yield body

    def _scan(self, key, spec, *, store):
        common, target, metadata = self._mapping(spec)
        observed = self.workspace._observe(spec, common, target)
        hasher = hashlib.sha256()
        count, total = 0, 0
        def save(area, path, body):
            nonlocal count, total
            count += 1
            total += body["size"]
            if count > self.policy.max_entries or total > self.policy.max_bytes:
                raise Denied("checkpoint limit exceeded; original work retained, no partial checkpoint accepted")
            hasher.update(canonical_bytes(body) + b"\n")
            if store:
                self.connection.execute("INSERT INTO checkpoint_entries VALUES (?,?,?,?,?,?)", (key, count, area, path, canonical_bytes(body), fingerprint(body)))
                self.checkpoint("after_checkpoint_entry")
        def walk(area, directory_fd, prefix=b""):
            before = _identity(os.fstat(directory_fd))
            save(area, prefix, {"area": area, "path": base64.b64encode(prefix).decode(), "kind": "directory", "mode": stat.S_IMODE(before[3]), "size": 0, "digest": None, "link": None})
            for name in sorted(os.listdir(directory_fd), key=os.fsencode):
                raw_name = os.fsencode(name)
                if area == "worktree" and not prefix and raw_name == b".git":
                    continue  # Validated pointer; linked Git metadata is captured separately.
                path = prefix + (b"/" if prefix else b"") + raw_name
                initial = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if initial.st_uid != self.workspace.uid:
                    raise Denied("checkpoint entry belongs to another UID")
                mode = stat.S_IMODE(initial.st_mode)
                if stat.S_ISDIR(initial.st_mode):
                    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    try:
                        if _identity(os.fstat(fd)) != _identity(initial):
                            raise Denied("checkpoint directory changed before opening")
                        walk(area, fd, path)
                    finally:
                        os.close(fd)
                elif stat.S_ISLNK(initial.st_mode):
                    link = os.fsencode(os.readlink(name, dir_fd=directory_fd))
                    save(area, path, {"area": area, "path": base64.b64encode(path).decode(), "kind": "symlink", "mode": mode,
                                      "size": len(link), "digest": digest(link), "link": base64.b64encode(link).decode()})
                elif stat.S_ISREG(initial.st_mode) and initial.st_nlink == 1:
                    if total + initial.st_size > self.policy.max_bytes:
                        raise Denied("checkpoint byte limit exceeded; work preserved")
                    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory_fd)
                    size, file_hash, sequence = 0, hashlib.sha256(), 0
                    try:
                        if _identity(os.fstat(fd)) != _identity(initial):
                            raise Denied("checkpoint file changed before opening")
                        while True:
                            chunk = os.read(fd, CHUNK_BYTES)
                            if not chunk:
                                break
                            size += len(chunk)
                            if total + size > self.policy.max_bytes:
                                raise Denied("checkpoint byte limit exceeded while reading; work preserved")
                            file_hash.update(chunk)
                            if store:
                                self.connection.execute("INSERT INTO checkpoint_chunks VALUES (?,?,?,?,?,?)", (key, area, path, sequence, chunk, digest(chunk)))
                            sequence += 1
                        if size != initial.st_size or _identity(os.fstat(fd)) != _identity(initial):
                            raise Denied("checkpoint file changed while reading")
                    finally:
                        os.close(fd)
                    save(area, path, {"area": area, "path": base64.b64encode(path).decode(), "kind": "file", "mode": mode,
                                      "size": size, "digest": "sha256:" + file_hash.hexdigest(), "link": None})
                else:
                    raise Denied("special/linked checkpoint entry needs evidenced repair; no file is silently skipped")
                if _identity(os.stat(name, dir_fd=directory_fd, follow_symlinks=False)) != _identity(initial):
                    raise Denied("checkpoint entry changed during capture")
            if _identity(os.fstat(directory_fd)) != before:
                raise Denied("checkpoint directory changed during capture")
        for area, folder in (("worktree", target), ("git", metadata)):
            self.workspace._private(folder, directory=True)
            fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                walk(area, fd)
            finally:
                os.close(fd)
        if self.workspace._observe(spec, common, target) != observed:
            raise Denied("HEAD, branch or Git status changed during checkpoint")
        return {"workspace": observed, "manifest_digest": "sha256:" + hasher.hexdigest(), "entry_count": count, "total_bytes": total}

    def inspect(self, key):
        row = self._row(key)
        if row is None or row["state"] != "sealed":
            raise Denied("complete sealed checkpoint required; request/partial capture is not a handoff")
        hasher, count, total = hashlib.sha256(), 0, 0
        entries = self.connection.execute("SELECT sequence,area,path,body,digest FROM checkpoint_entries WHERE snapshot_id=? ORDER BY sequence", (key,)).fetchall()
        for sequence, area, path, raw, stored_digest in entries:
            body = strict_json(raw)
            exact(body, {"area", "path", "kind", "mode", "size", "digest", "link"})
            if sequence != count + 1 or body["area"] != area or body["path"] != base64.b64encode(path).decode() or fingerprint(body) != stored_digest or \
                    area not in {"worktree", "git"} or body["kind"] not in {"directory", "file", "symlink"}:
                raise Denied("checkpoint entry/index changed")
            integer(body["mode"], 0)
            integer(body["size"], 0)
            if body["kind"] == "file":
                size, file_hash = 0, hashlib.sha256()
                for chunk in self._content(key, area, path):
                    size += len(chunk)
                    file_hash.update(chunk)
                if size != body["size"] or "sha256:" + file_hash.hexdigest() != body["digest"] or body["link"] is not None:
                    raise Denied("checkpoint content missing or changed")
            elif body["kind"] == "symlink":
                link = base64.b64decode(body["link"], validate=True)
                if len(link) != body["size"] or digest(link) != body["digest"]:
                    raise Denied("checkpoint symlink changed")
            elif body["size"] != 0 or body["digest"] is not None or body["link"] is not None:
                raise Denied("checkpoint directory metadata changed")
            if body["kind"] != "file" and self.connection.execute("SELECT 1 FROM checkpoint_chunks WHERE snapshot_id=? AND area=? AND path=?", (key, area, path)).fetchone():
                raise Denied("unexpected checkpoint chunks on a non-file entry")
            hasher.update(canonical_bytes(body) + b"\n")
            count += 1
            total += body["size"]
        if ("sha256:" + hasher.hexdigest(), count, total) != (row["body"]["manifest_digest"], row["body"]["entry_count"], row["body"]["total_bytes"]) or \
                count > self.policy.max_entries or total > self.policy.max_bytes:
            raise Denied("checkpoint manifest incomplete or changed")
        if self.connection.execute("SELECT 1 FROM checkpoint_chunks c LEFT JOIN checkpoint_entries e ON c.snapshot_id=e.snapshot_id AND c.area=e.area AND c.path=e.path WHERE c.snapshot_id=? AND e.snapshot_id IS NULL", (key,)).fetchone():
            raise Denied("orphan checkpoint chunks are not part of the sealed manifest")
        return row["body"]

    def read_file(self, key, area, path):
        self.inspect(key)
        path = os.fsencode(path)
        row = self.connection.execute("SELECT body FROM checkpoint_entries WHERE snapshot_id=? AND area=? AND path=?", (key, area, path)).fetchone()
        if row is None or strict_json(row[0])["kind"] != "file":
            raise Denied("checkpoint regular file required")
        return b"".join(self._content(key, area, path))

    def current(self, key):
        sealed = self.inspect(key)
        spec = self._row(key)["spec"]
        with self.workspace.writer_guard(spec):
            observed = self._scan(key, spec, store=False)
            return all(observed[field] == sealed[field] for field in observed)

    def capture(self, key, spec):
        identifier(key)
        spec = validate_spec(strict_json(canonical_bytes(spec)), self.workspace.policy)
        with self.workspace.writer_guard(spec):
            common, _, _ = self._mapping(spec)
            self.workspace._git(common, ["fsck", "--full", "--no-reflogs", "--no-dangling"])
            prior = self._row(key)
            if prior and prior["spec"] != spec:
                raise Denied("checkpoint request cannot change root/execution/workspace/contract")
            if prior and prior["state"] == "sealed":
                body = self.inspect(key)
                observed = self._scan(key, spec, store=False)
                if any(observed[field] != body[field] for field in observed):
                    raise Denied("sealed checkpoint is stale; retain it and request a new verified checkpoint")
                return {"created_now": False, "checkpoint": body}
            if prior is None:
                with self._transaction():
                    self.connection.execute("INSERT INTO checkpoints VALUES (?,?,?,'planned',NULL,NULL)", (key, canonical_bytes(spec), fingerprint(spec)))
                    self.checkpoint("before_checkpoint_request_commit")
                self.checkpoint("after_checkpoint_request_commit")
            with self._transaction():
                captured = self._scan(key, spec, store=True)
                body = {"schema": SCHEMA, "id": key, "spec_digest": fingerprint(spec), "policy_digest": fingerprint(self.policy.body()), **captured, "admitted": False}
                self.checkpoint("before_checkpoint_seal_commit")
                if self._scan(key, spec, store=False) != captured:
                    raise Denied("checkpoint changed before sealing; preserve source without accepting partial state")
                self.connection.execute("UPDATE checkpoints SET state='sealed',body=?,digest=? WHERE id=?", (canonical_bytes(body), fingerprint(body), key))
            self.checkpoint("after_checkpoint_seal_commit")
            return {"created_now": True, "checkpoint": self.inspect(key)}
