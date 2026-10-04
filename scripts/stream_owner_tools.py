"""Stream owner files plus explicit live-socket metadata, without source temp files.

The previous BSD tar cohort remains an unaccepted attempt. This is a distinct
capture format: all selected file bytes and links are represented, while Unix
sockets have metadata in the manifest, not misleading empty file replacements.
No activation, socket-state recovery, ACL/xattr closure or final writer fence is
claimed. Production roots are literal; fixture callers supply their own roots.
"""
import gzip
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import tarfile
import time


MEMBERS = (".CFUserTextEncoding", ".DS_Store", ".anydesk", ".aspnet", ".azure", ".bun", ".cargo",
           ".claude.json", ".claude.json.bak-trust-20260924-190310", ".config", ".copilot", ".dotnet",
           ".gitconfig", ".homebrew", ".kimi-code", ".local", ".matplotlib", ".net", ".nuget",
           ".rustup", ".ssh", ".templateengine", ".webos", ".zcompdump", ".zprofile", ".zsh_history",
           ".zsh_sessions", ".zshrc", ".zshrc.bak-opus5-20260727-192500")
SCHEMA = "ccrelay.owner_tools_file_manifest.v1"
MAX_ARCHIVE = 20 << 30
MAX_ENTRIES = 750000
MAX_MANIFEST = 160 << 20
MAX_FILE_BYTES = 40 << 30
MANIFEST_NAME = "capture.json"


class DigestWriter:
    def __init__(self, output, limit):
        self.output, self.limit, self.count = output, limit, 0
        self.hash = hashlib.sha256()

    def write(self, value):
        if len(value) > self.limit - self.count:
            raise ValueError("archive byte bound")
        if self.output.write(value) != len(value):
            raise OSError("short output write")
        self.hash.update(value)
        self.count += len(value)
        return len(value)

    def flush(self):
        self.output.flush()


class DigestReader:
    def __init__(self, source, deadline):
        self.source, self.deadline = source, deadline
        self.hash = hashlib.sha256()
        self.count = 0

    def read(self, size):
        if time.monotonic() >= self.deadline:
            raise TimeoutError("file read deadline")
        value = self.source.read(size)
        self.hash.update(value)
        self.count += len(value)
        return value


def identity(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_uid,
            metadata.st_gid, metadata.st_nlink, metadata.st_size,
            metadata.st_mtime_ns, metadata.st_ctime_ns)


def safe_name(name):
    if not isinstance(name, str) or not name or name.startswith("/") or "\\" in name or \
            any(part in ("", ".", "..") for part in name.split("/")) or \
            any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in name):
        raise ValueError("unsafe archive name")
    return name


def capture(root, output, *, owner_uid, members=MEMBERS, max_entries=MAX_ENTRIES,
            max_archive=MAX_ARCHIVE, max_manifest=MAX_MANIFEST, max_file_bytes=MAX_FILE_BYTES, timeout_seconds=850,
            expected_leaves=None):
    if any(type(v) is not int or v <= 0 for v in (max_entries, max_archive, max_manifest, max_file_bytes, timeout_seconds)):
        raise ValueError("positive capture bounds required")
    members = tuple(members)
    leaf_mode = expected_leaves is not None
    if not members or len(set(members)) != len(members) or any(
            ("/" in safe_name(n) and not leaf_mode) or n == MANIFEST_NAME for n in members):
        raise ValueError("unique direct source members required")
    if leaf_mode and (not isinstance(expected_leaves, dict) or set(expected_leaves) != set(members) or
            any(row.get('kind') not in ('file', 'symlink') for row in expected_leaves.values())):
        raise ValueError('Exact regular-file/symlink selection required')
    root = Path(root)
    metadata = root.lstat()
    if not root.is_absolute() or root.resolve() != root or not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != owner_uid:
        raise ValueError("literal owner root required")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    writer = DigestWriter(output, max_archive)
    records, file_bytes, sockets = [], 0, 0
    started, deadline = time.time(), time.monotonic() + timeout_seconds
    try:
        if identity(os.fstat(root_fd)) != identity(metadata):
            raise ValueError("source root replaced")
        with gzip.GzipFile(fileobj=writer, mode="wb", compresslevel=1, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                def visit(parent_fd, base, relative):
                    nonlocal file_bytes, sockets
                    if time.monotonic() >= deadline:
                        raise TimeoutError("capture deadline")
                    if len(records) >= max_entries:
                        raise ValueError("source entry bound")
                    safe_name(relative)
                    before = os.stat(base, dir_fd=parent_fd, follow_symlinks=False)
                    if leaf_mode and not (stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)):
                        raise ValueError('Selected leaf changed object type')
                    info = tarfile.TarInfo(relative)
                    info.mode, info.uid, info.gid = stat.S_IMODE(before.st_mode), before.st_uid, before.st_gid
                    info.mtime = before.st_mtime_ns // 1000000000
                    info.pax_headers["mtime"] = "%d.%09d" % divmod(before.st_mtime_ns, 1000000000)
                    record = {"name": relative, "mode": info.mode, "uid": info.uid, "gid": info.gid,
                              "sourceDevice": before.st_dev, "sourceInode": before.st_ino,
                              "sourceLinks": before.st_nlink, "mtimeNs": before.st_mtime_ns,
                              "ctimeNs": before.st_ctime_ns}
                    records.append(record)
                    if stat.S_ISDIR(before.st_mode):
                        record["kind"] = "directory"
                        descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                        try:
                            if identity(os.fstat(descriptor)) != identity(before):
                                raise ValueError("directory replaced")
                            names = sorted(os.listdir(descriptor))
                            info.type = tarfile.DIRTYPE
                            archive.addfile(info)
                            for child in names:
                                visit(descriptor, child, relative + "/" + child)
                            if names != sorted(os.listdir(descriptor)):
                                raise ValueError("directory source set changed")
                        finally:
                            os.close(descriptor)
                    elif stat.S_ISREG(before.st_mode):
                        if before.st_size > max_file_bytes - file_bytes:
                            raise ValueError("logical file byte bound")
                        descriptor = os.open(base, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
                        with os.fdopen(descriptor, "rb", buffering=0) as source:
                            if identity(os.fstat(source.fileno())) != identity(before):
                                raise ValueError("file replaced")
                            info.size = before.st_size
                            reader = DigestReader(source, deadline)
                            archive.addfile(info, reader)
                            if reader.count != before.st_size or identity(os.fstat(source.fileno())) != identity(before):
                                raise ValueError("file changed during capture")
                        record.update(kind="file", bytes=reader.count, sha256=reader.hash.hexdigest())
                        file_bytes += reader.count
                    elif stat.S_ISLNK(before.st_mode):
                        record.update(kind="symlink", target=os.readlink(base, dir_fd=parent_fd))
                        info.type, info.linkname = tarfile.SYMTYPE, record["target"]
                        archive.addfile(info)
                        if os.readlink(base, dir_fd=parent_fd) != record["target"]:
                            raise ValueError("source link changed")
                    elif stat.S_ISSOCK(before.st_mode):
                        record.update(kind="socket", representation="metadata-only",
                                      restore="recreate via its owning application; kernel state is not portable")
                        sockets += 1
                    else:
                        raise ValueError("unsupported source object; not silently omitted")
                    if identity(os.stat(base, dir_fd=parent_fd, follow_symlinks=False)) != identity(before):
                        raise ValueError("source entry changed during capture")
                    if leaf_mode:
                        expected = expected_leaves[relative]
                        keys = ('kind', 'bytes', 'sha256') if record['kind'] == 'file' else ('kind', 'target')
                        if any(record.get(key) != expected.get(key) for key in keys):
                            raise ValueError('Selected leaf differs from observed source contents')

                for member in members:
                    if not leaf_mode:
                        visit(root_fd, member, member)
                        continue
                    descriptors, parent = [], root_fd
                    try:
                        parts = member.split('/')
                        for part in parts[:-1]:
                            descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                            descriptors.append(descriptor)
                            parent = descriptor
                        visit(parent, parts[-1], member)
                    finally:
                        for descriptor in reversed(descriptors):
                            os.close(descriptor)
                manifest = {"schema": SCHEMA, "members": list(members), "entries": records,
                            "fileBytes": file_bytes, "socketCount": sockets, "startedAt": started,
                            "finishedAt": time.time(), "fileBytesVerifiedDuringCapture": True,
                            "sourceTemporaryFiles": False, "sourceWritersFrozen": False,
                            "consistentFinalSnapshot": False, "socketKernelStatePreserved": False,
                            "macAclAndXattrClosure": False}
                if leaf_mode:
                    manifest['selectionMode'] = 'exact-leaf-paths'
                raw = json.dumps(manifest, ensure_ascii=True, separators=(",", ":")).encode()
                if len(raw) > max_manifest:
                    raise ValueError("manifest byte bound")
                info = tarfile.TarInfo(MANIFEST_NAME)
                info.size, info.mode = len(raw), 0o600
                archive.addfile(info, io.BytesIO(raw))
    finally:
        os.close(root_fd)
    return {"schema": "ccrelay.mac_archive_producer.v1", "producerExit": 0, "warningBytes": 0,
            "warningTruncated": False, "bytes": writer.count, "sha256": writer.hash.hexdigest(),
            "fileManifestSchema": SCHEMA, "fileManifestEntries": len(records), "fileBytes": file_bytes,
            "socketCount": sockets, "socketKernelStatePreserved": False, "sourceTemporaryFiles": False,
            "consistentFinalSnapshot": False}


def verify(path, *, max_entries=MAX_ENTRIES, max_manifest=MAX_MANIFEST, max_file_bytes=MAX_FILE_BYTES, timeout_seconds=850,
           expected_leaves=None):
    actual, manifest, total = {}, None, 0
    deadline = time.monotonic() + timeout_seconds
    with tarfile.open(path, mode="r|gz") as archive:
        for member in archive:
            if time.monotonic() >= deadline:
                raise TimeoutError("verification deadline")
            if manifest is not None or len(actual) >= max_entries or member.name in actual:
                raise ValueError("entry count/order/duplicates")
            safe_name(member.name)
            if member.name == MANIFEST_NAME:
                if not member.isfile() or member.size > max_manifest or member.mode != 0o600:
                    raise ValueError("invalid manifest member")
                manifest = json.load(archive.extractfile(member))
                continue
            record = {"name": member.name, "mode": member.mode, "uid": member.uid, "gid": member.gid,
                      "mtimeNs": int(Decimal(member.pax_headers.get("mtime", str(member.mtime))) * 1000000000)}
            if member.isfile():
                if member.size < 0 or member.size > max_file_bytes - total:
                    raise ValueError("logical file byte bound")
                reader = DigestReader(archive.extractfile(member), deadline)
                while reader.read(65536):
                    pass
                if reader.count != member.size:
                    raise ValueError("short archive file")
                record.update(kind="file", bytes=reader.count, sha256=reader.hash.hexdigest())
                total += reader.count
            elif member.isdir():
                record["kind"] = "directory"
            elif member.issym():
                record.update(kind="symlink", target=member.linkname)
            else:
                raise ValueError("unexpected archive type")
            actual[member.name] = record
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA or \
            manifest.get("fileBytesVerifiedDuringCapture") is not True or \
            any(manifest.get(key) is not False for key in ("sourceTemporaryFiles", "sourceWritersFrozen",
                "consistentFinalSnapshot", "socketKernelStatePreserved", "macAclAndXattrClosure")):
        raise ValueError("missing or incompatible manifest")
    declared = manifest.get("entries")
    members = manifest.get("members")
    leaf_mode = manifest.get('selectionMode') == 'exact-leaf-paths'
    if manifest.get('selectionMode') not in (None, 'exact-leaf-paths') or \
            leaf_mode != (expected_leaves is not None):
        raise ValueError('Exact leaf archives require independent expected selection')
    if not isinstance(members, list) or not members or any("/" in safe_name(n) and not leaf_mode for n in members) or \
            len(set(members)) != len(members) or not isinstance(declared, list) or len(declared) > max_entries:
        raise ValueError("invalid source declaration")
    if leaf_mode and (not isinstance(expected_leaves, dict) or set(expected_leaves) != set(members)):
        raise ValueError('Selected source declaration differs from expected set')
    names, sockets = set(), 0
    for record in declared:
        if not isinstance(record, dict):
            raise ValueError("invalid entry record")
        name = safe_name(record.get("name"))
        if name in names or (name not in members if leaf_mode else name.split("/")[0] not in members):
            raise ValueError("duplicate or outside declared source set")
        names.add(name)
        if leaf_mode:
            expected = expected_leaves[name]
            keys = ('kind', 'bytes', 'sha256') if expected.get('kind') == 'file' else ('kind', 'target')
            if expected.get('kind') not in ('file', 'symlink') or any(record.get(key) != expected.get(key) for key in keys):
                raise ValueError('Archived leaf differs from independent source observation')
        if record.get("kind") == "socket":
            if name in actual or record.get("representation") != "metadata-only" or \
                    record.get("restore") != "recreate via its owning application; kernel state is not portable":
                raise ValueError("socket falsely represented as archived bytes")
            sockets += 1
        else:
            observed = actual.pop(name, None)
            if observed is None or any(record.get(key) != value for key, value in observed.items()):
                raise ValueError("entry bytes or metadata differ from source manifest")
    if actual or manifest.get("fileBytes") != total or manifest.get("socketCount") != sockets or \
            not all(member in names for member in members):
        raise ValueError("manifest coverage or totals differ")
    return {"schema": "ccrelay.owner_tools_target_verification.v1", "verified": True,
            "fileManifestEntries": len(declared), "fileBytes": total, "socketCount": sockets,
            "consistentFinalSnapshot": False, "socketKernelStatePreserved": False,
            "activeProfileChanged": False, "extractedToFilesystem": False}


def dirty_selection(raw):
    if len(raw) > 4 << 20:
        raise ValueError('Dirty source selection bound')
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('schema') != 'ccrelay.dirty_source_selection.v1' or \
            not isinstance(value.get('entries'), list) or not 1 <= len(value['entries']) <= 5000:
        raise ValueError('Exact dirty-source selection required')
    rows = value['entries']
    names = [safe_name(row.get('name')) for row in rows]
    if len(set(names)) != len(names) or any(row.get('kind') not in ('file', 'symlink') for row in rows):
        raise ValueError('Duplicate or unsupported dirty source selection')
    return dict(zip(names, rows))


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--verify":
            path = sys.argv[2]
            if sys.platform != "linux" or os.geteuid() != 1000 or not re.fullmatch(
                    r"/mnt/c/ProgramData/OracovaMigration/[0-9a-f]{32}/vm-owner-tools-manifest\.tar\.gz", path):
                raise ValueError("literal PC verification archive required")
            print(json.dumps(verify(path), separators=(",", ":")))
        elif len(sys.argv) == 4 and sys.argv[1] == '--verify-dirty':
            selection, path = sys.argv[2:]
            if sys.platform != 'linux' or os.geteuid() != 1000 or not re.fullmatch(
                    r'/mnt/c/ProgramData/OracovaMigration/stream-helper-[0-9a-f]{32}/dirty-selection\.json', selection) or not re.fullmatch(
                    r'/mnt/c/ProgramData/OracovaMigration/[0-9a-f]{32}/vm-dirty-work-manifest\.tar\.gz', path):
                raise ValueError('Literal PC dirty verification inputs required')
            with open(selection, 'rb') as source:
                expected = dirty_selection(source.read((4 << 20) + 1))
            checked = verify(path, expected_leaves=expected)
            checked['expectedSelectionMatched'] = True
            print(json.dumps(checked, separators=(',', ':')))
        elif len(sys.argv) == 2 and sys.argv[1] == '--dirty-selection':
            if sys.platform != 'darwin' or os.geteuid() == 0 or pwd.getpwuid(os.geteuid()).pw_name != 'pouya':
                raise ValueError('Ordinary Mac owner required')
            expected = dirty_selection(sys.stdin.buffer.read((4 << 20) + 1))
            report = capture('/Users/pouya/.openclaw/workspace', sys.stdout.buffer, owner_uid=os.geteuid(),
                             members=sorted(expected), expected_leaves=expected)
            print(json.dumps(report, separators=(',', ':')), file=sys.stderr)
        elif len(sys.argv) == 1:
            if sys.platform != "darwin" or os.geteuid() == 0 or pwd.getpwuid(os.geteuid()).pw_name != "pouya":
                raise ValueError("ordinary Mac owner required")
            report = capture("/Users/pouya", sys.stdout.buffer, owner_uid=os.geteuid())
            print(json.dumps(report, separators=(",", ":")), file=sys.stderr)
        else:
            raise ValueError("unsupported arguments")
    except Exception as error:
        print(json.dumps({"schema": "ccrelay.mac_archive_producer.v1", "producerExit": 1,
                          "errorType": type(error).__name__}, separators=(",", ":")), file=sys.stderr)
        sys.exit(1)
