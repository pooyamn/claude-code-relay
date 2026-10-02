"""Single local bot poll owner, bounded transport and real durable-cycle health.

The poller never runs a model, subprocess, download, callback answer or send.
Its lock coordinates cooperating processes on one host; it cannot fence an
unmanaged process on another machine. Sustained 409 means investigate ownership,
not endlessly restart or steal/delete a webhook.
"""
import fcntl
import os
from pathlib import Path
import secrets
import stat
import threading
import time
import urllib.error
import urllib.request

from .artifacts import fsync_dir, write_new
from .contracts import canonical_bytes
from .identity import Denied, integer, observe_process, protected_path
from .intake import MAX_RESPONSE, provider_json


class PollError(Exception):
    def __init__(self, code, retry_after=0):
        # Never retain an exception URL/description containing the token.
        self.code, self.retry_after = code, retry_after
        super().__init__("Telegram intake error code " + str(code))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise PollError(302)


class ReadOnlyBot:
    """Intake-only methods, not globally read-only remote state.

    getUpdates acknowledges earlier updates and sets its subscription filter.
    Those effects are allowed ONLY after the poller's identity/durability gates.
    No messages, webhook changes or file operations are exposed.
    """
    def __init__(self, token, *, timeout):
        if type(token) is not str or not token or any(char.isspace() for char in token):
            raise Denied("explicit protected bot token required")
        integer(timeout)
        self._token, self.timeout = token, timeout

    def request(self, method, parameters=None):
        if method not in {"getMe", "getWebhookInfo", "getUpdates"}:
            raise Denied("intake transport cannot mutate bot configuration or send")
        request = urllib.request.Request("https://api.telegram.org/bot" + self._token + "/" + method,
                                         canonical_bytes(parameters or {}), {"Content-Type": "application/json"})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as error:
            raw = error.read(MAX_RESPONSE + 1)
            try:
                result = provider_json(raw)
                code = result.get("error_code", error.code) if type(result) is dict else error.code
                parameters = (result.get("parameters") or {}) if type(result) is dict else {}
                retry = parameters.get("retry_after", 0) if type(parameters) is dict else 0
                raise PollError(integer(code), integer(retry, 0)) from None
            except Denied:
                raise PollError(error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise PollError(0) from None
        result = provider_json(raw)
        if type(result) is not dict or type(result.get("ok")) is not bool:
            raise Denied("invalid Bot API envelope")
        if not result["ok"]:
            parameters = result.get("parameters") or {}
            retry = parameters.get("retry_after", 0) if type(parameters) is dict else 0
            raise PollError(integer(result.get("error_code", 0), 0), integer(retry, 0))
        return raw

    def identity(self):
        return provider_json(self.request("getMe")).get("result")

    def webhook(self):
        return provider_json(self.request("getWebhookInfo")).get("result")

    def updates(self, offset, timeout):
        return self.request("getUpdates", {"offset": offset, "timeout": timeout, "limit": 100,
                                           "allowed_updates": ["message", "callback_query"]})


class PollerLock:
    def __init__(self, directory, *, bot_id, owner_uid, observer=observe_process):
        if os.geteuid() != owner_uid:
            raise Denied("poller lock requires the protected ingress UID")
        directory = protected_path(directory, owners={0, owner_uid}, directory=True, private=True)
        if directory.lstat().st_uid != owner_uid:
            raise Denied("wrong poller registry owner")
        self.path = directory / (str(integer(bot_id)) + ".lock")
        self.uid, self.bot_id, self.observer = owner_uid, bot_id, observer
        self.fd = None
        self.generation = None

    def __enter__(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            protected_path(self.path, owners={0, self.uid}, private=True)
            if os.fstat(fd).st_nlink != 1:
                raise Denied("linked lock file rejected")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            process = self.observer(os.getpid())
            if process.uid != self.uid:
                raise Denied("poller kernel identity mismatch")
            self.generation = process.start_identity
            value = {"schema": "ccrelay.poller_owner.v1", "bot_id": self.bot_id, "pid": os.getpid(),
                     "process_start": self.generation, "lease_id": secrets.token_hex(16)}
            os.ftruncate(fd, 0)
            os.write(fd, canonical_bytes(value))
            os.fsync(fd)
            fsync_dir(self.path.parent)
            self.fd = fd
            self.check()
            return self
        except Exception:
            os.close(fd)
            self.fd = None
            raise

    def check(self):
        if self.fd is None:
            raise Denied("poller lifetime lock not held")
        protected_path(self.path, owners={0, self.uid}, private=True)
        opened, linked = os.fstat(self.fd), self.path.lstat()
        process = self.observer(os.getpid())
        if (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino) or not stat.S_ISREG(linked.st_mode) or \
                linked.st_nlink != 1 or process.uid != self.uid or process.start_identity != self.generation:
            raise Denied("poller owner/path generation changed")

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        # Never unlink lifetime locks: doing so permits two different inodes.


class CycleHealth:
    def __init__(self, *, grace_seconds, startup_seconds, availability_seconds, clock=time.monotonic):
        self.clock, self.grace = clock, integer(grace_seconds)
        self._lock = threading.Lock()
        self.durable_deadline = clock() + integer(startup_seconds) + self.grace
        self.phase, self.deadline, self.cycles = "starting", self.durable_deadline, 0
        self.availability = integer(availability_seconds)

    def phase_started(self, phase, allowed_seconds):
        with self._lock:
            self.phase, self.deadline = phase, self.clock() + allowed_seconds + self.grace
            if phase == "provider_cooldown":
                self.durable_deadline = max(self.durable_deadline, self.deadline)

    def committed_cycle(self):
        with self._lock:
            self.phase, self.deadline = "durable_cycle", self.clock() + self.grace
            self.cycles += 1
            self.durable_deadline = self.clock() + self.availability + self.grace

    def status(self):
        with self._lock:
            return {"phase": self.phase, "durable_cycles": self.cycles,
                    "stale": self.clock() > min(self.deadline, self.durable_deadline)}


class DurablePoller:
    def __init__(self, bot, ledger, guard, health, *, expected_username, long_poll_seconds,
                 conflict_limit, network_timeout, wall_clock=time.time):
        if type(expected_username) is not str or not expected_username:
            raise Denied("pinned verified bot username required")
        if not 1 <= integer(long_poll_seconds) < integer(network_timeout) <= 60 or not 1 <= integer(conflict_limit) <= 10:
            raise Denied("invalid polling/timeout/conflict policy")
        self.bot, self.ledger, self.guard, self.health = bot, ledger, guard, health
        self.username, self.long_poll, self.conflict_limit = expected_username, long_poll_seconds, conflict_limit
        self.timeout, self.clock = network_timeout, wall_clock
        self.offset = 0  # Observe pending updates before any ACK after restart.
        self.verified = False

    def verify(self):
        if self.verified:
            raise Denied("verification cannot renew a running poller's startup allowance")
        if self.username.lower() != self.ledger.policy.bot_username.lower():
            raise Denied("intake routing and transport bot usernames differ")
        self.guard.check()
        self.health.phase_started("verifying_identity", 2 * self.timeout)
        identity = self.bot.identity()
        if type(identity) is not dict or type(identity.get("id")) is not int or identity["id"] != self.ledger.policy.owner.bot_id or \
                identity.get("is_bot") is not True or str(identity.get("username", "")).lower() != self.username.lower():
            raise Denied("configured token is not the pinned test bot; no polling")
        webhook = self.bot.webhook()
        if type(webhook) is not dict or webhook.get("url") != "":
            raise Denied("webhook ownership is incompatible; never delete it automatically")
        self.ledger.reconcile_spool()
        self.ledger.materialize()
        self.verified = True
        self.health.phase_started("awaiting_first_poll", self.timeout)

    def step(self):
        if not self.verified:
            raise Denied("verify bot identity and webhook ownership before polling")
        self.guard.check()
        state = self.ledger.state()
        if state["conflicts"] >= self.conflict_limit:
            raise Denied("sustained poll conflict; inspect competing owner, no restart loop")
        remaining = max(0, state["retry_at"] - int(self.clock()))
        if remaining:
            self.health.phase_started("provider_cooldown", remaining + self.timeout)
            return {"wait_seconds": remaining, "status": "provider_cooldown"}
        # Verify phase completion before renewing any health deadline. A caller
        # cannot make a stuck loop healthy by repeatedly emitting a timer tick.
        if self.health.status()["stale"]:
            raise Denied("polling cycle stale; inspect before admitting another request")
        self.health.phase_started("polling_and_commit", self.timeout)
        try:
            raw = self.bot.updates(self.offset, self.long_poll)
        except PollError as error:
            state = self.ledger.poll_failure(error.code, error.retry_after)
            if error.code == 409 and state["conflicts"] >= self.conflict_limit:
                raise Denied("sustained 409: competing poller or webhook must be reconciled") from None
            if error.code in {401, 403}:
                raise Denied("bot credentials rejected; no automatic fallback") from None
            if error.code == 429:
                remaining = max(0, state["retry_at"] - int(self.clock()))
                self.health.phase_started("provider_cooldown", remaining + self.timeout)
                return {"wait_seconds": remaining, "status": "provider_cooldown"}
            return {"wait_seconds": 1, "status": "poll_error", "code": error.code}
        next_offset = self.ledger.capture(raw, self.offset)
        self.ledger.materialize()
        self.offset = next_offset  # No higher request until capture COMMIT succeeds.
        self.health.committed_cycle()
        return {"wait_seconds": 0, "status": "durably_captured", "next_offset": self.offset}


class LivenessWatchdog:
    """Independent thread observes real phase deadlines, never starts a poller."""
    def __init__(self, health, fatal):
        self.health, self.fatal = health, fatal
        self.stop = threading.Event()
        self.thread = None

    def tick(self):
        if self.health.status()["stale"]:
            self.fatal("intake cycle deadline exceeded")
            return False
        return True

    def start(self):
        def run():
            while not self.stop.wait(1):
                if not self.tick():
                    return
        self.thread = threading.Thread(target=run, name="ccrelay-intake-liveness", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
