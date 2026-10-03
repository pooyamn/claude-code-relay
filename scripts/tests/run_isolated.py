#!/usr/bin/env python3
"""Run copied regression sources in an OS sandbox, never in relay-work.

macOS uses sandbox-exec; Linux uses bubblewrap with private namespaces. No
unsandboxed fallback is permitted. Linux execution requires target validation.
Only source allowlists are copied; host config, transcripts and credentials are
not fixtures. The child environment is constructed from scratch, without HOME.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import platform
import stat


LEGACY_SOURCES = (
    "claude-relay-send.py", "relay-extract-message.py", "relay-turn-done",
    "claude-tui-backend-multi", "relay-alt-launch", "claude-relay-group",
)
BROKER_SOURCES = ("ccrelay_broker.py", "ccrelay_broker_mcp.py", "ccrelay_owner_gate.py", "ccrelay_intake.py", "ccrelay_outbound.py", "ccrelay_native.py", "ccrelay_work.py", "ccrelay_admission.py", "ccrelayd.py", "relay_tg.py", "relay_bot_commands.py", "relay_model_controls.py", "relay_codex_bubble.py", "relay_codex_goal.py", "relay-codex-proto.py", "relay_ws.py", "relay-ws-edit-server.mjs", "pc_native_stdio.py")
DIAGNOSTIC_SOURCES = ("check-pc-claude-transport.py",)
DEPLOY_SOURCES = (
    "identity-plan.py", "identity-drill.py", "run-identity-drill.sh", "setup-wsl.sh", "pull-from-mac.sh",
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

# Official v1.3.2 darwin-arm64 release, independently verified archive digest:
# e2020b073c44f692685a24d6abc378817eb81ffaaf49fd0531ef8565f767f2f5.
# Never execute a host runtime or copy plugins/private keys into the sandbox.
AGE_RUNTIME_PINS = {
    ("darwin", "arm64"): {
        "age": "sha256:4012dfc2725883beafb710894af4f599b7a94f8c8e0f51f02cc96ab8df33915e",
        "age-keygen": "sha256:c16e229245123d0ad27442317461d63915416cad0294395cd19ca93feb3211ea",
    },
}


def copy_age_runtime(source, destination):
    pins = AGE_RUNTIME_PINS.get((sys.platform, platform.machine()))
    if pins is None:
        raise RuntimeError("no reviewed age test artifact for this platform; target pin required")
    source = Path(source)
    destination.mkdir(mode=0o700)
    for name, expected in pins.items():
        path = source / name
        before = path.lstat()
        def identity(value):
            return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                    value.st_ctime_ns, value.st_mode, value.st_uid, value.st_nlink)
        if path.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RuntimeError("age test runtime must be regular unlinked binaries")
        hasher = hashlib.sha256()
        with path.open("rb") as handle, (destination / name).open("xb") as output:
            if identity(os.fstat(handle.fileno())) != identity(before):
                raise RuntimeError("age test runtime changed before copy")
            for chunk in iter(lambda: handle.read(65536), b""):
                hasher.update(chunk)
                output.write(chunk)
            if identity(os.fstat(handle.fileno())) != identity(before) or identity(path.lstat()) != identity(before) or "sha256:" + hasher.hexdigest() != expected:
                raise RuntimeError("age test runtime does not match reviewed artifact")
        (destination / name).chmod(0o500)


def copy_sources(source: Path, target: Path) -> None:
    target.mkdir()
    for name in (*LEGACY_SOURCES, *BROKER_SOURCES, *DIAGNOSTIC_SOURCES):
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
            "(allow signal (target same-sandbox))\n"
            "(allow mach-lookup (global-name \"com.apple.system.opendirectoryd.libinfo\"))\n"
            "(allow file-read-metadata)\n"
            f"(allow file-read* {clauses} (subpath {json.dumps(str(scratch))}) (literal \"/\")"
            " (literal \"/dev/null\") (literal \"/dev/urandom\") (literal \"/dev/random\")"
            # Only this process's descriptors, not other processes or host paths.
            # Child spawning closes all unrelated FDs; crypto explicitly passes
            # just its verified, no-follow ciphertext FD to the age subprocess.
            " (regex #\"^/dev/fd/[0-9]+$\"))\n"
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
    batches, pending = [], []
    for name in ordered:
        # Real replay cases include Git/checkpoint setup and actual crash
        # children. Measured single cases take ~25s on this Mac; sharing the
        # unchanged 60s child ceiling would exceed it. Preserve every case.
        if name.startswith("test_core_post_merge."):
            if pending:
                batches.append(pending)
                pending = []
            batches.append([name])
        else:
            pending.append(name)
            if len(pending) == 4:
                batches.append(pending)
                pending = []
    if pending:
        batches.append(pending)
    return batches


def select_core_tests(catalog, modules=(), tests=()):
    """Select only discovered IDs; never import a selector outside the sandbox."""
    core_batches(catalog)  # Validate the complete catalog, even for focused runs.
    if not modules and not tests:
        return list(catalog)
    if len(set(modules)) != len(modules) or len(set(tests)) != len(tests) or \
            any(type(module) is not str or not re.fullmatch(r"test_core[A-Za-z0-9_]*", module)
                for module in modules) or any(test not in catalog for test in tests):
        raise RuntimeError("invalid, duplicate or undiscovered focused core selector")
    if any(not any(name.startswith(module + ".") for name in catalog) for module in modules):
        raise RuntimeError("focused core module has no discovered tests")
    return [name for name in catalog if name in tests or
            any(name.startswith(module + ".") for module in modules)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("legacy", "core", "all"), default="all")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--core-module", action="append", default=[],
                        help="run every discovered test in this exact core module; repeatable")
    parser.add_argument("--core-test", action="append", default=[],
                        help="run this exact discovered core test ID; repeatable")
    parser.add_argument("--age-runtime", type=Path,
                        help="directory of reviewed age/age-keygen binaries, copied into sandbox; no keys/plugins")
    args = parser.parse_args()
    if args.timeout < 1 or args.timeout > 60:
        parser.error("suite timeout must be between 1 and 60 seconds")
    if args.suite == "legacy" and (args.core_module or args.core_test):
        parser.error("core selectors require --suite core or all")
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
        if args.age_runtime is not None:
            runtime = scratch / "age-runtime"
            copy_age_runtime(args.age_runtime, runtime)
            env["CCRELAY_TEST_AGE_DIR"] = str(runtime)
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
            catalog = json.loads(result.stdout)
            selected = select_core_tests(catalog, args.core_module, args.core_test)
            batches = core_batches(selected)
            if args.core_module or args.core_test:
                print(f"Focused core selection: {len(selected)} of {len(catalog)} discovered tests; "
                      "not a full-core run", flush=True)
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
