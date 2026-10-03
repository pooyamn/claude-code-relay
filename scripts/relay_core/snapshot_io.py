"""Shared standalone SQLite export; callers must fence the whole writer cohort."""
import os
import sqlite3

from .artifacts import write_new
from .identity import Denied


def sqlite_copy(source, destination):
    write_new(destination, b"", mode=0o600)
    # Never back up the connection holding BEGIN IMMEDIATE: it waits on itself.
    reader = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(destination)
    try:
        # Importing a WAL header must not create an on-disk wal-index.
        target.execute("PRAGMA locking_mode=EXCLUSIVE")
        reader.backup(target)
        if target.execute("PRAGMA journal_mode=DELETE").fetchone() != ("delete",):
            raise Denied("snapshot database did not leave WAL mode")
        target.execute("PRAGMA trusted_schema=OFF")
        if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise Denied("snapshot database integrity check failed")
    finally:
        target.close()
        reader.close()
    fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fchmod(fd, 0o400)
        os.fsync(fd)
    finally:
        os.close(fd)
