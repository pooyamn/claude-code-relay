"""Real local Git/UID/files; substituted Mac target paths and writer proof."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
from unittest import mock

from native_launch_fixtures import fixture, open_store
from relay_core.artifacts import digest
from relay_core.identity import Policy
from relay_core.native_workspace import WorkspacePreparation
from test_core_identity import policy_fields


def git(args, *, data=None):
    return subprocess.run(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", *args], input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10,
                          env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                               "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}, umask=0o077).stdout


def fixture_fields(folder, *, initialize=True):
    folder = Path(folder)
    folder.mkdir(mode=0o700, exist_ok=True)
    with mock.patch("relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path)):
        _, spec = fixture(open_store(folder / "inputs"))
    raw = policy_fields()
    raw["roles"][0]["uid"] = os.geteuid()
    policy = Policy(raw)
    home = folder / "role"
    for path in (home, home / "repos", home / "repos/fixture", home / "worktrees"):
        path.mkdir(mode=0o700, exist_ok=True)
    common = home / "repos/fixture/git"
    if initialize and not common.exists():
        git(["init", "--bare", "--template=", str(common)])
        first = b"original tracked bytes\n"
        ignored = b"cache/\n"
        stream = (b"blob\nmark :1\ndata " + str(len(first)).encode() + b"\n" + first +
                  b"blob\nmark :2\ndata " + str(len(ignored)).encode() + b"\n" + ignored +
                  b"commit refs/heads/main\nauthor Fixture <fixture@example.invalid> 1700000000 +0000\n"
                  b"committer Fixture <fixture@example.invalid> 1700000000 +0000\ndata 7\nfixture\n"
                  b"M 100644 :1 src/main.py\nM 100644 :2 .gitignore\n\ndone\n")
        git(["--git-dir=" + str(common), "fast-import", "--quiet"], data=stream)
    spec["role_uid"], spec["broker_policy_digest"] = os.geteuid(), policy.digest
    spec["workspace"]["base_commit"] = git(["--git-dir=" + str(common), "rev-parse", "refs/heads/main"]).strip().decode()
    spec["workspace"]["mode"] = "create"
    spec["provider_session_id"] = None
    contract = {"executable": "/usr/bin/git", "digest": digest(Path("/usr/bin/git").read_bytes()),
                "version_line": git(["--version"]).strip().decode()}
    return policy, spec, home, common, contract


@contextmanager
def fake_writer_guard(spec):
    # No native writer is launched in fixtures. This is not OS descendant proof.
    yield


@contextmanager
def open_workspace(policy, home, contract, *, guard=fake_writer_guard, checkpoint=lambda _: None):
    with mock.patch("relay_core.native_workspace._role_home", return_value=home), \
            mock.patch("relay_core.native_workspace.protected_path", side_effect=lambda path, **_: Path(path)), \
            mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)):
        journal = WorkspacePreparation(policy=policy, role_id="builder", git_contract=contract,
                                       writer_guard=guard, checkpoint=checkpoint)
        try:
            yield journal
        finally:
            journal.close()
