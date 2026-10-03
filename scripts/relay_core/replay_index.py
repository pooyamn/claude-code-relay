"""Strict index inspection for the pinned Git replay adapter, not authority.

Git's debug format is not a stable API. Check every byte of its framing and
refuse incompatible output; binary/version pin and target compatibility tests
remain mandatory. Paths are NUL framed, never split on embedded newlines.
"""
import base64
import hashlib
import re

from .contracts import canonical_bytes
from .identity import Denied, exact, integer
from .publications import oid


ASSUME = 0x8000
INTENT = 0x20000000
SKIP = 0x40000000
SEMANTIC_FLAGS = ASSUME | INTENT | SKIP
DEBUG = re.compile(rb"  ctime: [0-9]+:[0-9]+\n  mtime: [0-9]+:[0-9]+\n"
                   rb"  dev: [0-9]+\tino: [0-9]+\n  uid: [0-9]+\tgid: [0-9]+\n"
                   rb"  size: [0-9]+\tflags: ([a-f0-9]{1,8})\n")


def path_bytes(encoded):
    try:
        path = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError):
        raise Denied("invalid replay index path encoding") from None
    if not path or len(path) > 4096 or b"\0" in path or \
            any(part in {b"", b".", b"..", b".git"} for part in path.split(b"/")) or \
            base64.b64encode(path).decode() != encoded:
        raise Denied("unsafe replay index path")
    return path


def validate_entry(entry):
    exact(entry, {"path", "mode", "oid", "flags", "present"})
    path_bytes(entry["path"])
    oid(entry["oid"])
    if entry["mode"] not in {"100644", "100755", "120000"} or \
            integer(entry["flags"], 0) & ~SEMANTIC_FLAGS or type(entry["present"]) is not bool:
        raise Denied("unsupported replay index entry; source retained")
    return entry


def parse_index(raw, *, max_entries):
    """Return stage-zero blob entries with persistent semantic flag bits."""
    if type(raw) is not bytes or len(raw) > 1024 * 1024:
        raise Denied("bounded pinned Git index observation required")
    entries, position, prior = [], 0, None
    while position < len(raw):
        end = raw.find(b"\0", position)
        if end < 0:
            raise Denied("unterminated Git index observation")
        header = re.fullmatch(rb"([0-7]{6}) ([a-f0-9]{40}|[a-f0-9]{64}) ([0-3])\t(.+)", raw[position:end], re.S)
        detail = DEBUG.match(raw, end + 1)
        if header is None or detail is None:
            raise Denied("pinned Git debug format changed; preserve source for compatibility review")
        mode, object_id, stage, path = header.groups()
        flags = int(detail[1], 16)
        # Low bits and documented in-memory/cache hints are not task state.
        # Unknown extended flags must not be silently discarded.
        if stage != b"0" or flags & 0x3000 or flags & ~(0x003FFFFF | INTENT | SKIP):
            raise Denied("unmerged or unknown index flags retained; replay cannot omit them")
        entry = validate_entry({"path": base64.b64encode(path).decode(), "mode": mode.decode(),
                                "oid": object_id.decode(), "flags": flags & SEMANTIC_FLAGS, "present": False})
        if prior is not None and path <= prior or len(entries) >= max_entries:
            raise Denied("duplicate, unordered or excessive Git index entries")
        entries.append(entry)
        prior, position = path, detail.end()
    return entries


def manifest(entries, raw_index_digest):
    hasher = hashlib.sha256()
    for entry in entries:
        validate_entry(entry)
        hasher.update(canonical_bytes(entry) + b"\n")
    return {"schema": "ccrelay.replay_index.v1", "count": len(entries),
            "digest": "sha256:" + hasher.hexdigest(), "raw_index_digest": raw_index_digest}
