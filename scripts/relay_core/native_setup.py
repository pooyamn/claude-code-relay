"""Worker-owned bundle copies/discovery links, never native readiness or authority.

The protected launcher must supply reviewed inputs and the real writer fence.
No worker RPC, live entry point, permission config activation or native call exists.
"""
import os
from pathlib import Path

from .artifacts import ArtifactStore, fsync_dir
from .contracts import canonical_bytes, fingerprint
from .identity import Denied, identifier, strict_json
from .native_launch import COMPONENT, inspect_package, validate_spec
from .outbox import DeliveryLedger


SCHEMA = "ccrelay.native_setup_journal.v1"
PHASES = {"planned", "copied", "linked"}


class WorktreeSetup(DeliveryLedger):
    def __init__(self, workspace, *, checkpoint=lambda _: None):
        workspace._check_lock()
        if os.geteuid() == 0 or os.geteuid() != workspace.uid:
            raise Denied("setup requires the current non-root workspace worker UID")
        self.workspace = workspace
        folder = workspace.home / "native-setup"
        if not folder.exists() and not folder.is_symlink():
            folder.mkdir(mode=0o700)
        workspace._private(folder, directory=True)
        artifacts = folder / "artifacts"
        if not artifacts.exists() and not artifacts.is_symlink():
            artifacts.mkdir(mode=0o700)
        workspace._private(artifacts, directory=True)
        self.store = ArtifactStore(artifacts, owner_uid=workspace.uid)
        super().__init__(folder, owner_uid=workspace.uid, policy_digest=workspace.policy_digest, checkpoint=checkpoint)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _initialize_component(self):
        self.connection.execute("CREATE TABLE setup_metadata (schema TEXT NOT NULL)")
        self.connection.execute("INSERT INTO setup_metadata VALUES (?)", (SCHEMA,))
        self.connection.execute("CREATE TABLE setups (session_id TEXT PRIMARY KEY,spec BLOB NOT NULL,bundle_digest TEXT NOT NULL,phase TEXT NOT NULL)")

    def _validate_component(self):
        if self.connection.execute("SELECT schema FROM setup_metadata").fetchall() != [(SCHEMA,)]:
            raise Denied("unknown setup journal schema; preserve for reviewed migration")
        for (session_id,) in self.connection.execute("SELECT session_id FROM setups").fetchall():
            self._row(session_id)

    def _row(self, session_id):
        self._check_lock()
        row = self.connection.execute("SELECT spec,bundle_digest,phase FROM setups WHERE session_id=?", (identifier(session_id),)).fetchone()
        if row is None:
            return None
        spec = validate_spec(strict_json(row[0]), self.workspace.policy)
        if spec["session_id"] != session_id or spec["role_id"] != self.workspace.role_id or row[2] not in PHASES:
            raise Denied("setup journal mapping changed")
        self.store._directory(row[1])  # Validate the digest before using a path.
        return {"spec": spec, "bundle_digest": row[1], "phase": row[2]}

    def _phase(self, session_id, phase):
        with self._transaction():
            self.connection.execute("UPDATE setups SET phase=? WHERE session_id=?", (phase, session_id))
            self.checkpoint("before_setup_" + phase + "_commit")
        self.checkpoint("after_setup_" + phase + "_commit")

    def _parents(self, target, worktree, *, create=False):
        current = worktree
        for part in target.relative_to(worktree).parts[:-1]:
            current = current / part
            if not current.exists() and not current.is_symlink():
                if not create:
                    continue
                current.mkdir(mode=0o700)
                fsync_dir(current.parent)
            self.workspace._private(current, directory=True)

    def _link(self, target, source, worktree, *, replay):
        self._parents(target, worktree)
        if not target.exists() and not target.is_symlink():
            return False
        if not replay or not target.is_symlink() or target.lstat().st_uid != self.workspace.uid or \
                target.lstat().st_nlink != 1 or os.readlink(target) != str(source):
            raise Denied("existing setup path differs; preserve project instructions/skills without overwrite")
        return True

    def apply(self, source_store, bundle_digest):
        if os.geteuid() != self.workspace.uid:
            raise Denied("setup worker UID changed")
        package = inspect_package(source_store, self.workspace.policy, bundle_digest)
        spec = package["spec"]
        session_id = spec["session_id"]
        worktree = self.workspace.home / "worktrees" / session_id
        common = self.workspace.home / "repos" / spec["workspace"]["repo_id"] / "git"
        copied = self.store._directory(bundle_digest)
        links = [(worktree / Path(package["instruction_file"]).name, copied / package["instruction_file"])]
        links += [(worktree / item["discovery_target"], copied / item["directory"]) for item in package["skills"]]
        with self.workspace.writer_guard(spec):
            self.workspace._check_lock()
            if self.workspace.policy.digest != self.policy_digest:
                raise Denied("setup policy changed")
            workspace_row = self.workspace._row(session_id)
            if workspace_row is None or workspace_row["phase"] != "prepared" or workspace_row["spec"] != spec:
                raise Denied("exact prepared workspace required before installing a bundle")
            self.workspace._git(common, ["fsck", "--full", "--no-reflogs", "--no-dangling"])
            self.workspace._observe(spec, common, worktree)
            row = self._row(session_id)
            if row is not None and (row["spec"] != spec or row["bundle_digest"] != bundle_digest):
                raise Denied("changing setup bundle requires reviewed writer transfer; no replacement")
            # Preflight every destination before registering or creating links.
            for target, source in links:
                present = self._link(target, source, worktree, replay=row is not None)
                if row is not None and row["phase"] == "linked" and not present:
                    raise Denied("recorded setup link disappeared; preserve for evidenced repair")
            if row is None:
                with self._transaction():
                    self.connection.execute("INSERT INTO setups VALUES (?,?,?,?)", (
                        session_id, canonical_bytes(spec), bundle_digest, "planned"))
                    self.checkpoint("before_setup_register_commit")
                self.checkpoint("after_setup_register_commit")
            manifest, contents = source_store.verify(bundle_digest)
            self.checkpoint("before_setup_bundle_copy")
            actual = self.store.install(COMPONENT, [{"path": entry["path"], "content": contents[entry["path"]],
                                                   "executable": entry["executable"]} for entry in manifest["files"]])
            if actual != bundle_digest:
                raise Denied("worker copy differs from pinned launch bundle")
            self.checkpoint("after_setup_bundle_copy")
            self._phase(session_id, "copied" if row is None or row["phase"] != "linked" else "linked")
            for index, (target, source) in enumerate(links):
                self._parents(target, worktree, create=True)
                if not self._link(target, source, worktree, replay=True):
                    self.checkpoint("before_setup_link_" + str(index))
                    os.symlink(str(source), target)  # Atomic no-clobber publication.
                    fsync_dir(target.parent)
                    self.checkpoint("after_setup_link_" + str(index))
            self.store.verify(bundle_digest)
            for target, source in links:
                if not self._link(target, source, worktree, replay=True):
                    raise Denied("setup links incomplete")
            self._phase(session_id, "linked")
            return {"schema": "ccrelay.native_setup_observation.v1", "session_id": session_id,
                    "spec_digest": fingerprint(spec), "bundle_digest": bundle_digest,
                    "links": [str(target.relative_to(worktree)) for target, _ in links],
                    "files_installed": True, "native_loaded": False, "runtime_ready": False, "admitted": False}
