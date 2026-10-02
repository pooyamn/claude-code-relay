"""Pure, pre-enrolled render alternatives; no error-text guessing or I/O.

The protected runtime must characterize a definite format/media rejection and
authorize its exact recipe. Recipes cannot change routes, buttons or file bytes,
and plain alternatives retain the original Markdown rather than stripping links
from rendered HTML. One alternative per original operation bounds repair.
"""
import copy
import relay_tg

from .identity import Denied, exact
from .contracts import canonical_bytes


KINDS = {"html_to_plain": "sendMessage", "edit_html_to_plain": "editMessageText",
         "rich_to_plain": "sendRichMessage", "photo_to_document": "sendPhoto"}


def plain_pieces(text, limit=4096):
    """Bound Telegram text in UTF-16 units without dropping any source character."""
    if type(text) is not str or not text:
        raise Denied("nonempty retained source text required")
    pieces, buffer, size = [], [], 0
    for character in text:
        units = 2 if ord(character) > 0xffff else 1
        if size + units > limit:
            pieces.append("".join(buffer))
            buffer, size = [], 0
        buffer.append(character)
        size += units
    if buffer:
        pieces.append("".join(buffer))
    return pieces


def recipe(operation, *, kind, content=None, parts=None):
    if type(kind) is not str or kind not in KINDS or operation["method"] != KINDS[kind]:
        raise Denied("known alternative for the exact original method required")
    args, assets = copy.deepcopy(operation["args"]), copy.deepcopy(operation["assets"])
    method = operation["method"]
    if kind == "photo_to_document":
        if content is not None or parts is not None or set(assets) != {"photo"} or args.get("photo") != "attach://photo" or \
                set(args) - {"chat_id", "message_thread_id", "photo", "disable_notification", "protect_content", "reply_parameters", "reply_markup"}:
            raise Denied("photo alternative requires the exact uncaptained immutable upload")
        args.pop("photo")
        args["document"] = "attach://document"
        operations = [{"method": "sendDocument", "args": args, "assets": {"document": assets["photo"]}}]
    else:
        if assets or type(content) is not str or not content:
            raise Denied("retained text and no media assets required for text repair")
        if kind == "rich_to_plain":
            if type(parts) is not list or not parts or any(type(part) is not list or len(part) != 2 or
                    type(part[0]) is not str or part[0] not in {"table", "text"} or type(part[1]) is not str for part in parts):
                raise Denied("retained rich parts required")
            rendered = "".join(relay_tg._rich_table_html(text) if tag == "table" else relay_tg._rich_text_html(text) for tag, text in parts)
            if args.get("rich_message") != {"html": rendered} or content != "\n\n".join(text for _, text in parts):
                raise Denied("rich original and exact plain source disagree")
            args.pop("rich_message")
            method = "sendMessage"
        else:
            if parts is not None or args.get("parse_mode") != "HTML" or args.get("text") != relay_tg.md_to_html(content) or "entities" in args:
                raise Denied("original HTML is not the rendering of retained Markdown")
            args.pop("text")
            args.pop("parse_mode")
        pieces = plain_pieces(content)
        if kind == "edit_html_to_plain" and len(pieces) != 1:
            raise Denied("an edit alternative cannot overwrite itself with several chunks")
        operations = []
        for index, piece in enumerate(pieces):
            parameters = {**args, "text": piece}
            if index != len(pieces) - 1:
                parameters.pop("reply_markup", None)
            operations.append({"method": method, "args": parameters, "assets": {}})
    value = {"schema": "ccrelay.telegram_repair_recipe.v1", "kind": kind, "content": content, "parts": parts,
             "operations": operations}
    canonical_bytes(value)
    return value


def validate_recipe(value, original):
    exact(value, {"schema", "kind", "content", "parts", "operations"})
    if value["schema"] != "ccrelay.telegram_repair_recipe.v1" or value != recipe(original, kind=value["kind"], content=value["content"], parts=value["parts"]):
        raise Denied("alternative changed original content, assets or delivery controls")
    return value
