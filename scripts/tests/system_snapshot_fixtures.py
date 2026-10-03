"""Invented component state only; never discovers or reads host backup sources."""
from contextlib import nullcontext
import os
from pathlib import Path
import sqlite3

from relay_core.artifacts import write_new
from relay_core.system_snapshot import Component, SnapshotPolicy, capture, component_spec


def fixture(folder):
    folder = Path(folder)
    components = []
    for key in ("broker", "worker"):
        root = folder / key
        root.mkdir(mode=0o700)
        path = root / "state.sqlite"
        write_new(path, b"", mode=0o600)
        db = sqlite3.connect(str(path), isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE state(id TEXT PRIMARY KEY,body BLOB)")
        db.execute("INSERT INTO state VALUES ('action-1',?)", (b"unknown external outcome; do not replay",))
        write_new(root / "memory.md", b"verified company decision and dispute history\n", mode=0o600)
        write_new(root / "uncommitted\nnotes", b"uncommitted\0binary", mode=0o400)
        (root / "empty").mkdir(mode=0o500)
        (root / "literal-link").symlink_to("../outside-never-read")
        write_new(root / "runtime.lock", b"invented live PID", mode=0o600)
        components.append(Component(key, root, os.geteuid(), "sha256:" + "a" * 64,
            {b"state.sqlite": db}, {b"runtime.lock": {"reason": "process ownership must be re-established", "recovery": "generated"}}))
    policy = policy_for(components)
    return tuple(components), policy


def policy_for(components):
    return SnapshotPolicy({"schema": "ccrelay.system_snapshot_policy.v1",
        "components": {c.id: component_spec(c) for c in components}, "max_entries": 256, "max_bytes": 8 * 1024 * 1024})


def capture_fixture(components, policy, destination, **kwargs):
    return capture(components, policy, destination, owner_uid=os.geteuid(), cohort_id="fixture",
                   writer_guard=lambda _: nullcontext(), now=lambda: 100000, **kwargs)
