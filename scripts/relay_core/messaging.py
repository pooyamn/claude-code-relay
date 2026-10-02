"""Kernel-authenticated message enrollment/logging; native delivery is gated.

Caller identity is the Authority Actor, never cwd or message text. Stable IDs
are caller-chosen opaque intent IDs scoped to that authenticated session.
Message logs are limited to the two participants. The legacy three-hop limit
is retained with verified parent IDs; it is NOT the root progress watchdog.
"""
from .contracts import canonical_bytes, create, fingerprint, intent_payload
from .identity import Denied, exact, identifier, integer


HOP_LIMIT = 3


def message_id(session_id, intent_id):
    identifier(session_id)
    identifier(intent_id)
    return "message-" + fingerprint({"session": session_id, "intent": intent_id})[7:]


def summary(current):
    record = current["record"]
    data = record.to_dict()
    return {"id": record.id, "state": "held" if current["hold_reason"] is not None else data["state"],
            "reason": current["hold_reason"], "root_task": data["root_task_id"],
            "from": data["from_session_id"], "to": data["to_session_id"], "text": data["body"],
            "mode": data["mode"], "expected_turn_id": data["expected_turn_id"],
            "hop": current["context"]["hop"], "reply_to": current["context"]["reply_to"],
            "attempt_id": data["attempt_id"], "receipt_id": data["receipt_id"],
            "meaning": "persistent_intent_not_queued_model_input" if data["state"] == "stored" else
                       "input_accepted_not_task_completed" if data["state"] == "confirmed" else
                       "delivery_outcome_not_task_progress"}


class BrokerMessages:
    def __init__(self, authority, ledger):
        if authority.policy.digest != ledger.policy_digest:
            raise Denied("message outbox and broker policy differ")
        self.authority, self.ledger = authority, ledger

    def dispatch(self, actor, method, args):
        if actor.policy_digest != self.authority.policy.digest:
            raise Denied("stale message actor policy")
        if method == "send_message":
            return self.send(actor, args)
        if method == "message_status":
            exact(args, {"id"})
            return {"ok": True, "message": summary(self._visible(actor, args["id"]))}
        if method == "message_log":
            if type(args) is not dict or set(args) - {"limit", "before_id"}:
                raise Denied("bounded message log arguments required")
            limit = args.get("limit", 20)
            integer(limit)
            candidates = self.ledger.messages_for(actor.session_id, limit, before_id=args.get("before_id"))
            messages, size = [], 1000
            for row in candidates:
                item = summary(self._context(row))
                item_size = len(canonical_bytes(item)) + 1
                if size + item_size > 48000:
                    break
                messages.append(item)
                size += item_size
            # Cursor pagination, not truncated message bodies. A full page may
            # lead to one empty final page; no participant's content is dropped.
            has_more = len(messages) < len(candidates) or len(candidates) == limit
            return {"ok": True, "messages": messages,
                    "next_before_id": messages[-1]["id"] if messages and has_more else None}
        raise Denied("unsupported message operation")

    def _visible(self, actor, mid):
        current = self.ledger.load(mid)
        if current is None or current["record"].kind != "message" or actor.session_id not in {
                current["record"].fields["from_session_id"], current["record"].fields["to_session_id"]}:
            raise Denied("message is not visible to this session")
        return self._context(current)

    def _context(self, current):
        context = current["context"]
        exact(context, {"schema", "policy_digest", "from_role_id", "from_execution_id", "reply_to", "hop"})
        if context["schema"] != "ccrelay.broker_message_context.v1" or context["policy_digest"] != self.authority.policy.digest:
            raise Denied("unsupported message provenance")
        for key in ("from_role_id", "from_execution_id"):
            identifier(context[key])
        if context["reply_to"] is not None:
            identifier(context["reply_to"])
        integer(context["hop"])
        if context["hop"] > HOP_LIMIT:
            raise Denied("invalid message hop evidence")
        return current

    def send(self, actor, args):
        exact(args, {"intent_id", "to", "text", "reply_to", "mode", "expected_turn_id"})
        mid = message_id(actor.session_id, args["intent_id"])
        identifier(args["to"])
        if args["to"] == actor.session_id or type(args["text"]) is not str or not args["text"] or \
                len(args["text"].encode("utf-8")) > 16000 or len(canonical_bytes(args["text"])) > 24000 or \
                type(args["mode"]) is not str or args["mode"] not in {"steer", "start"}:
            raise Denied("valid peer, bounded message and explicit steer/start mode required")
        fields = {"id": mid, "root_task_id": actor.root_task_id, "from_session_id": actor.session_id,
                  "to_session_id": args["to"], "body": args["text"], "mode": args["mode"],
                  "expected_turn_id": args["expected_turn_id"]}
        record = create("message", id=fields.pop("id"), **fields,
                        intent_digest=fingerprint(intent_payload("message", {**fields, "id": mid})),
                        state="stored", attempt_id=None, receipt_id=None, outcome_evidence_id=None)
        if args["reply_to"] is not None:
            identifier(args["reply_to"])
        old = self.ledger.load(mid)
        if old is not None:
            self._context(old)
            if intent_payload("message", old["record"].fields) != intent_payload("message", record.fields) or \
                    old["context"]["reply_to"] != args["reply_to"]:
                raise Denied("stable message intent reused for changed parameters")
            return {"ok": True, "replayed": True, "message": summary(old)}
        target = self.authority.registry.session(args["to"])
        role = None if target is None else self.authority.policy.roles.get(target["role_id"])
        if target is None or target["revoked"] or target["policy_digest"] != actor.policy_digest or \
                role is None or not role.fields["enabled"]:
            raise Denied("target is not a current registered role session")
        hop = 1
        if args["reply_to"] is not None:
            parent = self._visible(actor, args["reply_to"])
            parent_record = parent["record"]
            if parent_record.fields["to_session_id"] != actor.session_id or parent_record.fields["state"] != "confirmed" or \
                    parent_record.fields["root_task_id"] != actor.root_task_id:
                raise Denied("reply requires confirmed inbound message and admitted inherited root")
            hop = parent["context"]["hop"] + 1
            if hop > HOP_LIMIT:
                raise Denied("three-hop message limit reached; request owner intervention")
        context = {"schema": "ccrelay.broker_message_context.v1", "policy_digest": actor.policy_digest,
                   "from_role_id": actor.role_id, "from_execution_id": actor.execution_id,
                   "reply_to": args["reply_to"], "hop": hop}
        current = self.ledger.store(record, context)
        # PR 7/9 have not yet supplied trusted runtime readiness/admission.
        # Enrollment is useful and durable, but never reported as delivery.
        current = self.ledger.hold(mid, "runtime_delivery_gate_pending")
        return {"ok": True, "replayed": False, "message": summary(current)}
