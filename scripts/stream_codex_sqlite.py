"""Backup live SQLite into memory, then stream a synthetic archive; no source temp.

Only the production entry point selects the literal Mac Codex home. Fixtures
call the functions with their own roots. Verification changes WAL header flags
ONLY in a disposable memory copy, as documented by SQLite's deserialize API.
The archived original snapshot is never modified or installed as active state.
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import re
import resource
import sqlite3
import stat
import sys
import tarfile
import time


NAME = re.compile(r"[a-z][a-z0-9_]*\.sqlite\Z")
MAX_DB = 1 << 30
MAX_TOTAL = 2 << 30
MANIFEST_LIMIT = 65536
SCHEMA = "ccrelay.memory_sqlite_snapshot.v1"


class DigestWriter:
    def __init__(self, output, limit):
        self.output, self.limit, self.count = output, limit, 0
        self.hash = hashlib.sha256()

    def write(self, value):
        if len(value) > self.limit - self.count:
            raise ValueError("compressed archive byte bound exceeded")
        if self.output.write(value) != len(value):
            raise OSError("partial archive write")
        self.hash.update(value)
        self.count += len(value)
        return len(value)

    def flush(self):
        self.output.flush()


class BlobReader:
    def __init__(self, value):
        self.value, self.offset = value, 0

    def read(self, size):
        end = min(len(self.value), self.offset + size)
        result = self.value[self.offset:end]
        self.offset = end
        return result


def inspect_blob(value):
    if len(value) < 100 or value[:16] != b"SQLite format 3\x00" or value[18:20] not in (b"\x01\x01", b"\x02\x02"):
        raise ValueError("unsupported SQLite image/header")
    # sqlite3_deserialize cannot use WAL-mode images. Normalize its temporary
    # input only; keep the authoritative serialized bytes and digest untouched.
    derived = value[:18] + b"\x01\x01" + value[20:] if value[18:20] == b"\x02\x02" else value
    check = sqlite3.connect(":memory:")
    try:
        check.deserialize(derived)
        check.execute("PRAGMA query_only=ON")
        check.execute("PRAGMA temp_store=MEMORY")
        if check.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("serialized image failed integrity check")
    finally:
        check.close()


def _member(archive, name, value, captured_at):
    record = tarfile.TarInfo(name)
    record.size, record.mode, record.mtime = len(value), 0o600, int(captured_at)
    archive.addfile(record, BlobReader(value))


def stream_snapshot(root, output, *, owner_uid, max_database_bytes=MAX_DB,
                    max_total_bytes=MAX_TOTAL, timeout_seconds=180):
    for bound in (max_database_bytes, max_total_bytes, timeout_seconds):
        if type(bound) is not int or bound <= 0:
            raise ValueError("explicit positive bounds required")
    root = Path(root)
    meta = root.lstat()
    if not root.is_absolute() or root.resolve() != root or not stat.S_ISDIR(meta.st_mode) or meta.st_uid != owner_uid:
        raise ValueError("literal owned source directory required")
    names = sorted(p.name for p in root.iterdir() if NAME.fullmatch(p.name))
    if not 1 <= len(names) <= 32:
        raise ValueError("bounded nonempty SQLite source set required")
    started, deadline = time.time(), time.monotonic() + timeout_seconds
    writer = DigestWriter(output, max_total_bytes)
    records, total = [], 0
    with gzip.GzipFile(fileobj=writer, mode="wb", compresslevel=1, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
            for name in names:
                if time.monotonic() >= deadline:
                    raise TimeoutError("snapshot cohort deadline")
                path = root / name
                before = path.lstat()
                if not stat.S_ISREG(before.st_mode) or before.st_uid != owner_uid or before.st_nlink != 1:
                    raise ValueError("literal single-link owned database required")
                if before.st_size > max_database_bytes:
                    raise ValueError("source database byte bound exceeded")
                # NEVER immutable=1 on a live WAL source. mode=ro prevents SQL
                # data writes; SQLite may initialize tiny WAL/SHM companions.
                source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
                memory = sqlite3.connect(":memory:")
                captured_at = time.time()
                try:
                    source.execute("PRAGMA query_only=ON")
                    source.execute("PRAGMA temp_store=MEMORY")
                    source.execute("PRAGMA cache_size=-8192")
                    page_size = source.execute("PRAGMA page_size").fetchone()[0]
                    memory.execute("PRAGMA page_size=" + str(page_size))
                    def progress(status, remaining, pages):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("database backup deadline")
                        if pages * page_size > max_database_bytes or total + pages * page_size > max_total_bytes:
                            raise ValueError("snapshot page/total bound exceeded")
                    source.backup(memory, pages=256, progress=progress, sleep=0.01)
                    if memory.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                        raise ValueError("memory snapshot integrity failed")
                    value = memory.serialize()
                finally:
                    memory.close()
                    source.close()
                after = path.lstat()
                if (before.st_dev, before.st_ino, before.st_uid, stat.S_IFMT(before.st_mode)) != \
                        (after.st_dev, after.st_ino, after.st_uid, stat.S_IFMT(after.st_mode)):
                    raise ValueError("source database identity changed")
                if len(value) > max_database_bytes or total + len(value) > max_total_bytes:
                    raise ValueError("serialized snapshot bound exceeded")
                total += len(value)
                records.append({"name": name, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest(),
                                "capturedAt": captured_at, "quickCheck": "ok", "sourceDevice": before.st_dev,
                                "sourceInode": before.st_ino, "sourceUid": before.st_uid})
                _member(archive, name, value, captured_at)
                del value
            if names != sorted(p.name for p in root.iterdir() if NAME.fullmatch(p.name)):
                raise ValueError("SQLite source set changed")
            manifest = {"schema": SCHEMA, "startedAt": started, "finishedAt": time.time(), "databases": records,
                        "consistentPerDatabase": True, "consistentFinalSnapshot": False,
                        "sourceWritersStopped": False, "sourceTemporaryDatabaseFiles": False,
                        "sqliteVersion": sqlite3.sqlite_version}
            raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            if len(raw) > MANIFEST_LIMIT:
                raise ValueError("snapshot manifest bound exceeded")
            _member(archive, "capture.json", raw, time.time())
    return {"schema": "ccrelay.mac_archive_producer.v1", "producerExit": 0, "warningBytes": 0,
            "warningTruncated": False, "bytes": writer.count, "sha256": writer.hash.hexdigest(),
            "snapshotSchema": SCHEMA, "databaseCount": len(records), "databaseBytes": total,
            "consistentPerDatabase": True, "consistentFinalSnapshot": False,
            "sourceTemporaryDatabaseFiles": False}


def verify_archive(path, *, max_database_bytes=MAX_DB, max_total_bytes=MAX_TOTAL):
    records, manifest, total = [], None, 0
    with tarfile.open(path, mode="r|gz") as archive:
        for member in archive:
            if manifest is not None or not member.isfile() or member.size < 0 or member.mode != 0o600:
                raise ValueError("unexpected archive entry/order/type")
            stream = archive.extractfile(member)  # A stream only: NEVER extract to a pathname.
            if member.name == "capture.json":
                if member.size > MANIFEST_LIMIT:
                    raise ValueError("manifest byte bound")
                manifest = json.loads(stream.read(MANIFEST_LIMIT + 1))
            else:
                if not NAME.fullmatch(member.name) or member.size > max_database_bytes or \
                        len(records) >= 32 or member.name in {r["name"] for r in records} or total + member.size > max_total_bytes:
                    raise ValueError("database name/count/byte bound")
                value = stream.read(member.size + 1)
                if len(value) != member.size:
                    raise ValueError("incomplete database member")
                inspect_blob(value)
                total += len(value)
                records.append({"name": member.name, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()})
                del value
    if not records or not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA or \
            manifest.get("consistentPerDatabase") is not True or manifest.get("consistentFinalSnapshot") is not False or \
            manifest.get("sourceWritersStopped") is not False or manifest.get("sourceTemporaryDatabaseFiles") is not False:
        raise ValueError("missing/incompatible memory snapshot manifest")
    declared = manifest.get("databases")
    if not isinstance(declared, list) or len(declared) != len(records) or [r["name"] for r in records] != sorted(r["name"] for r in records):
        raise ValueError("source/target database manifest set differs")
    for expected, actual in zip(declared, records):
        if any(expected.get(key) != actual[key] for key in actual) or expected.get("quickCheck") != "ok":
            raise ValueError("source/target database digest or integrity differs")
    return {"schema": "ccrelay.memory_sqlite_target_verification.v1", "verified": True,
            "databaseCount": len(records), "databaseBytes": total, "consistentPerDatabase": True,
            "consistentFinalSnapshot": False, "activeProfileChanged": False, "extractedToFilesystem": False,
            "walHeaderNormalization": "disposable verification memory only; archive unchanged"}


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--verify":
            path = sys.argv[2]
            if sys.platform != "linux" or os.geteuid() != 1000 or not re.fullmatch(
                    r"/mnt/c/ProgramData/OracovaMigration/[0-9a-f]{32}/vm-codex-sqlite\.tar\.gz", path):
                raise ValueError("literal PC verification archive required")
            print(json.dumps(verify_archive(path), separators=(",", ":")))
        elif len(sys.argv) == 1:
            if sys.platform != "darwin" or os.geteuid() == 0 or pwd.getpwuid(os.geteuid()).pw_name != "pouya":
                raise ValueError("ordinary Mac owner required")
            report = stream_snapshot("/Users/pouya/.codex", sys.stdout.buffer, owner_uid=os.geteuid())
            report["peakRssBytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            print(json.dumps(report, separators=(",", ":")), file=sys.stderr)
        else:
            raise ValueError("unsupported capture arguments")
    except Exception as error:
        print(json.dumps({"schema": "ccrelay.mac_archive_producer.v1", "producerExit": 1,
                          "errorType": type(error).__name__}, separators=(",", ":")), file=sys.stderr)
        sys.exit(1)
