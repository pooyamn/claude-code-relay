"""Direct Telegram Bot API transport for the relay (no OpenClaw).

Replaces every `openclaw message send/edit/delete` the relay used. Stdlib only.

Formatting: the relay writes Markdown. It goes out as classic `sendMessage` with
parse_mode=HTML, converted here. Not rich messages: on the user's client a rich
message silently DROPS a code block (measured 2026-09-22 and again 2026-09-28,
topic 1876 -- Telegram stored the `pre` block, the client did not draw it), and
the relay ships every table as a code block so it scrolls sideways. Classic HTML
<pre> renders. If Telegram rejects the HTML (bad nesting), the same text is sent
plain rather than lost.

Token: read from the env file named by a session's transport record, never from
argv (argv is visible to every process on the machine).
"""
import html
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request
import uuid

TG_LIMIT = 4096


def load_token(env_path):
    with open(os.path.expanduser(env_path)) as f:
        for line in f:
            k, _, v = line.strip().partition("=")
            if k == "CCRELAY_BOT_TOKEN" and v:
                return v.strip()
    raise RuntimeError(f"no CCRELAY_BOT_TOKEN in {env_path}")


class TGError(Exception):
    def __init__(self, desc, code=0, retry_after=0):
        super().__init__(desc)
        self.desc, self.code, self.retry_after = desc, code, retry_after


class Bot:
    def __init__(self, token, timeout=70):
        self.token, self.timeout = token, timeout
        self.base = f"https://api.telegram.org/bot{token}/"

    # --- raw calls ------------------------------------------------------------
    def _decode(self, raw):
        d = json.loads(raw)
        if not d.get("ok"):
            p = d.get("parameters") or {}
            raise TGError(d.get("description", "error"), d.get("error_code", 0),
                          p.get("retry_after", 0))
        return d["result"]

    def call(self, method, params=None, timeout=None, max_wait=30):
        """JSON call. A 429 is honoured (sleep retry_after, try again) up to
        max_wait seconds in total -- Telegram tells us exactly how long, so this
        is the rate limit doing its job, not a blind retry."""
        body = json.dumps(params or {}).encode()
        waited = 0
        while True:
            req = urllib.request.Request(self.base + method, body,
                                         {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                    return self._decode(r.read())
            except urllib.error.HTTPError as e:
                try:
                    self._decode(e.read())
                except TGError as te:
                    if te.code == 429 and te.retry_after and waited + te.retry_after <= max_wait:
                        time.sleep(te.retry_after)
                        waited += te.retry_after
                        continue
                    raise
                raise TGError(f"HTTP {e.code}", e.code)

    def upload(self, method, fields, file_field, path, max_wait=60):
        """multipart/form-data upload of one local file."""
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in fields.items():
            if v is None:
                continue
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"'
                         f'\r\n\r\n{v}\r\n'.encode())
        name = os.path.basename(path)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}";'
                     f' filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
                     + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        waited = 0
        while True:
            req = urllib.request.Request(self.base + method, body,
                                         {"Content-Type": f"multipart/form-data; boundary={boundary}"})
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    return self._decode(r.read())
            except urllib.error.HTTPError as e:
                try:
                    self._decode(e.read())
                except TGError as te:
                    if te.code == 429 and te.retry_after and waited + te.retry_after <= max_wait:
                        time.sleep(te.retry_after)
                        waited += te.retry_after
                        continue
                    raise
                raise TGError(f"HTTP {e.code}", e.code)

    def download(self, file_id, dest_dir):
        info = self.call("getFile", {"file_id": file_id})
        fp = info["file_path"]
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(fp))
        url = f"https://api.telegram.org/file/bot{self.token}/{fp}"
        with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                f.write(b)
        return dest


def thread_params(thread):
    """General topic (id 1) takes NO message_thread_id -- Telegram rejects
    sending to thread 1 ("message thread not found")."""
    t = str(thread or "")
    return {"message_thread_id": int(t)} if t and t != "1" else {}


# --- Markdown -> Telegram HTML ---------------------------------------------------
_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)


def _inline(s):
    """Inline markdown on ONE escaped line: code spans first (their content is
    literal), then links, bold, italic, strike."""
    out, last = [], 0
    for m in re.finditer(r"`([^`\n]+)`", s):
        out.append(_inline_rich(s[last:m.start()]))
        out.append("<code>" + m.group(1) + "</code>")
        last = m.end()
    out.append(_inline_rich(s[last:]))
    return "".join(out)


def _inline_rich(s):
    # Links become placeholders first: an URL is full of `_` and `*`, and the
    # emphasis rules below would otherwise cut tags into the href.
    links = []

    def _keep(m):
        links.append(f'<a href="{m.group(2)}">{m.group(1)}</a>')
        return f"\x00{len(links) - 1}\x00"
    s = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+|tg://[^)\s]+)\)", _keep, s)
    s = re.sub(r"(?<![\"'>=])(https?://[^\s<]+)",
               lambda m: (links.append(m.group(1)), f"\x00{len(links) - 1}\x00")[1], s)
    s = _emph(s)
    return re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], s)


def _emph(s):
    s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(?=\S)(.+?)(?<=\S)__", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])", r"<i>\1</i>", s)
    s = re.sub(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])", r"<i>\1</i>", s)
    s = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<s>\1</s>", s)
    return s


def md_to_html(md):
    parts, last = [], 0
    for m in _FENCE.finditer(md or ""):
        parts.append(("t", md[last:m.start()]))
        parts.append(("c", m.group(1)))
        last = m.end()
    tail = (md or "")[last:]
    # An UNCLOSED fence (a truncated bubble) is still a code block to the end;
    # matching only closed fences printed the bubble as raw text with ``` in it.
    um = re.search(r"^```[^\n]*\n", tail, re.M)
    if um:
        parts.append(("t", tail[:um.start()]))
        parts.append(("c", re.sub(r"\n?```\s*$", "", tail[um.end():])))
    else:
        parts.append(("t", tail))
    out = []
    for kind, chunk in parts:
        if kind == "c":
            out.append("<pre>" + html.escape(chunk.rstrip("\n"), quote=False) + "</pre>")
            continue
        lines = []
        for ln in chunk.split("\n"):
            e = html.escape(ln, quote=False)
            h = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", e)
            if h:
                lines.append("<b>" + _inline(h.group(1)) + "</b>")
                continue
            q = re.match(r"^&gt;\s?(.*)$", e)
            if q:
                lines.append("<blockquote>" + _inline(q.group(1)) + "</blockquote>")
                continue
            e = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", e)
            if re.fullmatch(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*", e):
                lines.append("")
                continue
            lines.append(_inline(e))
        out.append("\n".join(lines))
    s = "".join(out)
    return s.replace("</blockquote>\n<blockquote>", "\n")


def html_to_plain(h):
    return html.unescape(re.sub(r"<[^>]+>", "", h))


# --- relay-facing operations -----------------------------------------------------
def _split_for_html(md, limit=TG_LIMIT):
    """Pieces of `md` whose HTML fits `limit`. The caller already chunks to the
    plain cap with a margin; this only catches the rare reply whose escaping
    (&amp;, tags) pushes it over, by halving on a line boundary."""
    h = md_to_html(md)
    if len(h) <= limit:
        return [md]
    lines = md.split("\n")
    if len(lines) < 2:
        return [md[:len(md) // 2], md[len(md) // 2:]]
    mid = len(lines) // 2
    a, b = "\n".join(lines[:mid]), "\n".join(lines[mid:])
    # keep a code fence balanced across the cut
    if a.count("```") % 2:
        a, b = a + "\n```", "```\n" + b
    return _split_for_html(a, limit) + _split_for_html(b, limit)


_TROW = re.compile(r"^\s*\|.*\|\s*$")
_TSEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def segments(md):
    """[(kind, text)] with kind in code | table | text. A fenced block holding
    nothing but a pipe table is a TABLE (models fence wide tables themselves)."""
    out, last = [], 0
    for m in _FENCE.finditer(md or ""):
        out.extend(_split_tables(md[last:m.start()]))
        body = m.group(1).strip("\n")
        lines = body.split("\n")
        if len(lines) >= 2 and all(_TROW.match(l) for l in lines) and _TSEP.match(lines[1]):
            out.append(("table", body))
        else:
            out.append(("code", m.group(0)))
        last = m.end()
    out.extend(_split_tables((md or "")[last:]))
    return [(k, t) for k, t in out if t.strip()]


def _split_tables(text):
    out, buf, lines, i = [], [], text.split("\n"), 0
    while i < len(lines):
        if (_TROW.match(lines[i]) and i + 1 < len(lines) and _TSEP.match(lines[i + 1])):
            j = i + 2
            while j < len(lines) and _TROW.match(lines[j]):
                j += 1
            out.append(("text", "\n".join(buf))); buf = []
            out.append(("table", "\n".join(lines[i:j])))
            i = j
            continue
        buf.append(lines[i]); i += 1
    out.append(("text", "\n".join(buf)))
    return out


def _rich_text_html(md):
    """Prose for a rich message: one <p> per paragraph, inline markup kept."""
    paras = [p for p in re.split(r"\n\s*\n", md.strip()) if p.strip()]
    return "".join("<p>" + md_to_html(p).replace("\n", "<br>") + "</p>" for p in paras)


def _rich_table_html(table_md):
    rows = [_cells(l) for l in table_md.strip().split("\n")]
    head, body = rows[0], [r for r in rows[2:]]
    th = "".join(f"<th>{_inline(html.escape(c, quote=False))}</th>" for c in head)
    trs = "".join("<tr>" + "".join(f"<td>{_inline(html.escape(c, quote=False))}</td>"
                                   for c in r) + "</tr>" for r in body)
    return f"<table bordered striped><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


RICH_HTML_BUDGET = 30000      # under TELEGRAM_RICH_TEXT_LIMIT (32768) with margin


def _fit_rich(parts):
    """Split [(kind, md)] into groups whose rich HTML fits one message. A table
    too big for one message is cut by ROWS, each piece repeating the header, so
    every message is still a real table rather than a fallback code block."""
    groups, cur, size = [], [], 0
    for k, t in parts:
        pieces = [t]
        if k == "table" and len(_rich_table_html(t)) > RICH_HTML_BUDGET:
            lines = t.strip().split("\n")
            head, rows, pieces, buf = lines[:2], lines[2:], [], []
            for r in rows:
                if buf and len(_rich_table_html("\n".join(head + buf + [r]))) > RICH_HTML_BUDGET:
                    pieces.append("\n".join(head + buf)); buf = []
                buf.append(r)
            if buf:
                pieces.append("\n".join(head + buf))
        for piece in pieces:
            h = len(_rich_table_html(piece) if k == "table" else _rich_text_html(piece))
            if cur and size + h > RICH_HTML_BUDGET:
                groups.append(cur); cur, size = [], 0
            cur.append((k, piece)); size += h
    if cur:
        groups.append(cur)
    return groups


def send_rich(bot, chat, thread, parts, silent=False):
    """parts: [(table|text, md)] -> one native rich message."""
    h = "".join(_rich_table_html(t) if k == "table" else _rich_text_html(t) for k, t in parts)
    p = {"chat_id": int(chat), **thread_params(thread), "rich_message": {"html": h}}
    if silent:
        p["disable_notification"] = True
    return str(bot.call("sendRichMessage", p)["message_id"])


def send_text(bot, chat, thread, md, silent=False, reply_markup=None):
    """Send markdown; returns the LAST message id (str) or ''.

    A reply with a table goes out as a native RICH message so the table is a real
    table. Code blocks never go in a rich message -- the client drops them -- so
    they are split out and sent classic, in order."""
    segs = segments(md)
    if any(k == "table" for k, _ in segs) and not reply_markup:
        mid, group = "", []

        def flush():
            nonlocal mid, group
            if not group:
                return
            try:
                if any(k == "table" for k, _ in group):
                    for g in _fit_rich(group):
                        mid = send_rich(bot, chat, thread, g, silent)
                else:
                    mid = _send_classic(bot, chat, thread,
                                        "\n\n".join(t for _, t in group), silent)
            except TGError as e:
                # rich refused (size, markup): the same content classic, never lost
                mid = _send_classic(bot, chat, thread, "\n\n".join(
                    ("```\n" + t + "\n```") if k == "table" else t for k, t in group), silent)
            group = []
        for k, t in segs:
            if k == "code":
                flush()
                mid = _send_classic(bot, chat, thread, t, silent)
            else:
                group.append((k, t))
        flush()
        return mid
    return _send_classic(bot, chat, thread, md, silent, reply_markup)


def _send_classic(bot, chat, thread, md, silent=False, reply_markup=None):
    mid = ""
    pieces = _split_for_html(md)
    for i, piece in enumerate(pieces):
        p = {"chat_id": int(chat), **thread_params(thread),
             "link_preview_options": {"is_disabled": True}}
        if silent:
            p["disable_notification"] = True
        if reply_markup and i == len(pieces) - 1:
            p["reply_markup"] = reply_markup
        try:
            r = bot.call("sendMessage", {**p, "text": md_to_html(piece), "parse_mode": "HTML"})
        except TGError as e:
            if "parse" not in e.desc.lower() and "entit" not in e.desc.lower():
                raise
            r = bot.call("sendMessage", {**p, "text": piece[:TG_LIMIT]})
        mid = str(r["message_id"])
    return mid


def fit_tail(md, limit=TG_LIMIT):
    """Shrink a LIVE view to fit by dropping its OLDEST lines.

    A progress bubble shows a terminal's tail: the newest line is the one that
    matters. Cutting at the end (text[:limit]) threw away exactly that line and
    the closing ``` with it, so the bubble rendered as raw text. Lines are
    dropped from just inside the opening fence (or the top when there is none)."""
    if len(md_to_html(md)) <= limit:
        return md
    lines = md.split("\n")
    # keep everything up to and including the first opening fence (a status
    # line often sits above it), drop from just inside it
    head = next((i + 1 for i, l in enumerate(lines) if l.startswith("```")), 0)
    lo, hi = head, len(lines) - 1          # drop lines[head:k]; find the smallest k
    while lo < hi:
        k = (lo + hi) // 2
        if len(md_to_html("\n".join(lines[:head] + ["…"] + lines[k:]))) <= limit:
            hi = k
        else:
            lo = k + 1
    return "\n".join(lines[:head] + ["…"] + lines[lo:])


def edit_text(bot, chat, mid, md, reply_markup=None):
    p = {"chat_id": int(chat), "message_id": int(mid),
         "link_preview_options": {"is_disabled": True}}
    if reply_markup is not None:
        p["reply_markup"] = reply_markup
    md = fit_tail(md)
    h = md_to_html(md)
    try:
        return bot.call("editMessageText", {**p, "text": h, "parse_mode": "HTML"}, max_wait=5)
    except TGError as e:
        if "not modified" in e.desc:
            return None
        if "parse" in e.desc.lower() or "entit" in e.desc.lower():
            return bot.call("editMessageText", {**p, "text": md[:TG_LIMIT]}, max_wait=5)
        raise


def delete(bot, chat, mid):
    return bot.call("deleteMessage", {"chat_id": int(chat), "message_id": int(mid)})


def send_media(bot, chat, thread, path, caption="", document=True):
    fields = {"chat_id": chat, **{k: str(v) for k, v in thread_params(thread).items()}}
    if caption:
        fields["caption"] = md_to_html(caption)[:1024]
        fields["parse_mode"] = "HTML"
    method, field = ("sendDocument", "document") if document else ("sendPhoto", "photo")
    try:
        r = bot.upload(method, fields, field, path)
    except TGError as e:
        # A photo Telegram refuses (too large, odd aspect ratio) still arrives
        # as a document instead of disappearing.
        if document:
            raise
        r = bot.upload("sendDocument", fields, "document", path)
    return str(r["message_id"])


def buttons_markup(options, prefix="ccsel:"):
    return {"inline_keyboard": [[{"text": f"{i}. {o}"[:60], "callback_data": f"{prefix}{i}"}]
                                for i, o in enumerate(options, 1)]}
