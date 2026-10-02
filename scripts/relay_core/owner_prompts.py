"""Protected, receipt-bound owner prompt preparation. No bot/model calls.

The installed ingress must use a root-controlled OwnerPolicy, this authenticated
kernel channel, the protected send ledger and exclusive send ownership. Neither
a decoded view nor a worker-supplied receipt establishes those boundaries.
Live wiring, target OS acceptance and multi-company grants remain disabled.
"""
from datetime import datetime, timezone
import json
from pathlib import PurePosixPath
import re

from .broker_wire import client_request
from .contracts import canonical_bytes, decode, intent_payload
from .identity import Denied, exact, identifier
from .owner_gate import OwnerPolicy, timestamp
from .telegram_producers import bundle
from .telegram_repair import plain_pieces
from .telegram_scheduler import stable_id


class OwnerIngressClient:
    """Only the owner gate authenticates the caller; no peer UID in requests."""
    def __init__(self, policy, socket_path):
        if not isinstance(policy, OwnerPolicy) or not policy.enabled:
            raise Denied("enabled installed owner policy required for protected ingress")
        if type(socket_path) is not str or not socket_path.startswith("/") or \
                str(PurePosixPath(socket_path)) != socket_path or ".." in PurePosixPath(socket_path).parts or "\x00" in socket_path:
            raise Denied("explicit protected owner socket required")
        self.policy, self.socket_path = policy, socket_path

    def request(self, method, args):
        request = {"schema": "ccrelay.owner_request.v1", "request_id": stable_id("owner-request-", {
                   "method": method, "args": args, "policy": self.policy.digest}), "method": method, "args": args}
        response = client_request(self.socket_path, request, broker_uid=self.policy.gate_uid)
        if type(response) is not dict or response.get("ok") is not True:
            raise Denied("protected owner request denied; preserve original prompt")
        exact(response, {"ok", "request_id", "result"})
        if response["request_id"] != request["request_id"]:
            raise Denied("owner response does not match this request")
        return response["result"]

    def read(self, action_id):
        return self.request("read_prompt", {"action_id": identifier(action_id)})

    def bind(self, action_id, receipt):
        result = self.request("bind_prompt", {"action_id": identifier(action_id), "receipt": receipt})
        exact(result, {"bound"})
        if result["bound"] is not True:
            raise Denied("owner gate did not confirm prompt binding")


def prompt_bundle(view, policy):
    """Deterministic exact-action UI from an authenticated gate view, not prose."""
    exact(view, {"schema", "policy_digest", "prompt", "receipt"})
    if view["schema"] != "ccrelay.owner_prompt_view.v1" or view["policy_digest"] != policy.digest:
        raise Denied("owner prompt schema or installed policy changed")
    prompt = view["prompt"]
    exact(prompt, {"action", "approval", "approve_data", "deny_data"})
    action, approval = decode(prompt["action"]), decode(prompt["approval"])
    if action.kind != "external_action" or approval.kind != "approval" or \
            (approval.fields["action_id"], approval.fields["action_digest"], approval.fields["owner_id"]) != \
            (action.id, action.fields["intent_digest"], "telegram:" + str(policy.owner_id)):
        raise Denied("approval is not bound to the exact owner/action")
    approve = prompt["approve_data"]
    if type(approve) is not str or not re.fullmatch(r"cc1:[A-Za-z0-9_-]{32}:a", approve) or \
            prompt["deny_data"] != approve[:-1] + "d":
        raise Denied("one exact opaque decision nonce required")
    expiry = approval.fields["expires_at"]
    timestamp(expiry)
    # ASCII JSON visibly escapes controls/bidi/non-ASCII data, preserves every
    # parameter, and cannot escape a Markdown fence: these sends are plain text.
    parameters = json.dumps(action.to_dict()["parameters"], ensure_ascii=True, sort_keys=True, indent=2)
    content = ("Owner approval\n"
               f"Action: {action.id}\nKind: {action.fields['action_kind']}\n"
               f"Root task: {action.fields['root_task_id']}\nRequested by: {action.fields['requested_by_session_id']}\n"
               f"Intent digest: {action.fields['intent_digest']}\nApproval: {approval.id}\n"
               f"Owner: telegram:{policy.owner_id}\nExpires (UTC): {expiry}\n\n"
               "Parameters (exact JSON, including any screening verdict/exception):\n" + parameters +
               "\n\nButtons apply only to this exact action. Conversation text is not approval.")
    markup = {"inline_keyboard": [[{"text": "Approve exact action", "callback_data": approve},
                                   {"text": "Deny", "callback_data": prompt["deny_data"]}]]}
    source = {"schema": "ccrelay.owner_prompt_source.v1", "owner_policy_digest": policy.digest,
              "action": intent_payload("external_action", action.to_dict()), "approval_id": approval.id,
              "owner_id": approval.fields["owner_id"], "expires_at": expiry, "text": content, "reply_markup": markup}
    pieces = plain_pieces(content)
    operations = [{"method": "sendMessage", "args": {"chat_id": policy.chat_id,
                  **({"message_thread_id": policy.thread_id} if policy.thread_id is not None else {}),
                  "text": piece, "link_preview_options": {"is_disabled": True},
                  **({"reply_markup": markup} if position == len(pieces) - 1 else {})}, "assets": {}}
                  for position, piece in enumerate(pieces)]
    return bundle(bundle_id=stable_id("tg-owner-prompt-", source), root_task_id=action.fields["root_task_id"],
                  session_id=action.fields["requested_by_session_id"], chat_id=policy.chat_id,
                  thread_id=policy.thread_id, lane="approval", source_kind="approval", content=source, operations=operations)


class OwnerPromptBridge:
    def __init__(self, producer, channel, *, ownership_check, checkpoint=lambda _: None):
        if not isinstance(channel, OwnerIngressClient) or not callable(ownership_check):
            raise Denied("protected authenticated owner channel and exclusive send ownership required")
        self.producer, self.channel, self.ledger = producer, channel, producer.ledger
        self.policy, self.ownership_check, self.checkpoint = channel.policy, ownership_check, checkpoint
        if self.policy.bot_id != self.ledger.policy.bot_id or self.policy.chat_id not in self.ledger.policy.raw["allowed_chats"] or \
                self.policy.thread_id == 1:
            raise Denied("owner route must match the send policy; general topic policy uses null, not 1")

    def prepared(self, action_id):
        self.ownership_check()
        view = self.channel.read(action_id)
        value = prompt_bundle(view, self.policy)
        if view["prompt"]["action"]["id"] != action_id:
            raise Denied("gate view belongs to another action")
        return view, value

    def enqueue(self, action_id):
        view, value = self.prepared(action_id)
        existing = self.ledger.bundle(value["id"])
        if view["receipt"] is not None and existing is None:
            raise Denied("bound prompt lacks local send history; reconcile restore, never replace it")
        if existing is None:
            prompt = view["prompt"]
            if prompt["action"]["state"] != "stored" or prompt["approval"]["state"] != "pending" or \
                    datetime.fromtimestamp(self.ledger.now() / 1000, timezone.utc) >= timestamp(prompt["approval"]["expires_at"]):
                raise Denied("only an unexpired pending approval may enroll a new prompt")
        self.ownership_check()
        ticket = self.producer.enqueue(value)
        if view["receipt"] is not None and self.confirmed_receipt(value) != view["receipt"]:
            raise Denied("owner prompt receipt disagrees with protected send history")
        return ticket  # enrollment/confirmed delivery is never an owner decision

    def confirmed_receipt(self, expected):
        current = self.ledger.bundle(expected["id"])
        if current is None or canonical_bytes(current["body"]) != canonical_bytes(expected):
            raise Denied("prompt source, exact action, buttons or route changed")
        if self.ledger.status(expected["id"])["state"] != "confirmed":
            raise Denied("all required prompt chunks need confirmed delivery")
        items = self.ledger.items(expected["id"])
        last_id = None
        for position, item in enumerate(items):
            record = item["current"]["record"]
            evidence = self.ledger.captured_evidence(record.id)
            if item["repair"] is not None or record.fields["state"] != "confirmed" or \
                    evidence != self.ledger._evidence(record.fields["outcome_evidence_id"]) or evidence["outcome"] != "accepted" or \
                    len(evidence["payload"]["receipt"]["message_ids"]) != 1:
                raise Denied("prompt receipt lacks original protected attempt provenance")
            # The complete plain prompt has exactly one button-bearing message,
            # at its end. Earlier receipts do not authorize that button nonce.
            if "reply_markup" in item["operation"]["args"]:
                if position != len(items) - 1 or last_id is not None:
                    raise Denied("buttons must belong to the final exact prompt chunk")
                last_id = evidence["payload"]["receipt"]["message_ids"][0]
        if last_id is None:
            raise Denied("confirmed prompt lacks its decision buttons")
        return {"bot_id": self.policy.bot_id, "chat_id": self.policy.chat_id,
                "thread_id": self.policy.thread_id, "message_id": last_id}

    def bind(self, action_id):
        view, value = self.prepared(action_id)
        receipt = self.confirmed_receipt(value)
        if view["receipt"] is not None and view["receipt"] != receipt:
            raise Denied("owner prompt already binds another message; no rebinding")
        self.ownership_check()
        self.checkpoint("before_prompt_bind")
        self.channel.bind(action_id, receipt)
        self.checkpoint("after_prompt_bind")
        return {"bound": True, "receipt": receipt, "bundle_id": value["id"], "meaning": "delivery_not_owner_approval"}
