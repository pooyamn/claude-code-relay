"""Synthetic joined gate/send ledgers, never a live owner or Telegram channel."""
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import ccrelay_owner_gate
from relay_core.owner_prompts import OwnerIngressClient, OwnerPromptBridge
from relay_core.telegram_producers import TelegramProducers
from relay_core.telegram_scheduler import TelegramScheduler
from owner_fixtures import INGRESS, NOW, open_ledger
from telegram_fixtures import FakeOutbound, asset_store, open_telegram, protected_fixture


@contextmanager
def joined(folder, *, checkpoint=lambda _: None, after_bind=lambda: None, owner_policy=None):
    folder = Path(folder)
    (folder / "owner").mkdir(mode=0o700, exist_ok=True)
    now = [1790913600000]
    with protected_fixture():
        gate = open_ledger(folder / "owner", clock=lambda: NOW, fields=owner_policy)
        ledger = open_telegram(folder / "send", now=lambda: now[0], checkpoint=checkpoint)
        try:
            def request(path, request, *, broker_uid):
                # Kernel/channel observations ONLY are substituted on Mac;
                # both private DBs, captured bytes and process deaths are actual.
                if path != "/fixture/owner.sock" or broker_uid != gate.policy.gate_uid:
                    raise AssertionError("wrong configured gate channel")
                result = ccrelay_owner_gate.dispatch(gate, INGRESS, request)
                if request["method"] == "bind_prompt":
                    after_bind()
                return {"ok": True, "request_id": request["request_id"], "result": result}
            with mock.patch("relay_core.owner_prompts.client_request", side_effect=request):
                producer = TelegramProducers(ledger, authorize_source=lambda _: True)
                channel = OwnerIngressClient(gate.policy, "/fixture/owner.sock")
                bridge = OwnerPromptBridge(producer, channel, ownership_check=lambda: None, checkpoint=checkpoint)
                bot = FakeOutbound(folder / "provider.sqlite", checkpoint=checkpoint)
                scheduler = TelegramScheduler(ledger, bot, asset_store(folder / "assets"), ownership_check=lambda: None)
                yield gate, ledger, bridge, bot, scheduler, now
        finally:
            ledger.close()
            gate.close()
