"""Private, versioned launcher bindings. Not the task/admission ledger.

Registration is immutable and idempotent only for identical intent. Revocation
does not claim writer termination and cannot silently recycle a binding.
"""
import os
from pathlib import Path
import sqlite3

from .contracts import canonical_bytes
from .identity import Denied, protected_path, strict_json, validate_binding


class BindingRegistry:
    def __init__(self, directory, *, owner_uid):
        integer_owner = type(owner_uid) is int and owner_uid > 0
        if not integer_owner or os.geteuid() != owner_uid:
            raise Denied("registry must run as its protected owner")
        folder = protected_path(directory, owners={0, owner_uid}, directory=True, private=True)
        if folder.lstat().st_uid != owner_uid:
            raise Denied("registry directory has wrong owner")
        self.path = Path(folder) / "bindings.sqlite"
        new = not self.path.exists() and not self.path.is_symlink()
        if new:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        protected_path(self.path, owners={owner_uid, 0}, private=True)
        self.connection = sqlite3.connect(str(self.path), isolation_level=None)
        self.owner_uid = owner_uid
        try:
            if new:
                self.connection.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE metadata (schema TEXT NOT NULL);
                    INSERT INTO metadata VALUES ('ccrelay.binding_registry.v1');
                    CREATE TABLE bindings (
                        session_id TEXT PRIMARY KEY, cgroup TEXT UNIQUE NOT NULL,
                        execution_id TEXT UNIQUE NOT NULL, body BLOB NOT NULL);
                    COMMIT;
                """)
            versions = self.connection.execute("SELECT schema FROM metadata").fetchall()
            if versions != [("ccrelay.binding_registry.v1",)]:
                raise Denied("unsupported registry schema; preserve database for migration")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA journal_mode=WAL")
        except Exception:
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    def _one(self, sql, value):
        row = self.connection.execute(sql, (value,)).fetchone()
        return None if row is None else self._decode_row(row)

    @staticmethod
    def _decode_row(row):
        body = validate_binding(strict_json(row[3]))
        if tuple(body[key] for key in ("session_id", "cgroup", "execution_id")) != row[:3]:
            raise Denied("binding index and record disagree; preserve for inspection")
        return body

    def session(self, session_id):
        return self._one("SELECT session_id,cgroup,execution_id,body FROM bindings WHERE session_id=?", session_id)

    def cgroup(self, cgroup):
        return self._one("SELECT session_id,cgroup,execution_id,body FROM bindings WHERE cgroup=?", cgroup)

    def rows(self):
        return [self._decode_row(row) for row in self.connection.execute("SELECT session_id,cgroup,execution_id,body FROM bindings ORDER BY session_id")]

    def register(self, binding):
        validate_binding(binding)
        body = canonical_bytes(binding)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            current = self.session(binding["session_id"])
            if current is None:
                self.connection.execute("INSERT INTO bindings VALUES (?,?,?,?)", (
                    binding["session_id"], binding["cgroup"], binding["execution_id"], body))
            elif canonical_bytes(current) != body:
                raise Denied("binding replacement needs verified writer-transfer protocol")
            self.connection.execute("COMMIT")
        except sqlite3.IntegrityError as error:
            self.connection.execute("ROLLBACK")
            raise Denied("duplicate session, execution or unit binding") from error
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def revoke(self, session_id):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.session(session_id)
            if row is None:
                raise Denied("unknown binding")
            row["revoked"] = True
            self.connection.execute("UPDATE bindings SET body=? WHERE session_id=?", (canonical_bytes(row), session_id))
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def snapshot(self, destination):
        # Caller must choose a NEW protected snapshot destination. This preserves WAL
        # transactions; copying a live DB/WAL trio is not a consistent snapshot.
        destination = Path(destination)
        protected_path(destination.parent, owners={0, self.owner_uid}, directory=True, private=True)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        target = sqlite3.connect(str(destination))
        try:
            self.connection.backup(target)
        finally:
            target.close()
