"""Protected immutable candidate store and bootstrap-only deployment pointer.

Installs bytes without executing candidate code, extracting archives, copying
homes or restarting services. Routine activation remains closed until PR 11.
Actual role/ACL/root-service enforcement still requires target Linux testing.
"""
import fcntl
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
from contextlib import contextmanager

from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, protected_path, strict_json
from . import screening


def digest(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def relative_path(value):
    if type(value) is not str or len(value) > 256 or not re.fullmatch(r"[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)*", value) or \
            any(part in {".", ".."} for part in value.split("/")) or value.split("/")[0] == "manifest.json":
        raise Denied("safe canonical candidate-relative path required")
    return value


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new(path, body, mode=0o400):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as output:
            output.write(body)
            output.flush()
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)


class DeploymentPolicy:
    def __init__(self, raw):
        exact(raw, {"schema", "bootstrap_enabled", "routine_enabled", "components"})
        if raw["schema"] != "ccrelay.deployment_policy.v1" or type(raw["bootstrap_enabled"]) is not bool or raw["routine_enabled"] is not False:
            raise Denied("unsupported deployment policy; routine gates are not yet implemented")
        self.bootstrap_enabled = raw["bootstrap_enabled"]
        if type(raw["components"]) is not list or not raw["components"]:
            raise Denied("explicit component allowlist required")
        components = {}
        for item in raw["components"]:
            exact(item, {"id", "credentialed", "routine_prefixes"})
            name = identifier(item["id"])
            prefixes = item["routine_prefixes"]
            if name in components or type(item["credentialed"]) is not bool or type(prefixes) is not list or \
                    any(type(prefix) is not str or not prefix.endswith("/") for prefix in prefixes):
                raise Denied("invalid component classification policy")
            for prefix in prefixes:
                relative_path(prefix[:-1])
            components[name] = {"credentialed": item["credentialed"], "routine_prefixes": tuple(prefixes)}
        self.components = components
        self.digest = fingerprint(raw)

    @classmethod
    def load(cls, path):
        protected_path(path, owners={0})
        return cls(strict_json(Path(path).read_bytes()))

    def classify(self, candidate, base):
        component = candidate["component"]
        if component not in self.components or base is not None and base["component"] != component:
            raise Denied("unknown/mismatched component")
        old = {} if base is None else {entry["path"]: entry for entry in base["files"]}
        new = {entry["path"]: entry for entry in candidate["files"]}
        changed = sorted(path for path in set(old) | set(new) if old.get(path) != new.get(path))
        if not changed:
            raise Denied("candidate makes no change")
        rule = self.components[component]
        reasons = []
        if base is None:
            reasons.append("bootstrap")
        if rule["credentialed"]:
            reasons.append("credential_boundary")
        if any(not any(path.startswith(prefix) for prefix in rule["routine_prefixes"]) for path in changed):
            reasons.append("outside_routine_allowlist")
        return {"schema": "ccrelay.change_classification.v1", "component": component,
                "candidate_digest": fingerprint(candidate), "base_digest": None if base is None else fingerprint(base),
                "policy_digest": self.digest, "changed_paths": changed,
                "class": "protected" if reasons else "routine", "reasons": reasons}


class ArtifactStore:
    def __init__(self, directory, *, owner_uid):
        if type(owner_uid) is not int or owner_uid <= 0 or os.geteuid() != owner_uid:
            raise Denied("artifact store requires its protected component UID")
        self.root = protected_path(directory, owners={0, owner_uid}, directory=True, private=True)
        if self.root.lstat().st_uid != owner_uid:
            raise Denied("wrong artifact directory owner")
        self.uid = owner_uid

    @contextmanager
    def locked(self):
        path = self.root / "deploy.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            protected_path(path, owners={0, self.uid}, private=True)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def _directory(self, artifact_digest):
        if type(artifact_digest) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", artifact_digest):
            raise Denied("valid artifact digest required")
        return self.root / artifact_digest[7:]

    def install(self, component, files):
        identifier(component)
        if type(files) is not list or not 1 <= len(files) <= 128:
            raise Denied("bounded complete candidate tree required")
        entries, contents, total = [], {}, 0
        for item in files:
            exact(item, {"path", "content", "executable"})
            path = relative_path(item["path"])
            body = item["content"]
            if path in contents or type(body) is not bytes or len(body) > 1024 * 1024 or type(item["executable"]) is not bool:
                raise Denied("invalid/duplicate candidate file")
            total += len(body)
            if total > 8 * 1024 * 1024:
                raise Denied("candidate tree exceeds byte limit")
            contents[path] = body
            entries.append({"path": path, "size": len(body), "digest": digest(body), "executable": item["executable"]})
        if any(str(parent) in contents for path in contents for parent in PurePosixPath(path).parents if str(parent) != "."):
            raise Denied("file/directory candidate path collision")
        manifest = {"schema": "ccrelay.artifact.v1", "component": component, "files": sorted(entries, key=lambda entry: entry["path"])}
        artifact_digest = fingerprint(manifest)
        final = self._directory(artifact_digest)
        with self.locked():
            if final.exists() or final.is_symlink():
                self.verify(artifact_digest)
                return artifact_digest
            staging = self.root / ("staging-" + secrets.token_hex(16))
            staging.mkdir(mode=0o700)
            # Failed stages are retained for inspection, never auto-selected.
            for entry in manifest["files"]:
                target = staging / entry["path"]
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                write_new(target, contents[entry["path"]], 0o500 if entry["executable"] else 0o400)
            write_new(staging / "manifest.json", canonical_bytes(manifest))
            for directory in sorted([p for p in staging.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
                os.chmod(directory, 0o500)
                fsync_dir(directory)
            os.chmod(staging, 0o500)
            fsync_dir(staging)
            os.rename(staging, final)
            fsync_dir(self.root)
        self.verify(artifact_digest)
        return artifact_digest

    def verify(self, artifact_digest):
        folder = self._directory(artifact_digest)
        protected_path(folder, owners={0, self.uid}, directory=True, private=True)
        manifest_path = folder / "manifest.json"
        manifest = strict_json(self._read(manifest_path, 0o400))
        exact(manifest, {"schema", "component", "files"})
        if manifest["schema"] != "ccrelay.artifact.v1" or fingerprint(manifest) != artifact_digest:
            raise Denied("artifact manifest/digest mismatch")
        identifier(manifest["component"])
        if type(manifest["files"]) is not list or not 1 <= len(manifest["files"]) <= 128:
            raise Denied("invalid artifact file count")
        contents, directories, total = {}, {folder}, 0
        for entry in manifest["files"]:
            exact(entry, {"path", "size", "digest", "executable"})
            path = relative_path(entry["path"])
            if path in contents or type(entry["executable"]) is not bool or type(entry["size"]) is not int or not 0 <= entry["size"] <= 1024 * 1024:
                raise Denied("invalid manifest file")
            target = folder / path
            body = self._read(target, 0o500 if entry["executable"] else 0o400)
            total += len(body)
            if len(body) != entry["size"] or digest(body) != entry["digest"] or total > 8 * 1024 * 1024:
                raise Denied("artifact file digest/size mismatch")
            contents[path] = body
            directories.update(parent for parent in target.parents if parent == folder or folder in parent.parents)
        expected = {folder / name for name in contents} | directories | {manifest_path}
        # Reject injected extra files, symlinks and hard links, including unused
        # imports. The entire selected tree, not just listed files, is checked.
        if set(folder.rglob("*")) | {folder} != expected:
            raise Denied("artifact contains unlisted entries")
        for directory in directories:
            protected_path(directory, owners={0, self.uid}, directory=True, private=True)
            if stat.S_IMODE(directory.lstat().st_mode) != 0o500:
                raise Denied("artifact directory is not sealed")
        return manifest, contents

    def _read(self, path, mode):
        protected_path(path, owners={0, self.uid}, private=True)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != mode or metadata.st_nlink != 1 or metadata.st_size > 1024 * 1024:
                raise Denied("unsealed/linked/oversized artifact file")
            with os.fdopen(fd, "rb", closefd=False) as source:
                return source.read(1024 * 1024 + 1)
        finally:
            os.close(fd)

    def active(self, component):
        path = self.root / (identifier(component) + ".active.json")
        if not path.exists() and not path.is_symlink():
            return None
        value = strict_json(self._read(path, 0o400))
        exact(value, {"schema", "component", "artifact_digest", "policy_digest", "action_id", "attempt_id"})
        if value["schema"] != "ccrelay.active_artifact.v1" or value["component"] != component:
            raise Denied("invalid active artifact record")
        self.verify(value["artifact_digest"])
        return value


class BootstrapDeployer:
    def __init__(self, policy, store, ledger, *, known_secrets=()):
        if store.uid != ledger.policy.gate_uid:
            raise Denied("deployer store and approval identities differ")
        self.policy, self.store, self.ledger = policy, store, ledger
        self.known_secrets = tuple(known_secrets)

    def plan(self, artifact_digest, screen_report, *, screening_exception=None):
        candidate, contents = self.store.verify(artifact_digest)
        active = self.store.active(candidate["component"])
        base = None if active is None else self.store.verify(active["artifact_digest"])[0]
        classification = self.policy.classify(candidate, base)
        masked = screening.payload(candidate, contents, known_secrets=self.known_secrets)
        checked = screening.report(screen_report, candidate, masked)
        needs_exception = checked["verdict"] != "clear"
        if needs_exception and (type(screening_exception) is not str or not screening_exception.strip()):
            raise Denied("missing/flagged screening requires explicit exact-version owner exception")
        if not needs_exception and screening_exception is not None:
            raise Denied("unexpected screening exception")
        return {"component": candidate["component"], "artifact_digest": artifact_digest,
                "base_digest": classification["base_digest"], "deployment_policy_digest": self.policy.digest,
                "owner_policy_digest": self.ledger.policy.digest, "classification": classification,
                "screening": checked, "screening_exception": screening_exception, "mode": "owner_bootstrap"}

    def activate(self, peer, action_id, attempt_id):
        self.ledger.policy.require(peer, self.store.uid)
        if not self.policy.bootstrap_enabled:
            raise Denied("bootstrap deployment disabled")
        with self.store.locked():
            action, approval = self.ledger.load(action_id)
            if action.fields["action_kind"] != "deploy_artifact":
                raise Denied("not an artifact deployment action")
            parameters = action.to_dict()["parameters"]
            if action.fields["state"] != "stored":
                raise Denied("attempt already claimed; reconcile without reactivation")
            expected = self.plan(parameters.get("artifact_digest"), parameters.get("screening"),
                                 screening_exception=parameters.get("screening_exception"))
            if canonical_bytes(expected) != canonical_bytes(parameters):
                raise Denied("candidate/base/policy/screening changed since owner review")
            claim = self.ledger.claim(peer, action.id, action.fields["intent_digest"], attempt_id)
            if not claim["may_execute"]:
                raise Denied("attempt has already been claimed")
            value = {"schema": "ccrelay.active_artifact.v1", "component": expected["component"],
                     "artifact_digest": expected["artifact_digest"], "policy_digest": self.policy.digest,
                     "action_id": action.id, "attempt_id": attempt_id}
            pending = self.store.root / ("pointer-" + secrets.token_hex(16))
            write_new(pending, canonical_bytes(value))
            os.replace(pending, self.store.root / (value["component"] + ".active.json"))
            fsync_dir(self.store.root)
            return self.ledger.confirm(peer, action.id, attempt_id, "artifact-pointer-" + attempt_id,
                                       "pointer-verified-" + attempt_id)

    def reconcile(self, peer, action_id):
        self.ledger.policy.require(peer, self.store.uid)
        with self.store.locked():
            action = self.ledger.recover(peer, action_id)
            if action.fields["state"] != "unknown":
                return action
            value = self.store.active(action.fields["parameters"]["component"])
            if value is not None and value["action_id"] == action.id and value["attempt_id"] == action.fields["attempt_id"] and \
                    value["artifact_digest"] == action.fields["parameters"]["artifact_digest"] and \
                    value["policy_digest"] == action.fields["parameters"]["deployment_policy_digest"]:
                fsync_dir(self.store.root)
                return self.ledger.confirm(peer, action.id, value["attempt_id"], "artifact-pointer-" + value["attempt_id"],
                                           "pointer-reconciled-" + value["attempt_id"])
            return action  # Absence is not authority to reactivate or reconsume.
