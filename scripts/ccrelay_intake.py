#!/usr/bin/env python3
"""Target durable intake preparation. --plan reads examples; --run needs root policy.

No native/model dispatch, media downloads, sends, credential migration or live
configuration changes. Khadang-only testing; no production-bot cutover path.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading

sys.dont_write_bytecode = True  # --plan must not create cache files either.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_core.identity import Denied, Policy, exact, integer, protected_path, strict_json
from relay_core.owner_gate import OwnerPolicy
from relay_core.intake import IntakeLedger, IntakePolicy
from relay_core.polling import CycleHealth, DurablePoller, LivenessWatchdog, PollerLock, ReadOnlyBot


POLLER_ROOT = "/var/lib/ccrelay-pollers"  # Host-wide, never keyed by a state/config directory.


def configuration(raw):
    exact(raw, {"schema", "enabled", "test_bot", "expected_username", "env_path", "state_dir",
                "broker_policy", "owner_policy", "intake_policy", "long_poll_seconds", "network_timeout",
                "commit_grace_seconds", "conflict_limit"})
    if raw["schema"] != "ccrelay.intake_config.v1" or type(raw["enabled"]) is not bool or raw["test_bot"] != "khadang":
        raise Denied("unsupported config; only explicitly pinned Khadang testing is prepared")
    for key in ("env_path", "state_dir", "broker_policy", "owner_policy", "intake_policy"):
        path = raw[key]
        if type(path) is not str or not path.startswith("/") or ".." in path.split("/") or "\x00" in path:
            raise Denied("explicit protected absolute config path required")
    if type(raw["expected_username"]) is not str or not raw["expected_username"]:
        raise Denied("expected bot username required")
    for key in ("long_poll_seconds", "network_timeout", "commit_grace_seconds", "conflict_limit"):
        integer(raw[key])
    if not raw["long_poll_seconds"] < raw["network_timeout"] <= 60 or raw["commit_grace_seconds"] > 60 or raw["conflict_limit"] > 10:
        raise Denied("invalid transport/liveness policy")
    return raw


def token_from_file(path, uid):
    protected_path(path, owners={0, uid}, private=True)
    values = []
    for line in Path(path).read_text().splitlines():
        key, separator, value = line.strip().partition("=")
        if key == "CCRELAY_BOT_TOKEN" and separator and value.strip():
            values.append(value.strip())
    if len(values) != 1:
        raise Denied("one protected bot token required")
    return values[0]


def plan():
    folder = Path(__file__).resolve().parents[1] / "deploy" / "wsl" / "identities"
    broker = Policy(strict_json((folder / "broker-policy.json.example").read_bytes()))
    owner = OwnerPolicy(strict_json((folder / "owner-policy.json.example").read_bytes()), broker)
    intake = IntakePolicy(strict_json((folder / "intake-policy.json.example").read_bytes()), owner, broker)
    cfg = configuration(strict_json((folder / "intake-config.json.example").read_bytes()))
    return {"schema": "ccrelay.intake_plan.v1", "mode": "read-only-examples", "enabled": cfg["enabled"],
            "policy_digest": intake.digest, "bot_identity_is_placeholder": True, "test_bot": cfg["test_bot"],
            "poller_registry": POLLER_ROOT, "network_calls": False, "state_changes": False,
            "pending": ["verified Khadang getMe identity and existing poller ownership", "real Linux UID/lock/durability tests",
                        "PR 5 effectful dispatch/reconciliation", "PR 6 receipts and approval UI", "owner-authorized activation"]}


def run(raw):
    cfg = configuration(raw)
    if not cfg["enabled"] or cfg["expected_username"].startswith("REPLACE_"):
        raise Denied("intake disabled or bot identity still a placeholder")
    if sys.platform != "linux":
        raise Denied("target Linux process/ownership enforcement required")
    broker = Policy.load(cfg["broker_policy"])
    owner = OwnerPolicy.load(cfg["owner_policy"], broker)
    if not owner.enabled or os.geteuid() != owner.ingress_uid:
        raise Denied("enabled owner policy and protected ingress UID required")
    policy = IntakePolicy.load(cfg["intake_policy"], owner, broker)
    os.umask(0o077)
    health = CycleHealth(grace_seconds=cfg["commit_grace_seconds"], startup_seconds=3 * cfg["network_timeout"],
                         availability_seconds=cfg["network_timeout"])
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())

    def fatal(_):
        # Terminates ONLY this configured target process. No daemon lookup,
        # supervisor respawn or blocking I/O before stopping a wedged poller.
        os._exit(75)

    with PollerLock(POLLER_ROOT, bot_id=owner.bot_id, owner_uid=owner.ingress_uid) as guard:
        ledger = IntakeLedger(cfg["state_dir"], policy)
        watchdog = LivenessWatchdog(health, fatal)
        try:
            bot = ReadOnlyBot(token_from_file(cfg["env_path"], owner.ingress_uid), timeout=cfg["network_timeout"])
            poller = DurablePoller(bot, ledger, guard, health, expected_username=cfg["expected_username"],
                                   long_poll_seconds=cfg["long_poll_seconds"], conflict_limit=cfg["conflict_limit"],
                                   network_timeout=cfg["network_timeout"])
            watchdog.start()
            poller.verify()
            while not stop.is_set():
                result = poller.step()
                # Event.wait keeps shutdown responsive during known provider
                # cooldowns; it never starts another poller or model turn.
                stop.wait(min(result["wait_seconds"], 1))
        finally:
            watchdog.close()
            ledger.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--run", action="store_true")
    parser.add_argument("--config")
    args = parser.parse_args()
    if args.plan:
        print(json.dumps(plan(), indent=2))
        return
    if not args.config:
        parser.error("--run requires --config")
    protected_path(args.config, owners={0})
    run(strict_json(Path(args.config).read_bytes()))


if __name__ == "__main__":
    try:
        main()
    except (Denied, OSError, ValueError):
        # Do not print provider exception URLs, raw updates or private arguments.
        print("intake stopped: ownership, schema, durable state or transport gate failed; inspect protected evidence", file=sys.stderr)
        raise SystemExit(78)
