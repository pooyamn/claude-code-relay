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
from .telegram_repair import recipe


class _Capture:
    def __init__(self):
        self.operations = []

    def call(self, method, args):
        self.operations.append({"method": method, "args": args, "assets": {}})
        # A formatting-only placeholder. It NEVER leaves this private planner
        # and cannot authorize completion or supply an owner approval prompt ID.
        return {"message_id": len(self.operations)}


def text_operations(text, chat_id, thread_id, *, silent=False, reply_markup=None):
    return text_plan(text, chat_id, thread_id, silent=silent, reply_markup=reply_markup)[0]


def text_plan(text, chat_id, thread_id, *, silent=False, reply_markup=None):
    if type(text) is not str or not text.strip():
        raise Denied("nonempty original text required")
    operations, recipes = [], []
    common = {"chat_id": chat_id, **relay_tg.thread_params(thread_id)}
    if silent:
        common["disable_notification"] = True
    def classic(markdown, markup=None):
        pieces = relay_tg._split_for_html(markdown)
        for index, piece in enumerate(pieces):
            args = {**common, "link_preview_options": {"is_disabled": True}, "text": relay_tg.md_to_html(piece), "parse_mode": "HTML"}
            if markup and index == len(pieces) - 1:
                args["reply_markup"] = markup
            operation = {"method": "sendMessage", "args": args, "assets": {}}
            operations.append(operation)
            recipes.append(recipe(operation, kind="html_to_plain", content=piece))
    segments = relay_tg.segments(text)
    if not any(kind == "table" for kind, _ in segments) or reply_markup:
        classic(text, reply_markup)
    else:
        group = []
        def flush():
            if any(kind == "table" for kind, _ in group):
                for fitted in relay_tg._fit_rich(group):
                    collector = _Capture()
                    relay_tg.send_rich(collector, chat_id, thread_id, fitted, silent)
                    operation = collector.operations[0]
                    operations.append(operation)
                    recipes.append(recipe(operation, kind="rich_to_plain", content="\n\n".join(value for _, value in fitted),
                                          parts=[[kind, value] for kind, value in fitted]))
            elif group:
                classic("\n\n".join(value for _, value in group))
            group.clear()
        for kind, value in segments:
            if kind == "code":
                flush()
                classic(value)
            else:
                group.append((kind, value))
        flush()
    return operations, recipes


def bundle(*, bundle_id, root_task_id, session_id, chat_id, thread_id, lane, content, operations,
           source_kind, native_session_id=None, turn_id=None, submission_id=None, cursor=None, coalesce_key=None, repair_plans=None):
    return {"schema": "ccrelay.telegram_bundle.v2", "id": bundle_id, "root_task_id": root_task_id,
            "session_id": session_id, "chat_id": chat_id, "thread_id": thread_id, "lane": lane,
            "source": {"native_session_id": native_session_id, "turn_id": turn_id, "submission_id": submission_id,
                       "source_kind": source_kind, "content": content, "content_digest": fingerprint(content)},
            "operations": operations, "cursor": cursor, "coalesce_key": coalesce_key,
            "repair_plans": [None] * len(operations) if repair_plans is None else repair_plans}


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
        operations, recipes = text_plan(content, binding["chat_id"], binding["thread_id"], silent=silent, reply_markup=reply_markup)
        return self.enqueue(bundle(content=content, operations=operations, repair_plans=recipes, **binding))

    def media(self, *, method, reference, caption="", silent=False, **binding):
        if method not in MEDIA_FIELDS or type(caption) is not str:
            raise Denied("supported explicit media method and retained caption required")
        field = MEDIA_FIELDS[method]
        args = {"chat_id": binding["chat_id"], **relay_tg.thread_params(binding["thread_id"]), field: "attach://" + field}
        if silent:
            args["disable_notification"] = True
        operations = [{"method": method, "args": args, "assets": {field: reference}}]
        recipes = [recipe(operations[0], kind="photo_to_document") if method == "sendPhoto" else None]
        # Never slice a required caption at 1024 bytes, or fit_tail a final reply.
        # Use full ordered text chunks after the retained original attachment.
        if caption.strip():
            chunks, alternatives = text_plan(caption, binding["chat_id"], binding["thread_id"], silent=silent)
            operations += chunks
            recipes += alternatives
        return self.enqueue(bundle(content={"asset": reference, "caption": caption}, operations=operations, repair_plans=recipes, **binding))

    def status_edit(self, *, content, message_id, coalesce_key, **binding):
        integer(message_id)
        if binding["lane"] != "status":
            raise Denied("tail-trimming is limited to disposable status")
        fitted = relay_tg.fit_tail(content)
        operation = {"method": "editMessageText", "args": {"chat_id": binding["chat_id"], "message_id": message_id,
                     "text": relay_tg.md_to_html(fitted), "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}}, "assets": {}}
        alternative = recipe(operation, kind="edit_html_to_plain", content=fitted)
        return self.enqueue(bundle(content=content, operations=[operation], repair_plans=[alternative], coalesce_key=coalesce_key, **binding))
