"""Real isolated Git replay; merge provenance and target fences are synthetic."""
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from native_workspace_fixtures import fixture_fields, git, open_workspace
from relay_core.contracts import fingerprint
from relay_core.identity import strict_json
from relay_core.post_merge import PostMergeReplay, ReplayMerge, ReplayPolicy
from relay_core.worktree_checkpoints import CheckpointPolicy, WorktreeCheckpoints


def commit(target, message):
    git(["-C", str(target), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", message])
    return git(["-C", str(target), "rev-parse", "HEAD"]).strip().decode()


def fields(folder, *, dirty=True, conflict=None):
    policy, spec, home, common, contract = fixture_fields(folder)
    target = home / "worktrees/builder.task"
    with open_workspace(policy, home, contract) as workspace:
        workspace.prepare(spec)
    (target / "published.txt").write_bytes(b"published candidate\n")
    git(["-C", str(target), "add", "published.txt"])
    published = commit(target, "published")
    (target / "later.txt").write_bytes(b"later committed work\n")
    if conflict == "committed":
        (target / "src/main.py").write_bytes(b"local committed replacement\n")
    git(["-C", str(target), "add", "later.txt", "src/main.py"])
    commit(target, "later")
    # A true squash commit: published candidate tree, but not its commit parent.
    tree = git(["--git-dir=" + str(common), "rev-parse", published + "^{tree}"]).strip().decode()
    merged = git(["--git-dir=" + str(common), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                  "commit-tree", tree, "-p", spec["workspace"]["base_commit"], "-m", "squashed publication"]).strip().decode()
    if conflict in {"committed", "dirty", "untracked", "ignored"}:
        upstream = home / "upstream-fixture"
        git(["--git-dir=" + str(common), "worktree", "add", "--detach", str(upstream), merged])
        if conflict in {"committed", "dirty"}:
            (upstream / "src/main.py").write_bytes(b"upstream replacement\n")
            git(["-C", str(upstream), "add", "src/main.py"])
        elif conflict == "untracked":
            (upstream / "unfinished\nnotes").write_bytes(b"upstream owns this path\n")
            git(["-C", str(upstream), "add", "unfinished\nnotes"])
        else:
            (upstream / "cache").mkdir()
            (upstream / "cache/output").write_bytes(b"upstream now tracks ignored path\n")
            git(["-C", str(upstream), "add", "-f", "cache/output"])
        merged = commit(upstream, "upstream")
    if dirty:
        (target / "src/main.py").write_bytes(b"staged future bytes\n")
        git(["-C", str(target), "add", "src/main.py"])
        (target / "src/main.py").write_bytes(b"unstaged future bytes\n")
        (target / "unfinished\nnotes").write_bytes(b"untracked\x00binary")
        (target / "cache").mkdir(mode=0o700)
        (target / "cache/output").write_bytes(b"ignored output")
        (target / "empty-dir").mkdir(mode=0o700)
    return policy, spec, home, common, contract, published, merged


@contextmanager
def replay_fixture(data, *, checkpoint=lambda _: None, verify=None, guard=None):
    policy, spec, home, common, contract, published, merged = data
    kwargs = {} if guard is None else {"guard": guard}
    def reader(scope):
        return ReplayMerge(fingerprint(scope), fingerprint({"synthetic_merge_not_github": True}), scope["publication_id"],
                           scope["spec"]["root_task_id"], scope["published_sha"], scope["merged_sha"], True, True)
    with open_workspace(policy, home, contract, **kwargs) as workspace, \
            mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)), \
            WorktreeCheckpoints(workspace, CheckpointPolicy(256, 8 * 1024 * 1024)) as snapshots, \
            PostMergeReplay(snapshots, ReplayPolicy("Fixture", "fixture@example.invalid", 8), verify_merge=verify or reader, checkpoint=checkpoint) as replay:
        yield replay


def request(replay, data, key="replay-1"):
    return replay.request(key, data[1], "publication-1", published_sha=data[5], merged_sha=data[6])


def loaded_fields(folder):
    folder = Path(folder)
    saved = strict_json((folder / "fixture-inputs.json").read_bytes())
    return (*fixture_fields(folder, initialize=False), saved["published"], saved["merged"])
