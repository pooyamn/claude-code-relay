"""Common protected producer gateway; planning does not perform Telegram I/O.

Reuse existing rich-table/code formatting, but never its retrying transports or
last-message-ID-as-success convention. Producers receive a durable bundle ticket;
only the scheduler's complete receipt set can advance a registered reply cursor.
Live watchers/bus/owner UI must be cut over together after their trusted bridges
and exclusive Khadang acceptance. This module does not rewire them itself.
"""
import relay_tg

from .contracts import fingerprint
from .identity import Denied, integer
from .telegram_outbound import MEDIA_FIELDS


class _Capture:
    def __init__(self):
        self.operations = []

    def call(self, method, args):
        self.operations.append({"method": method, "args": args, "assets": {}})
        # A formatting-only placeholder. It NEVER leaves this private planner
        # and cannot authorize completion or supply an owner approval prompt ID.
        return {"message_id": len(self.operations)}


def text_operations(text, chat_id, thread_id, *, silent=False, reply_markup=None):
    if type(text) is not str or not text.strip():
        raise Denied("nonempty original text required")
    collector = _Capture()
    relay_tg.send_text(collector, chat_id, thread_id, text, silent, reply_markup)
    return collector.operations


def bundle(*, bundle_id, root_task_id, session_id, chat_id, thread_id, lane, content, operations,
           source_kind, native_session_id=None, turn_id=None, submission_id=None, cursor=None, coalesce_key=None):
    return {"schema": "ccrelay.telegram_bundle.v1", "id": bundle_id, "root_task_id": root_task_id,
            "session_id": session_id, "chat_id": chat_id, "thread_id": thread_id, "lane": lane,
            "source": {"native_session_id": native_session_id, "turn_id": turn_id, "submission_id": submission_id,
                       "source_kind": source_kind, "content": content, "content_digest": fingerprint(content)},
            "operations": operations, "cursor": cursor, "coalesce_key": coalesce_key}


class TelegramProducers:
    def __init__(self, ledger, *, authorize_source):
        if not callable(authorize_source):
            raise Denied("protected source/root/route authorization required")
        self.ledger, self.authorize_source = ledger, authorize_source

    def enqueue(self, value):
        self.ledger.validate_bundle(value)
        # Source IDs are attribution, not authentication. The bridge must bind
        # them to kernel-authenticated/admitted sessions and fixed owner routes.
        if self.authorize_source(value) is not True:
            raise Denied("outbound source/route authorization denied")
        return self.ledger.enqueue(value)

    def text(self, *, content, silent=False, reply_markup=None, **binding):
        operations = text_operations(content, binding["chat_id"], binding["thread_id"],
                                     silent=silent, reply_markup=reply_markup)
        return self.enqueue(bundle(content=content, operations=operations, **binding))

    def media(self, *, method, reference, caption="", silent=False, **binding):
        if method not in MEDIA_FIELDS or type(caption) is not str:
            raise Denied("supported explicit media method and retained caption required")
        field = MEDIA_FIELDS[method]
        args = {"chat_id": binding["chat_id"], **relay_tg.thread_params(binding["thread_id"]), field: "attach://" + field}
        if silent:
            args["disable_notification"] = True
        operations = [{"method": method, "args": args, "assets": {field: reference}}]
        # Never slice a required caption at 1024 bytes, or fit_tail a final reply.
        # Use full ordered text chunks after the retained original attachment.
        if caption.strip():
            operations += text_operations(caption, binding["chat_id"], binding["thread_id"], silent=silent)
        return self.enqueue(bundle(content={"asset": reference, "caption": caption}, operations=operations, **binding))

    def status_edit(self, *, content, message_id, coalesce_key, **binding):
        integer(message_id)
        if binding["lane"] != "status":
            raise Denied("tail-trimming is limited to disposable status")
        fitted = relay_tg.fit_tail(content)
        operation = {"method": "editMessageText", "args": {"chat_id": binding["chat_id"], "message_id": message_id,
                     "text": relay_tg.md_to_html(fitted), "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}}, "assets": {}}
        return self.enqueue(bundle(content=content, operations=[operation], coalesce_key=coalesce_key, **binding))
