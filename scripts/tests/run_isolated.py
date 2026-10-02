#!/usr/bin/env python3
"""Run copied regression sources in an OS sandbox, never in relay-work.

macOS uses sandbox-exec; Linux uses bubblewrap with private namespaces. No
unsandboxed fallback is permitted. Linux execution requires target validation.
Only source allowlists are copied; host config, transcripts and credentials are
not fixtures. The child environment is constructed from scratch, without HOME.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


LEGACY_SOURCES = (
    "claude-relay-send.py", "relay-extract-message.py", "relay-turn-done",
    "claude-tui-backend-multi", "relay-alt-launch", "claude-relay-group",
)
BROKER_SOURCES = ("ccrelay_broker.py", "ccrelay_broker_mcp.py", "ccrelay_owner_gate.py", "ccrelay_intake.py", "ccrelay_outbound.py", "ccrelay_native.py", "ccrelay_work.py", "ccrelay_admission.py", "ccrelayd.py", "relay_tg.py", "relay_bot_commands.py", "relay_model_controls.py", "relay_codex_bubble.py", "relay_codex_goal.py", "relay-codex-proto.py", "relay_ws.py", "relay-ws-edit-server.mjs")
DEPLOY_SOURCES = (
    "identity-plan.py", "setup-wsl.sh", "pull-from-mac.sh",
    "identities/ccrelay.sysusers.conf", "identities/ccrelay.tmpfiles.conf",
    "identities/broker-policy.json.example", "identities/session.service.in",
    "identities/binding-read-policy.json.example",
    "identities/native-config.json.example",
    "identities/work-config.json.example",
    "identities/admission-config.json.example",
    "systemd/ccrelay-broker.service",
    "identities/owner-policy.json.example", "identities/deployment-policy.json.example",
    "systemd/ccrelay-owner-gate.service",
    "identities/intake-policy.json.example", "identities/intake-config.json.example", "systemd/ccrelay-intake.service",
    "identities/outbound-policy.json.example", "identities/outbound-config.json.example",
)


def copy_sources(source: Path, target: Path) -> None:
    target.mkdir()
    for name in (*LEGACY_SOURCES, *BROKER_SOURCES):
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"not a regular source file: {name}")
        shutil.copy2(path, target / name)
    for name in ("tests", "relay_core"):
        if (source / name).is_symlink() or not (source / name).is_dir():
            raise RuntimeError(f"not a regular source directory: {name}")
        destination = target / name
        destination.mkdir()
        for path in sorted((source / name).rglob("*")):
            if path.is_symlink():
                raise RuntimeError(f"source symlink not allowed: {path.name}")
            if path.is_file() and path.suffix in {".py", ".sh"} and "__pycache__" not in path.parts:
                copied = destination / path.relative_to(source / name)
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, copied)
    for name in DEPLOY_SOURCES:
        path = source.parent / "deploy" / "wsl" / name
        if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file():
            raise RuntimeError(f"not a regular deployment source: {name}")
        copied = target.parent / "deploy" / "wsl" / name
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, copied)
    # Synthetic native resolver config, never a copy of host model settings.
    for token, backend in (("ox", "opencode"), ("ik3", "kimi")):
        (target / f"relay-claude-settings-{token}.json").write_text(
            json.dumps({"backend": backend, "model": "fixture/model"}), encoding="utf-8")


def child_environment(scratch: Path, copied: Path, denied: Path) -> dict:
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C", "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(copied), "TMPDIR": str(scratch / "tmp"),
        "CCRELAY_TEST_SCRATCH": str(scratch), "CCRELAY_DENIED_SENTINEL": str(denied),
        "CCRELAY_ISOLATED_TEST": "1",
    }


def sandbox_command(scratch: Path, command: list, env: dict) -> list:
    if sys.platform == "darwin":
        binary = shutil.which("sandbox-exec")
        if not binary:
            raise RuntimeError("sandbox-exec unavailable; refusing unsandboxed execution")
        # System runtimes only. No general /Users, /Volumes, home or network read.
        readable = ("/System", "/usr", "/bin", "/sbin", "/Library/Developer", "/Library/Apple")
        clauses = "\n".join(f"(subpath {json.dumps(p)})" for p in readable)
        profile = (
            "(version 1)\n(deny default)\n(allow process*)\n(allow sysctl-read)\n"
            "(allow mach-lookup (global-name \"com.apple.system.opendirectoryd.libinfo\"))\n"
            "(allow file-read-metadata)\n"
            f"(allow file-read* {clauses} (subpath {json.dumps(str(scratch))}) (literal \"/\")"
            " (literal \"/dev/null\") (literal \"/dev/urandom\") (literal \"/dev/random\"))\n"
            f"(allow file-write* (subpath {json.dumps(str(scratch))}) (literal \"/dev/null\"))\n"
        )
        return [binary, "-p", profile, *command]
    if sys.platform.startswith("linux"):
        binary = shutil.which("bwrap")
        if not binary:
            raise RuntimeError("bubblewrap unavailable; install in target test environment, no unsafe fallback")
        result = [binary, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv"]
        for directory in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
            if Path(directory).exists():
                result += ["--ro-bind", directory, directory]
        result += ["--dir", "/etc"]
        for filename in ("/etc/ld.so.cache", "/etc/localtime"):
            if Path(filename).exists():
                result += ["--ro-bind", filename, filename]
        result += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
        result += ["--bind", str(scratch), str(scratch), "--chdir", str(scratch)]
        for key, value in env.items():
            result += ["--setenv", key, value]
        return [*result, "--", *command]
    raise RuntimeError("no reviewed OS test sandbox on this platform")


def core_batches(catalog):
    """Every sandbox-discovered test exactly once; retain the per-child bound."""
    if type(catalog) is not list or not catalog or len(catalog) > 4096 or \
            any(type(name) is not str or len(name) > 512 or not re.fullmatch(
                r"test_core[A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.test[A-Za-z0-9_]*", name) for name in catalog) or \
            len(set(catalog)) != len(catalog):
        raise RuntimeError("invalid/duplicate sandbox core test catalog")
    ordered = sorted(catalog)
    return [ordered[index:index + 4] for index in range(0, len(ordered), 4)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("legacy", "core", "all"), default="all")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if args.timeout < 1 or args.timeout > 60:
        parser.error("suite timeout must be between 1 and 60 seconds")
    source = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="ccrelay-test-") as folder, \
            tempfile.TemporaryDirectory(prefix="ccrelay-denied-") as forbidden:
        scratch = Path(folder).resolve()
        denied = Path(forbidden).resolve() / "synthetic-secret"
        denied.write_text("SYNTHETIC OUTSIDE SANDBOX", encoding="utf-8")
        (scratch / "tmp").mkdir()
        copied = scratch / "scripts"
        copy_sources(source, copied)
        env = child_environment(scratch, copied, denied)
        commands = [[sys.executable, str(copied / "tests" / "isolation_probe.py")]]
        if args.suite in {"legacy", "all"}:
            commands += [["/bin/bash", str(copied / "tests" / "run_tests.sh")]]
        for command in commands:
            wrapped = sandbox_command(scratch, command, env)
            result = subprocess.run(wrapped, cwd=scratch, env=env, timeout=args.timeout)
            if result.returncode:
                return result.returncode
        if args.suite in {"core", "all"}:
            # Discovery imports candidate tests ONLY inside the same OS sandbox.
            # The growing suite is serialized into bounded processes, not given
            # a larger timeout or run concurrently in shared scratch directories.
            driver = copied / "tests/core_batch.py"
            result = subprocess.run(sandbox_command(scratch, [sys.executable, str(driver), "--list"], env),
                                    cwd=scratch, env=env, timeout=args.timeout, capture_output=True)
            if result.returncode:
                sys.stderr.buffer.write(result.stderr)
                return result.returncode
            if len(result.stdout) > 2 * 1024 * 1024:
                raise RuntimeError("core test catalog exceeds bound")
            batches = core_batches(json.loads(result.stdout))
            print(f"Core catalog: {sum(map(len, batches))} tests in {len(batches)} serial batches", flush=True)
            for batch in batches:
                command = [sys.executable, str(driver), "--run", *batch]
                result = subprocess.run(sandbox_command(scratch, command, env), cwd=scratch, env=env, timeout=args.timeout)
                if result.returncode:
                    return result.returncode
        if denied.read_text(encoding="utf-8") != "SYNTHETIC OUTSIDE SANDBOX":
            raise RuntimeError("sandbox modified outside sentinel")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"isolated tests: {error}", file=sys.stderr)
        raise SystemExit(2)
