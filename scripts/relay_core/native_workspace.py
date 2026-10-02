"""Worker-UID local worktree setup; journal/observations grant no authority.

The protected launcher must validate the reviewed package, current binding and
hold a real writer/descendant fence across writer_guard. Neither a Python context
manager nor this worker-owned SQLite journal authenticates that proof. Native
startup, instruction installation, admission and target-OS integration are separate.
"""
import configparser
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile

from .artifacts import digest
from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, protected_path, strict_json
from .native_launch import _path, validate_spec
from .outbox import DeliveryLedger


SCHEMA = "ccrelay.native_workspace_journal.v1"
PHASES = {"planned", "creating", "checkout", "promoting", "prepared"}


def _role_home(role_id):
    return Path("/var/lib/ccrelay/roles") / identifier(role_id)


class WorkspacePreparation(DeliveryLedger):
    def __init__(self, *, policy, role_id, git_contract, writer_guard, checkpoint=lambda _: None):
        role = policy.roles.get(identifier(role_id))
        if role is None or not role.fields["enabled"] or os.geteuid() == 0 or os.geteuid() != role.fields["uid"]:
            raise Denied("workspace Git must run as the intended non-root worker UID")
        if not callable(writer_guard):
            raise Denied("trusted current-writer/descendant fence required")
        exact(git_contract, {"executable", "digest", "version_line"})
        _path(git_contract["executable"])
        if type(git_contract["digest"]) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", git_contract["digest"]) or \
                type(git_contract["version_line"]) is not str or not re.fullmatch(r"git version [^\r\n\x00]{1,120}", git_contract["version_line"]):
            raise Denied("explicit Git binary/version pins required")
        self.policy, self.role_id, self.uid = policy, role_id, role.fields["uid"]
        self.git_contract = strict_json(canonical_bytes(git_contract))
        self.git_digest = fingerprint(self.git_contract)
        self.writer_guard = writer_guard
        self.home = self._private(_role_home(role_id), directory=True)
        folder = self.home / "workspace-preparation"
        if not folder.exists() and not folder.is_symlink():
            folder.mkdir(mode=0o700)
        super().__init__(folder, owner_uid=self.uid, policy_digest=policy.digest, checkpoint=checkpoint)

    def _private(self, path, *, directory=False):
        path = protected_path(path, owners={0, self.uid}, directory=directory, private=True)
        metadata = path.lstat()
        if (not stat.S_ISDIR(metadata.st_mode) if directory else not stat.S_ISREG(metadata.st_mode)) or \
                metadata.st_uid != self.uid or metadata.st_mode & 0o077 or \
                not directory and metadata.st_nlink != 1:
            raise Denied("role-private unlinked workspace metadata required")
        return path

    def _initialize_component(self):
        self.connection.execute("CREATE TABLE workspace_metadata (schema TEXT NOT NULL,git_contract_digest TEXT NOT NULL)")
        self.connection.execute("INSERT INTO workspace_metadata VALUES (?,?)", (SCHEMA, self.git_digest))
        self.connection.execute("CREATE TABLE workspaces (session_id TEXT PRIMARY KEY,spec BLOB NOT NULL,spec_digest TEXT NOT NULL,phase TEXT NOT NULL)")

    def _validate_component(self):
        if self.connection.execute("SELECT schema,git_contract_digest FROM workspace_metadata").fetchall() != [(SCHEMA, self.git_digest)]:
            raise Denied("unknown workspace journal schema/Git pin; preserve for migration")
        for (session_id,) in self.connection.execute("SELECT session_id FROM workspaces").fetchall():
            self._row(session_id)

    def _row(self, session_id):
        self._check_lock()
        row = self.connection.execute("SELECT session_id,spec,spec_digest,phase FROM workspaces WHERE session_id=?", (identifier(session_id),)).fetchone()
        if row is None:
            return None
        spec = validate_spec(strict_json(row[1]), self.policy)
        if spec["role_id"] != self.role_id or spec["session_id"] != row[0] or fingerprint(spec) != row[2] or row[3] not in PHASES:
            raise Denied("workspace journal mapping/specification changed")
        return {"spec": spec, "spec_digest": row[2], "phase": row[3]}

    def _phase(self, spec, phase):
        with self._transaction():
            row = self._row(spec["session_id"])
            if row is None or row["spec"] != spec or self.policy.digest != self.policy_digest:
                raise Denied("workspace policy/specification changed during preparation")
            self.connection.execute("UPDATE workspaces SET phase=? WHERE session_id=?", (phase, spec["session_id"]))
            self.checkpoint("before_workspace_" + phase + "_commit")
        self.checkpoint("after_workspace_" + phase + "_commit")

    def _repository(self, common):
        self._private(common, directory=True)
        config = self._private(common / "config")
        body = config.read_bytes()
        if len(body) > 4096:
            raise Denied("bounded canonical role-private bare Git config required")
        parser = configparser.RawConfigParser(strict=True)
        try:
            parser.read_string(body.decode("utf-8"))
        except (UnicodeError, configparser.Error):
            raise Denied("invalid role-private bare Git config") from None
        if set(parser.sections()) - {"core", "extensions"} or parser.defaults() or "core" not in parser:
            raise Denied("Git includes, filters, remotes and arbitrary setup configuration are not permitted")
        core = dict(parser["core"])
        if set(core) - {"repositoryformatversion", "filemode", "bare", "logallrefupdates", "ignorecase", "precomposeunicode"} or \
                core.get("bare") != "true" or core.get("filemode") not in {"true", "false"} or \
                core.get("repositoryformatversion") not in {"0", "1"} or \
                any(core.get(key, "false") not in {"true", "false"} for key in ("logallrefupdates", "ignorecase", "precomposeunicode")):
            raise Denied("only canonical local bare repository settings supported")
        extensions = dict(parser["extensions"]) if "extensions" in parser else {}
        if extensions not in ({}, {"objectformat": "sha256"}) or bool(extensions) != (core["repositoryformatversion"] == "1"):
            raise Denied("unsupported Git repository extension")
        for name in ("objects/info/alternates", "objects/info/http-alternates", "commondir", "config.worktree", "shallow", "info/grafts"):
            path = common / name
            if path.exists() or path.is_symlink():
                raise Denied("external, worktree-configured or incomplete Git object topology unsupported")
        for name in ("objects", "refs", "HEAD"):
            self._private(common / name, directory=name != "HEAD")

    def _git(self, common, args, *, worktree=None, allowed=(0,)):
        self._check_lock()
        role = self.policy.roles.get(self.role_id)
        if self.policy.digest != self.policy_digest or role is None or not role.fields["enabled"] or role.fields["uid"] != self.uid:
            raise Denied("workspace policy/role changed before Git effect")
        if fingerprint(self.git_contract) != self.git_digest:
            raise Denied("Git contract changed during preparation; reviewed migration required")
        self._repository(common)
        executable = protected_path(self.git_contract["executable"], owners={0})
        if executable.lstat().st_uid != 0 or executable.stat().st_size > 32 * 1024 * 1024 or \
                digest(executable.read_bytes()) != self.git_contract["digest"]:
            raise Denied("installed Git binary pin changed")
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"}
        controls = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.attributesFile=/dev/null",
                    "-c", "core.excludesFile=/dev/null", "-c", "protocol.allow=never", "-c", "gc.auto=0", "-c", "maintenance.auto=false"]
        location = ["--git-dir=" + str(common)] if worktree is None else ["-C", str(worktree)]
        with tempfile.TemporaryFile(dir=self.folder) as output, tempfile.TemporaryFile(dir=self.folder) as errors:
            process = subprocess.Popen([str(executable), *location, *controls, *args], stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=errors, env=env, start_new_session=True, umask=0o077)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise Denied("Git preparation timed out; effects remain unconfirmed for fenced reconciliation") from None
            output.seek(0)
            errors.seek(0)
            body, error = output.read(1024 * 1024 + 1), errors.read(65536 + 1)
        if len(body) > 1024 * 1024 or len(error) > 65536:
            raise Denied("Git result exceeds bounded inspection size; workspace preserved")
        if process.returncode not in allowed:
            raise Denied("Git preparation failed (" + str(process.returncode) + "): " + error.decode("utf-8", errors="replace"))
        return process.returncode, body

    def _linked(self, common, worktree):
        self._private(worktree, directory=True)
        pointer = self._private(worktree / ".git").read_bytes()
        if len(pointer) > 4096 or not pointer.startswith(b"gitdir: ") or not pointer.endswith(b"\n"):
            raise Denied("exact Git linked-worktree pointer required")
        try:
            metadata = Path(pointer[8:-1].decode("utf-8"))
        except UnicodeError:
            raise Denied("invalid worktree metadata pointer") from None
        if not metadata.is_absolute() or metadata.parent != common / "worktrees" or \
                not re.fullmatch(r"[A-Za-z0-9_.-]+", metadata.name):
            raise Denied("worktree points outside role-private repository metadata")
        self._private(metadata, directory=True)
        if self._private(metadata / "commondir").read_bytes() != b"../..\n" or \
                self._private(metadata / "gitdir").read_bytes() != str(worktree / ".git").encode() + b"\n":
            raise Denied("worktree/common-directory backlinks disagree")
        if (metadata / "config.worktree").exists() or (metadata / "config.worktree").is_symlink():
            raise Denied("unexpected per-worktree Git configuration")
        for name in ("HEAD", "index"):
            if (metadata / name).exists() or (metadata / name).is_symlink():
                self._private(metadata / name)

    def _observe(self, spec, common, worktree):
        self._linked(common, worktree)
        head = self._git(common, ["rev-parse", "--verify", "HEAD^{commit}"], worktree=worktree)[1].strip().decode("ascii")
        branch = self._git(common, ["symbolic-ref", "--short", "HEAD"], worktree=worktree)[1].strip().decode("ascii")
        if not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", head) or branch != spec["workspace"]["branch"]:
            raise Denied("workspace branch/head differs from requested mapping")
        self._git(common, ["merge-base", "--is-ancestor", spec["workspace"]["base_commit"], head])
        status = self._git(common, ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching", "--ignore-submodules=all"], worktree=worktree)[1]
        return {"schema": "ccrelay.native_workspace_observation.v1", "session_id": spec["session_id"],
                "spec_digest": fingerprint(spec), "head": head, "branch": branch, "dirty": bool(status),
                "status_digest": digest(status), "runtime_ready": False, "admitted": False}

    def prepare(self, raw):
        spec = validate_spec(raw, self.policy)
        if spec["role_id"] != self.role_id or spec["role_uid"] != self.uid or self.policy.digest != self.policy_digest:
            raise Denied("workspace role/policy no longer current")
        workspace = spec["workspace"]
        common = self.home / "repos" / workspace["repo_id"] / "git"
        parent = self._private(self.home / "worktrees", directory=True)
        target = parent / spec["session_id"]
        stage = parent / (".ccrelay-" + fingerprint(spec)[7:])
        # A trusted launcher guard must cover this role's actual workspace and
        # shared Git metadata, including surviving native/tool/Git descendants.
        with self.writer_guard(spec):
            self._repository(common)
            version = self._git(common, ["--version"])[1].strip().decode("ascii")
            if version != self.git_contract["version_line"]:
                raise Denied("Git version/adapter compatibility pin changed")
            # Existence is not integrity: a role owns its Git object files and
            # can replace bytes under an unchanged hash-shaped filename. Check
            # full objects (not connectivity-only) before any workspace effect.
            self._git(common, ["fsck", "--full", "--no-reflogs", "--no-dangling"])
            self._git(common, ["cat-file", "-e", workspace["base_commit"] + "^{commit}"])
            row = self._row(spec["session_id"])
            if row is not None and row["spec"] != spec:
                raise Denied("workspace execution/spec transfer requires protected writer-transfer protocol")
            if row is None:
                if stage.exists() or stage.is_symlink():
                    raise Denied("unowned staging worktree; preserve for inspection")
                if workspace["mode"] == "create":
                    if target.exists() or target.is_symlink():
                        raise Denied("create cannot overwrite or adopt an existing workspace")
                    code, _ = self._git(common, ["show-ref", "--verify", "--quiet", "refs/heads/" + workspace["branch"]], allowed=(0, 1))
                    if code == 0:
                        raise Denied("create cannot adopt an existing branch")
                else:
                    self._observe(spec, common, target)
                with self._transaction():
                    self.connection.execute("INSERT INTO workspaces VALUES (?,?,?,?)", (
                        spec["session_id"], canonical_bytes(spec), fingerprint(spec), "planned"))
                    self.checkpoint("before_workspace_register_commit")
                self.checkpoint("after_workspace_register_commit")
                row = self._row(spec["session_id"])
            if workspace["mode"] == "reuse" or row["phase"] == "prepared":
                observed = self._observe(spec, common, target)
                self._phase(spec, "prepared")
                return observed
            # A target after an interrupted promotion is reconciled in place,
            # retaining even later dirty work. Never rerun initial checkout there.
            if target.exists() or target.is_symlink():
                if row["phase"] != "promoting" or stage.exists() or stage.is_symlink():
                    raise Denied("unexpected workspace/stage collision; original files preserved")
                observed = self._observe(spec, common, target)
                self._phase(spec, "prepared")
                return observed
            if not stage.exists() and not stage.is_symlink():
                if row["phase"] not in {"planned", "creating"}:
                    raise Denied("recorded staging worktree missing; preserve journal without fallback")
                code, _ = self._git(common, ["show-ref", "--verify", "--quiet", "refs/heads/" + workspace["branch"]], allowed=(0, 1))
                if code == 0:
                    raise Denied("partial branch-only setup needs evidenced repair; no branch reset")
                self._phase(spec, "creating")
                self.checkpoint("before_git_worktree_add")
                self._git(common, ["worktree", "add", "--no-checkout", "-b", workspace["branch"], str(stage), workspace["base_commit"]])
                self.checkpoint("after_git_worktree_add")
            self._linked(common, stage)
            if row["phase"] == "planned":
                row = self._row(spec["session_id"])
            if row["phase"] not in {"creating", "checkout", "promoting"}:
                raise Denied("unrecognized staging recovery state")
            observed = self._observe(spec, common, stage)
            if observed["head"] != workspace["base_commit"]:
                raise Denied("staging head changed before publication")
            if observed["dirty"]:
                # Only an unexposed empty staging tree can be initialized. A
                # partial/modified checkout is preserved, not reset or cleaned.
                if set(path.name for path in stage.iterdir()) != {".git"} or row["phase"] == "promoting":
                    raise Denied("incomplete or changed staging checkout needs evidenced repair")
                self._phase(spec, "checkout")
                self.checkpoint("before_git_checkout")
                self._git(common, ["read-tree", workspace["base_commit"]], worktree=stage)
                self._git(common, ["checkout-index", "--all"], worktree=stage)
                self.checkpoint("after_git_checkout")
                observed = self._observe(spec, common, stage)
                if observed["dirty"]:
                    raise Denied("staging checkout incomplete; no native readiness")
            self._phase(spec, "promoting")
            self.checkpoint("before_git_worktree_move")
            self._git(common, ["worktree", "move", str(stage), str(target)])
            self.checkpoint("after_git_worktree_move")
            observed = self._observe(spec, common, target)
            self._phase(spec, "prepared")
            return observed
