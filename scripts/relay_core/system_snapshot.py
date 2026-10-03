"""Coordinated recovery bytes for an explicit component cohort, not activation.

The protected driver must hold every filesystem/native writer fence while all
registered SQLite writers are frozen together. Original bytes are never changed.
Literal paths, links, modes and empty directories are metadata, not archive paths.
Payloads stream to private numbered files; the complete manifest publishes last.

This is an unencrypted local capture foundation. It does not upload, schedule,
prune, restore, authenticate its own contents or prove full-system coverage.
"""
import base64
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat

from .artifacts import digest, fsync_dir, write_new
from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, integer, protected_path, strict_json
from .snapshot_io import sqlite_copy


SCHEMA = "ccrelay.system_snapshot.v1"
ROW_LIMIT = 32768
MANIFEST_LIMIT = 65536
CHUNK = 65536


def _hash(value):
    if type(value) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise Denied("exact component/version digest required")
    return value


def _path(encoded, *, root=False):
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError):
        raise Denied("invalid recovery path encoding") from None
    if type(encoded) is not str or base64.b64encode(raw).decode() != encoded or len(raw) > 4096 or \
            b"\0" in raw or (not raw and not root) or \
            (raw and any(part in {b"", b".", b".."} for part in raw.split(b"/"))):
        raise Denied("unsafe recovery-relative path")
    return raw


def _identity(value):
    return (value.st_dev, value.st_ino, value.st_uid, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _private(path, uid, *, directory=False, sealed=False):
    path = protected_path(path, owners={0, uid}, private=True, directory=directory)
    value = path.lstat()
    if value.st_uid != uid or (not directory and (value.st_nlink != 1 or
            stat.S_IMODE(value.st_mode) != (0o400 if sealed else 0o600))):
        raise Denied("private owned unlinked capture storage required")
    return path


class SnapshotPolicy:
    def __init__(self, raw):
        exact(raw, {"schema", "components", "max_entries", "max_bytes"})
        if raw["schema"] != "ccrelay.system_snapshot_policy.v1" or type(raw["components"]) is not dict or \
                not 1 <= len(raw["components"]) <= 128:
            raise Denied("explicit complete required-component policy needed")
        for key, value in raw["components"].items():
            identifier(key)
            if key == "manifest.json":
                raise Denied("component ID collides with the cohort manifest")
            exact(value, {"root", "owner_uid", "version_digest", "databases", "exclusions"})
            integer(value["owner_uid"], 0)
            _hash(value["version_digest"])
            try:
                root = base64.b64decode(value["root"], validate=True)
            except (TypeError, ValueError):
                raise Denied("invalid protected source root encoding") from None
            if type(value["root"]) is not str or not root.startswith(b"/") or b"\0" in root or b".." in root.split(b"/") or \
                    base64.b64encode(root).decode() != value["root"]:
                raise Denied("absolute protected source root required")
            if type(value["databases"]) is not list or type(value["exclusions"]) is not dict:
                raise Denied("protected source database/exclusion inventory required")
            paths = [_path(encoded) for encoded in value["databases"]]
            if paths != sorted(set(paths)):
                raise Denied("protected database paths must be unique and ordered")
            for encoded, rule in value["exclusions"].items():
                if _path(encoded) in paths:
                    raise Denied("a required database cannot be excluded")
                _exclusion(rule)
        self.body = strict_json(canonical_bytes(raw))
        self.max_entries = integer(raw["max_entries"])
        self.max_bytes = integer(raw["max_bytes"])
        if self.max_entries > 1000000:
            raise Denied("snapshot entry bound exceeds supported inventory")
        self.digest = fingerprint(self.body)


@dataclass(frozen=True)
class Component:
    id: str
    root: Path
    owner_uid: int
    version_digest: str
    databases: dict
    exclusions: dict


def component_spec(component):
    """Pin sources and exclusions in protected config, not caller declarations."""
    return {"root": base64.b64encode(os.fsencode(component.root)).decode(), "owner_uid": component.owner_uid,
            "version_digest": component.version_digest,
            "databases": [base64.b64encode(path).decode() for path in sorted(component.databases)],
            "exclusions": {base64.b64encode(path).decode(): rule for path, rule in component.exclusions.items()}}


def _exclusion(rule):
    exact(rule, {"reason", "recovery"})
    if type(rule["reason"]) is not str or not 1 <= len(rule["reason"]) <= 512 or \
            rule["recovery"] not in {"generated", "owner_relogin"}:
        raise Denied("exclusions must state generated recovery or owner re-login")


def _components(components, policy, *, frozen=False):
    if type(components) is not tuple or type(policy) is not SnapshotPolicy or \
            fingerprint(policy.body) != policy.digest:
        raise Denied("exact protected component cohort and unchanged policy required")
    ids, roots, connections = set(), [], []
    for component in components:
        if type(component) is not Component:
            raise Denied("explicit component required")
        identifier(component.id)
        integer(component.owner_uid, 0)
        if type(component.databases) is not dict or type(component.exclusions) is not dict or \
                any(type(path) is not bytes for path in (*component.databases, *component.exclusions)):
            raise Denied("explicit literal database and exclusion inventories required")
        _hash(component.version_digest)
        if component.id in ids or policy.body["components"].get(component.id) != component_spec(component):
            raise Denied("duplicate, unexpected or incompatible component")
        ids.add(component.id)
        root = _private(component.root, component.owner_uid, directory=True)
        if any(root == other or root.is_relative_to(other) or other.is_relative_to(root) for other in roots):
            raise Denied("component roots overlap")
        roots.append(root)
        if type(component.databases) is not dict or type(component.exclusions) is not dict:
            raise Denied("explicit database and exclusion inventories required")
        for raw, connection in component.databases.items():
            if type(raw) is not bytes:
                raise Denied("literal byte paths required for database inventory")
            _path(base64.b64encode(raw).decode())
            if type(connection) is not sqlite3.Connection or connection.in_transaction is not frozen:
                raise Denied("quiescent actual SQLite connections required; caller transactions retained")
            databases = connection.execute("PRAGMA database_list").fetchall()
            if len(databases) != 1 or databases[0][1:] != ("main", str(root / os.fsdecode(raw))):
                raise Denied("SQLite connection path/attachments differ from component inventory")
            if connection in connections:
                raise Denied("database connection appears twice")
            connections.append(connection)
        for raw, rule in component.exclusions.items():
            if type(raw) is not bytes:
                raise Denied("literal byte paths required for exclusions")
            _path(base64.b64encode(raw).decode())
            _exclusion(rule)
            if raw in component.databases:
                raise Denied("a required database cannot be excluded")
    if ids != set(policy.body["components"]):
        raise Denied("required component missing; no complete capture can be published")
    return roots


@contextmanager
def _frozen(components):
    with ExitStack() as held:
        connections = sorted(((Path(c.root) / os.fsdecode(path), db, c.owner_uid) for c in components
                              for path, db in c.databases.items()), key=lambda item: str(item[0]))
        anchors = {}
        for path, _, uid in connections:
            _private(path, uid, sealed=stat.S_IMODE(path.lstat().st_mode) == 0o400)
            anchors[path] = _identity(path.lstat())
        def validate():
            for path, before in anchors.items():
                if _identity(path.lstat()) != before:
                    raise Denied("database source file identity changed within held writer fence")
        for _, db, _ in connections:
            if db.in_transaction:
                raise Denied("caller transaction is not a capture boundary")
            db.execute("BEGIN IMMEDIATE")
            held.callback(db.execute, "ROLLBACK")
            validate()
        yield validate
        validate()


def _file(fd, destination=None, *, limit):
    first = _identity(os.fstat(fd))
    hasher, size, target = hashlib.sha256(), 0, None
    try:
        if destination is not None:
            target = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        while True:
            chunk = os.read(fd, CHUNK)
            if not chunk:
                break
            if size == 0 and chunk.startswith(b"SQLite format 3\0"):
                raise Denied("unregistered SQLite file requires a consistent database adapter")
            size += len(chunk)
            if size > limit:
                raise Denied("snapshot byte bound exceeded; source and partial capture retained")
            hasher.update(chunk)
            if target is not None:
                view = memoryview(chunk)
                while view:
                    count = os.write(target, view)
                    if count <= 0:
                        raise Denied("snapshot copy made no progress")
                    view = view[count:]
        if size != first[5] or _identity(os.fstat(fd)) != first:
            raise Denied("file changed while capturing")
        if target is not None:
            os.fchmod(target, 0o400)
            os.fsync(target)
        return size, "sha256:" + hasher.hexdigest()
    finally:
        if target is not None:
            os.close(target)


def _payload_info(path, uid, *, limit):
    _private(path, uid, sealed=True)
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        # SQLite payloads are standalone sealed snapshots, not live raw files.
        size, hasher = 0, hashlib.sha256()
        if _identity(os.fstat(fd)) != _identity(before):
            raise Denied("capture payload was replaced")
        while True:
            chunk = os.read(fd, CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise Denied("capture payload exceeds bound")
            hasher.update(chunk)
        if size != before.st_size or _identity(os.fstat(fd)) != _identity(before) or _identity(path.lstat()) != _identity(before):
            raise Denied("capture payload changed while reading")
        return size, "sha256:" + hasher.hexdigest()
    finally:
        os.close(fd)


def _scan(component, destination, policy, budget, checkpoint, *, store, prior=None):
    rows, matched, database_paths = [], set(), set()
    root = Path(component.root)
    generated = {path + suffix: {"reason": "SQLite sidecar replaced by standalone database snapshot", "recovery": "generated"}
                 for path in component.databases for suffix in (b"-wal", b"-shm")}
    if set(generated) & (set(component.exclusions) | set(component.databases)):
        raise Denied("SQLite sidecars cannot overlap explicit source rules")
    exclusions = {**component.exclusions, **generated}
    def add(body):
        budget[0] += 1
        budget[1] += body["size"]
        if budget[0] > policy.max_entries or budget[1] > policy.max_bytes:
            raise Denied("complete snapshot exceeds configured bounds; no successful manifest")
        rows.append(body)
        if store:
            checkpoint("after_system_snapshot_entry")
    def walk(fd, path=b""):
        initial = _identity(os.fstat(fd))
        if initial[2] != component.owner_uid:
            raise Denied("component directory changed owner")
        add({"path": base64.b64encode(path).decode(), "kind": "directory", "mode": stat.S_IMODE(initial[3]),
             "size": 0, "digest": None, "link": None, "payload": None, "exclusion": None})
        for name in sorted(os.listdir(fd), key=os.fsencode):
            raw = path + (b"/" if path else b"") + os.fsencode(name)
            encoded = base64.b64encode(raw).decode()
            _path(encoded)
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if before.st_uid != component.owner_uid:
                raise Denied("component entry belongs to another owner")
            if raw in exclusions:
                matched.add(raw)
                add({"path": encoded, "kind": "excluded", "mode": stat.S_IMODE(before.st_mode), "size": 0,
                     "digest": None, "link": None, "payload": None, "exclusion": exclusions[raw]})
            elif stat.S_ISDIR(before.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    if _identity(os.fstat(child)) != _identity(before):
                        raise Denied("directory replaced before capture")
                    walk(child, raw)
                finally:
                    os.close(child)
            elif stat.S_ISLNK(before.st_mode):
                link = os.fsencode(os.readlink(name, dir_fd=fd))
                if len(link) > 8192:
                    raise Denied("symlink target exceeds capture bound")
                add({"path": encoded, "kind": "symlink", "mode": stat.S_IMODE(before.st_mode), "size": len(link),
                     "digest": digest(link), "link": base64.b64encode(link).decode(), "payload": None, "exclusion": None})
            elif stat.S_ISREG(before.st_mode) and before.st_nlink == 1:
                payload = f"{len(rows):08d}.blob"
                if raw in component.databases:
                    database_paths.add(raw)
                    if store:
                        sqlite_copy(root / os.fsdecode(raw), destination / payload)
                        checkpoint("after_system_snapshot_database")
                    size, hashed = _payload_info(destination / payload, os.geteuid(), limit=policy.max_bytes - budget[1])
                    kind = "database"
                else:
                    child = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        if _identity(os.fstat(child)) != _identity(before):
                            raise Denied("file replaced before capture")
                        size, hashed = _file(child, destination / payload if store else None, limit=policy.max_bytes - budget[1])
                    finally:
                        os.close(child)
                    kind = "file"
                add({"path": encoded, "kind": kind, "mode": stat.S_IMODE(before.st_mode), "size": size,
                     "digest": hashed, "link": None, "payload": payload, "exclusion": None})
            else:
                raise Denied("special or hardlinked component entry cannot be silently omitted")
            if _identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) != _identity(before):
                raise Denied("component entry changed during capture")
        if _identity(os.fstat(fd)) != initial:
            raise Denied("component directory changed during capture")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        before = _identity(root.lstat())
        if _identity(os.fstat(fd)) != before:
            raise Denied("component root replaced before capture")
        walk(fd)
        if _identity(root.lstat()) != before:
            raise Denied("component root replaced during capture")
    finally:
        os.close(fd)
    if not set(component.exclusions) <= matched or set(component.databases) != database_paths:
        raise Denied("configured exclusion or database is missing; source retained for review")
    if prior is not None and rows != prior:
        raise Denied("component changed between capture and final validation")
    return rows


def capture(components, policy, destination, *, owner_uid, cohort_id, writer_guard, now, checkpoint=lambda _: None):
    integer(owner_uid, 0)
    identifier(cohort_id)
    if os.geteuid() != owner_uid or not callable(writer_guard) or not callable(now):
        raise Denied("protected capture owner, whole-cohort writer fence and clock required")
    roots = _components(components, policy)
    destination = Path(destination)
    _private(destination.parent, owner_uid, directory=True)
    if not destination.is_absolute() or ".." in destination.parts or any(
            destination == root or destination.is_relative_to(root) or root.is_relative_to(destination) for root in roots):
        raise Denied("new protected capture must not overlap any source")
    captured = integer(now(), 0)  # Conservative capture age includes fence acquisition.
    destination.mkdir(mode=0o700)
    manifest = {"schema": SCHEMA, "cohort_id": cohort_id, "owner_uid": owner_uid, "policy_digest": policy.digest,
                "captured_at_ms": captured, "finished_at_ms": None, "scope": "configured-cohort",
                "restore_mode": "paused", "full_system_backup": False, "encrypted": False, "components": []}
    with writer_guard(components), _frozen(components) as validate_databases:
        checkpoint("after_system_snapshot_freeze")
        validate_databases()
        budget, captured_rows = [0, 0], {}
        for component in sorted(components, key=lambda c: c.id):
            folder = destination / component.id
            folder.mkdir(mode=0o700)
            rows = _scan(component, folder, policy, budget, checkpoint, store=True)
            validate_databases()
            entries_digest = _write_rows(folder / "entries.jsonl", rows)
            fsync_dir(folder)
            captured_rows[component.id] = rows
            manifest["components"].append({"id": component.id, "owner_uid": component.owner_uid,
                "version_digest": component.version_digest, "entry_count": len(rows),
                "total_bytes": sum(row["size"] for row in rows), "entries_digest": entries_digest})
        budget = [0, 0]
        for component in components:
            _scan(component, destination / component.id, policy, budget, checkpoint, store=False, prior=captured_rows[component.id])
            validate_databases()
        _components(components, policy, frozen=True)
        manifest["finished_at_ms"] = integer(now(), captured)
        raw = canonical_bytes(manifest)
        if len(raw) > MANIFEST_LIMIT:
            raise Denied("cohort manifest exceeds bound")
        _inspect_components(destination, manifest, policy, owner_uid)
        checkpoint("before_system_snapshot_manifest")
        validate_databases()
        write_new(destination / "manifest.json", raw)
        fsync_dir(destination)
        checkpoint("after_system_snapshot_manifest")
    return manifest


def _write_rows(path, rows):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    hasher = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            for row in rows:
                raw = canonical_bytes(row) + b"\n"
                if len(raw) > ROW_LIMIT:
                    raise Denied("component manifest row exceeds bound")
                hasher.update(raw)
                handle.write(raw)
            handle.flush()
        os.fchmod(fd, 0o400)
        os.fsync(fd)
    finally:
        os.close(fd)
    return "sha256:" + hasher.hexdigest()


@contextmanager
def _sealed_read(path, uid):
    _private(path, uid, sealed=True)
    before = _identity(path.lstat())
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if _identity(os.fstat(fd)) != before:
            raise Denied("sealed capture metadata replaced before inspection")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            yield handle
        if _identity(os.fstat(fd)) != before or _identity(path.lstat()) != before:
            raise Denied("sealed capture metadata changed during inspection")
    finally:
        os.close(fd)


def _inspect_components(folder, manifest, policy, uid):
    if type(manifest["components"]) is not list or len(manifest["components"]) != len(policy.body["components"]):
        raise Denied("capture component inventory is incomplete")
    ids, budget = [], [0, 0]
    for component in manifest["components"]:
        exact(component, {"id", "owner_uid", "version_digest", "entry_count", "total_bytes", "entries_digest"})
        key = identifier(component["id"])
        integer(component["owner_uid"], 0)
        _hash(component["entries_digest"])
        expected = policy.body["components"].get(key)
        if expected is None or (expected["owner_uid"], expected["version_digest"]) != (component["owner_uid"], component["version_digest"]):
            raise Denied("missing or incompatible captured component")
        ids.append(key)
        root = _private(folder / key, uid, directory=True)
        database_paths = {_path(encoded) for encoded in expected["databases"]}
        explicit = {_path(encoded): rule for encoded, rule in expected["exclusions"].items()}
        generated = {path + suffix: {"reason": "SQLite sidecar replaced by standalone database snapshot", "recovery": "generated"}
                     for path in database_paths for suffix in (b"-wal", b"-shm")}
        if set(generated) & (set(explicit) | database_paths):
            raise Denied("captured database rules overlap")
        exclusions = {**explicit, **generated}
        found, paths, count, total, hasher = {"entries.jsonl"}, {}, 0, 0, hashlib.sha256()
        with _sealed_read(root / "entries.jsonl", uid) as handle:
            while True:
                raw = handle.readline(ROW_LIMIT + 1)
                if not raw:
                    break
                if len(raw) > ROW_LIMIT or not raw.endswith(b"\n"):
                    raise Denied("unbounded or incomplete capture inventory row")
                row = strict_json(raw)
                exact(row, {"path", "kind", "mode", "size", "digest", "link", "payload", "exclusion"})
                path = _path(row["path"], root=count == 0)
                kind = row["kind"]
                mode, size = integer(row["mode"], 0), integer(row["size"], 0)
                if type(kind) is not str or mode > 0o7777 or path in paths or count == 0 and (path or kind != "directory") or \
                        path and paths.get(path.rpartition(b"/")[0]) != "directory":
                    raise Denied("capture inventory path/type structure changed")
                if (path in database_paths) != (kind == "database") or (path in exclusions) != (kind == "excluded"):
                    raise Denied("captured database/exclusion differs from protected source policy")
                paths[path] = kind
                if kind in {"file", "database"}:
                    payload = f"{count:08d}.blob"
                    if row["payload"] != payload or row["link"] is not None or row["exclusion"] is not None or \
                            _payload_info(root / payload, uid, limit=policy.max_bytes - budget[1]) != (size, _hash(row["digest"])):
                        raise Denied("capture payload identity/bytes changed")
                    found.add(payload)
                    if kind == "database":
                        db = sqlite3.connect((root / payload).as_uri() + "?mode=ro&immutable=1", uri=True)
                        try:
                            db.execute("PRAGMA trusted_schema=OFF")
                            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or \
                                    db.execute("PRAGMA journal_mode").fetchone() != ("delete",):
                                raise Denied("captured database is corrupt or needs omitted WAL bytes")
                        finally:
                            db.close()
                elif kind == "symlink":
                    try:
                        link = base64.b64decode(row["link"], validate=True)
                    except (TypeError, ValueError):
                        raise Denied("invalid captured link") from None
                    if len(link) > 8192 or len(link) != size or digest(link) != row["digest"] or \
                            base64.b64encode(link).decode() != row["link"] or row["payload"] is not None or row["exclusion"] is not None:
                        raise Denied("captured link metadata changed")
                elif kind in {"directory", "excluded"}:
                    if size != 0 or any(row[field] is not None for field in ("digest", "payload", "link")):
                        raise Denied("non-payload capture entry changed")
                    if kind == "excluded":
                        _exclusion(row["exclusion"])
                        if row["exclusion"] != exclusions[path]:
                            raise Denied("exclusion recovery differs from protected policy")
                    elif row["exclusion"] is not None:
                        raise Denied("directory cannot hide an exclusion")
                else:
                    raise Denied("unknown captured entry type; preserve for reviewed migration")
                hasher.update(raw)
                count += 1
                total += size
                budget[0] += 1
                budget[1] += size
                if budget[0] > policy.max_entries or budget[1] > policy.max_bytes:
                    raise Denied("capture inventory exceeds policy")
        if not (database_paths | set(explicit)) <= set(paths) or count != integer(component["entry_count"]) or total != integer(component["total_bytes"], 0) or \
                "sha256:" + hasher.hexdigest() != component["entries_digest"] or {p.name for p in root.iterdir()} != found:
            raise Denied("capture entries are missing, changed or unlisted")
    if ids != sorted(set(policy.body["components"])):
        raise Denied("capture component ordering, coverage or uniqueness changed")
    if {p.name for p in folder.iterdir()} != set(ids) | ({"manifest.json"} if (folder / "manifest.json").exists() else set()):
        raise Denied("capture contains unknown component paths")


def _manifest(raw, policy, owner_uid):
    """Validate a pending manifest before publishing its complete marker."""
    if len(raw) > MANIFEST_LIMIT:
        raise Denied("cohort manifest exceeds bound")
    manifest = strict_json(raw)
    exact(manifest, {"schema", "cohort_id", "owner_uid", "policy_digest", "captured_at_ms", "finished_at_ms",
                     "scope", "restore_mode", "full_system_backup", "encrypted", "components"})
    identifier(manifest["cohort_id"])
    start = integer(manifest["captured_at_ms"], 0)
    integer(manifest["finished_at_ms"], start)
    if manifest["schema"] != SCHEMA or type(manifest["owner_uid"]) is not int or manifest["owner_uid"] != owner_uid or \
            manifest["policy_digest"] != policy.digest or manifest["scope"] != "configured-cohort" or \
            manifest["restore_mode"] != "paused" or manifest["full_system_backup"] is not False or manifest["encrypted"] is not False:
        raise Denied("unsupported capture schema/owner/scope; preserve original bytes")
    return manifest


def inspect_snapshot(directory, policy, *, owner_uid):
    """Read-only integrity against protected expected policy; no restore permission."""
    integer(owner_uid, 0)
    if type(policy) is not SnapshotPolicy or os.geteuid() != owner_uid or fingerprint(policy.body) != policy.digest:
        raise Denied("capture owner and unchanged protected policy required")
    folder = _private(directory, owner_uid, directory=True)
    with _sealed_read(folder / "manifest.json", owner_uid) as handle:
        raw = handle.read(MANIFEST_LIMIT + 1)
    manifest = _manifest(raw, policy, owner_uid)
    _inspect_components(folder, manifest, policy, owner_uid)
    with _sealed_read(folder / "manifest.json", owner_uid) as handle:
        if handle.read(MANIFEST_LIMIT + 1) != raw:
            raise Denied("cohort manifest changed during payload inspection")
    return manifest
