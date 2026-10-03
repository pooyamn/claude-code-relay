"""Telegram-local recovery bytes, not a full-system backup or send permission.

The protected driver calls capture between requests, with asset/spool writers
quiesced. Both SQLite writers are frozen together; independent read connections
copy their committed WAL state without deadlocking the held write transactions.
Files are streamed and checked for changes. The manifest is published last.

Dependency hashes are references, not proof those external components were
captured, are authentic or currently authorize delivery. Encryption, coordinated
broker/native/company capture and target-host durability remain separate gates.
"""
from contextlib import ExitStack, contextmanager
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat

from .artifacts import fsync_dir, relative_path, write_new
from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, integer, protected_path
from .intake import MAX_RESPONSE, provider_json
from .snapshot_io import sqlite_copy as _sqlite_copy
from .telegram_outbound import OutboundPolicy, validate_asset


SCHEMA = "ccrelay.telegram_component_snapshot.v1"
DEPENDENCIES = {"broker_registry", "native_source_registry", "company_root_context",
                "adapter_artifact", "binding_read_policy"}
DIRECTORIES = ("outbox", "outbox/responses", "source-grants", "assets", "policy")
DATABASES = ("outbox/outbox.sqlite", "source-grants/source-grants.sqlite")
REQUIRED = {*DATABASES, "policy/outbound.json"}
QUEUE_TABLES = {"metadata", "intents", "evidence", "telegram_metadata", "telegram_bundles",
                "telegram_operations", "telegram_cooldowns", "telegram_chats", "telegram_repairs", "telegram_streams"}
GRANT_TABLES = {"metadata", "grants", "grant_events"}
SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
HEX = r"[0-9a-f]{64}"


def _digest(value):
    if type(value) is not str or not SHA.fullmatch(value):
        raise Denied("exact component digest required")
    return value


def _directory(path, uid):
    path = protected_path(path, owners={0, uid}, directory=True, private=True)
    value = path.lstat()
    if value.st_uid != uid or not stat.S_ISDIR(value.st_mode) or value.st_mode & 0o077:
        raise Denied("component directory has wrong owner/type/private mode")
    return path


def _stamp(path, uid, *, sealed=False):
    protected_path(path, owners={uid}, private=True)
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or value.st_uid != uid or \
            stat.S_IMODE(value.st_mode) not in ({0o400} if sealed else {0o400, 0o600}):
        raise Denied("private unlinked component file required; published bytes must be sealed")
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _read(path, uid, limit):
    before = _stamp(path, uid, sealed=True)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit or _stamp(path, uid, sealed=True) != before or \
                os.fstat(fd).st_ino != before[1]:
            raise Denied("bounded unchanged sealed component required")
        return raw
    finally:
        os.close(fd)


def _stream(path, uid, destination=None, *, sealed=False, expected=None, output_mode=0o400):
    """Hash/copy arbitrary DB/upload sizes with bounded working memory."""
    before = _stamp(path, uid, sealed=sealed)
    if expected is not None and before != expected:
        raise Denied("component changed before snapshot copy")
    source = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    target = None
    try:
        observed = os.fstat(source)
        if (observed.st_dev, observed.st_ino) != before[:2]:
            raise Denied("component replaced before snapshot copy")
        if destination is not None:
            target = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        hasher, size = hashlib.sha256(), 0
        while True:
            chunk = os.read(source, 65536)
            if not chunk:
                break
            size += len(chunk)
            hasher.update(chunk)
            if target is not None:
                view = memoryview(chunk)
                while view:
                    written = os.write(target, view)
                    if written <= 0:
                        raise Denied("snapshot copy did not make progress")
                    view = view[written:]
        if size != before[5] or _stamp(path, uid, sealed=sealed) != before:
            raise Denied("component changed during snapshot copy")
        if target is not None:
            os.fchmod(target, output_mode)
            os.fsync(target)
        return {"size_bytes": size, "digest": "sha256:" + hasher.hexdigest()}
    finally:
        os.close(source)
        if target is not None:
            os.close(target)


def _payloads(folder, uid, kind):
    _directory(folder, uid)
    result = {}
    for path in sorted(folder.iterdir()):
        pending = bool(re.fullmatch(r"[0-9a-f]{32}\.pending", path.name))
        published = bool(re.fullmatch(HEX + (r"\.blob" if kind == "assets" else r"\.body"), path.name))
        if kind == "responses" and path.name.endswith(".receipt"):
            identifier(path.name[:-8])
            published = True
        if not pending and not published:
            raise Denied("unrecognized component file; preserve it for reviewed migration")
        result[path.name] = _stamp(path, uid, sealed=not pending)
    return result


def _db_root(folder, uid, database, *, outbox=False):
    _directory(folder, uid)
    allowed = {database, database + "-wal", database + "-shm"}
    if outbox:
        allowed |= {"outbox.lock", "responses"}
    for path in folder.iterdir():
        if path.name not in allowed:
            raise Denied("unrecognized database component; preserve it for reviewed migration")
        if outbox and path.name == "responses":
            _directory(path, uid)
        else:
            _stamp(path, uid)


@contextmanager
def _frozen(ledger, grants):
    ledger._check_lock()
    if ledger.connection.in_transaction or grants.db.in_transaction:
        raise Denied("snapshot requires a quiescent boundary, not a caller transaction")
    with ExitStack() as held:
        # Fixed ordering avoids competing capture writers taking opposite locks.
        for connection in (grants.db, ledger.connection):
            connection.execute("BEGIN IMMEDIATE")
            held.callback(connection.execute, "ROLLBACK")
        ledger._check_lock()
        yield


def _validate_databases(folder, manifest):
    uid = manifest["owner_uid"]
    policy = OutboundPolicy(provider_json(_read(folder / "policy/outbound.json", uid, MAX_RESPONSE)))
    expected = [([("ccrelay.outbox.v1", manifest["outbound_policy_digest"])], QUEUE_TABLES),
                ([("ccrelay.telegram_source_grants.v1", manifest["outbound_policy_digest"],
                   manifest["broker_policy_digest"])], GRANT_TABLES)]
    for path, (metadata, tables) in zip(DATABASES, expected):
        # immutable is only for the sealed standalone snapshot, never the live WAL.
        db = sqlite3.connect((folder / path).as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            db.execute("PRAGMA trusted_schema=OFF")
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or \
                    db.execute("SELECT * FROM metadata").fetchall() != metadata:
                raise Denied("snapshot database integrity/schema/policy mismatch")
            shape = db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            if {name for kind, name in shape if kind == "table"} != tables or \
                    any(kind not in {"table", "index"} for kind, _ in shape):
                raise Denied("unknown snapshot database component shape; preserve for migration")
            if path == DATABASES[0]:
                rows = db.execute("SELECT schema,bot_id,last_clock_ms,global_after_ms FROM telegram_metadata").fetchall()
                if len(rows) != 1 or rows[0][:2] != ("ccrelay.telegram_queue.v2", manifest["bot_id"]):
                    raise Denied("snapshot queue schema/bot mismatch")
                integer(rows[0][2], 0)
                integer(rows[0][3], 0)
                # Original manifests include original filenames/MIME types and
                # every pre-enrolled repair upload. Missing bytes are not a
                # complete local backup even when SQLite itself is healthy.
                for bundle_id, raw, body_digest in db.execute("SELECT id,body,digest FROM telegram_bundles"):
                    body = provider_json(raw)
                    exact(body, {"schema", "id", "root_task_id", "session_id", "chat_id", "thread_id", "lane",
                                 "source", "operations", "cursor", "coalesce_key", "repair_plans"})
                    if body["schema"] != "ccrelay.telegram_bundle.v2" or body["id"] != bundle_id or \
                            fingerprint(body) != body_digest or type(body["operations"]) is not list or \
                            not body["operations"] or type(body["repair_plans"]) is not list:
                        raise Denied("snapshot bundle format/digest mismatch")
                    operations = list(body["operations"])
                    for recipe in body["repair_plans"]:
                        if recipe is not None:
                            if type(recipe) is not dict or type(recipe.get("operations")) is not list:
                                raise Denied("unknown snapshot repair manifest")
                            operations.extend(recipe["operations"])
                    for operation in operations:
                        policy.operation(operation, body["chat_id"])
                        for reference in operation["assets"].values():
                            validate_asset(reference)
                            info = _stream(folder / "assets" / (reference["digest"][7:] + ".blob"), uid, sealed=True)
                            if info != {"size_bytes": reference["size_bytes"], "digest": reference["digest"]}:
                                raise Denied("snapshot lacks exact original/repair upload bytes")
        finally:
            db.close()


def _new_tree(destination, uid, sources):
    destination = Path(destination)
    if not destination.is_absolute() or ".." in destination.parts:
        raise Denied("absolute new protected destination required")
    _directory(destination.parent, uid)
    if any(destination == source or destination.is_relative_to(source) or source.is_relative_to(destination)
           for source in sources):
        raise Denied("snapshot/restore destination overlaps its sources")
    destination.mkdir(mode=0o700)  # Existing paths, including symlinks, are never overwritten.
    for name in DIRECTORIES:
        (destination / name).mkdir(mode=0o700)
    fsync_dir(destination.parent)
    return destination


def _tree_files(folder, uid, *, published):
    actual = set()
    for path in folder.rglob("*"):
        name = path.relative_to(folder).as_posix()
        if name in DIRECTORIES:
            _directory(path, uid)
        else:
            _stamp(path, uid, sealed=True)
            if published and name == "manifest.json":
                continue
            actual.add(name)
    if any(not (folder / name).is_dir() for name in DIRECTORIES):
        raise Denied("snapshot lacks its complete directory layout")
    return actual


def capture(ledger, grants, assets, destination, *, cohort_id, external_digests, checkpoint=lambda _: None):
    """Protected-driver API, never a worker RPC. Failure leaves source bytes intact."""
    uid = ledger.owner_uid
    integer(uid)
    identifier(cohort_id)
    exact(external_digests, DEPENDENCIES)
    external_digests = {key: _digest(value) for key, value in sorted(external_digests.items())}
    if os.geteuid() != uid or grants.uid != uid or assets.owner_uid != uid or grants.ledger is not ledger or \
            ledger.policy_digest != ledger.policy.digest or fingerprint(ledger.policy.raw) != ledger.policy.digest:
        raise Denied("snapshot requires the matching protected Telegram component owners/policies")
    for folder, database, outbox in ((ledger.folder, "outbox.sqlite", True),
                                     (grants.folder, "source-grants.sqlite", False)):
        _db_root(folder, uid, database, outbox=outbox)
    _directory(assets.folder, uid)
    database_identity = {path: _stamp(path, uid)[:5] for path in (ledger.path, grants.path)}
    manifest = {"schema": SCHEMA, "cohort_id": cohort_id, "owner_uid": uid, "bot_id": ledger.policy.bot_id,
                "captured_at_ms": ledger.now(), "outbound_policy_digest": ledger.policy.digest,
                "broker_policy_digest": _digest(grants.authority.policy.digest),
                "external_digests": external_digests, "scope": "telegram-local", "restore_mode": "paused",
                "full_system_backup": False, "files": []}
    destination = _new_tree(destination, uid, (ledger.folder, grants.folder, assets.folder))
    with _frozen(ledger, grants):
        inventories = [(assets.folder, "assets", _payloads(assets.folder, uid, "assets")),
                       (ledger.responses, "outbox/responses", _payloads(ledger.responses, uid, "responses"))]
        checkpoint("after_snapshot_freeze")
        for source, name in ((ledger.path, DATABASES[0]), (grants.path, DATABASES[1])):
            if _stamp(source, uid)[:5] != database_identity[source]:
                raise Denied("live database path changed during capture")
            _sqlite_copy(source, destination / name)
            if _stamp(source, uid)[:5] != database_identity[source]:
                raise Denied("live database path changed during capture")
            checkpoint("after_snapshot_database")
        write_new(destination / "policy/outbound.json", canonical_bytes(ledger.policy.raw))
        for source, prefix, inventory in inventories:
            for name, stamp in inventory.items():
                _stream(source / name, uid, destination / prefix / name,
                        sealed=not name.endswith(".pending"), expected=stamp)
                checkpoint("after_snapshot_file")
        for source, prefix, inventory in inventories:
            if _payloads(source, uid, "assets" if prefix == "assets" else "responses") != inventory:
                raise Denied("component files changed during capture; writers must be quiesced")
        _validate_databases(destination, manifest)
        names = sorted([*REQUIRED, *(prefix + "/" + name for _, prefix, inventory in inventories for name in inventory)])
        for name in names:
            info = _stream(destination / name, uid, sealed=True)
            if name.endswith((".blob", ".body")) and info["digest"] != "sha256:" + Path(name).stem:
                raise Denied("snapshot content-addressed bytes have changed")
            # Pending bytes survive forensics, but never become receipt/upload evidence.
            manifest["files"].append({"path": name, **info, "forensic_only": name.endswith(".pending")})
        raw = canonical_bytes(manifest)
        if len(raw) > MAX_RESPONSE:
            raise Denied("snapshot manifest exceeds inspection bound; source bytes retained")
        if _tree_files(destination, uid, published=False) != set(names):
            raise Denied("snapshot export has missing or unlisted component files")
        for directory in reversed(DIRECTORIES):
            fsync_dir(destination / directory)
        fsync_dir(destination)
        ledger._check_lock()
        checkpoint("before_snapshot_manifest")
        write_new(destination / "manifest.json", raw)
        fsync_dir(destination)
        checkpoint("after_snapshot_manifest")
    return manifest


def inspect_snapshot(directory, *, owner_uid):
    """Read-only byte/schema integrity; NOT authenticity, current grants or activation."""
    integer(owner_uid)
    if os.geteuid() != owner_uid:
        raise Denied("snapshot inspection requires its protected owner")
    folder = _directory(directory, owner_uid)
    manifest = provider_json(_read(folder / "manifest.json", owner_uid, MAX_RESPONSE))
    exact(manifest, {"schema", "cohort_id", "owner_uid", "bot_id", "captured_at_ms", "outbound_policy_digest",
                     "broker_policy_digest", "external_digests", "scope", "restore_mode", "full_system_backup", "files"})
    if manifest["schema"] != SCHEMA or type(manifest["owner_uid"]) is not int or manifest["owner_uid"] != owner_uid or \
            manifest["scope"] != "telegram-local" or manifest["restore_mode"] != "paused" or manifest["full_system_backup"] is not False:
        raise Denied("unsupported snapshot scope/schema/owner; preserve for reviewed recovery")
    identifier(manifest["cohort_id"])
    integer(manifest["bot_id"])
    integer(manifest["captured_at_ms"], 0)
    _digest(manifest["outbound_policy_digest"])
    _digest(manifest["broker_policy_digest"])
    exact(manifest["external_digests"], DEPENDENCIES)
    for value in manifest["external_digests"].values():
        _digest(value)
    if type(manifest["files"]) is not list:
        raise Denied("complete snapshot file inventory required")
    names = []
    for item in manifest["files"]:
        exact(item, {"path", "size_bytes", "digest", "forensic_only"})
        name = relative_path(item["path"])
        names.append(name)
        integer(item["size_bytes"], 0)
        _digest(item["digest"])
        if type(item["forensic_only"]) is not bool or item["forensic_only"] != name.endswith(".pending"):
            raise Denied("pending snapshot bytes cannot become delivery evidence")
        info = _stream(folder / name, owner_uid, sealed=True)
        if info != {"size_bytes": item["size_bytes"], "digest": item["digest"]}:
            raise Denied("snapshot bytes differ from manifest")
        if name.endswith((".blob", ".body")) and info["digest"] != "sha256:" + Path(name).stem:
            raise Denied("snapshot content-addressed bytes have changed")
    if names != sorted(set(names)) or not REQUIRED <= set(names):
        raise Denied("snapshot inventory is duplicate, unordered or incomplete")
    if _tree_files(folder, owner_uid, published=True) != set(names):
        raise Denied("snapshot has missing or unlisted files/directories")
    # Validate path classes too: a forged manifest cannot rename pending data.
    _payloads(folder / "assets", owner_uid, "assets")
    _payloads(folder / "outbox/responses", owner_uid, "responses")
    if set(names) - REQUIRED != {"assets/" + name for name in _payloads(folder / "assets", owner_uid, "assets")} | \
            {"outbox/responses/" + name for name in _payloads(folder / "outbox/responses", owner_uid, "responses")}:
        raise Denied("unknown snapshot payload location")
    policy = OutboundPolicy(provider_json(_read(folder / "policy/outbound.json", owner_uid, MAX_RESPONSE)))
    if policy.digest != manifest["outbound_policy_digest"] or policy.bot_id != manifest["bot_id"]:
        raise Denied("snapshot policy identity mismatch")
    _validate_databases(folder, manifest)
    return manifest


def restore_snapshot(directory, destination, *, owner_uid, checkpoint=lambda _: None):
    """Materialize a NEW local component tree only; never open a runtime or sender.

    No current permission is inferred, grants renewed, offsets reset, attempts
    retried, lock ownership imported or service activated. The coordinator must
    keep services stopped until full-system/external-outcome review finishes.
    """
    manifest = inspect_snapshot(directory, owner_uid=owner_uid)
    source = Path(directory)
    destination = _new_tree(destination, owner_uid, (source,))
    for item in manifest["files"]:
        name = item["path"]
        info = _stream(source / name, owner_uid, destination / name, sealed=True,
                       output_mode=0o600 if name in DATABASES else 0o400)
        if info != {"size_bytes": item["size_bytes"], "digest": item["digest"]}:
            raise Denied("snapshot changed during restore; retained destination is incomplete")
        checkpoint("after_restore_file")
    if inspect_snapshot(source, owner_uid=owner_uid) != manifest:
        raise Denied("snapshot manifest changed during restore")
    for directory_name in reversed(DIRECTORIES):
        fsync_dir(destination / directory_name)
    fsync_dir(destination)
    checkpoint("before_restore_manifest")
    write_new(destination / "restore.json", canonical_bytes({"schema": "ccrelay.telegram_component_restore.v1",
              "snapshot_digest": fingerprint(manifest), "cohort_id": manifest["cohort_id"],
              "mode": "paused", "activation_performed": False, "full_system_backup": False}))
    fsync_dir(destination)
    checkpoint("after_restore_manifest")
    return manifest
