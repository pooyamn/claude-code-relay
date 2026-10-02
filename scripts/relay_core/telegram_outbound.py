"""Protected Telegram send primitives. No key discovery or hidden retries.

The scheduler is the sole effect owner; this transport performs one fixed-host
request. Its token is explicit and remains out of exception text. Uploads use
private content-addressed bytes, never worker-supplied host paths or URLs.
"""
from dataclasses import dataclass
import hashlib
import os
import re
import urllib.error
import urllib.request
import uuid

from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, integer, protected_path
from .intake import provider_json
from .outbox import fsync_directory
from .polling import NoRedirect, PollError, PollerLock


SEND_METHODS = frozenset({"sendMessage", "sendRichMessage", "sendDocument", "sendPhoto", "sendVoice",
                          "sendAudio", "sendVideo", "sendAnimation", "sendVideoNote", "sendSticker", "sendMediaGroup"})
EDIT_METHODS = frozenset({"editMessageText", "editMessageCaption", "editMessageReplyMarkup"})
METHODS = SEND_METHODS | EDIT_METHODS | {"deleteMessage", "answerCallbackQuery", "sendChatAction"}
LANES = {"approval": 0, "alert": 0, "callback": 0, "reply": 10, "bus": 30, "status": 40}
MEDIA_FIELDS = {"sendDocument": "document", "sendPhoto": "photo", "sendVoice": "voice", "sendAudio": "audio",
                "sendVideo": "video", "sendAnimation": "animation", "sendVideoNote": "video_note", "sendSticker": "sticker"}
COMMON = {"chat_id", "message_thread_id", "disable_notification", "protect_content", "reply_parameters", "reply_markup"}
CAPTION = {"caption", "parse_mode", "caption_entities", "show_caption_above_media", "has_spoiler"}
ARGUMENTS = {
    "sendMessage": COMMON | {"text", "parse_mode", "entities", "link_preview_options"},
    "sendRichMessage": COMMON | {"rich_message"},
    "sendMediaGroup": COMMON - {"reply_markup"} | {"media"},
    "editMessageText": {"chat_id", "message_id", "text", "parse_mode", "entities", "link_preview_options", "reply_markup"},
    "editMessageCaption": {"chat_id", "message_id", "caption", "parse_mode", "caption_entities", "show_caption_above_media", "reply_markup"},
    "editMessageReplyMarkup": {"chat_id", "message_id", "reply_markup"},
    "deleteMessage": {"chat_id", "message_id"},
    "answerCallbackQuery": {"callback_query_id", "text", "show_alert", "cache_time"},
    "sendChatAction": {"chat_id", "message_thread_id", "action"},
}
for _method, _field in MEDIA_FIELDS.items():
    ARGUMENTS[_method] = COMMON | CAPTION | {_field, "thumbnail", "duration", "width", "height", "length", "title", "performer", "supports_streaming", "disable_content_type_detection"}


class OutboundPolicy:
    def __init__(self, raw):
        exact(raw, {"schema", "bot_id", "bot_username", "test_bot", "allowed_chats", "global_spacing_ms",
                    "chat_spacing_ms", "group_spacing_ms", "max_rate_limit_retries", "max_upload_bytes",
                    "compatibility_digest", "retryable_methods", "repairable_methods"})
        if raw["schema"] != "ccrelay.telegram_outbound_policy.v2" or raw["test_bot"] != "khadang":
            raise Denied("only explicit Khadang preparation is supported")
        for key in ("bot_id", "global_spacing_ms", "chat_spacing_ms", "group_spacing_ms", "max_upload_bytes"):
            integer(raw[key])
        integer(raw["max_rate_limit_retries"], 0)
        if raw["max_rate_limit_retries"] > 50 or raw["max_upload_bytes"] > 50 * 1024 * 1024 or \
                type(raw["bot_username"]) is not str or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", raw["bot_username"]):
            raise Denied("bounded retry/upload policy and pinned bot username required")
        chats = raw["allowed_chats"]
        if type(chats) is not list or not chats or any(type(chat) is not int or chat == 0 for chat in chats) or len(set(chats)) != len(chats):
            raise Denied("nonempty unique exact chat allowlist required")
        digest = raw["compatibility_digest"]
        if type(digest) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise Denied("reviewed Telegram adapter compatibility digest required")
        methods = raw["retryable_methods"]
        if type(methods) is not list or any(type(method) is not str or method not in METHODS for method in methods) or len(set(methods)) != len(methods):
            raise Denied("explicit characterized rate-limit rejection capabilities required")
        repairs = raw["repairable_methods"]
        if type(repairs) is not list or any(type(method) is not str or method not in {"sendMessage", "sendRichMessage", "sendPhoto", "editMessageText"} for method in repairs) or len(set(repairs)) != len(repairs):
            raise Denied("explicit characterized format/media repair capabilities required")
        self._raw = canonical_bytes(raw)
        self._digest = fingerprint(raw)

    @property
    def raw(self):
        return provider_json(self._raw)  # mutable caller copy cannot change pinned policy

    @property
    def digest(self):
        return self._digest

    @property
    def bot_id(self):
        return self.raw["bot_id"]

    def operation(self, operation, chat_id):
        exact(operation, {"method", "args", "assets"})
        if type(operation["method"]) is not str or operation["method"] not in METHODS or \
                type(operation["args"]) is not dict or type(operation["assets"]) is not dict:
            raise Denied("explicit supported send/edit/media/callback operation required")
        args, method = operation["args"], operation["method"]
        if set(args) - ARGUMENTS[method]:
            raise Denied("parameters outside pinned outbound capability")
        if chat_id not in self.raw["allowed_chats"] or type(chat_id) is not int or chat_id == 0:
            raise Denied("outbound destination is not allowed")
        # Forbid paid sends and remote file/path discovery even when a provider
        # would accept the parameters. Chat/topic changes require a new intent.
        if any(key in args for key in ("allow_paid_broadcast", "business_connection_id", "inline_message_id")):
            raise Denied("paid or unverified alternate delivery topology denied")
        if method == "answerCallbackQuery":
            if type(args.get("callback_query_id")) is not str or not args["callback_query_id"] or "chat_id" in args:
                raise Denied("bound callback query required")
        elif type(args.get("chat_id")) is not int or args["chat_id"] != chat_id:
            raise Denied("exact chat destination required")
        if "message_thread_id" in args:
            integer(args["message_thread_id"])
            if args["message_thread_id"] == 1:
                raise Denied("general topic uses an omitted thread field")
        if method in EDIT_METHODS | {"deleteMessage"}:
            integer(args.get("message_id"))
        for name, reference in operation["assets"].items():
            if type(name) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", name):
                raise Denied("safe multipart field required")
            validate_asset(reference)
        used = set()
        def check(value):
            if type(value) is not str or not value:
                raise Denied("explicit file ID or private attachment reference required")
            if value.startswith("attach://"):
                name = value[9:]
                if name not in operation["assets"]:
                    raise Denied("attachment reference has no immutable asset")
                used.add(name)
            elif not re.fullmatch(r"[A-Za-z0-9_-]+", value):
                raise Denied("media must be a pinned file ID or private upload, not URL/host path")
        if method in MEDIA_FIELDS and MEDIA_FIELDS[method] not in args:
            raise Denied("required media field missing")
        for field in ("document", "photo", "voice", "audio", "video", "animation", "video_note", "sticker", "thumbnail"):
            if field in args:
                check(args[field])
        if method == "sendMediaGroup":
            media = args.get("media")
            if type(media) is not list or not 2 <= len(media) <= 10:
                raise Denied("media group requires two through ten exact items")
            for item in media:
                if type(item) is not dict or type(item.get("media")) is not str:
                    raise Denied("media group item required")
                if set(item) - ({"type", "media", "thumbnail", "duration", "width", "height", "title", "performer", "supports_streaming"} | CAPTION) or \
                        type(item.get("type")) is not str or item["type"] not in {"photo", "video", "document", "audio"}:
                    raise Denied("unsupported media group capability")
                check(item["media"])
                if "thumbnail" in item:
                    check(item["thumbnail"])
        if used != set(operation["assets"]) or len(used) > 10 or \
                sum(ref["size_bytes"] for ref in operation["assets"].values()) > self.raw["max_upload_bytes"]:
            raise Denied("unused attachments or total upload budget exceeded")
        if method in {"sendMessage", "editMessageText"} and (type(args.get("text")) is not str or not args["text"]):
            raise Denied("nonempty message text required")
        if method == "sendRichMessage":
            exact(args.get("rich_message"), {"html"})
            if type(args["rich_message"]["html"]) is not str or not args["rich_message"]["html"]:
                raise Denied("pinned rich HTML required")
        if len(canonical_bytes(operation)) > 48000:
            raise Denied("operation exceeds protected intent frame size")
        return operation


def validate_asset(reference):
    exact(reference, {"digest", "size_bytes", "filename", "mime_type"})
    if type(reference["digest"]) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", reference["digest"]):
        raise Denied("content-addressed asset digest required")
    integer(reference["size_bytes"], 0)
    name = reference["filename"]
    if type(name) is not str or not name or len(name.encode("utf-8")) > 240 or any(c in name for c in '\r\n"\\/') or \
            any(ord(c) < 32 for c in name) or name in {".", ".."}:
        raise Denied("safe retained upload filename required")
    if type(reference["mime_type"]) is not str or not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", reference["mime_type"]):
        raise Denied("explicit safe MIME type required")
    return reference


class AssetStore:
    def __init__(self, directory, *, owner_uid, max_bytes):
        if os.geteuid() != integer(owner_uid):
            raise Denied("asset store requires protected owner UID")
        self.folder = protected_path(directory, owners={0, owner_uid}, directory=True, private=True)
        if self.folder.lstat().st_uid != owner_uid:
            raise Denied("asset directory has wrong owner")
        self.owner_uid, self.max_bytes = owner_uid, integer(max_bytes)

    def stage(self, data, *, filename, mime_type):
        if type(data) is not bytes or len(data) > self.max_bytes:
            raise Denied("bounded upload bytes required")
        reference = validate_asset({"digest": "sha256:" + hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
                                    "filename": filename, "mime_type": mime_type})
        path = self.folder / (reference["digest"][7:] + ".blob")
        if not path.exists() and not path.is_symlink():
            temporary = self.folder / (uuid.uuid4().hex + ".pending")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                os.fchmod(handle.fileno(), 0o400)
                os.fsync(handle.fileno())
            # Protected directory + serialized scheduler ownership; never stage
            # bytes from arbitrary caller paths. Interrupted temporaries remain.
            os.replace(temporary, path)
            fsync_directory(self.folder)
        self.read(reference)
        return reference

    def read(self, reference):
        validate_asset(reference)
        path = self.folder / (reference["digest"][7:] + ".blob")
        protected_path(path, owners={self.owner_uid}, private=True)
        metadata = path.lstat()
        if metadata.st_nlink != 1 or metadata.st_size != reference["size_bytes"] or metadata.st_size > self.max_bytes or metadata.st_mode & 0o222:
            raise Denied("upload asset ownership, links, size or sealed mode changed")
        with path.open("rb") as handle:
            data = handle.read(self.max_bytes + 1)
        if "sha256:" + hashlib.sha256(data).hexdigest() != reference["digest"]:
            raise Denied("upload asset bytes changed")
        return data


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes

    def __post_init__(self):
        integer(self.status)
        if self.status > 599 or type(self.body) is not bytes or len(self.body) > 8 * 1024 * 1024:
            raise Denied("bounded HTTP response required")


class SendOwnership(PollerLock):
    """Reuse the kernel generation/flock guard in a SEPARATE send registry.

    This does not poll, take over an existing poller or fence another machine.
    Target wiring must pin one host-wide registry, distinct from ingress locks,
    and retire every competing legacy sender before enabling this owner.
    """


class SingleAttemptBot:
    def __init__(self, token, *, timeout_seconds=30, opener=None):
        if type(token) is not str or not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            raise Denied("explicit protected bot token required")
        integer(timeout_seconds)
        if timeout_seconds > 60:
            raise Denied("bounded single-request timeout required")
        self.base = "https://api.telegram.org/bot" + token + "/"
        self.timeout = timeout_seconds
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def request(self, method, args, assets, store):
        if method != "getMe" and method not in METHODS:
            raise Denied("method outside outbound adapter capability")
        if type(args) is not dict or type(assets) is not dict or (method == "getMe" and (args or assets)) or \
                (method != "getMe" and set(args) - ARGUMENTS[method]):
            raise Denied("parameters outside single-attempt adapter capability")
        if len(assets) > 10 or any(type(name) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", name) for name in assets):
            raise Denied("bounded safe multipart fields required")
        for reference in assets.values():
            validate_asset(reference)
        if assets and (store is None or sum(ref["size_bytes"] for ref in assets.values()) > store.max_bytes):
            raise Denied("total immutable upload budget exceeded")
        if assets:
            boundary = uuid.uuid4().hex
            parts = []
            for key, value in args.items():
                if type(key) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
                    raise Denied("safe multipart parameter name required")
                value = canonical_bytes(value).decode() if type(value) in {dict, list, bool} else str(value)
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'.encode() + value.encode() + b"\r\n")
            for key, reference in assets.items():
                data = store.read(reference)
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{reference["filename"]}"\r\nContent-Type: {reference["mime_type"]}\r\n\r\n'.encode()
                             + data + b"\r\n")
            body = b"".join(parts) + f"--{boundary}--\r\n".encode()
            content_type = "multipart/form-data; boundary=" + boundary
        else:
            body, content_type = canonical_bytes(args), "application/json"
        request = urllib.request.Request(self.base + method, body, {"Content-Type": content_type})
        try:
            with self.opener.open(request, timeout=self.timeout) as result:
                raw = result.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise Denied("oversized outbound response")
                return Response(result.status, raw)
        except urllib.error.HTTPError as error:
            raw = error.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise Denied("oversized outbound error") from None
            return Response(error.code, raw)
        except (OSError, ValueError, urllib.error.URLError, PollError):
            raise Denied("outbound request outcome unknown; inspect durable attempt") from None


def verify_bot(response, policy):
    body = provider_json(response.body)
    result = body.get("result") if type(body) is dict else None
    if response.status != 200 or type(body) is not dict or body.get("ok") is not True or type(result) is not dict or \
            type(result.get("id")) is not int or result["id"] != policy.bot_id or result.get("is_bot") is not True or \
            result.get("username") != policy.raw["bot_username"]:
        raise Denied("outbound bot identity mismatch")


def receipt(response, operation, policy, chat_id):
    """Validate exact supported outcome; unknown/5xx/network is never retried."""
    body = provider_json(response.body)
    if type(body) is not dict or type(body.get("ok")) is not bool:
        raise Denied("unrecognized Telegram response")
    if body["ok"] is False:
        code = body.get("error_code")
        if type(code) is not int or response.status not in {200, code} or code not in {400, 401, 403, 404, 429}:
            raise Denied("response does not establish a definite rejection")
        retry = (body.get("parameters") or {}).get("retry_after", 0) if type(body.get("parameters") or {}) is dict else 0
        integer(retry, 0)
        if code == 429 and (retry <= 0 or retry > 2147483647):
            raise Denied("rate limit lacks a valid provider retry hint")
        if type(body.get("parameters")) is dict and "migrate_to_chat_id" in body["parameters"]:
            raise Denied("destination migration requires explicit reauthorization")
        return {"outcome": "rejected", "code": code, "retry_after": retry, "message_ids": []}
    if response.status != 200 or "result" not in body:
        raise Denied("inconsistent successful Telegram response")
    method, args = operation["method"], operation["args"]
    result = body["result"]
    if method in {"answerCallbackQuery", "deleteMessage", "sendChatAction"}:
        if result is not True:
            raise Denied("unsupported boolean acknowledgment")
        return {"outcome": "accepted", "code": 200, "retry_after": 0, "message_ids": []}
    results = result if method == "sendMediaGroup" else [result]
    if type(results) is not list or not results or (method == "sendMediaGroup" and len(results) != len(args["media"])):
        raise Denied("media group receipt count mismatch")
    ids = []
    for message in results:
        if type(message) is not dict or type(message.get("chat")) is not dict or \
                type(message["chat"].get("id")) is not int or message["chat"]["id"] != chat_id or \
                type(message.get("from")) is not dict or message["from"].get("is_bot") is not True or \
                type(message["from"].get("id")) is not int or message["from"]["id"] != policy.bot_id:
            raise Denied("receipt belongs to another bot/chat")
        integer(message.get("message_id"))
        if method in EDIT_METHODS and message["message_id"] != args["message_id"]:
            raise Denied("edit receipt belongs to another message")
        if "message_thread_id" in message:
            integer(message["message_thread_id"])
        if method in SEND_METHODS and message.get("message_thread_id") not in \
                ({None, 1} if "message_thread_id" not in args else {args["message_thread_id"]}):
            raise Denied("receipt belongs to another topic")
        ids.append(message["message_id"])
    if len(set(ids)) != len(ids):
        raise Denied("duplicate message IDs in receipt")
    return {"outcome": "accepted", "code": 200, "retry_after": 0, "message_ids": ids}
