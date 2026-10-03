"""Worker-owned, fenced post-merge replay candidates; not publication authority.

Original files/index remain untouched. Promotion onto the original native path
and protected merge/fence readers are separate gates; no fetch or model is run.
"""
import base64
import copy
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import stat
import tempfile

from .artifacts import digest
from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, integer, strict_json
from .native_launch import _hash, validate_spec
from .outbox import DeliveryLedger, fsync_directory
from .publications import oid
from .replay_index import ASSUME, INTENT, SKIP, manifest, parse_index, path_bytes, validate_entry
from .worktree_checkpoints import WorktreeCheckpoints


SCHEMA = "ccrelay.post_merge.v2"
PHASES = {"planned", "captured", "creating", "created", "advancing", "source_loaded", "rebasing", "rebased", "applying", "applied", "overlaying", "restoring_index", "index_restored", "ready", "conflicted", "recovery_required"}


def _file_identity(value):
    # Reads may advance atime. Content/type/owner/mode/identity changes may not.
    return (value.st_dev, value.st_ino, value.st_uid, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


@dataclass(frozen=True)
class ReplayPolicy:
    committer_name: str
    committer_email: str
    max_pending: int

    def __post_init__(self):
        for value in (self.committer_name, self.committer_email):
            if type(value) is not str or not 1 <= len(value) <= 200 or any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise Denied("explicit bounded replay committer required")
        if "@" not in self.committer_email or integer(self.max_pending) > 128:
            raise Denied("explicit bounded replay policy required")


@dataclass(frozen=True)
class ReplayMerge:
    scope_digest: str
    source_digest: str
    publication_id: str
    root_task_id: str
    published_sha: str
    merged_sha: str
    verified_merged: bool
    currently_authorized: bool


class PostMergeReplay(DeliveryLedger):
    def __init__(self, snapshots, policy, *, verify_merge, checkpoint=lambda _: None):
        if type(snapshots) is not WorktreeCheckpoints or type(policy) is not ReplayPolicy or not callable(verify_merge):
            raise Denied("existing complete checkpoint component, explicit policy and protected merge reader required")
        self.snapshots, self.workspace, self.policy, self.verify_merge = snapshots, snapshots.workspace, policy, verify_merge
        folder = self.workspace.home / "post-merge"
        if not folder.exists() and not folder.is_symlink():
            folder.mkdir(mode=0o700)
        self.workspace._private(folder, directory=True)
        super().__init__(folder, owner_uid=self.workspace.uid, policy_digest=self.workspace.policy_digest, checkpoint=checkpoint)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _initialize_component(self):
        self.connection.execute("CREATE TABLE replay_metadata(schema TEXT,policy BLOB,git_digest TEXT)")
        self.connection.execute("INSERT INTO replay_metadata VALUES (?,?,?)", (SCHEMA, canonical_bytes(asdict(self.policy)), self.workspace.git_digest))
        self.connection.execute("CREATE TABLE replays(id TEXT PRIMARY KEY,session_id TEXT,body BLOB,digest TEXT)")
        self.connection.execute("CREATE UNIQUE INDEX one_replay_per_session ON replays(session_id)")
        self.connection.execute("CREATE TABLE replay_history(id TEXT,revision INTEGER,body BLOB,digest TEXT,PRIMARY KEY(id,revision))")
        self.connection.execute("CREATE TABLE replay_files(id TEXT,path BLOB,body BLOB,digest TEXT,PRIMARY KEY(id,path))")
        self.connection.execute("CREATE TABLE replay_index_entries(id TEXT,path BLOB,body BLOB,digest TEXT,PRIMARY KEY(id,path))")

    def _validate_component(self):
        if self.connection.execute("SELECT schema,policy,git_digest FROM replay_metadata").fetchall() != \
                [(SCHEMA, canonical_bytes(asdict(self.policy)), self.workspace.git_digest)]:
            raise Denied("unsupported replay policy/schema/Git pin; preserve for migration")
        if self.connection.execute("SELECT 1 FROM replay_index_entries e LEFT JOIN replays r ON e.id=r.id WHERE r.id IS NULL LIMIT 1").fetchone():
            raise Denied("orphaned replay index rows retained for inspection")
        for (key,) in self.connection.execute("SELECT id FROM replays").fetchall():
            self.load_replay(key)

    def load_replay(self, key):
        self._check_lock()
        row = self.connection.execute("SELECT session_id,body,digest FROM replays WHERE id=?", (identifier(key),)).fetchone()
        if row is None:
            return None
        body = strict_json(row[1])
        exact(body, {"schema", "id", "revision", "phase", "spec", "stage_spec", "publication_id", "published_sha", "merged_sha", "source_sha", "merge", "stash_sha", "source_checkpoint", "stage_checkpoint", "index_state", "finding", "admitted"})
        if body["schema"] != SCHEMA or body["id"] != key or body["phase"] not in PHASES or body["spec"]["session_id"] != row[0] or \
                fingerprint(body) != row[2] or body["admitted"] is not False:
            raise Denied("replay index/material changed")
        validate_spec(body["spec"], self.workspace.policy)
        validate_spec(body["stage_spec"], self.workspace.policy)
        integer(body["revision"], 0)
        latest = self.connection.execute("SELECT body,digest FROM replay_history WHERE id=? AND revision=?", (key, body["revision"])).fetchone()
        count, maximum = self.connection.execute("SELECT COUNT(*),MAX(revision) FROM replay_history WHERE id=?", (key,)).fetchone()
        if latest != (row[1], row[2]) or count != body["revision"] + 1 or maximum != body["revision"]:
            raise Denied("replay history incomplete")
        for field in ("published_sha", "merged_sha", "source_sha"):
            oid(body[field])
        self._index_entries(body)
        return body

    def _index_entries(self, body):
        rows = self.connection.execute("SELECT path,body,digest FROM replay_index_entries WHERE id=? ORDER BY path", (body["id"],)).fetchall()
        if body["index_state"] is None:
            if rows or body["phase"] != "planned":
                raise Denied("uncaptured or orphaned replay index material")
            return []
        state = body["index_state"]
        exact(state, {"schema", "count", "digest", "raw_index_digest"})
        _hash(state["digest"])
        _hash(state["raw_index_digest"])
        if integer(state["count"], 0) > self.snapshots.policy.max_entries or len(rows) != state["count"]:
            raise Denied("replay index manifest count changed")
        entries = []
        for path, raw, hashed in rows:
            entry = validate_entry(strict_json(raw))
            if path_bytes(entry["path"]) != path or fingerprint(entry) != hashed:
                raise Denied("replay index row changed")
            entries.append(entry)
        if manifest(entries, state["raw_index_digest"]) != state:
            raise Denied("replay index manifest changed")
        return entries

    def _save(self, body):
        raw, hashed = canonical_bytes(body), fingerprint(body)
        if len(raw) > 65536:
            raise Denied("replay references exceed bound; source preserved")
        self.connection.execute("INSERT OR REPLACE INTO replays VALUES (?,?,?,?)", (body["id"], body["spec"]["session_id"], raw, hashed))
        self.connection.execute("INSERT INTO replay_history VALUES (?,?,?,?)", (body["id"], body["revision"], raw, hashed))

    def _phase(self, body, phase, *, index_entries=None, **changes):
        with self._transaction():
            if self.load_replay(body["id"]) != body:
                raise Denied("replay changed before transition")
            if index_entries is not None:
                if body["phase"] != "planned" or phase != "captured" or body["index_state"] is not None:
                    raise Denied("index capture must join its first durable phase")
                for entry in index_entries:
                    raw = canonical_bytes(validate_entry(entry))
                    self.connection.execute("INSERT INTO replay_index_entries VALUES (?,?,?,?)", (body["id"], path_bytes(entry["path"]), raw, fingerprint(entry)))
            self._save({**body, **changes, "phase": phase, "revision": body["revision"] + 1})
            self.checkpoint("before_replay_" + phase + "_commit")
        self.checkpoint("after_replay_" + phase + "_commit")
        return self.load_replay(body["id"])

    def _scope(self, body):
        return {field: body[field] for field in ("id", "spec", "publication_id", "published_sha", "merged_sha", "source_sha")}

    def _merge(self, scope):
        receipt = self.verify_merge(strict_json(canonical_bytes(scope)))
        if type(receipt) is not ReplayMerge or receipt.scope_digest != fingerprint(scope) or \
                (receipt.publication_id, receipt.root_task_id, receipt.published_sha, receipt.merged_sha) != \
                (scope["publication_id"], scope["spec"]["root_task_id"], scope["published_sha"], scope["merged_sha"]) or \
                receipt.verified_merged is not True or receipt.currently_authorized is not True:
            raise Denied("independently verified exact completed merge and current replay authority required")
        _hash(receipt.source_digest)
        return asdict(receipt)

    def _paths(self, body):
        common = self.workspace.home / "repos" / body["spec"]["workspace"]["repo_id"] / "git"
        source = self.workspace.home / "worktrees" / body["spec"]["session_id"]
        stage = self.workspace.home / "worktrees" / body["stage_spec"]["session_id"]
        return common, source, stage

    def _git(self, common, args, *, worktree=None, allowed=(0,), index_file=None):
        return self.workspace._git(common, ["-c", "user.name=" + self.policy.committer_name, "-c", "user.email=" + self.policy.committer_email,
                                           "-c", "commit.gpgSign=false", "-c", "rebase.rescheduleFailedExec=false", *args], worktree=worktree, allowed=allowed, index_file=index_file)

    def _retain(self, common, ref, head):
        code, found = self._git(common, ["rev-parse", "--verify", "--quiet", ref], allowed=(0, 1))
        if code == 0:
            if found.strip().decode() != head:
                raise Denied("retained replay reference changed")
        else:
            self._git(common, ["update-ref", ref, head, "0" * len(head)])

    def _fresh(self, body):
        sealed = self.snapshots.inspect(body["source_checkpoint"])
        current = self.snapshots._scan(body["source_checkpoint"], body["spec"], store=False)
        if any(current[field] != sealed[field] for field in current):
            raise Denied("original work changed; retain candidate and checkpoint without installing stale replay")

    def _observe_index(self, common, target, *, index_file=None):
        raw = self._git(common, ["ls-files", "--stage", "--debug", "-z", "--full-name"], worktree=target, index_file=index_file)[1]
        return parse_index(raw, max_entries=self.snapshots.policy.max_entries)

    def _index_command(self, common, target, options, entries, *, index_file=None):
        # Bound argv bytes as well as entry count; paths are literal, including
        # leading dashes, tabs, newlines and pathspec-looking punctuation.
        batch, size = [], 0
        for entry in entries:
            path = path_bytes(entry["path"])
            if batch and (size + len(path) > 32768 or len(batch) == 128):
                self._git(common, ["--literal-pathspecs", *options, "--", *batch], worktree=target, index_file=index_file)
                batch, size = [], 0
            batch.append(os.fsdecode(path))
            size += len(path) + 1
        if batch:
            self._git(common, ["--literal-pathspecs", *options, "--", *batch], worktree=target, index_file=index_file)

    def _capture_index(self, body, common, source, temporary):
        raw = self.snapshots.read_file(body["source_checkpoint"], "git", "index")
        temporary.write(raw)
        temporary.flush()
        os.fsync(temporary.fileno())
        present = {path for (path,) in self.snapshots.connection.execute(
            "SELECT path FROM checkpoint_entries WHERE snapshot_id=? AND area='worktree'", (body["source_checkpoint"],))}
        entries = self._observe_index(common, source, index_file=temporary.name)
        for entry in entries:
            entry["present"] = path_bytes(entry["path"]) in present
        return entries, manifest(entries, digest(raw))

    def _normalize_index(self, common, source, temporary, entries):
        # Only the private copy is rewritten. Preserve absent skip-worktree
        # entries as index-only state, not accidental working-tree deletions.
        self._git(common, ["update-index", "--no-split-index"], worktree=source, index_file=temporary.name)
        for flag, option in ((ASSUME, "--no-assume-unchanged"), (SKIP, "--no-skip-worktree")):
            selected = [entry for entry in entries if entry["flags"] & flag and
                        not (entry["flags"] & SKIP and not entry["present"])]
            self._index_command(common, source, ["update-index", option], selected, index_file=temporary.name)
        # Git stash cannot represent intent-to-add. Overlay these exact files
        # from the full checkpoint, then restore intent without staging bytes.
        self._index_command(common, source, ["update-index", "--force-remove"],
                            [entry for entry in entries if entry["flags"] & INTENT], index_file=temporary.name)

    def _target(self, stage, entry):
        parts = path_bytes(entry["path"]).split(b"/")
        target = stage.joinpath(*(os.fsdecode(part) for part in parts))
        for parent in [stage, *list(target.parents)[:len(parts) - 1][::-1]]:
            if parent.is_symlink() or not parent.is_dir():
                raise Denied("index restoration would follow a link or replace a parent")
        return target

    def _remove_generated_skip_file(self, stage, entry):
        target = self._target(stage, entry)
        if not target.exists() and not target.is_symlink():
            return
        metadata = target.lstat()
        if metadata.st_uid != self.workspace.uid:
            raise Denied("generated skip-worktree file owner changed")
        hasher = hashlib.new("sha1" if len(entry["oid"]) == 40 else "sha256")
        if entry["mode"] == "120000" and stat.S_ISLNK(metadata.st_mode):
            content = os.fsencode(os.readlink(target))
            hasher.update(b"blob " + str(len(content)).encode() + b"\0" + content)
        elif entry["mode"] in {"100644", "100755"} and stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
            mode = "100755" if metadata.st_mode & 0o111 else "100644"
            if mode != entry["mode"] or metadata.st_size > self.snapshots.policy.max_bytes:
                raise Denied("generated skip-worktree file mode/size changed")
            hasher.update(b"blob " + str(metadata.st_size).encode() + b"\0")
            fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                if _file_identity(os.fstat(fd)) != _file_identity(metadata):
                    raise Denied("generated skip-worktree file changed before inspection")
                while True:
                    chunk = os.read(fd, 256 * 1024)
                    if not chunk:
                        break
                    hasher.update(chunk)
                if _file_identity(os.fstat(fd)) != _file_identity(metadata):
                    raise Denied("generated skip-worktree file changed during inspection")
            finally:
                os.close(fd)
        else:
            raise Denied("generated skip-worktree file type changed")
        if hasher.hexdigest() != entry["oid"] or _file_identity(target.lstat()) != _file_identity(metadata):
            raise Denied("changed candidate bytes retained; cannot restore sparse absence")
        # This is a proved-clean, generated candidate file, never source work.
        # Its exact bytes remain in Git; the original absence stays untouched.
        target.unlink()
        fsync_directory(target.parent)
        self.checkpoint("after_replay_skip_absence_effect")

    def _absent_intent(self, body, stage, entry, *, create):
        target = self._target(stage, entry)
        path = path_bytes(entry["path"])
        placeholder = {"schema": "ccrelay.replay_index_placeholder.v1", "path": entry["path"], "mode": entry["mode"]}
        raw, hashed = canonical_bytes(placeholder), fingerprint(placeholder)
        saved = self.connection.execute("SELECT body,digest FROM replay_files WHERE id=? AND path=?", (body["id"], path)).fetchone()
        exists = target.exists() or target.is_symlink()
        if saved is None:
            if exists:
                raise Denied("absent intent-to-add collides with candidate work")
            if not create:
                return
            with self._transaction():
                self.connection.execute("INSERT INTO replay_files VALUES (?,?,?,?)", (body["id"], path, raw, hashed))
        elif saved != (raw, hashed):
            raise Denied("intent-to-add placeholder reservation changed")
        if create and not exists:
            if entry["mode"] == "120000":
                os.symlink(".", target)
            else:
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700 if entry["mode"] == "100755" else 0o600)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            fsync_directory(target.parent)
            self.checkpoint("after_replay_intent_placeholder_effect")
        elif exists:
            metadata = target.lstat()
            matches = target.is_symlink() and os.readlink(target) == "." if entry["mode"] == "120000" else \
                stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and metadata.st_size == 0 and \
                bool(metadata.st_mode & 0o111) == (entry["mode"] == "100755")
            if metadata.st_uid != self.workspace.uid or not matches:
                raise Denied("intent-to-add placeholder changed; retain candidate work")
            if not create:
                target.unlink()
                fsync_directory(target.parent)
                self.checkpoint("after_replay_intent_absence_effect")

    def _restore_index(self, body):
        common, _, stage = self._paths(body)
        entries = self._index_entries(body)
        current = {entry["path"]: entry for entry in self._observe_index(common, stage)}
        for entry in entries:
            found = current.get(entry["path"])
            if entry["flags"] & INTENT:
                if found is None:
                    if not entry["present"]:
                        self._absent_intent(body, stage, entry, create=True)
                    self._index_command(common, stage, ["add", "--intent-to-add", "--force"], [entry])
                    self.checkpoint("after_replay_intent_index_effect")
                    found = self._observe_index(common, stage)
                    found = next((value for value in found if value["path"] == entry["path"]), None)
                if found is None or not found["flags"] & INTENT or (found["mode"], found["oid"]) != (entry["mode"], entry["oid"]):
                    raise Denied("intent-to-add collided with tracked candidate state")
                if not entry["present"]:
                    self._absent_intent(body, stage, entry, create=False)
            elif entry["flags"] and found is None:
                raise Denied("flagged source entry deleted by upstream; resolve retained candidate")
            if entry["flags"] & SKIP and not entry["present"]:
                self._remove_generated_skip_file(stage, found)
        for flag, option in ((ASSUME, "--assume-unchanged"), (SKIP, "--skip-worktree")):
            self._index_command(common, stage, ["update-index", option], [entry for entry in entries if entry["flags"] & flag])
        self.checkpoint("after_replay_index_flags_effect")
        restored = {entry["path"]: entry for entry in self._observe_index(common, stage)}
        if any(restored.get(entry["path"], {}).get("flags") != entry["flags"] for entry in entries if entry["flags"]):
            raise Denied("candidate index flags did not round-trip")

    def request(self, key, spec, publication_id, *, published_sha, merged_sha):
        key, publication_id = identifier(key), identifier(publication_id)
        spec = validate_spec(strict_json(canonical_bytes(spec)), self.workspace.policy)
        published_sha, merged_sha = oid(published_sha), oid(merged_sha)
        common = self.workspace.home / "repos" / spec["workspace"]["repo_id"] / "git"
        source = self.workspace.home / "worktrees" / spec["session_id"]
        with self.workspace.writer_guard(spec):
            prior = self.load_replay(key)
            if prior:
                if (prior["spec"], prior["publication_id"], prior["published_sha"], prior["merged_sha"]) != (spec, publication_id, published_sha, merged_sha):
                    raise Denied("replay request cannot change source or merge identity")
                return prior
            observed = self.workspace._observe(spec, common, source)
            source_sha = observed["head"]
            self._git(common, ["fsck", "--full", "--no-reflogs", "--no-dangling"])
            self._git(common, ["merge-base", "--is-ancestor", published_sha, source_sha])
            self._git(common, ["merge-base", "--is-ancestor", spec["workspace"]["base_commit"], merged_sha])
            scope = {"id": key, "spec": spec, "publication_id": publication_id, "published_sha": published_sha, "merged_sha": merged_sha, "source_sha": source_sha}
            merge = self._merge(scope)
            tag = fingerprint(scope)[7:]
            stage_spec = copy.deepcopy(spec)
            stage_spec["session_id"], stage_spec["provider_session_id"] = "replay." + tag[:40], None
            stage_spec["workspace"].update(branch=spec["role_id"] + "/replay/" + tag, mode="create",
                worktree="/var/lib/ccrelay/roles/" + spec["role_id"] + "/worktrees/" + stage_spec["session_id"])
            validate_spec(stage_spec, self.workspace.policy)
        self.snapshots.capture("replay-source-" + tag, spec)
        with self.workspace.writer_guard(spec):
            sealed = self.snapshots.inspect("replay-source-" + tag)
            if sealed["workspace"]["head"] != source_sha or self.snapshots._scan("replay-source-" + tag, spec, store=False)["manifest_digest"] != sealed["manifest_digest"]:
                raise Denied("source changed before replay request checkpoint")
            with self._transaction():
                if self.connection.execute("SELECT COUNT(*) FROM replays").fetchone()[0] >= self.policy.max_pending or \
                        self.connection.execute("SELECT 1 FROM replays WHERE session_id=?", (spec["session_id"],)).fetchone():
                    raise Denied("bounded replay already pending; preserve original and existing candidate")
                if self.workspace._observe(spec, common, source) != observed or self._merge(scope) != merge:
                    raise Denied("source/merge changed while preparing replay")
                self._save({"schema": SCHEMA, **scope, "revision": 0, "phase": "planned", "stage_spec": stage_spec, "merge": merge,
                            "stash_sha": None, "source_checkpoint": "replay-source-" + tag, "stage_checkpoint": "replay-result-" + tag,
                            "index_state": None, "finding": None, "admitted": False})
                self.checkpoint("before_replay_request_commit")
            self.checkpoint("after_replay_request_commit")
        return self.load_replay(key)

    def _finding(self, body, reason, *, phase="conflicted"):
        common, _, stage = self._paths(body)
        status = self._git(common, ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching"], worktree=stage)[1]
        return self._phase(body, phase, finding={"reason": reason, "status_digest": digest(status), "meaning": "original_and_candidate_retained_no_execution_grant"})

    def _overlay(self, body):
        self.snapshots.inspect(body["source_checkpoint"])
        _, _, stage = self._paths(body)
        tracked = {path_bytes(entry["path"]) for entry in self._index_entries(body) if not entry["flags"] & INTENT}
        entries = self.snapshots.connection.execute("SELECT path,body FROM checkpoint_entries WHERE snapshot_id=? AND area='worktree' ORDER BY sequence", (body["source_checkpoint"],)).fetchall()
        directories = []
        for raw_path, raw in entries:
            if not raw_path or raw_path in tracked:
                continue
            entry = strict_json(raw)
            parts = raw_path.split(b"/")
            if any(part in {b"", b".", b".."} for part in parts) or parts[0] == b".git":
                raise Denied("unsafe checkpoint overlay path")
            target = stage.joinpath(*(os.fsdecode(part) for part in parts))
            for parent in [stage, *list(target.parents)[:len(parts) - 1][::-1]]:
                if parent.is_symlink() or not parent.is_dir():
                    raise Denied("overlay would follow a link or replace a parent")
            exists = target.exists() or target.is_symlink()
            if entry["kind"] == "directory":
                if not exists:
                    target.mkdir(mode=0o700)
                elif target.is_symlink() or not target.is_dir():
                    raise Denied("local directory collides with replayed tracked content")
                directories.append((target, entry["mode"]))
                continue
            saved = self.connection.execute("SELECT body,digest FROM replay_files WHERE id=? AND path=?", (body["id"], raw_path)).fetchone()
            if saved:
                if saved != (raw, fingerprint(entry)):
                    raise Denied("reserved replay file changed")
            else:
                if exists:
                    raise Denied("untracked/ignored local work collides with replayed content")
                with self._transaction():
                    self.connection.execute("INSERT INTO replay_files VALUES (?,?,?,?)", (body["id"], raw_path, raw, fingerprint(entry)))
            if entry["kind"] == "symlink":
                wanted = os.fsdecode(base64.b64decode(entry["link"], validate=True))
                if exists:
                    if not target.is_symlink() or os.readlink(target) != wanted:
                        raise Denied("reserved overlay symlink changed")
                else:
                    os.symlink(wanted, target)
            else:
                initial = target.lstat() if exists else None
                complete = initial is not None and initial.st_size == entry["size"]
                # A prior attempt may have finished and restored a read-only
                # mode. Reconciliation verifies those bytes without requesting
                # write access; only unfinished copies need a writable handle.
                access = os.O_RDONLY if complete else os.O_RDWR
                try:
                    fd = os.open(target, access | os.O_NOFOLLOW | os.O_NONBLOCK |
                                 (0 if exists else os.O_CREAT | os.O_EXCL), 0o600)
                except OSError as error:
                    raise Denied("reserved overlay file cannot be opened safely; candidate retained") from error
                try:
                    actual = os.fstat(fd)
                    if initial is not None and _file_identity(actual) != _file_identity(initial):
                        raise Denied("reserved overlay file changed before inspection")
                    if not stat.S_ISREG(actual.st_mode) or actual.st_uid != self.workspace.uid or actual.st_nlink != 1 or actual.st_size > entry["size"]:
                        raise Denied("reserved overlay file type/owner/size changed")
                    remaining = actual.st_size
                    for chunk in self.snapshots._content(body["source_checkpoint"], "worktree", raw_path):
                        present = min(remaining, len(chunk))
                        if os.read(fd, present) != chunk[:present]:
                            raise Denied("partial overlay bytes disagree with retained checkpoint")
                        remaining -= present
                        pending = memoryview(chunk)[present:]
                        while pending:
                            written = os.write(fd, pending)
                            if written <= 0:
                                raise Denied("overlay write made no progress")
                            pending = pending[written:]
                    if complete and _file_identity(os.fstat(fd)) != _file_identity(actual):
                        raise Denied("completed overlay file changed during inspection")
                    mode_changed = stat.S_IMODE(os.fstat(fd).st_mode) != entry["mode"]
                    if mode_changed:
                        os.fchmod(fd, entry["mode"])
                    if not complete or mode_changed:
                        os.fsync(fd)
                    if _file_identity(target.lstat()) != _file_identity(os.fstat(fd)):
                        raise Denied("reserved overlay file replaced during reconciliation")
                finally:
                    os.close(fd)
            fsync_directory(target.parent)
            self.checkpoint("after_replay_overlay_file")
        for directory, mode in reversed(directories):
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fchmod(fd, mode)
                os.fsync(fd)
            finally:
                os.close(fd)

    def run(self, key):
        body = self.load_replay(key)
        if body is None:
            raise Denied("known replay request required")
        if body["phase"] in {"ready", "conflicted", "recovery_required"}:
            if body["phase"] == "ready":
                with self.workspace.writer_guard(body["spec"]):
                    self._fresh(body)
                    candidate = self.snapshots.inspect(body["stage_checkpoint"])
                    current = self.snapshots._scan(body["stage_checkpoint"], body["stage_spec"], store=False)
                    if any(current[field] != candidate[field] for field in current) or self._merge(self._scope(body)) != body["merge"]:
                        raise Denied("sealed candidate/source/authority changed; historical ready state grants no installation")
            return body
        common, source, stage = self._paths(body)
        if body["phase"] == "planned":
            with self.workspace.writer_guard(body["spec"]):
                if self._merge(self._scope(body)) != body["merge"] or self.workspace._observe(body["spec"], common, source)["head"] != body["source_sha"]:
                    raise Denied("current completed merge/source required before capture")
                self._fresh(body)
                pointer = Path((source / ".git").read_bytes()[8:-1].decode())
                if any((pointer / name).exists() for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer")):
                    raise Denied("unfinished original Git operation retained; resolve before post-merge replay")
                tag = fingerprint(self._scope(body))[7:]
                self._retain(common, "refs/ccrelay/replay/" + tag + "/source", body["source_sha"])
                self._retain(common, "refs/ccrelay/replay/" + tag + "/merged", body["merged_sha"])
                stash_ref = "refs/ccrelay/replay/" + tag + "/dirty"
                code, stash = self._git(common, ["rev-parse", "--verify", "--quiet", stash_ref], allowed=(0, 1))
                # Inspection and normalization use the sealed raw index copy,
                # never the writer's. Capture rows even after a retained stash
                # reference survived a crash before the phase commit.
                with tempfile.NamedTemporaryFile(dir=self.workspace.folder, prefix="replay-index.") as temporary:
                    entries, index_state = self._capture_index(body, common, source, temporary)
                    if code:
                        self._normalize_index(common, source, temporary, entries)
                        stash = self._git(common, ["stash", "create"], worktree=source, index_file=temporary.name)[1]
                        if stash.strip():
                            self._retain(common, stash_ref, oid(stash.strip().decode()))
                stash_sha = oid(stash.strip().decode()) if stash.strip() else None
                self._fresh(body)
                body = self._phase(body, "captured", stash_sha=stash_sha, index_state=index_state, index_entries=entries)
        if body["phase"] in {"captured", "creating"}:
            if body["phase"] == "captured":
                body = self._phase(body, "creating")
            self.workspace.prepare(body["stage_spec"])
            self.checkpoint("after_replay_stage_create_effect")
            body = self._phase(body, "created")
        with self.workspace.writer_guard(body["spec"]):
            self._fresh(body)
            if self._merge(self._scope(body)) != body["merge"]:
                raise Denied("merge/replay authority changed before Git replay")
            if body["phase"] in {"created", "advancing"}:
                observed = self.workspace._observe(body["stage_spec"], common, stage)
                if observed["dirty"]:
                    raise Denied("changed staging tree before source loading")
                if observed["head"] != body["source_sha"]:
                    if observed["head"] != body["spec"]["workspace"]["base_commit"]:
                        raise Denied("unexpected replay staging head")
                    if body["phase"] == "created":
                        body = self._phase(body, "advancing")
                    self._git(common, ["merge", "--ff-only", body["source_sha"]], worktree=stage)
                    self.checkpoint("after_replay_source_load_effect")
                body = self._phase(body, "source_loaded")
            if body["phase"] == "rebasing":
                pointer = Path((stage / ".git").read_bytes()[8:-1].decode())
                if any((pointer / name).exists() for name in ("rebase-merge", "rebase-apply")):
                    return self._finding(body, "unfinished_rebase_retained")
                head = self._git(common, ["rev-parse", "HEAD"], worktree=stage)[1].strip().decode()
                code, _ = self._git(common, ["merge-base", "--is-ancestor", body["merged_sha"], head], allowed=(0, 1))
                if code:
                    return self._finding(body, "unconfirmed_rebase_effect", phase="recovery_required")
                body = self._phase(body, "rebased")
            elif body["phase"] == "source_loaded":
                body = self._phase(body, "rebasing")
                code, _ = self._git(common, ["rebase", "--merge", "--rebase-merges", "--keep-empty", "--empty=keep", "--reapply-cherry-picks", "--no-autostash", "--no-update-refs",
                                            "--onto", body["merged_sha"], body["published_sha"]], worktree=stage, allowed=(0, 1))
                self.checkpoint("after_replay_rebase_effect")
                if code:
                    return self._finding(body, "rebase_conflict_or_failure_retained")
                body = self._phase(body, "rebased")
            if body["phase"] == "applying":
                return self._finding(body, "unconfirmed_dirty_apply_not_repeated", phase="recovery_required")
            if body["phase"] == "rebased":
                if body["stash_sha"]:
                    body = self._phase(body, "applying")
                    code, _ = self._git(common, ["stash", "apply", "--index", body["stash_sha"]], worktree=stage, allowed=(0, 1))
                    self.checkpoint("after_replay_dirty_apply_effect")
                    if code:
                        return self._finding(body, "staged_or_unstaged_replay_conflict_retained")
                body = self._phase(body, "applied")
            if body["phase"] in {"applied", "overlaying"}:
                if body["phase"] == "applied":
                    body = self._phase(body, "overlaying")
                try:
                    self._overlay(body)
                except Denied as error:
                    return self._finding(body, str(error))
                body = self._phase(body, "restoring_index")
            if body["phase"] == "restoring_index":
                try:
                    self._overlay(body)  # Revalidate reserved bytes after a crash.
                    self._restore_index(body)
                except Denied as error:
                    return self._finding(body, str(error))
                body = self._phase(body, "index_restored")
        self.snapshots.capture(body["stage_checkpoint"], body["stage_spec"])
        with self.workspace.writer_guard(body["spec"]):
            self._fresh(body)
            if self._merge(self._scope(body)) != body["merge"]:
                raise Denied("merge/replay authority changed before candidate seal")
            candidate = self.snapshots.inspect(body["stage_checkpoint"])
            current = self.snapshots._scan(body["stage_checkpoint"], body["stage_spec"], store=False)
            if any(current[field] != candidate[field] for field in current):
                raise Denied("replay candidate changed before seal")
            body = self._phase(body, "ready")
        return body
